#!/usr/bin/env python3
"""
main.py — Entry point for the Salesforce → ClickUp opportunity sync.

Intended to be called by a system cron job:
    0 7 * * * /usr/bin/python3 /home/user/SFDC-x-ClickUp-Opp-Sync/main.py >> /home/user/SFDC-x-ClickUp-Opp-Sync/logs/cron.log 2>&1

Pass --list-fields to print all custom fields on the configured ClickUp list
and exit (useful for initial setup to find the correct field UUIDs).
"""
from __future__ import annotations

import logging
import sys

from config.settings import load_settings
from utils.logger import setup_logging


def list_fields_mode(settings) -> int:
    """Print all custom fields on the configured ClickUp list and exit."""
    from clickup.client import ClickUpClient

    client = ClickUpClient(settings.clickup_api_token, settings.clickup_list_id)
    fields = client.get_list_fields()

    if not fields:
        print(f"No custom fields found on list {settings.clickup_list_id}.")
        return 0

    print(f"\nCustom fields on ClickUp list {settings.clickup_list_id}:\n")
    print(f"{'NAME':<45} {'TYPE':<20} {'ID'}")
    print("-" * 100)
    for f in sorted(fields, key=lambda x: x.get("name", "")):
        print(f"{f.get('name', ''):<45} {f.get('type', ''):<20} {f.get('id', '')}")

    print(f"\nTotal: {len(fields)} field(s)")
    print("\nCopy the IDs above into your GitHub secrets as CLICKUP_FIELD_ID_<CANONICAL_NAME>")
    return 0


def main() -> int:
    list_fields = "--list-fields" in sys.argv

    # 1. Load settings (raises ValueError on missing required config)
    try:
        settings = load_settings()
    except ValueError as exc:
        # Logging isn't set up yet — print to stderr so cron captures it
        print(f"[FATAL] Configuration error: {exc}", file=sys.stderr)
        return 1

    # --list-fields: print fields and exit (no Gmail/CSV needed)
    if list_fields:
        return list_fields_mode(settings)

    # 2. Set up logging
    setup_logging(settings.log_file, settings.log_level)
    logger = logging.getLogger(__name__)
    logger.info("=== Salesforce → ClickUp sync starting ===")

    try:
        # 3. Fetch the latest CSV attachment from Gmail via IMAP
        from gmail.client import fetch_latest_csv_attachment

        logger.info(
            "Connecting to Gmail IMAP as %s, searching for subject='%s'...",
            settings.gmail_address,
            settings.gmail_subject_pattern,
        )
        csv_bytes = fetch_latest_csv_attachment(
            address=settings.gmail_address,
            app_password=settings.gmail_app_password,
            imap_host=settings.gmail_imap_host,
            subject_pattern=settings.gmail_subject_pattern,
            attachment_name_pattern=settings.gmail_attachment_name_pattern,
        )

        # 4. Parse the CSV
        from sync.parser import parse_csv

        logger.info("Parsing CSV...")
        opportunities = parse_csv(csv_bytes, settings.csv_field_map)

        if not opportunities:
            logger.warning("No valid opportunities found in CSV. Nothing to sync.")
            return 0

        # 5. Run the sync
        from clickup.client import ClickUpClient
        from sync.engine import run_sync

        clickup_client = ClickUpClient(settings.clickup_api_token, settings.clickup_list_id)

        sf_id_field_id = settings.clickup_field_ids.get("sf_opportunity_id", "")

        summary = run_sync(
            opportunities=opportunities,
            clickup_client=clickup_client,
            sf_id_field_id=sf_id_field_id,
            field_ids=settings.clickup_field_ids,
        )

        # 6. Log final summary
        logger.info(
            "=== Sync finished: created=%d updated=%d closed=%d skipped=%d errors=%d ===",
            summary.created,
            summary.updated,
            summary.closed,
            summary.skipped,
            len(summary.errors),
        )

        if summary.errors:
            for err in summary.errors:
                logger.error("  Error: %s", err)
            return 1  # Exit 1 so cron MAILTO alerts fire

        return 0

    except FileNotFoundError as exc:
        logger.error("File/resource not found: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled exception during sync: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
