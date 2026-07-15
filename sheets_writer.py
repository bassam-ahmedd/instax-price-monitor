"""
Reads item codes from column B of the sheet and writes back last-checked /
price / availability / link columns for Extra and Jarir.

Layout: A=Last Checked, B=Item Description, C-E=Extra (Price/Avail/Link),
F-H=Jarir (Price/Avail/Link). If your sheet is still in the old layout
(A=Item Description ... H=Last Checked), run migrate_sheet_layout.py once
first (see README) - this module assumes the new layout.

Auth: expects the full service-account JSON in the GOOGLE_SERVICE_ACCOUNT_JSON
env var (GitHub Actions secret), OR a path to the JSON file in
GOOGLE_SERVICE_ACCOUNT_FILE for local runs.
"""
import json
import os
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = os.environ.get("SHEET_ID", "1x0ywQLO_QAp6sXesGGa44_99Bs2RtSjMLKiHgSIy_VA")
SHEET_TAB = os.environ.get("SHEET_TAB", "Sheet1")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

HEADER = [
    "Last Checked",
    "Item Description",
    "Extra Price (SAR)", "Extra Availability", "Extra Link",
    "Jarir Price (SAR)", "Jarir Availability", "Jarir Link",
]


def _get_client() -> gspread.Client:
    raw_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        info = json.loads(raw_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        file_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service-account.json")
        creds = Credentials.from_service_account_file(file_path, scopes=SCOPES)
    return gspread.authorize(creds)


def get_worksheet():
    client = _get_client()
    sh = client.open_by_key(SHEET_ID)
    return sh.worksheet(SHEET_TAB)


def read_items() -> list:
    ws = get_worksheet()
    col_b = ws.col_values(2)
    # Skip header row; drop blanks
    return [v for v in col_b[1:] if v.strip()]


def ensure_header(ws):
    current = ws.row_values(1)
    if current != HEADER:
        ws.update("A1", [HEADER])
    ws.freeze(rows=1)  # idempotent - harmless if already frozen


def write_results(rows: list):
    """
    rows: list of dicts, each:
    {
        "item": str,
        "extra": {"price", "availability", "link"},
        "jarir": {"price", "availability", "link"},
    }
    Writes in the same row order as the item appears in column B.
    """
    ws = get_worksheet()
    ensure_header(ws)

    existing_items = ws.col_values(2)[1:]
    item_to_row = {name: idx + 2 for idx, name in enumerate(existing_items)}  # +2: header + 1-index

    now_uae = datetime.now(timezone.utc).astimezone(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")  # GitHub runners are UTC; sheet notes it's UTC

    updates = []
    for row in rows:
        item = row["item"]
        row_num = item_to_row.get(item)
        if not row_num:
            continue  # item not found in sheet (shouldn't happen)

        extra = row["extra"]
        jarir = row["jarir"]
        values = [
            extra.get("price", ""), extra.get("availability", ""), extra.get("link", ""),
            jarir.get("price", ""), jarir.get("availability", ""), jarir.get("link", ""),
        ]
        updates.append({"range": f"A{row_num}", "values": [[now_uae]]})
        updates.append({"range": f"C{row_num}:H{row_num}", "values": [values]})

    if updates:
        ws.batch_update(updates)
