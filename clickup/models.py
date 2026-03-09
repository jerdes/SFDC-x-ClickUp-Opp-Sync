"""
clickup/models.py — Helpers for working with ClickUp task dicts.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


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


def _to_timestamp_ms(date_str: str) -> int | None:
    """
    Convert a date string to Unix timestamp in milliseconds (required by ClickUp date fields).
    Handles formats Salesforce commonly exports: M/D/YYYY, MM/DD/YYYY, YYYY-MM-DD.
    Returns None if parsing fails.
    """
    formats = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y")
    clean = date_str.strip()
    for fmt in formats:
        try:
            dt = datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    logger.warning("Could not parse date '%s' — skipping field.", date_str)
    return None


def _to_number(value_str: str) -> float | None:
    """
    Convert a currency/number string to a float.
    Strips leading $, commas, whitespace.  Returns None on failure.
    """
    clean = re.sub(r"[$,\s]", "", value_str.strip())
    try:
        return float(clean)
    except ValueError:
        logger.warning("Could not parse number '%s' — skipping field.", value_str)
        return None


# Canonical names that map to ClickUp date fields (require Unix ms timestamps)
_DATE_FIELDS = {"close_date", "next_step_date", "created_date"}

# Canonical names that map to ClickUp currency or number fields (require numeric values)
_NUMBER_FIELDS = {"sales_estimated_quota_relief"}

# Canonical names that map to ClickUp url fields (value must start with http/https)
_URL_FIELDS = {"map_url", "three_whys"}


def _is_valid_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def build_custom_fields_payload(
    opportunity: "Opportunity",  # type: ignore[name-defined]  # forward ref
    field_ids: dict[str, str],
    field_options: dict[str, dict[str, int]] | None = None,
) -> list[dict]:
    """
    Build the custom_fields array for a ClickUp create/update request body.

    Only includes fields that have a configured field ID and a non-empty value.

    Args:
        opportunity: An Opportunity instance from sync/parser.py.
        field_ids: Maps canonical field name -> ClickUp custom field UUID.
        field_options: Optional mapping of field_uuid -> {option_name_lower -> orderindex}
            for drop_down fields.  When provided, text values are converted to
            the integer orderindex ClickUp requires.  Fields whose text value
            cannot be matched to an option are skipped with a warning.

    Returns:
        List of {"id": "<uuid>", "value": <value>} dicts.
    """
    # Fields that carry boolean/checkbox semantics in the CSV
    _CHECKBOX_FIELDS = {
        "cuo_meeting_completed",
        "evaluation_agreed",
        "pricing_discussed",
        "decision_criteria_met",
        "economic_buyer_approved",
    }

    payload: list[dict] = []

    # Map canonical name -> value from the Opportunity dataclass
    field_values: dict[str, str] = {
        "sf_opportunity_id":            opportunity.sf_opportunity_id,
        "account_name":                 opportunity.account_name,
        "stage":                        opportunity.stage,
        "sales_estimated_quota_relief": opportunity.sales_estimated_quota_relief,
        "close_date":                   opportunity.close_date,
        "next_step_date":               opportunity.next_step_date,
        "next_step":                    opportunity.next_step,
        "forecast_category":            opportunity.forecast_category,
        "metrics":                      opportunity.metrics,
        "economic_buyer":               opportunity.economic_buyer,
        "decision_criteria":            opportunity.decision_criteria,
        "decision_process":             opportunity.decision_process,
        "paper_process":                opportunity.paper_process,
        "implicated_pain":              opportunity.implicated_pain,
        "champion_name":                opportunity.champion_name,
        "competitor":                   opportunity.competitor,
        "other_competitor":             opportunity.other_competitor,
        "cuo_meeting_completed":        opportunity.cuo_meeting_completed,
        "evaluation_agreed":            opportunity.evaluation_agreed,
        "pricing_discussed":            opportunity.pricing_discussed,
        "decision_criteria_met":        opportunity.decision_criteria_met,
        "economic_buyer_approved":      opportunity.economic_buyer_approved,
        "ironclad_signatory":           opportunity.ironclad_signatory,
        "map_url":                      opportunity.map_url,
        "three_whys":                   opportunity.three_whys,
        "created_date":                 opportunity.created_date,
    }

    for canonical, value in field_values.items():
        field_id = field_ids.get(canonical)
        if not field_id:
            continue  # field not configured — skip silently

        if canonical in _CHECKBOX_FIELDS:
            bool_val = value.strip().lower() in ("true", "yes", "1", "checked", "✓")
            payload.append({"id": field_id, "value": bool_val})

        elif canonical in _DATE_FIELDS:
            if value:
                ts = _to_timestamp_ms(value)
                if ts is not None:
                    payload.append({"id": field_id, "value": ts})

        elif canonical in _NUMBER_FIELDS:
            if value:
                num = _to_number(value)
                if num is not None:
                    payload.append({"id": field_id, "value": num})

        elif canonical in _URL_FIELDS:
            if value:
                if _is_valid_url(value):
                    payload.append({"id": field_id, "value": value})
                else:
                    logger.warning(
                        "Skipping '%s' for field '%s' — not a valid URL (must start with http/https).",
                        value, canonical,
                    )

        elif field_options and field_id in field_options:
            # Dropdown field — ClickUp requires the option's integer orderindex,
            # not the option text.  Look up by lowercased name.
            if value:
                options = field_options[field_id]
                orderindex = options.get(value.strip().lower())
                if orderindex is not None:
                    payload.append({"id": field_id, "value": orderindex})
                else:
                    logger.warning(
                        "Dropdown option '%s' not found for field '%s' — skipping. "
                        "Available options: %s",
                        value, canonical, list(options.keys()),
                    )

        else:
            # text / short_text — pass as-is
            if value:
                payload.append({"id": field_id, "value": value})

    return payload


def _values_equal(target, current) -> bool:
    """
    Compare a target value (already converted from CSV) with the current value
    returned by the ClickUp API.  Returns True when they represent identical data.
    """
    # current absent / empty → always different (target is non-empty by construction)
    if current is None or current == "":
        return False

    # Checkbox: bool target, ClickUp may return Python bool, 0/1, or "true"/"false"
    if isinstance(target, bool):
        if isinstance(current, bool):
            return target == current
        try:
            return target == (str(current).lower() in ("true", "1", "yes"))
        except Exception:  # noqa: BLE001
            return False

    # Date (int ms) or number/currency (float) — compare numerically with small tolerance
    if isinstance(target, (int, float)):
        try:
            return abs(float(target) - float(current)) < 1
        except (ValueError, TypeError):
            return False

    # Text / short_text / url — plain string comparison
    return str(target).strip() == str(current).strip()


def get_changed_fields_payload(
    opportunity: "Opportunity",  # type: ignore[name-defined]
    existing_task: dict,
    field_ids: dict[str, str],
    field_options: dict[str, dict[str, int]] | None = None,
) -> list[dict]:
    """
    Return a custom_fields payload containing only fields whose target value
    (from the CSV) differs from the current value stored in the ClickUp task.

    Args:
        opportunity: Parsed Opportunity with CSV values.
        existing_task: The full task dict returned by the ClickUp API.
        field_ids: Maps canonical field name -> ClickUp custom field UUID.

    Returns:
        Subset of build_custom_fields_payload(opportunity, field_ids) containing
        only entries where the value has changed.
    """
    target_payload = build_custom_fields_payload(opportunity, field_ids, field_options)

    # Index current ClickUp field values by field UUID
    current_by_id: dict[str, object] = {
        cf["id"]: cf.get("value")
        for cf in existing_task.get("custom_fields", [])
    }

    return [
        item for item in target_payload
        if not _values_equal(item["value"], current_by_id.get(item["id"]))
    ]
