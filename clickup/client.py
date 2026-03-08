"""
clickup/client.py — All HTTP interactions with the ClickUp REST API v2.
"""
from __future__ import annotations

import logging
import time

import requests

from clickup.models import build_custom_fields_payload
from sync.parser import Opportunity

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.clickup-stg.com/api/v2"
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

        logger.info("Fetched %d total tasks from ClickUp list %s", len(tasks), self._list_id)
        return tasks

    def create_task(self, opportunity: Opportunity, field_ids: dict[str, str]) -> dict:
        """
        Create a new ClickUp task for the given opportunity.
        Returns the created task dict.
        """
        custom_fields = build_custom_fields_payload(opportunity, field_ids)
        body: dict = {
            "name": opportunity.name,
            "custom_fields": custom_fields,
        }
        task = self._post(f"/list/{self._list_id}/task", body)
        logger.debug("Created task id=%s for SF id=%s", task.get("id"), opportunity.sf_opportunity_id)
        return task

    def update_task(self, task_id: str, opportunity: Opportunity, field_ids: dict[str, str]) -> dict:
        """
        Update an existing ClickUp task with the latest opportunity data.
        Returns the updated task dict.
        """
        custom_fields = build_custom_fields_payload(opportunity, field_ids)
        body: dict = {
            "name": opportunity.name,
            "custom_fields": custom_fields,
        }
        task = self._put(f"/task/{task_id}", body)
        logger.debug("Updated task id=%s for SF id=%s", task_id, opportunity.sf_opportunity_id)
        return task

    def close_task(self, task_id: str, opportunity: Opportunity, field_ids: dict[str, str]) -> dict:
        """
        Update the task's custom fields with final stage data and mark it closed.
        Returns the final task dict.
        """
        custom_fields = build_custom_fields_payload(opportunity, field_ids)
        body: dict = {
            "name": opportunity.name,
            "status": "closed",
            "custom_fields": custom_fields,
        }
        task = self._put(f"/task/{task_id}", body)
        logger.debug(
            "Closed task id=%s (stage=%s) for SF id=%s",
            task_id,
            opportunity.stage,
            opportunity.sf_opportunity_id,
        )
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
