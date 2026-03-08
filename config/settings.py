"""
settings.py — loads all configuration from .env and exposes a typed Settings object.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env relative to this project root regardless of where the script is called from
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass
class Settings:
    # --- Gmail (IMAP + App Password) ---
    gmail_address: str
    gmail_app_password: str
    gmail_imap_host: str
    gmail_subject_pattern: str
    gmail_attachment_name_pattern: str

    # --- ClickUp ---
    clickup_api_token: str
    clickup_list_id: str

    # ClickUp custom field IDs (one per synced column)
    clickup_field_ids: dict[str, str]

    # --- CSV field mapping: canonical_name -> CSV column header ---
    csv_field_map: dict[str, str]

    # --- Logging ---
    log_file: str
    log_level: str


# Canonical field names and their corresponding env-var suffixes
_FIELD_REGISTRY: list[tuple[str, str]] = [
    # (canonical_name, ENV_VAR_SUFFIX)
    ("sf_opportunity_id",          "SF_OPPORTUNITY_ID"),
    ("owner",                      "OWNER"),
    ("account_name",               "ACCOUNT_NAME"),
    ("stage",                      "STAGE"),
    ("arr",                        "ARR"),
    ("sales_estimated_quota_relief", "SALES_ESTIMATED_QUOTA_RELIEF"),
    ("close_date",                 "CLOSE_DATE"),
    ("next_step_date",             "NEXT_STEP_DATE"),
    ("next_step",                  "NEXT_STEP"),
    ("forecast_category",          "FORECAST_CATEGORY"),
    ("type",                       "TYPE"),
    ("metrics",                    "METRICS"),
    ("economic_buyer",             "ECONOMIC_BUYER"),
    ("decision_criteria",          "DECISION_CRITERIA"),
    ("decision_process",           "DECISION_PROCESS"),
    ("paper_process",              "PAPER_PROCESS"),
    ("implicated_pain",            "IMPLICATED_PAIN"),
    ("champion_name",              "CHAMPION_NAME"),
    ("competitor",                 "COMPETITOR"),
    ("other_competitor",           "OTHER_COMPETITOR"),
    ("cuo_meeting",                "CUO_MEETING"),
    ("completed",                  "COMPLETED"),
    ("evaluation_agreed",          "EVALUATION_AGREED"),
    ("pricing_discussed",          "PRICING_DISCUSSED"),
    ("decision_criteria_met",      "DECISION_CRITERIA_MET"),
    ("economic_buyer_approved",    "ECONOMIC_BUYER_APPROVED"),
    ("department",                 "DEPARTMENT"),
    ("ironclad_signatory",         "IRONCLAD_SIGNATORY"),
    ("map_url",                    "MAP_URL"),
    ("three_whys",                 "THREE_WHYS"),
    ("plan",                       "PLAN"),
    ("number_of_plan_seats",       "NUMBER_OF_PLAN_SEATS"),
    ("created_date",               "CREATED_DATE"),
]

# CSV column headers for each canonical field
_CSV_HEADER_DEFAULTS: dict[str, str] = {
    "sf_opportunity_id":            "Opportunity ID",
    "name":                         "Opportunity Name",
    "owner":                        "Opportunity Owner",
    "account_name":                 "Account Name",
    "stage":                        "Stage",
    "arr":                          "Annual Recurring Revenue (ARR)",
    "sales_estimated_quota_relief": "Sales Estimated Quota Relief",
    "close_date":                   "Close Date",
    "next_step_date":               "Next Step Date",
    "next_step":                    "Next Step",
    "forecast_category":            "Forecast Category",
    "type":                         "Type",
    "metrics":                      "Metrics",
    "economic_buyer":               "Economic Buyer",
    "decision_criteria":            "Decision Criteria",
    "decision_process":             "Decision Process",
    "paper_process":                "Paper Process",
    "implicated_pain":              "Implicated Pain",
    "champion_name":                "Champion Name",
    "competitor":                   "Competitor",
    "other_competitor":             "Other Competitor",
    "cuo_meeting":                  "CUO Meeting",
    "completed":                    "Completed",
    "evaluation_agreed":            "Evaluation Agreed",
    "pricing_discussed":            "Pricing Discussed",
    "decision_criteria_met":        "Decision Criteria Met",
    "economic_buyer_approved":      "Economic Buyer Approved",
    "department":                   "Department",
    "ironclad_signatory":           "Ironclad Signatory",
    "map_url":                      "Mutual Action Plan (MAP) URL",
    "three_whys":                   "3 Whys Business Case",
    "plan":                         "Plan",
    "number_of_plan_seats":         "Number of Plan Seats",
    "created_date":                 "Created Date",
}


def load_settings() -> Settings:
    # Build csv_field_map: canonical_name -> CSV column header
    # Allow override via CSV_MAP_<CANONICAL_UPPER> env vars
    csv_field_map: dict[str, str] = {}
    for canonical, default_header in _CSV_HEADER_DEFAULTS.items():
        env_key = f"CSV_MAP_{canonical.upper()}"
        csv_field_map[canonical] = os.getenv(env_key, default_header)

    # Build clickup_field_ids: canonical_name -> ClickUp field UUID
    # These must all be present (except 'name' which is the task title)
    clickup_field_ids: dict[str, str] = {}
    for canonical, suffix in _FIELD_REGISTRY:
        env_key = f"CLICKUP_FIELD_ID_{suffix}"
        value = os.getenv(env_key, "")
        if value:
            clickup_field_ids[canonical] = value
        # Missing field IDs are allowed at load time; the engine will skip them
        # with a warning rather than crashing — useful during initial setup.

    return Settings(
        gmail_address=_require("GMAIL_ADDRESS"),
        gmail_app_password=_require("GMAIL_APP_PASSWORD"),
        gmail_imap_host=_optional("GMAIL_IMAP_HOST", "imap.gmail.com"),
        gmail_subject_pattern=_optional("GMAIL_SUBJECT_PATTERN", "Salesforce Opportunity"),
        gmail_attachment_name_pattern=_optional("GMAIL_ATTACHMENT_NAME_PATTERN", ".csv"),
        clickup_api_token=_require("CLICKUP_API_TOKEN"),
        clickup_list_id=_require("CLICKUP_LIST_ID"),
        clickup_field_ids=clickup_field_ids,
        csv_field_map=csv_field_map,
        log_file=_optional("LOG_FILE", "logs/sync.log"),
        log_level=_optional("LOG_LEVEL", "INFO"),
    )
