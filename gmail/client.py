"""
gmail/client.py — Fetch the latest Salesforce CSV attachment via Gmail IMAP.

Uses only Python stdlib (imaplib, email) — no Google API credentials needed.
Requires a Google App Password: Google Account → Security → App passwords.
"""
from __future__ import annotations

import email
import email.policy
import fnmatch
import imaplib
import logging
from email.message import EmailMessage

logger = logging.getLogger(__name__)

_IMAP_PORT = 993


def fetch_latest_csv_attachment(
    address: str,
    app_password: str,
    imap_host: str,
    subject_pattern: str,
    attachment_name_pattern: str,
) -> bytes:
    """
    Connect to Gmail via IMAP, find the most recent email whose subject contains
    subject_pattern, and return the bytes of its first CSV attachment.

    Args:
        address: Gmail address (e.g. you@gmail.com).
        app_password: 16-character Google App Password (spaces optional).
        imap_host: IMAP server hostname (default: imap.gmail.com).
        subject_pattern: Substring to match in the email subject.
        attachment_name_pattern: Glob or suffix to match the attachment filename (e.g. ".csv").

    Returns:
        Raw bytes of the matched CSV attachment.

    Raises:
        FileNotFoundError: No matching email or attachment found.
        imaplib.IMAP4.error: Authentication or connection failure.
    """
    app_password = app_password.replace(" ", "")  # strip spaces from copied password

    logger.info("Connecting to IMAP host %s as %s", imap_host, address)
    with imaplib.IMAP4_SSL(imap_host, _IMAP_PORT) as imap:
        imap.login(address, app_password)
        logger.debug("IMAP login successful.")

        # List available mailboxes for debugging
        _, mailboxes = imap.list()
        logger.info("Available IMAP mailboxes: %s", [m.decode() for m in mailboxes if m])

        status, select_data = imap.select('"[Gmail]/All Mail"', readonly=True)
        if status != "OK":
            raise FileNotFoundError(
                "Could not select '[Gmail]/All Mail'. "
                "Ensure IMAP is enabled in Gmail settings."
            )
        logger.info("All Mail message count: %s", select_data[0].decode() if select_data else "unknown")

        # Search for messages with the subject pattern
        search_criterion = f'SUBJECT "{subject_pattern}"'
        logger.info("Searching with criterion: %s", search_criterion)
        status, data = imap.search(None, search_criterion)
        if status != "OK" or not data or not data[0]:
            raise FileNotFoundError(
                f"No emails found matching subject: '{subject_pattern}'. "
                "Check GMAIL_SUBJECT_PATTERN in .env."
            )

        # IMAP search returns message IDs oldest-first; take the last (most recent)
        message_ids = data[0].split()
        most_recent_id = message_ids[-1]

        logger.info(
            "Found %d email(s) matching subject '%s'. Checking most recent only.",
            len(message_ids),
            subject_pattern,
        )

        csv_bytes = _try_fetch_attachment(imap, most_recent_id, attachment_name_pattern)
        if csv_bytes is not None:
            logger.info(
                "Downloaded CSV attachment (%d bytes) from message id=%s",
                len(csv_bytes),
                most_recent_id.decode(),
            )
            return csv_bytes

        raise FileNotFoundError(
            f"The most recent matching email did not contain an attachment matching "
            f"'{attachment_name_pattern}'. Check GMAIL_ATTACHMENT_NAME_PATTERN in .env."
        )


def _try_fetch_attachment(imap: imaplib.IMAP4_SSL, msg_id: bytes, name_pattern: str) -> bytes | None:
    """
    Fetch a single message by ID and return the bytes of the first attachment
    whose filename matches name_pattern. Returns None if no match found.
    """
    status, msg_data = imap.fetch(msg_id, "(RFC822)")
    if status != "OK" or not msg_data or msg_data[0] is None:
        logger.warning("Could not fetch message id=%s", msg_id.decode())
        return None

    raw_bytes = msg_data[0][1]  # type: ignore[index]
    msg: EmailMessage = email.message_from_bytes(raw_bytes, policy=email.policy.default)  # type: ignore[assignment]

    for part in msg.walk():
        filename = part.get_filename() or ""
        if not filename:
            continue

        matched = (
            fnmatch.fnmatch(filename.lower(), name_pattern.lower())
            or filename.lower().endswith(name_pattern.lower().lstrip("*"))
        )
        if matched:
            logger.debug("Found attachment: %s in message id=%s", filename, msg_id.decode())
            payload = part.get_payload(decode=True)
            if payload:
                return payload

    return None
