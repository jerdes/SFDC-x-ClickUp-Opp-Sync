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

# Hardcoded CSV value → ClickUp option UUID maps for dropdown fields.
# ClickUp's POST/PUT custom field API requires the option UUID, not the option text
# or its orderindex.  Multiple CSV spellings can map to the same UUID.
_STAGE_MAP: dict[str, str] = {
    "0 - pre acceptance":               "2c959e13-554d-448d-9468-e840e0b5babb",
    "0 - pre-acceptance":               "2c959e13-554d-448d-9468-e840e0b5babb",
    "1 - initial interest":             "19143056-7265-4bd4-a448-e261db5a3310",
    "2 - investigate & educate":        "f7a4af3e-882f-4358-8c01-d9d7628d1db6",
    "3 - proposal":                     "7336c6d0-125a-45e6-aecc-c8293d67b698",
    "3 - validate & justify":           "7336c6d0-125a-45e6-aecc-c8293d67b698",
    "4 - negotiation":                  "edde4543-fee9-48c9-8516-1a474756c31e",
    "4 - finalize":                     "edde4543-fee9-48c9-8516-1a474756c31e",
    "4 - paper process":                "edde4543-fee9-48c9-8516-1a474756c31e",
    "4 & 5 - paper process & closing":  "edde4543-fee9-48c9-8516-1a474756c31e",
    "5 - closing":                      "edde4543-fee9-48c9-8516-1a474756c31e",
    "6 - closed won":                   "a87bc1f2-b39e-4884-8cc2-3ed54b46388e",
    "closed won":                       "a87bc1f2-b39e-4884-8cc2-3ed54b46388e",
    "7 - closed lost":                  "67d93608-1d17-40ba-aff4-1722934f964b",
    "closed lost":                      "67d93608-1d17-40ba-aff4-1722934f964b",
}

_FORECAST_CATEGORY_MAP: dict[str, str] = {
    "best case":  "7e6232aa-5350-4633-9123-adffeaf5f90f",
    "pipeline":   "7e6232aa-5350-4633-9123-adffeaf5f90f",
    "likely":     "8a1f2085-6edc-4ae0-bf06-27e7487d5844",
    "closed lost":"8a1f2085-6edc-4ae0-bf06-27e7487d5844",
    "commit":     "28272d00-42a0-4493-89d9-c97ffdb585a3",
    "closed won": "28272d00-42a0-4493-89d9-c97ffdb585a3",
}

# Maps canonical field name → CSV-value-to-UUID lookup
_DROPDOWN_UUID_MAPS: dict[str, dict[str, str]] = {
    "stage":             _STAGE_MAP,
    "forecast_category": _FORECAST_CATEGORY_MAP,
}


def build_dropdown_maps_from_fields(
    list_fields: list[dict],
    field_ids: dict[str, str],
) -> dict[str, dict[str, int]]:
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
        Dict mapping canonical dropdown name → {csv_display_name_lower → orderindex}.
    """
    # Field types that carry selectable options with orderindex
    _DROPDOWN_TYPES = {"drop_down", "dropdown", "labels"}

    _DROPDOWN_CANONICALS = set(_DROPDOWN_UUID_MAPS.keys())

    # Log what field IDs are configured for dropdown canonicals
    for canon in _DROPDOWN_CANONICALS:
        fid = field_ids.get(canon)
        logger.info("Dropdown config: canonical '%s' → field_id=%s", canon, fid or "(not set)")

    uuid_to_canonical: dict[str, str] = {
        field_ids[canon]: canon
        for canon in _DROPDOWN_CANONICALS
        if canon in field_ids
    }

    # Log all fields returned by the API for diagnostic purposes
    logger.info(
        "ClickUp list has %d custom field(s): %s",
        len(list_fields),
        [(f.get("name"), f.get("type"), f.get("id")) for f in list_fields],
    )

    result: dict[str, dict[str, int]] = {}
    for field in list_fields:
        field_id = field.get("id")
        canonical = uuid_to_canonical.get(field_id)
        if not canonical:
            continue
        field_type = field.get("type", "")
        if field_type not in _DROPDOWN_TYPES:
            logger.warning(
                "Field '%s' (id=%s) mapped to canonical '%s' has type '%s', "
                "expected one of %s — skipping dropdown option extraction.",
                field.get("name"), field_id, canonical, field_type, _DROPDOWN_TYPES,
            )
            continue
        options = field.get("type_config", {}).get("options", [])
        name_to_orderindex: dict[str, int] = {}
        for opt in options:
            name = opt.get("name")
            orderindex = opt.get("orderindex")
            if name is not None and orderindex is not None:
                name_to_orderindex[name.strip().lower()] = int(orderindex)
        result[canonical] = name_to_orderindex
        logger.info(
            "Dropdown '%s': loaded %d option(s) from ClickUp: %s",
            canonical,
            len(name_to_orderindex),
            list(name_to_orderindex.keys()),
        )

    for canon in _DROPDOWN_CANONICALS:
        if canon not in result:
            logger.warning(
                "Dropdown '%s': could not load options from ClickUp API — "
                "check that CLICKUP_FIELD_ID_%s is set and points to a dropdown field.",
                canon, canon.upper(),
            )

    return result


def _is_valid_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def build_custom_fields_payload(
    opportunity: "Opportunity",  # type: ignore[name-defined]  # forward ref
    field_ids: dict[str, str],
    dropdown_maps: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """
    Build the custom_fields array for a ClickUp create/update request body.

    Only includes fields that have a configured field ID and a non-empty value.
    Dropdown fields (stage, forecast_category) are converted to option UUIDs
    via the hardcoded _DROPDOWN_UUID_MAPS lookup.

    Args:
        opportunity: An Opportunity instance from sync/parser.py.
        field_ids: Maps canonical field name -> ClickUp custom field UUID.

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
            if not value.strip():
                continue  # no CSV value — leave the checkbox as-is in ClickUp
            # CSV exports '1' for checked, '0' for unchecked
            bool_val = value.strip() in ("1", "true", "yes", "checked", "✓")
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

        elif canonical in _DROPDOWN_UUID_MAPS:
            # Dropdown field — ClickUp's POST /task/{id}/field/{field_id}
            # endpoint expects the orderindex (integer), not the option UUID.
            # Use the dynamically-fetched maps (name → orderindex) when available.
            if value:
                csv_key = value.strip().lower()
                if dropdown_maps is not None and canonical in dropdown_maps:
                    orderindex = dropdown_maps[canonical].get(csv_key)
                    if orderindex is not None:
                        payload.append({"id": field_id, "value": orderindex})
                    else:
                        logger.warning(
                            "No ClickUp option for %s value '%s' — skipping. "
                            "Known values: %s",
                            canonical, value, list(dropdown_maps[canonical].keys()),
                        )
                else:
                    # No dynamic maps available — fall back to hardcoded UUID map
                    uuid_map = _DROPDOWN_UUID_MAPS[canonical]
                    option_uuid = uuid_map.get(csv_key)
                    if option_uuid is not None:
                        payload.append({"id": field_id, "value": option_uuid})
                    else:
                        logger.warning(
                            "No ClickUp option UUID for %s value '%s' — skipping. "
                            "Known values: %s",
                            canonical, value, list(uuid_map.keys()),
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
    target_payload = build_custom_fields_payload(opportunity, field_ids, dropdown_maps)

    # Index current ClickUp field values by field UUID
    current_by_id: dict[str, object] = {
        cf["id"]: cf.get("value")
        for cf in existing_task.get("custom_fields", [])
    }

    return [
        item for item in target_payload
        if not _values_equal(item["value"], current_by_id.get(item["id"]))
    ]
