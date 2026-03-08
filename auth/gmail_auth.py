"""
gmail_auth.py — Gmail OAuth2 credential lifecycle.

First run: opens a browser consent screen and saves token.json.
All subsequent runs: loads and silently refreshes the token.
"""
from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service(credentials_file: str, token_file: str) -> Resource:
    """
    Returns an authorized Gmail API service object.

    - If token_file exists and is valid: loads and refreshes it silently.
    - If token_file is missing or invalid: runs the browser consent flow
      and saves the new token to token_file.

    Args:
        credentials_file: Path to credentials.json from Google Cloud Console.
        token_file: Path where the OAuth token is persisted between runs.

    Returns:
        An authorized googleapiclient Resource for the Gmail API.
    """
    creds: Credentials | None = None
    token_path = Path(token_file)
    creds_path = Path(credentials_file)

    if not creds_path.exists():
        raise FileNotFoundError(
            f"Gmail credentials file not found: {credentials_file}\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        logger.debug("Loaded existing Gmail token from %s", token_path)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Gmail token expired — refreshing silently.")
            creds.refresh(Request())
        else:
            logger.info(
                "No valid Gmail token found — starting browser consent flow. "
                "This only happens once."
            )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        logger.info("Gmail token saved to %s", token_path)

    service = build("gmail", "v1", credentials=creds)
    logger.debug("Gmail API service created successfully.")
    return service
