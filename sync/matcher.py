"""
sync/matcher.py — Match Salesforce opportunities to existing ClickUp tasks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from clickup.models import get_custom_field_value
from sync.parser import Opportunity

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    to_create: list[Opportunity] = field(default_factory=list)
    to_update: list[tuple[Opportunity, dict]] = field(default_factory=list)
    to_close_orphans: list[dict] = field(default_factory=list)


def match_opportunities(
    opportunities: list[Opportunity],
    clickup_tasks: list[dict],
    sf_id_field_id: str,
) -> MatchResult:
    """
    Categorise opportunities and ClickUp tasks into three buckets:

    - to_create: SF opportunity has no matching ClickUp task → create it.
    - to_update: SF opportunity matches a ClickUp task → compare and update.
    - to_close_orphans: ClickUp task has an SF ID not present in the CSV at all
      → the opportunity was removed from the report, so close the task.

    Matching is by the Salesforce Opportunity ID stored as a custom field on
    each ClickUp task.  If multiple ClickUp tasks share the same SF ID a
    warning is logged and the first one found is used; duplicates should be
    resolved manually.

    Args:
        opportunities: Parsed opportunities from the CSV.
        clickup_tasks: All tasks fetched from the ClickUp list.
        sf_id_field_id: UUID of the ClickUp custom field holding the SF ID.

    Returns:
        MatchResult with three buckets.
    """
    if not sf_id_field_id:
        raise ValueError(
            "CLICKUP_FIELD_ID_SF_OPPORTUNITY_ID is not set. "
            "This field is required for matching."
        )

    # Build index: sf_opportunity_id -> first ClickUp task with that ID.
    # Warn on duplicates — there should only ever be one task per SF ID.
    task_index: dict[str, dict] = {}
    for task in clickup_tasks:
        sf_id = get_custom_field_value(task, sf_id_field_id)
        if not sf_id:
            continue
        sf_id = sf_id.strip()
        if sf_id in task_index:
            logger.warning(
                "Duplicate ClickUp tasks for SF Opportunity ID '%s': "
                "keeping task id=%s, ignoring task id=%s. "
                "Remove the duplicate manually.",
                sf_id,
                task_index[sf_id]["id"],
                task["id"],
            )
        else:
            task_index[sf_id] = task

    logger.debug(
        "Task index built: %d ClickUp tasks have a Salesforce Opportunity ID.",
        len(task_index),
    )

    result = MatchResult()
    csv_sf_ids: set[str] = set()

    for opp in opportunities:
        csv_sf_ids.add(opp.sf_opportunity_id)
        existing_task = task_index.get(opp.sf_opportunity_id)
        if existing_task is None:
            result.to_create.append(opp)
        else:
            result.to_update.append((opp, existing_task))

    # Any ClickUp task whose SF ID is not in the CSV is an orphan → close it.
    for sf_id, task in task_index.items():
        if sf_id not in csv_sf_ids:
            result.to_close_orphans.append(task)

    logger.info(
        "Match result: %d to create, %d to update, %d orphans to close.",
        len(result.to_create),
        len(result.to_update),
        len(result.to_close_orphans),
    )
    return result
