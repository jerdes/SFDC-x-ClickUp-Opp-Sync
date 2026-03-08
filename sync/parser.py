"""
sync/parser.py — Parse the Salesforce CSV into a list of Opportunity dataclasses.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    # Matching key
    sf_opportunity_id: str

    # Task title in ClickUp
    name: str

    # All other synced fields (may be empty string if not present in CSV)
    owner: str = ""
    account_name: str = ""
    stage: str = ""
    arr: str = ""
    sales_estimated_quota_relief: str = ""
    close_date: str = ""
    next_step_date: str = ""
    next_step: str = ""
    forecast_category: str = ""
    type: str = ""
    metrics: str = ""
    economic_buyer: str = ""
    decision_criteria: str = ""
    decision_process: str = ""
    paper_process: str = ""
    implicated_pain: str = ""
    champion_name: str = ""
    competitor: str = ""
    other_competitor: str = ""
    cuo_meeting: str = ""
    completed: str = ""
    evaluation_agreed: str = ""
    pricing_discussed: str = ""
    decision_criteria_met: str = ""
    economic_buyer_approved: str = ""
    department: str = ""
    ironclad_signatory: str = ""
    map_url: str = ""
    three_whys: str = ""
    plan: str = ""
    number_of_plan_seats: str = ""
    created_date: str = ""

    # Full original row — forward-compatible; preserves any extra columns
    raw: dict = field(default_factory=dict, repr=False)


def parse_csv(csv_bytes: bytes, field_map: dict[str, str]) -> list[Opportunity]:
    """
    Parse raw CSV bytes into a list of Opportunity instances.

    Args:
        csv_bytes: Raw bytes of the CSV file.
        field_map: Maps canonical field name -> CSV column header.
                   e.g. {"sf_opportunity_id": "Opportunity ID", "name": "Opportunity Name", ...}

    Returns:
        List of Opportunity instances. Rows missing sf_opportunity_id are skipped with a warning.
    """
    # Invert the map: CSV header -> canonical name
    header_to_canonical: dict[str, str] = {v: k for k, v in field_map.items()}

    text = csv_bytes.decode("utf-8-sig")  # handle BOM if present
    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise ValueError("CSV appears to be empty — no header row found.")

    # Warn about any mapped columns not present in this CSV
    csv_headers = set(reader.fieldnames)
    for canonical, csv_header in field_map.items():
        if csv_header not in csv_headers:
            logger.warning(
                "Expected CSV column '%s' (mapped from '%s') not found in file. "
                "It will be left blank. Check CSV_MAP_%s in .env.",
                csv_header,
                canonical,
                canonical.upper(),
            )

    opportunities: list[Opportunity] = []
    skipped = 0

    for row_num, row in enumerate(reader, start=2):  # row 1 is the header
        # Map each CSV header to its canonical name for this row
        canonical_row: dict[str, str] = {}
        for csv_header, value in row.items():
            canonical = header_to_canonical.get(csv_header or "")
            if canonical:
                canonical_row[canonical] = (value or "").strip()

        sf_id = canonical_row.get("sf_opportunity_id", "").strip()
        if not sf_id:
            logger.warning("Row %d skipped: missing Opportunity ID. Row data: %s", row_num, dict(row))
            skipped += 1
            continue

        name = canonical_row.get("name", "").strip()
        if not name:
            logger.warning("Row %d (id=%s) has no Opportunity Name — using ID as name.", row_num, sf_id)
            name = sf_id

        opp = Opportunity(
            sf_opportunity_id=sf_id,
            name=name,
            owner=canonical_row.get("owner", ""),
            account_name=canonical_row.get("account_name", ""),
            stage=canonical_row.get("stage", ""),
            arr=canonical_row.get("arr", ""),
            sales_estimated_quota_relief=canonical_row.get("sales_estimated_quota_relief", ""),
            close_date=canonical_row.get("close_date", ""),
            next_step_date=canonical_row.get("next_step_date", ""),
            next_step=canonical_row.get("next_step", ""),
            forecast_category=canonical_row.get("forecast_category", ""),
            type=canonical_row.get("type", ""),
            metrics=canonical_row.get("metrics", ""),
            economic_buyer=canonical_row.get("economic_buyer", ""),
            decision_criteria=canonical_row.get("decision_criteria", ""),
            decision_process=canonical_row.get("decision_process", ""),
            paper_process=canonical_row.get("paper_process", ""),
            implicated_pain=canonical_row.get("implicated_pain", ""),
            champion_name=canonical_row.get("champion_name", ""),
            competitor=canonical_row.get("competitor", ""),
            other_competitor=canonical_row.get("other_competitor", ""),
            cuo_meeting=canonical_row.get("cuo_meeting", ""),
            completed=canonical_row.get("completed", ""),
            evaluation_agreed=canonical_row.get("evaluation_agreed", ""),
            pricing_discussed=canonical_row.get("pricing_discussed", ""),
            decision_criteria_met=canonical_row.get("decision_criteria_met", ""),
            economic_buyer_approved=canonical_row.get("economic_buyer_approved", ""),
            department=canonical_row.get("department", ""),
            ironclad_signatory=canonical_row.get("ironclad_signatory", ""),
            map_url=canonical_row.get("map_url", ""),
            three_whys=canonical_row.get("three_whys", ""),
            plan=canonical_row.get("plan", ""),
            number_of_plan_seats=canonical_row.get("number_of_plan_seats", ""),
            created_date=canonical_row.get("created_date", ""),
            raw=dict(row),
        )
        opportunities.append(opp)

    logger.info(
        "CSV parsed: %d opportunities loaded, %d rows skipped.", len(opportunities), skipped
    )
    return opportunities
