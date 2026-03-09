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
    Convert a DD/MM/YYYY date string to Unix timestamp in milliseconds (required by ClickUp).
    Returns None if parsing fails.
    """
    try:
        dt = datetime.strptime(date_str.strip(), "%d/%m/%Y").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        logger.warning("Could not parse date '%s' (expected DD/MM/YYYY) — skipping field.", date_str)
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

# Canonical names that map to ClickUp checkbox fields (CSV: "1" = checked, "0" = unchecked)
_CHECKBOX_FIELDS = {
    "cuo_meeting_completed",
    "evaluation_agreed",
    "pricing_discussed",
    "decision_criteria_met",
    "economic_buyer_approved",
}

# Static maps: CSV value (lowercased) → exact ClickUp option name (as returned by the API).
# The orderindex is looked up live from the ClickUp list fields at runtime, so
# reordering options in ClickUp never breaks the sync.
_STAGE_CSV_TO_CLICKUP: dict[str, str] = {
    "0 - pre-acceptance":        "0 - pre acceptance",
    "1 - initial interest":      "1 - initial interest",
    "2 - investigate & educate": "2 - investigate & educate",
    "3 - validate & justify":    "3 - validate & justify",
    "4 - paper process":         "4 & 5 - paper process & closing",
    "5 - closing":               "4 & 5 - paper process & closing",
    "6 - closed won":            "6 - closed won",
    "7 - closed lost":           "closed lost",
}

_FORECAST_CATEGORY_CSV_TO_CLICKUP: dict[str, str] = {
    "best case": "best case",
    "likely":    "likely",
    "commit":    "commit",
}

# Maps canonical field name → CSV-value-to-ClickUp-name lookup
_DROPDOWN_CSV_MAPS: dict[str, dict[str, str]] = {
    "stage":             _STAGE_CSV_TO_CLICKUP,
    "forecast_category": _FORECAST_CATEGORY_CSV_TO_CLICKUP,
}


def build_dropdown_maps_from_fields(
    list_fields: list[dict],
    field_ids: dict[str, str],
) -> tuple[dict[str, dict[str, int]], set[str]]:
    """
    Build csv_value → orderindex maps for dropdown fields by reading the
    actual options from the ClickUp list field definitions returned by
    GET /list/{id}/field.

    ClickUp's POST /task/{id}/field/{field_id} endpoint expects the
    **orderindex** (integer) for dropdown fields, NOT the option UUID.

    Args:
        list_fields: Raw list of field dicts from ClickUpClient.get_list_fields().
        field_ids:   canonical_name → ClickUp field UUID mapping from settings.

    Returns:
        A 2-tuple of:
          - Dict mapping canonical dropdown name → {csv_display_name_lower → orderindex}
            for fields whose ClickUp type is actually a dropdown/labels field.
          - Set of canonical names whose configured field has a plain-text type
            (short_text, text) so the caller can write the value directly instead
            of attempting a dropdown lookup.
    """
    # Field types that carry selectable options with orderindex
    _DROPDOWN_TYPES = {"drop_down", "dropdown", "labels"}
    _TEXT_TYPES = {"short_text", "text", "url", "email"}

    _DROPDOWN_CANONICALS = set(_DROPDOWN_CSV_MAPS.keys())

    uuid_to_canonical: dict[str, str] = {
        field_ids[canon]: canon
        for canon in _DROPDOWN_CANONICALS
        if canon in field_ids
    }

    result: dict[str, dict[str, int]] = {}
    text_canonicals: set[str] = set()

    for field in list_fields:
        field_id = field.get("id")
        canonical = uuid_to_canonical.get(field_id)
        if not canonical:
            continue
        field_type = field.get("type", "")
        if field_type in _TEXT_TYPES:
            logger.info(
                "Field '%s' (id=%s) mapped to canonical '%s' is type '%s' — "
                "will write value as plain text.",
                field.get("name"), field_id, canonical, field_type,
            )
            text_canonicals.add(canonical)
            continue
        if field_type not in _DROPDOWN_TYPES:
            logger.warning(
                "Field '%s' (id=%s) mapped to canonical '%s' has unrecognised type '%s' — "
                "skipping.",
                field.get("name"), field_id, canonical, field_type,
            )
            continue
        options = field.get("type_config", {}).get("options", [])
        name_to_orderindex: dict[str, int] = {}
        for opt in options:
            name = opt.get("name")
            orderindex = opt.get("orderindex")
            if name is not None and orderindex is not None:
                name_to_orderindex[name.lower().strip()] = int(orderindex)
        result[canonical] = name_to_orderindex
        logger.info(
            "Dropdown '%s': loaded %d option(s) from ClickUp: %s",
            canonical,
            len(name_to_orderindex),
            list(name_to_orderindex.keys()),
        )

    for canon in _DROPDOWN_CANONICALS:
        if canon not in result and canon not in text_canonicals:
            logger.warning(
                "Dropdown '%s': could not load options from ClickUp API — "
                "check that CLICKUP_FIELD_ID_%s is set and points to a dropdown field.",
                canon, canon.upper(),
            )

    return result, text_canonicals


def _is_valid_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def build_custom_fields_payload(
    opportunity: "Opportunity",  # type: ignore[name-defined]  # forward ref
    field_ids: dict[str, str],
    dropdown_maps: dict[str, dict[str, str]] | None = None,
    text_canonicals: set[str] | None = None,
) -> list[dict]:
    """
    Build the custom_fields array for a ClickUp create/update request body.

    Only includes fields that have a configured field ID and a non-empty value.
    Dropdown fields (stage, forecast_category) are converted to option orderindexes
    via the dynamically-fetched maps, or written as plain text if the configured
    ClickUp field is actually a short_text/text type.

    Args:
        opportunity: An Opportunity instance from sync/parser.py.
        field_ids: Maps canonical field name -> ClickUp custom field UUID.
        dropdown_maps: Optional canonical → {csv_value_lower → orderindex} maps
            built from the live ClickUp list fields.
        text_canonicals: Set of canonical names whose configured ClickUp field is
            a plain-text type; values are written directly instead of as orderindexes.

    Returns:
        List of {"id": "<uuid>", "value": <value>} dicts.
    """
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
            if not value.strip():
                continue  # no CSV value — leave the checkbox as-is in ClickUp
            bool_val = value.strip() == "1"
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

        elif canonical in _DROPDOWN_CSV_MAPS:
            if value:
                # If the configured ClickUp field is plain text, write directly.
                if text_canonicals and canonical in text_canonicals:
                    payload.append({"id": field_id, "value": value.strip()})
                else:
                    # Dropdown field — two-step: CSV value → ClickUp name → orderindex.
                    csv_key = value.strip().lower()
                    clickup_name = _DROPDOWN_CSV_MAPS[canonical].get(csv_key)
                    if clickup_name is None:
                        logger.warning(
                            "No mapping for %s CSV value '%s' — skipping. "
                            "Known CSV values: %s",
                            canonical, value, list(_DROPDOWN_CSV_MAPS[canonical].keys()),
                        )
                    elif dropdown_maps is not None and canonical in dropdown_maps:
                        orderindex = dropdown_maps[canonical].get(clickup_name.lower())
                        if orderindex is not None:
                            payload.append({"id": field_id, "value": orderindex})
                        else:
                            logger.warning(
                                "CSV value '%s' maps to ClickUp option '%s' but that "
                                "option was not found in the live field options for '%s'. "
                                "Known ClickUp options: %s",
                                value, clickup_name, canonical,
                                list(dropdown_maps[canonical].keys()),
                            )
                    else:
                        logger.warning(
                            "No live dropdown options loaded for '%s' (value='%s') — skipping.",
                            canonical, value,
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
    dropdown_maps: dict[str, dict[str, str]] | None = None,
    text_canonicals: set[str] | None = None,
) -> list[dict]:
    """
    Return a custom_fields payload containing only fields whose target value
    (from the CSV) differs from the current value stored in the ClickUp task.

    Args:
        opportunity: Parsed Opportunity with CSV values.
        existing_task: The full task dict returned by the ClickUp API.
        field_ids: Maps canonical field name -> ClickUp custom field UUID.
        dropdown_maps: Optional canonical → {csv_value_lower → orderindex} maps.
        text_canonicals: Set of canonical names whose configured ClickUp field is
            a plain-text type.

    Returns:
        Subset of build_custom_fields_payload(opportunity, field_ids) containing
        only entries where the value has changed.
    """
    target_payload = build_custom_fields_payload(opportunity, field_ids, dropdown_maps, text_canonicals)

    # Index current ClickUp field values by field UUID
    current_by_id: dict[str, object] = {
        cf["id"]: cf.get("value")
        for cf in existing_task.get("custom_fields", [])
    }

    return [
        item for item in target_payload
        if not _values_equal(item["value"], current_by_id.get(item["id"]))
    ]
