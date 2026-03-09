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

# Canonical names that map to ClickUp dropdown fields.
# These need option-id mapping when the configured ClickUp field type is drop_down.
_DROPDOWN_FIELDS = {"stage", "forecast_category"}


def _forecast_aliases(option_name: str) -> list[str]:
    """Return known CSV aliases for forecast category options."""
    n = _normalize_dropdown_label(option_name)
    aliases: list[str] = []
    if "best case" in n:
        aliases.extend(["best case", "pipeline"])
    if "likely" in n:
        aliases.extend(["likely", "closed lost"])
    if "commit" in n:
        aliases.extend(["commit", "closed won"])
    return aliases


def _is_valid_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _normalize_dropdown_label(value: str) -> str:
    """
    Normalize dropdown labels for robust matching across formatting differences.
    Example: "Closed - Won" and "closed won" normalize to the same key.
    """
    lowered = value.strip().lower()
    # Keep alphanumerics, collapse everything else to spaces.
    collapsed = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(collapsed.split())


def _extract_stage_indexes(label: str) -> list[str]:
    """
    Extract numeric stage indexes from the prefix portion of a stage label.
    Examples:
      "4 & 5 - Paper Process & Closing" -> ["4", "5"]
      "6 - Closed Won" -> ["6"]
    """
    prefix = label.split("-", 1)[0]
    return re.findall(r"\d+", prefix)


def build_dropdown_option_maps(list_fields: list[dict], field_ids: dict[str, str]) -> dict[str, dict[str, str]]:
    """
    Build canonical dropdown mappings from CSV label -> ClickUp option id.

    Returns:
        dict of canonical field name -> {normalized_label: option_id}
    """
    by_id: dict[str, dict] = {f.get("id", ""): f for f in list_fields}
    result: dict[str, dict[str, str]] = {}

    for canonical in _DROPDOWN_FIELDS:
        field_id = field_ids.get(canonical, "")
        if not field_id:
            continue

        field = by_id.get(field_id)
        if not field:
            logger.warning("Configured field id for '%s' not found in ClickUp list fields: %s", canonical, field_id)
            continue

        if field.get("type") != "drop_down":
            continue

        options = field.get("type_config", {}).get("options", [])
        option_map: dict[str, str] = {}
        for opt in options:
            name = str(opt.get("name", "")).strip().lower()
            opt_id = str(opt.get("id", "")).strip()
            if name and opt_id:
                option_map[name] = opt_id
                option_map[_normalize_dropdown_label(name)] = opt_id

                # Stage-specific aliases keyed by stage index allow resilient mapping
                # when CSV label text differs but index is stable.
                if canonical == "stage":
                    for idx in _extract_stage_indexes(name):
                        option_map[f"__stage_index__{idx}"] = opt_id
                if canonical == "forecast_category":
                    for alias in _forecast_aliases(name):
                        option_map[_normalize_dropdown_label(alias)] = opt_id

        result[canonical] = option_map

    return result


def build_custom_fields_payload(
    opportunity: "Opportunity",  # type: ignore[name-defined]  # forward ref
    field_ids: dict[str, str],
    dropdown_option_maps: dict[str, dict[str, str]] | None = None,
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

        elif canonical in _DROPDOWN_FIELDS:
            if value:
                option_map = (dropdown_option_maps or {}).get(canonical, {})
                if option_map:
                    raw_key = value.strip().lower()
                    norm_key = _normalize_dropdown_label(value)
                    option_id = option_map.get(raw_key) or option_map.get(norm_key)

                    if not option_id and canonical == "stage":
                        stage_indexes = _extract_stage_indexes(value)
                        for idx in stage_indexes:
                            option_id = option_map.get(f"__stage_index__{idx}")
                            if option_id:
                                break

                    if option_id:
                        payload.append({"id": field_id, "value": option_id})
                    else:
                        logger.warning(
                            "No dropdown option match for field '%s' value '%s' — skipping field.",
                            canonical,
                            value,
                        )
                else:
                    # Backward-compatible fallback (non-dropdown field or no list metadata)
                    payload.append({"id": field_id, "value": value})

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
    dropdown_option_maps: dict[str, dict[str, str]] | None = None,
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
    target_payload = build_custom_fields_payload(opportunity, field_ids, dropdown_option_maps)

    # Index current ClickUp field values by field UUID
    current_by_id: dict[str, object] = {
        cf["id"]: cf.get("value")
        for cf in existing_task.get("custom_fields", [])
    }

    return [
        item for item in target_payload
        if not _values_equal(item["value"], current_by_id.get(item["id"]))
    ]
