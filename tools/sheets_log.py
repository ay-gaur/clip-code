#!/usr/bin/env python3
"""
sheets_log.py — Append rows to the CLIP OS Google Sheet.

Creates the "CLIP OS" spreadsheet and tabs if they don't exist.

Usage:
  python3 tools/sheets_log.py --tab "Leads" --data '{"Company": "Acme", "Contact": "John"}'
  python3 tools/sheets_log.py --tab "Research Notes" --data '{"Title": "...", "URL": "..."}'

Tabs and their schemas:
  Leads:          Date, Company, Contact, Source, Fit Score, Notes
  Content Ideas:  Date, Topic, Format, Source, Draft
  Outreach Log:   Date, Contact, Company, Channel, Subject, Status
  Research Notes: Date, Title, URL, Key Points, Source Type
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv
load_dotenv(BASE / ".env")

SHEET_NAME = "CLIP OS"

SHEET_SCHEMAS = {
    "Leads":          ["Date", "Company", "Contact", "Source", "Fit Score", "Notes"],
    "Content Ideas":  ["Date", "Topic", "Format", "Source", "Draft"],
    "Outreach Log":   ["Date", "Contact", "Company", "Channel", "Subject", "Status"],
    "Research Notes": ["Date", "Title", "URL", "Key Points", "Source Type"],
    # find-gap-leads skill — client / partner / audience buckets
    "Gap Leads":      ["Date", "Company", "Founder", "LinkedIn", "Domain", "Gap Score",
                       "Band", "Persona", "Missing Infra", "Meta Ads", "LinkedIn Note", "Source"],
    "Partners":       ["Date", "Name", "Company", "LinkedIn", "Domain", "Why Partner", "Source"],
    "Audience":       ["Date", "Company", "Founder", "Domain", "Stage", "Note", "Source"],
}


def _get_credentials():
    from google.oauth2.credentials import Credentials

    token_b64 = os.environ.get("GWORKSPACE_TOKEN") or os.environ.get("GOOGLE_TOKEN_B64")
    local_token = Path.home() / ".google-mcp" / "tokens" / "acmestudio.json"

    if token_b64:
        token_data = json.loads(base64.b64decode(token_b64).decode())
        return Credentials.from_authorized_user_info(token_data)
    if local_token.exists():
        return Credentials.from_authorized_user_file(str(local_token))
    raise RuntimeError("No acmestudio token found.")


def _get_services():
    from googleapiclient.discovery import build
    creds = _get_credentials()
    drive = build("drive", "v3", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)
    return drive, sheets


def _get_or_create_spreadsheet(drive, sheets) -> str:
    """Find or create the CLIP OS spreadsheet. Returns spreadsheet_id."""
    q = f"name='{SHEET_NAME}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    results = drive.files().list(q=q, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    # Create fresh spreadsheet
    body = {
        "properties": {"title": SHEET_NAME},
        "sheets": [{"properties": {"title": tab}} for tab in SHEET_SCHEMAS.keys()],
    }
    spreadsheet = sheets.spreadsheets().create(body=body, fields="spreadsheetId,sheets").execute()
    spreadsheet_id = spreadsheet["spreadsheetId"]

    # Write header rows for each tab
    for tab, headers in SHEET_SCHEMAS.items():
        sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab}'!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()

    print(f"[sheets_log] Created CLIP OS spreadsheet: {spreadsheet_id}")
    return spreadsheet_id


def _ensure_tab(sheets, spreadsheet_id: str, tab_name: str):
    """Add tab with headers if it doesn't exist."""
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title").execute()
    existing = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if tab_name in existing:
        return

    body = {"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
    sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()

    headers = SHEET_SCHEMAS.get(tab_name, ["Date", "Value"])
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A1",
        valueInputOption="RAW",
        body={"values": [headers]},
    ).execute()
    print(f"[sheets_log] Created tab: {tab_name}")


def append_row(tab_name: str, data: dict) -> bool:
    """Append a row to the specified tab. Date is prepended automatically."""
    try:
        drive, sheets = _get_services()
        spreadsheet_id = _get_or_create_spreadsheet(drive, sheets)
        _ensure_tab(sheets, spreadsheet_id, tab_name)

        headers = SHEET_SCHEMAS.get(tab_name, list(data.keys()))
        today = datetime.now().strftime("%Y-%m-%d")

        row = [today]
        for col in headers[1:]:  # skip "Date" — already prepended
            row.append(str(data.get(col, "")))

        sheets.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        print(f"[sheets_log] Appended row to '{tab_name}'")
        return True
    except Exception as e:
        print(f"[sheets_log] Failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tab", required=True, choices=list(SHEET_SCHEMAS.keys()))
    parser.add_argument("--data", required=True, help="JSON object with column values")
    args = parser.parse_args()

    try:
        data = json.loads(args.data)
    except json.JSONDecodeError as e:
        print(f"[sheets_log] Invalid JSON in --data: {e}", file=sys.stderr)
        sys.exit(1)

    success = append_row(args.tab, data)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
