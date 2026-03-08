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
    to_close: list[tuple[Opportunity, dict]] = field(default_factory=list)


def match_opportunities(
    opportunities: list[Opportunity],
    clickup_tasks: list[dict],
    sf_id_field_id: str,
    closed_stages: list[str],
) -> MatchResult:
    """
    Categorize opportunities into three groups based on whether a matching
    ClickUp task already exists and what the opportunity's current stage is.

    Matching is done via the Salesforce Opportunity ID stored as a custom
    field on each ClickUp task.

    Args:
        opportunities: Parsed opportunities from the CSV.
        clickup_tasks: All tasks fetched from the ClickUp list.
        sf_id_field_id: UUID of the ClickUp custom field that holds the SF Opportunity ID.
        closed_stages: Stage values that indicate a closed deal (e.g. ["Closed Won", "Closed Lost"]).

    Returns:
        MatchResult with three buckets: to_create, to_update, to_close.
    """
    if not sf_id_field_id:
        raise ValueError(
            "CLICKUP_FIELD_ID_SF_OPPORTUNITY_ID is not set in .env. "
            "This field is required for matching."
        )

    # Build index: sf_opportunity_id -> clickup_task
    task_index: dict[str, dict] = {}
    for task in clickup_tasks:
        sf_id = get_custom_field_value(task, sf_id_field_id)
        if sf_id:
            task_index[sf_id.strip()] = task

    logger.debug(
        "Task index built: %d ClickUp tasks have a Salesforce Opportunity ID.",
        len(task_index),
    )

    result = MatchResult()
    closed_set = {s.lower() for s in closed_stages}

    for opp in opportunities:
        existing_task = task_index.get(opp.sf_opportunity_id)
        is_closed = opp.stage.lower() in closed_set

        if existing_task is None:
            if is_closed:
                # Don't create ClickUp tasks for deals that are already closed
                logger.debug(
                    "Skipping closed opportunity with no existing task: %s (%s)",
                    opp.sf_opportunity_id,
                    opp.stage,
                )
            else:
                result.to_create.append(opp)
        elif is_closed:
            result.to_close.append((opp, existing_task))
        else:
            result.to_update.append((opp, existing_task))

    logger.info(
        "Match result: %d to create, %d to update, %d to close.",
        len(result.to_create),
        len(result.to_update),
        len(result.to_close),
    )
    return result
