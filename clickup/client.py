"""
clickup/client.py — All HTTP interactions with the ClickUp REST API v2.
"""
from __future__ import annotations

import logging
import time

import requests



logger = logging.getLogger(__name__)

_BASE_URL = "https://api.clickup.com/api/v2"
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

    def get_all_tasks(self) -> list[dict]:
        """
        Fetch every task in the list (including closed/archived) via pagination.
        Returns a flat list of task dicts.
        """
        tasks: list[dict] = []
        page = 0

        while True:
            params = {
                "page": page,
                "include_closed": "true",
                "archived": "true",
                "subtasks": "false",
            }
            data = self._get(f"/list/{self._list_id}/task", params=params)
            batch = data.get("tasks", [])
            tasks.extend(batch)
            logger.debug("Fetched page %d: %d tasks", page, len(batch))

            if not batch:
                break
            page += 1

        tasks = self._hydrate_missing_custom_fields(tasks)

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
        url = _BASE_URL + path
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

    def _hydrate_missing_custom_fields(self, tasks: list[dict]) -> list[dict]:
        """
        Some ClickUp list-task responses can omit the `custom_fields` key/value.
        Matching relies on the Salesforce ID custom field, so hydrate tasks via
        GET /task/{id} when needed.
        """
        missing = [t for t in tasks if not isinstance(t.get("custom_fields"), list)]
        if not missing:
            return tasks

        logger.warning(
            "%d task(s) missing custom_fields in list response. Hydrating task details...",
            len(missing),
        )

        hydrated_by_id: dict[str, dict] = {}
        for task in missing:
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
