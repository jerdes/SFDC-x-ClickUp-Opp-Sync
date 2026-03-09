"""
sync/engine.py — Orchestrates the create/update/close sync loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from clickup.client import ClickUpClient, ClickUpAPIError
from clickup.models import build_custom_fields_payload, get_changed_fields_payload
from sync.matcher import match_opportunities
from sync.parser import Opportunity

logger = logging.getLogger(__name__)


@dataclass
class SyncSummary:
    created: int = 0
    updated: int = 0
    closed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


_DROPDOWN_TYPES = {"drop_down", "labels"}


def _build_field_options(list_fields: list[dict]) -> dict[str, dict[str, int]]:
    """
    Build a lookup of drop_down/labels option names -> orderindex, keyed by field UUID.

    ClickUp dropdown-style fields require the integer orderindex of the chosen option,
    not the display text.  This lookup is built once per sync run from the list's
    field definitions and threaded through all payload-building calls.

    Returns:
        {field_uuid: {option_name_lower: orderindex, ...}, ...}
    """
    result: dict[str, dict[str, int]] = {}
    for f in list_fields:
        field_type = f.get("type", "")
        logger.debug("List field '%s' (id=%s) has type='%s'", f.get("name"), f.get("id"), field_type)
        if field_type in _DROPDOWN_TYPES:
            options = f.get("type_config", {}).get("options", [])
            option_map = {}
            for opt in options:
                name = opt.get("name")
                orderindex = opt.get("orderindex")
                if name is not None and orderindex is not None:
                    try:
                        option_map[name.lower()] = int(orderindex)
                    except (ValueError, TypeError):
                        pass
            result[f["id"]] = option_map
            logger.info(
                "Dropdown field '%s' (id=%s, type=%s): %d option(s) indexed: %s",
                f.get("name"), f.get("id"), field_type, len(option_map), list(option_map.keys()),
            )
    logger.debug("Built dropdown option map for %d field(s).", len(result))
    return result


def run_sync(
    opportunities: list[Opportunity],
    clickup_client: ClickUpClient,
    sf_id_field_id: str,
    field_ids: dict[str, str],
) -> SyncSummary:
    """
    Main sync loop. Rules:

    1. Search the ClickUp list for a task whose SF Opportunity ID matches.
       There should be at most one — duplicates are logged as warnings.
    2. Match found → compare every field against the CSV. Only send an API
       update if at least one value has changed. CSV is the source of truth.
    3. No match → create a new ClickUp task.
    4. ClickUp task exists but its SF ID is absent from the CSV → mark closed.

    A per-record try/except ensures one bad record never aborts the entire run.
    """
    summary = SyncSummary()

    # Fetch field definitions once to build the dropdown option lookup.
    # This lets us convert text values (e.g. "Prospecting") to the integer
    # orderindex ClickUp requires for drop_down custom fields.
    logger.info("Fetching list field definitions...")
    list_fields = clickup_client.get_list_fields()
    field_options = _build_field_options(list_fields)

    closed_status = "DONE"

    logger.info("Fetching all ClickUp tasks...")
    all_tasks = clickup_client.get_all_tasks(sf_id_field_id)

    match = match_opportunities(opportunities, all_tasks, sf_id_field_id)

    # --- Create ---
    for opp in match.to_create:
        try:
            custom_fields = build_custom_fields_payload(opp, field_ids, field_options)
            task = clickup_client.create_task(opp.name, custom_fields)

            # Explicitly set the SF Opportunity ID via the dedicated field endpoint.
            # The custom_fields array in the create body is not always persisted by
            # ClickUp, which would break matching on future runs.
            if sf_id_field_id:
                clickup_client.set_custom_field(
                    task["id"], sf_id_field_id, opp.sf_opportunity_id
                )

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

    # --- Update (only changed fields) ---
    for opp, task in match.to_update:
        task_id = task["id"]
        try:
            changed_fields = get_changed_fields_payload(opp, task, field_ids, field_options)
            name_changed = opp.name != task.get("name", "")

            if not changed_fields and not name_changed:
                summary.skipped += 1
                logger.debug(
                    "SKIPPED  '%s' (SF id=%s, CU id=%s) — no changes",
                    opp.name, opp.sf_opportunity_id, task_id,
                )
                continue

            clickup_client.update_task(task_id, opp.name, changed_fields)
            summary.updated += 1
            logger.info(
                "UPDATED  '%s' (SF id=%s, CU id=%s) — %d field(s) changed%s",
                opp.name, opp.sf_opportunity_id, task_id,
                len(changed_fields),
                ", name changed" if name_changed else "",
            )
        except ClickUpAPIError as exc:
            msg = f"Failed to UPDATE '{opp.name}' (SF id={opp.sf_opportunity_id}, CU id={task_id}): {exc}"
            logger.error(msg)
            summary.errors.append(msg)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error updating '{opp.name}' (SF id={opp.sf_opportunity_id}, CU id={task_id}): {exc}"
            logger.exception(msg)
            summary.errors.append(msg)

    # --- Close orphans (ClickUp tasks whose SF ID is absent from the CSV) ---
    for task in match.to_close_orphans:
        task_id = task["id"]
        task_name = task.get("name", task_id)
        try:
            clickup_client.close_orphan_task(task_id, closed_status)
            summary.closed += 1
            logger.info("CLOSED   '%s' (CU id=%s) — SF ID not in CSV", task_name, task_id)
        except ClickUpAPIError as exc:
            msg = f"Failed to CLOSE orphan '{task_name}' (CU id={task_id}): {exc}"
            logger.error(msg)
            summary.errors.append(msg)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error closing orphan '{task_name}' (CU id={task_id}): {exc}"
            logger.exception(msg)
            summary.errors.append(msg)

    logger.info(
        "Sync complete. created=%d updated=%d closed=%d skipped=%d errors=%d",
        summary.created,
        summary.updated,
        summary.closed,
        summary.skipped,
        len(summary.errors),
    )
    return summary
