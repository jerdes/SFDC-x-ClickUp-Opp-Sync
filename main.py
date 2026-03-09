#!/usr/bin/env python3
"""
main.py — Entry point for the Salesforce → ClickUp opportunity sync.

Intended to be called by a system cron job:
    0 7 * * * /usr/bin/python3 /home/user/SFDC-x-ClickUp-Opp-Sync/main.py >> /home/user/SFDC-x-ClickUp-Opp-Sync/logs/cron.log 2>&1
"""
from __future__ import annotations

import logging
import sys

from config.settings import load_settings
from utils.logger import setup_logging


def main() -> int:
    # 1. Load settings (raises ValueError on missing required config)
    try:
        settings = load_settings()
    except ValueError as exc:
        # Logging isn't set up yet — print to stderr so cron captures it
        print(f"[FATAL] Configuration error: {exc}", file=sys.stderr)
        return 1

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

        token = settings.clickup_api_token
        logger.info(
            "ClickUp token: length=%d, prefix='%s…'",
            len(token),
            token[:4] if len(token) > 4 else "???",
        )
        import os
        base_url = (os.getenv("CLICKUP_BASE_URL") or "https://api.clickup.com/api/v2").rstrip("/")
        logger.info("ClickUp base URL: %s", base_url)

        clickup_client = ClickUpClient(token, settings.clickup_list_id)
        clickup_client.validate_token()

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
