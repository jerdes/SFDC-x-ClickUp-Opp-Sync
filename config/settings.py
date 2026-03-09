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


def _require_any(keys: list[str]) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    raise ValueError(f"Missing required environment variable (one of): {', '.join(keys)}")


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
@@ -115,32 +123,32 @@ _CSV_HEADER_DEFAULTS: dict[str, str] = {
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
        clickup_api_token=_require_any(["CLICKUP_API_TOKEN", "CLICKUP_STAGING_API_KEY"]),
        clickup_list_id=_require("CLICKUP_LIST_ID"),
        clickup_field_ids=clickup_field_ids,
        csv_field_map=csv_field_map,
        log_file=_optional("LOG_FILE", "logs/sync.log"),
        log_level=_optional("LOG_LEVEL", "INFO"),
    )
