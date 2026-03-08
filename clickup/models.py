"""
clickup/models.py — Helpers for working with ClickUp task dicts.
"""
from __future__ import annotations


def get_custom_field_value(task: dict, field_id: str) -> str | None:
    """
    Extract the value of a custom field from a ClickUp task dict.

    Args:
        task: A task dict as returned by the ClickUp API.
        field_id: The UUID of the custom field to look up.

    Returns:
        The string value of the field, or None if not found / not set.
    """
    for cf in task.get("custom_fields", []):
        if cf.get("id") == field_id:
            value = cf.get("value")
            if value is None:
                return None
            return str(value)
    return None


def build_custom_fields_payload(
    opportunity: "Opportunity",  # type: ignore[name-defined]  # forward ref
    field_ids: dict[str, str],
) -> list[dict]:
    """
    Build the custom_fields array for a ClickUp create/update request body.

    Only includes fields that have a configured field ID and a non-empty value.

    Args:
        opportunity: An Opportunity instance from sync/parser.py.
        field_ids: Maps canonical field name -> ClickUp custom field UUID.

    Returns:
        List of {"id": "<uuid>", "value": "<value>"} dicts.
    """
    # Fields that carry boolean/checkbox semantics in the CSV
    _CHECKBOX_FIELDS = {
        "cuo_meeting",
        "completed",
        "evaluation_agreed",
        "pricing_discussed",
        "decision_criteria_met",
        "economic_buyer_approved",
    }

    payload: list[dict] = []

    # Map canonical name -> value from the Opportunity dataclass
    field_values: dict[str, str] = {
        "sf_opportunity_id":            opportunity.sf_opportunity_id,
        "owner":                        opportunity.owner,
        "account_name":                 opportunity.account_name,
        "stage":                        opportunity.stage,
        "arr":                          opportunity.arr,
        "sales_estimated_quota_relief": opportunity.sales_estimated_quota_relief,
        "close_date":                   opportunity.close_date,
        "next_step_date":               opportunity.next_step_date,
        "next_step":                    opportunity.next_step,
        "forecast_category":            opportunity.forecast_category,
        "type":                         opportunity.type,
        "metrics":                      opportunity.metrics,
        "economic_buyer":               opportunity.economic_buyer,
        "decision_criteria":            opportunity.decision_criteria,
        "decision_process":             opportunity.decision_process,
        "paper_process":                opportunity.paper_process,
        "implicated_pain":              opportunity.implicated_pain,
        "champion_name":                opportunity.champion_name,
        "competitor":                   opportunity.competitor,
        "other_competitor":             opportunity.other_competitor,
        "cuo_meeting":                  opportunity.cuo_meeting,
        "completed":                    opportunity.completed,
        "evaluation_agreed":            opportunity.evaluation_agreed,
        "pricing_discussed":            opportunity.pricing_discussed,
        "decision_criteria_met":        opportunity.decision_criteria_met,
        "economic_buyer_approved":      opportunity.economic_buyer_approved,
        "department":                   opportunity.department,
        "ironclad_signatory":           opportunity.ironclad_signatory,
        "map_url":                      opportunity.map_url,
        "three_whys":                   opportunity.three_whys,
        "plan":                         opportunity.plan,
        "number_of_plan_seats":         opportunity.number_of_plan_seats,
        "created_date":                 opportunity.created_date,
    }

    for canonical, value in field_values.items():
        field_id = field_ids.get(canonical)
        if not field_id:
            continue  # field not configured in .env — skip silently

        if canonical in _CHECKBOX_FIELDS:
            # Normalize checkbox values to ClickUp boolean (true/false)
            bool_val = value.strip().lower() in ("true", "yes", "1", "checked", "✓")
            payload.append({"id": field_id, "value": bool_val})
        else:
            # Only include non-empty text/date/number values
            if value:
                payload.append({"id": field_id, "value": value})

    return payload
