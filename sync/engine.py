"""
sync/engine.py — Orchestrates the create/update/close sync loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from clickup.client import ClickUpClient, ClickUpAPIError
from sync.matcher import match_opportunities
from sync.parser import Opportunity

logger = logging.getLogger(__name__)


@dataclass
class SyncSummary:
    created: int = 0
    updated: int = 0
    closed: int = 0
    errors: list[str] = field(default_factory=list)


def run_sync(
    opportunities: list[Opportunity],
    clickup_client: ClickUpClient,
    sf_id_field_id: str,
    field_ids: dict[str, str],
    closed_stages: list[str],
) -> SyncSummary:
    """
    Main sync loop: fetches all ClickUp tasks, matches against the CSV,
    then creates/updates/closes as needed.

    A per-record try/except ensures one bad record never aborts the run.

    Args:
        opportunities: Parsed opportunities from the CSV.
        clickup_client: Initialized ClickUpClient.
        sf_id_field_id: UUID of the SF Opportunity ID custom field in ClickUp.
        field_ids: Full map of canonical_name -> ClickUp field UUID.
        closed_stages: Stage values that trigger a close action.

    Returns:
        SyncSummary with counts and any per-record error messages.
    """
    summary = SyncSummary()

    logger.info("Fetching all ClickUp tasks...")
    all_tasks = clickup_client.get_all_tasks()

    match = match_opportunities(opportunities, all_tasks, sf_id_field_id, closed_stages)

    # --- Create ---
    for opp in match.to_create:
        try:
            clickup_client.create_task(opp, field_ids)
            summary.created += 1
            logger.info("CREATED  '%s' (SF id=%s)", opp.name, opp.sf_opportunity_id)
        except ClickUpAPIError as exc:
            msg = f"Failed to CREATE '{opp.name}' (SF id={opp.sf_opportunity_id}): {exc}"
            logger.error(msg)
            summary.errors.append(msg)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error creating '{opp.name}' (SF id={opp.sf_opportunity_id}): {exc}"
            logger.exception(msg)
            summary.errors.append(msg)

    # --- Update ---
    for opp, task in match.to_update:
        task_id = task["id"]
        try:
            clickup_client.update_task(task_id, opp, field_ids)
            summary.updated += 1
            logger.info("UPDATED  '%s' (SF id=%s, CU id=%s)", opp.name, opp.sf_opportunity_id, task_id)
        except ClickUpAPIError as exc:
            msg = f"Failed to UPDATE '{opp.name}' (SF id={opp.sf_opportunity_id}, CU id={task_id}): {exc}"
            logger.error(msg)
            summary.errors.append(msg)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error updating '{opp.name}' (SF id={opp.sf_opportunity_id}, CU id={task_id}): {exc}"
            logger.exception(msg)
            summary.errors.append(msg)

    # --- Close ---
    for opp, task in match.to_close:
        task_id = task["id"]
        try:
            clickup_client.close_task(task_id, opp, field_ids)
            summary.closed += 1
            logger.info(
                "CLOSED   '%s' (SF id=%s, CU id=%s, stage=%s)",
                opp.name,
                opp.sf_opportunity_id,
                task_id,
                opp.stage,
            )
        except ClickUpAPIError as exc:
            msg = f"Failed to CLOSE '{opp.name}' (SF id={opp.sf_opportunity_id}, CU id={task_id}): {exc}"
            logger.error(msg)
            summary.errors.append(msg)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error closing '{opp.name}' (SF id={opp.sf_opportunity_id}, CU id={task_id}): {exc}"
            logger.exception(msg)
            summary.errors.append(msg)

    logger.info(
        "Sync complete. created=%d updated=%d closed=%d errors=%d",
        summary.created,
        summary.updated,
        summary.closed,
        len(summary.errors),
    )
    return summary
