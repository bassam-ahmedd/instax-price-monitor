"""
Reads item codes from column B and writes back last-checked / our price /
competitor price+availability+link+comparison columns.

Layout: A=Last Checked, B=Item Description, C-E=Our price/availability/link
(AMT, ksa.amt.tv - "our" site), F-I=Extra (Price/Availability/Link/vs Us),
J-M=Jarir (Price/Availability/Link/vs Us). Header row is frozen.

"vs Us" columns say whether that competitor's price is Higher, Lower, or
the Same as ours, or N/A if either price is missing.

Self-healing: normalize_layout(), called at the start of every run, checks
whether column B actually contains the known item codes. If it doesn't
(wrong column order, a partial/interrupted previous write, stray rows),
it rebuilds the sheet from the canonical item list below rather than
trying to salvage possibly-misaligned data - the very next run repopulates
every price/availability/link column anyway, so there's nothing worth
preserving in a row that's already in question.

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
    "Our Price (SAR)", "Our Availability", "Our Link",
    "Extra Price (SAR)", "Extra Availability", "Extra Link", "Extra vs Us",
    "Jarir Price (SAR)", "Jarir Availability", "Jarir Link", "Jarir vs Us",
]
NUM_COLUMNS = len(HEADER)

# The 54 items from the original sourcing list, in their original order.
# Used only as a rebuild source when the sheet's layout looks broken -
# normal runs read the live column B instead of this.
CANONICAL_ITEMS = [
    "Instax Mini12 White", "Instax Mini12 Purple", "Instax Mini12 Blue", "Instax Mini12 Green",
    "INSTAX MINI EVO BR", "INSTAX MINI EVO PNK", "INSTAX MINI EVO CINEMA",
    "INSTAX MINI LIPLAY PLUS BG", "INSTAX MINI LIPLAY PLUS BL",
    "Instax Mini41 Black", "Instax Wide400 Green", "Instax Wide400 Black",
    "INSTAX SQR SQ1 ORG", "INSTAX SQR SQ1 BL", "INSTAX SQR SQ1 WHT", "INSTAX SQR SQ40 BK",
    "INSTAX WIDE EVO BK",
    "INSTAX MINI LINK3 WHT", "INSTAX MINI LINK3 PNK", "INSTAX MINI LINK3 GRN",
    "INSTAX MINI LINK PLUS BK", "INSTAX SQ LINK WHT", "INSTAX SQ LINK GRN",
    "INSTAX WIDE LINK WHT", "INSTAX WIDE LINK GRY",
    "Mini White-Twin Film", "MINI MACARON-SINGLE FILM", "MINI CONTETTI-SINGLE FILM",
    "MINI CONTACT-SINGLE FILM", "MINI HRT SKTCH-SINGLE FILM", "MINI LAVNDR-SINGLE FILM",
    "MINI RNBW-SINGLE FILM", "Mini White-Single Film", "MINI MONOCHROME-SINGLE FILM",
    "MINI BK FRM-SINGLE FILM", "MINI BL FRM-SINGLE FILM", "MINI PNK LEMND-SINGLE FILM",
    "MINI MERMAID-SINGLE FILM", "MINI BL MARBLE-SINGLE FILM", "MINI SPR ART-SINGLE FILM",
    "MINI GLTR-SINGLE FILM",
    "Wide White-Single Film", "Wide White-Twin Film", "WIDE BRUSH MET-SINGLE FILM",
    "SQR WHITE-SINGLE FILM", "SQR STR ILLM-SINGLE FILM", "SQR WHT MARBLE-SINGLE FILM",
    "SQR RNBW-SINGLE FILM", "SQR SNST-SINGLE FILM", "SQR BK FRM-SINGLE FILM",
    "INSTAX PAL WHT", "INSTAX PAL PNK", "INSTAX PAL BL", "INSTAX PAL GRN",
]

# If fewer than this many of the first 20 canonical items are found sitting
# correctly in column B, the layout is considered broken and gets rebuilt.
MIN_HEALTHY_MATCHES = 15


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


def normalize_layout(ws):
    """
    Ensure the sheet has the correct header, item codes in column B, and a
    frozen header row - repairing it first if it's in a broken or mixed
    state. Call this before read_items()/write_results() on every run.
    """
    all_values = ws.get_all_values()

    b_column = [row[1] if len(row) > 1 else "" for row in all_values[1:1 + len(CANONICAL_ITEMS)]]
    matches = sum(1 for i, item in enumerate(CANONICAL_ITEMS[:20]) if i < len(b_column) and b_column[i] == item)

    if matches >= MIN_HEALTHY_MATCHES:
        # Layout already looks right - just make sure header/freeze are set.
        if all_values and all_values[0] != HEADER:
            ws.update("A1", [HEADER])
        ws.freeze(rows=1)
        return

    print(
        f"[sheets_writer] Layout looks broken ({matches}/20 items found in the "
        f"expected place) - rebuilding from the canonical item list.",
        flush=True,
    )
    rows = [HEADER] + [["", item] + [""] * (NUM_COLUMNS - 2) for item in CANONICAL_ITEMS]
    ws.clear()
    ws.update("A1", rows)
    ws.freeze(rows=1)


def read_items() -> list:
    ws = get_worksheet()
    normalize_layout(ws)
    col_b = ws.col_values(2)
    return [v for v in col_b[1:] if v.strip()]


def _compare_to_us(their_price: str, our_price: str) -> str:
    """Higher / Lower / Same, or N/A if either price is missing or
    non-numeric (e.g. the item wasn't found on one side)."""
    try:
        their = float(their_price)
        our = float(our_price)
    except (TypeError, ValueError):
        return "N/A"
    if their > our:
        return "Higher"
    if their < our:
        return "Lower"
    return "Same"


def write_results(rows: list):
    """
    rows: list of dicts, each:
    {
        "item": str,
        "our": {"price", "availability", "link"},
        "extra": {"price", "availability", "link"},
        "jarir": {"price", "availability", "link"},
    }
    Writes in the same row order as the item appears in column B.
    """
    ws = get_worksheet()
    normalize_layout(ws)

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

        our = row["our"]
        extra = row["extra"]
        jarir = row["jarir"]

        extra_vs_us = _compare_to_us(extra.get("price", ""), our.get("price", ""))
        jarir_vs_us = _compare_to_us(jarir.get("price", ""), our.get("price", ""))

        values = [
            our.get("price", ""), our.get("availability", ""), our.get("link", ""),
            extra.get("price", ""), extra.get("availability", ""), extra.get("link", ""), extra_vs_us,
            jarir.get("price", ""), jarir.get("availability", ""), jarir.get("link", ""), jarir_vs_us,
        ]
        updates.append({"range": f"A{row_num}", "values": [[now_uae]]})
        updates.append({"range": f"C{row_num}:M{row_num}", "values": [values]})

    if updates:
        ws.batch_update(updates)
