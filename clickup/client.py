"""
clickup/client.py — All HTTP interactions with the ClickUp REST API v2.
"""
from __future__ import annotations

import logging
import os
import time

import requests



logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.clickup.com/api/v2"
_MAX_RETRIES = 3


class ClickUpAPIError(Exception):
    def __init__(self, status_code: int, body: str):
        super().__init__(f"ClickUp API error {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class ClickUpClient:
    def __init__(self, api_token: str, list_id: str):
        self._list_id = list_id
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": api_token,
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_token(self) -> dict:
        """
        Call GET /user to verify the API token is valid.
        Returns the user dict on success.
        Raises ClickUpAPIError on failure with a helpful message.
        """
        try:
            data = self._get("/user")
            user = data.get("user", {})
            logger.info(
                "ClickUp token validated: user='%s' (id=%s)",
                user.get("username", "?"),
                user.get("id", "?"),
            )
            return user
        except ClickUpAPIError as exc:
            if exc.status_code == 401:
                raise ClickUpAPIError(
                    401,
                    "Token rejected by ClickUp. Verify your CLICKUP_API_TOKEN: "
                    "go to ClickUp → Settings → Apps → API Token, regenerate, "
                    "and update the GitHub secret. "
                    f"Original error: {exc.body}",
                ) from exc
            raise

    def get_list_fields(self) -> list[dict]:
        """
        Fetch all custom fields defined on this ClickUp list.
        Returns a list of field dicts containing id, name, type, etc.
        """
        data = self._get(f"/list/{self._list_id}/field")
        return data.get("fields", [])

    def get_all_tasks(self, sf_id_field_id: str = "") -> list[dict]:
        """
        Fetch every task in the list (including closed and archived) via pagination.
        Returns a flat list of task dicts.
        """
        tasks: list[dict] = []

        # ClickUp v2: archived=true returns ONLY archived tasks; archived=false (default)
        # returns non-archived tasks. Fetch both passes and merge so no task is missed.
        for archived in ("false", "true"):
            page = 0
            while True:
                params = {
                    "page": page,
                    "include_closed": "true",
                    "archived": archived,
                    "subtasks": "false",
                }
                data = self._get(f"/list/{self._list_id}/task", params=params)
                batch = data.get("tasks", [])
                tasks.extend(batch)
                logger.debug(
                    "Fetched page %d (archived=%s): %d tasks", page, archived, len(batch)
                )

                if not batch:
                    break
                page += 1

        tasks = self._hydrate_tasks_for_matching(tasks, sf_id_field_id)

        logger.info("Fetched %d total tasks from ClickUp list %s", len(tasks), self._list_id)
        return tasks

    def get_task(self, task_id: str) -> dict:
        """
        Fetch a single task by ID. Used to hydrate list results when custom fields
        are missing from list-task responses.
        """
        return self._get(f"/task/{task_id}")

    def create_task(self, name: str, custom_fields: list[dict]) -> dict:
        """
        Create a new ClickUp task.
        Returns the created task dict.
        """
        body: dict = {"name": name, "custom_fields": custom_fields}
        task = self._post(f"/list/{self._list_id}/task", body)
        logger.debug("Created task id=%s name='%s'", task.get("id"), name)
        return task

    def update_task(self, task_id: str, name: str, custom_fields: list[dict]) -> dict:
        """
        Update a ClickUp task's name and/or a subset of its custom fields.
        Pass only the fields that have changed; unchanged fields are omitted.
        Returns the updated task dict.
        """
        body: dict = {"name": name, "custom_fields": custom_fields}
        task = self._put(f"/task/{task_id}", body)
        logger.debug("Updated task id=%s", task_id)
        return task

    def set_custom_field(self, task_id: str, field_id: str, value) -> None:
        """
        Explicitly set one custom field value using the dedicated ClickUp endpoint.
        More reliable than including custom_fields in the create/update body,
        which ClickUp may silently ignore for certain field types.
        """
        self._post(f"/task/{task_id}/field/{field_id}", {"value": value})
        logger.debug("Set field %s on task %s to %r", field_id, task_id, value)

    def close_orphan_task(self, task_id: str) -> dict:
        """
        Mark a ClickUp task as closed without touching its custom fields.
        Used when a task's SF Opportunity ID no longer appears in the CSV.
        Returns the updated task dict.
        """
        task = self._put(f"/task/{task_id}", {"status": "closed"})
        logger.debug("Closed orphan task id=%s", task_id)
        return task

    # ------------------------------------------------------------------
    # HTTP helpers with rate-limit retry
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, json=body)

    def _put(self, path: str, body: dict) -> dict:
        return self._request("PUT", path, json=body)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        base_url = (os.getenv("CLICKUP_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")
        logger.debug("ClickUp request: %s %s%s", method, base_url, path)
        url = base_url + path
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            resp = self._session.request(method, url, **kwargs)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                logger.warning(
                    "ClickUp rate limit hit (attempt %d/%d). Sleeping %ds.",
                    attempt,
                    _MAX_RETRIES,
                    retry_after,
                )
                time.sleep(retry_after)
                last_exc = ClickUpAPIError(429, resp.text)
                continue

            if not resp.ok:
                raise ClickUpAPIError(resp.status_code, resp.text)

            return resp.json()

        raise last_exc or ClickUpAPIError(429, "Rate limit exceeded after retries")

    def _task_has_field_value(self, task: dict, field_id: str) -> bool:
        """Return True when task has a non-empty value for the given custom field id."""
        if not field_id:
            return False
        for cf in task.get("custom_fields", []):
            if cf.get("id") == field_id:
                value = cf.get("value")
                return value is not None and str(value).strip() != ""
        return False

    def _hydrate_tasks_for_matching(self, tasks: list[dict], sf_id_field_id: str = "") -> list[dict]:
        """
        Some ClickUp list-task responses can omit the `custom_fields` key/value.
        Some responses also omit the Salesforce ID custom field even when
        `custom_fields` exists. Matching relies on that field, so hydrate task
        details via GET /task/{id} when needed.
        """
        needs_hydration: list[dict] = []
        for task in tasks:
            custom_fields = task.get("custom_fields")
            if not isinstance(custom_fields, list):
                needs_hydration.append(task)
                continue

            if sf_id_field_id and not self._task_has_field_value(task, sf_id_field_id):
                needs_hydration.append(task)

        if not needs_hydration:
            return tasks

        logger.warning(
            "%d task(s) missing matching data in list response. Hydrating task details...",
            len(needs_hydration),
        )

        hydrated_by_id: dict[str, dict] = {}
        for task in needs_hydration:
            task_id = task.get("id")
            if not task_id:
                continue
            try:
                hydrated_by_id[task_id] = self.get_task(task_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not hydrate task id=%s for custom fields; using list payload. Error: %s",
                    task_id,
                    exc,
                )

        if not hydrated_by_id:
            return tasks

        merged: list[dict] = []
        for task in tasks:
            task_id = task.get("id")
            merged.append(hydrated_by_id.get(task_id, task))
        return merged
