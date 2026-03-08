"""
gmail/client.py — Fetch the latest Salesforce CSV attachment from Gmail.
"""
from __future__ import annotations

import base64
import fnmatch
import logging

logger = logging.getLogger(__name__)


def fetch_latest_csv_attachment(
    service,
    subject_pattern: str,
    attachment_name_pattern: str,
) -> bytes:
    """
    Search Gmail for the most recent email matching subject_pattern that has
    an attachment whose filename matches attachment_name_pattern.

    Args:
        service: Authorized Gmail API Resource object.
        subject_pattern: Substring to match in the email subject.
        attachment_name_pattern: Glob pattern for the attachment filename (e.g. "*.csv").

    Returns:
        Raw bytes of the matched attachment.

    Raises:
        FileNotFoundError: If no matching email or attachment is found.
    """
    query = f'subject:"{subject_pattern}" has:attachment'
    logger.debug("Searching Gmail with query: %s", query)

    result = service.users().messages().list(userId="me", q=query, maxResults=10).execute()
    messages = result.get("messages", [])

    if not messages:
        raise FileNotFoundError(
            f"No Gmail messages found matching subject: '{subject_pattern}'. "
            "Check GMAIL_SUBJECT_PATTERN in .env."
        )

    # Messages are returned newest-first by default; take the first one.
    latest_id = messages[0]["id"]
    logger.info("Found %d matching email(s). Using latest message id=%s", len(messages), latest_id)

    msg = service.users().messages().get(
        userId="me", id=latest_id, format="full"
    ).execute()

    csv_bytes = _extract_attachment(service, msg, attachment_name_pattern)
    if csv_bytes is None:
        raise FileNotFoundError(
            f"Email id={latest_id} has no attachment matching '{attachment_name_pattern}'. "
            "Check GMAIL_ATTACHMENT_NAME_PATTERN in .env."
        )

    logger.info(
        "Downloaded CSV attachment (%d bytes) from message id=%s", len(csv_bytes), latest_id
    )
    return csv_bytes


def _extract_attachment(service, message: dict, name_pattern: str) -> bytes | None:
    """
    Walk the message payload recursively to find an attachment matching name_pattern.
    Returns decoded bytes, or None if not found.
    """
    parts = _flatten_parts(message.get("payload", {}))
    for part in parts:
        filename = part.get("filename", "")
        if not filename:
            continue
        if not fnmatch.fnmatch(filename.lower(), name_pattern.lower()):
            # Also match if the pattern is a suffix substring (e.g. ".csv")
            if not filename.lower().endswith(name_pattern.lower().lstrip("*")):
                continue

        logger.debug("Found attachment: %s", filename)
        body = part.get("body", {})

        if "data" in body:
            # Inline data
            return base64.urlsafe_b64decode(body["data"])

        if "attachmentId" in body:
            # Large attachment stored separately
            attachment = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message["id"], id=body["attachmentId"])
                .execute()
            )
            return base64.urlsafe_b64decode(attachment["data"])

    return None


def _flatten_parts(payload: dict) -> list[dict]:
    """Recursively collect all parts from a multipart message payload."""
    parts: list[dict] = []
    if "parts" in payload:
        for part in payload["parts"]:
            parts.extend(_flatten_parts(part))
    else:
        parts.append(payload)
    return parts
