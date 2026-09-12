"""
Reads item codes from column B and writes back last-checked / our price /
competitor price+availability+link+comparison columns.

Layout: A=Last Checked, B=Item Description, C-E=Our price/availability/link
(AMT, ksa.amt.tv - "our" site), then one 4-column block per competitor
(Price/Availability/Link/vs Us) in COMPETITORS order below: F-I=Extra,
J-M=Jarir, N-Q=Qomra, then R-U=Lowest Price/Website/Link/Diff (the
cheapest across all four sources including us - "Website" says "Us" when
our own price wins - and how it compares to our price: negative means a
competitor undercuts us, positive is impossible since 0 is the floor when
we're the cheapest ourselves). Header row is frozen.

"vs Us" columns say whether that competitor's price is Higher, Lower, or
the Same as ours, or N/A if either price is missing. The competitor's
Price cell is highlighted red when their price is Lower than ours, and
their Availability cell is highlighted red when they have stock and we
don't - both recomputed and re-applied (or cleared) every run.

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
import random
import time
from datetime import datetime, timezone

import gspread
import requests.exceptions
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

SHEET_ID = os.environ.get("SHEET_ID", "1x0ywQLO_QAp6sXesGGa44_99Bs2RtSjMLKiHgSIy_VA")
SHEET_TAB = os.environ.get("SHEET_TAB", "Sheet1")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# One entry per competitor, in the order their 4-column blocks appear
# after the "Our" block (C-E). Each key here must match a key in the
# results dict passed to write_results() (see main.py).
COMPETITORS = ["extra", "jarir", "qomra", "grandstores"]
COMPETITOR_LABELS = {"extra": "Extra", "jarir": "Jarir", "qomra": "Qomra", "grandstores": "GrandStores"}

HEADER = [
    "Last Checked",
    "Item Description", "Our SKU",
    "Our Price (SAR)", "Our Availability", "Our Link",
]
OUR_BLOCK_START = 2  # column C (0-indexed from A) - where the "Our" block begins
OUR_BLOCK_SIZE = 4   # SKU, Price, Availability, Link
for _key in COMPETITORS:
    _label = COMPETITOR_LABELS[_key]
    HEADER += [f"{_label} Price (SAR)", f"{_label} Availability", f"{_label} Link", f"{_label} vs Us"]
HEADER += ["Lowest Price (SAR)", "Lowest Price Website", "Lowest Price Link", "Price Diff (Lowest - Ours)"]
NUM_COLUMNS = len(HEADER)

# A-Z column letters for the columns we actually use (fine as long as
# NUM_COLUMNS stays under 26 - we're at 17).
def _column_letter(index: int) -> str:
    """0-indexed column number -> spreadsheet column letter(s) (0->A,
    25->Z, 26->AA, ...). NUM_COLUMNS reached exactly 26 with this addition
    - the old list(string.ascii_uppercase[:NUM_COLUMNS]) approach would
    silently break (wrong letter or IndexError) on the very next column
    added, so this handles multi-letter columns properly instead."""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


_COLUMN_LETTERS = [_column_letter(i) for i in range(NUM_COLUMNS)]

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


# --- Transient-failure handling -------------------------------------------
# The Sheets API intermittently answers with 503 ("The service is currently
# unavailable") and friends. Google's own guidance is to retry these with
# exponential backoff rather than treat them as failures. Without this, a
# single unlucky 503 on the very first call killed the whole daily run.
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = int(os.environ.get("SHEETS_MAX_ATTEMPTS", "6"))
BASE_DELAY_SECONDS = 2.0
MAX_DELAY_SECONDS = 60.0

# Cells per batch_update / batch_format request. Google lists high request
# complexity as a 503 trigger, so the per-run write is split rather than
# sent as one ~320-range call.
BATCH_CHUNK_SIZE = int(os.environ.get("SHEETS_BATCH_CHUNK_SIZE", "50"))


def _status_code(exc: APIError):
    """Best-effort HTTP status out of a gspread APIError."""
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    if code:
        return code
    try:
        return response.json()["error"]["code"]
    except Exception:
        return None


def _call(label: str, fn, *args, **kwargs):
    """Run a Sheets API call, retrying transient errors with backoff."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn(*args, **kwargs)
        except APIError as exc:
            status = _status_code(exc)
            if status not in RETRYABLE_STATUSES or attempt == MAX_ATTEMPTS:
                raise
            reason = f"HTTP {status}"
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            reason = type(exc).__name__

        delay = min(BASE_DELAY_SECONDS * (2 ** (attempt - 1)), MAX_DELAY_SECONDS)
        delay += random.uniform(0, 1)  # jitter, so retries don't sync up
        print(
            f"[sheets_writer] {label} failed ({reason}), attempt {attempt}/{MAX_ATTEMPTS} "
            f"- retrying in {delay:.1f}s",
            flush=True,
        )
        time.sleep(delay)


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _get_client() -> gspread.Client:
    raw_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        info = json.loads(raw_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        file_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service-account.json")
        creds = Credentials.from_service_account_file(file_path, scopes=SCOPES)
    return gspread.authorize(creds)


# Opened once per process: auth + open_by_key + worksheet were previously
# re-run for both read_items() and write_results(), doubling the number of
# calls that could hit a transient 503.
_WORKSHEET = None
_LAYOUT_CHECKED = False


def get_worksheet():
    global _WORKSHEET
    if _WORKSHEET is not None:
        return _WORKSHEET
    client = _get_client()
    sh = _call("open spreadsheet", client.open_by_key, SHEET_ID)
    _WORKSHEET = _call("open worksheet tab", sh.worksheet, SHEET_TAB)
    return _WORKSHEET


def normalize_layout(ws):
    """
    Ensure the sheet has the correct header, item codes in column B, and a
    frozen header row - repairing it first if it's in a broken or mixed
    state. Call this before read_items()/write_results() on every run.
    """
    global _LAYOUT_CHECKED
    if _LAYOUT_CHECKED:
        # Already verified earlier in this run; re-reading the whole sheet a
        # second time only adds another chance to hit a transient error.
        return

    all_values = _call("read sheet", ws.get_all_values)

    b_column = [row[1] if len(row) > 1 else "" for row in all_values[1:1 + len(CANONICAL_ITEMS)]]
    matches = sum(1 for i, item in enumerate(CANONICAL_ITEMS[:20]) if i < len(b_column) and b_column[i] == item)

    if matches >= MIN_HEALTHY_MATCHES:
        # Layout already looks right - just make sure header/freeze are set.
        if all_values and all_values[0] != HEADER:
            _call("write header", ws.update, "A1", [HEADER])
        _call("freeze header row", ws.freeze, rows=1)
        _LAYOUT_CHECKED = True
        return

    print(
        f"[sheets_writer] Layout looks broken ({matches}/20 items found in the "
        f"expected place) - rebuilding from the canonical item list.",
        flush=True,
    )
    rows = [HEADER] + [["", item] + [""] * (NUM_COLUMNS - 2) for item in CANONICAL_ITEMS]
    _call("clear sheet", ws.clear)
    _call("rebuild sheet", ws.update, "A1", rows)
    _call("freeze header row", ws.freeze, rows=1)
    _LAYOUT_CHECKED = True


def read_items() -> list:
    ws = get_worksheet()
    normalize_layout(ws)
    col_b = _call("read column B", ws.col_values, 2)
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


RED_HIGHLIGHT = {"backgroundColor": {"red": 0.957, "green": 0.706, "blue": 0.694}}
NO_HIGHLIGHT = {"backgroundColor": {"red": 1, "green": 1, "blue": 1}}


def _they_have_stock_we_dont(their_availability: str, our_availability: str) -> bool:
    return their_availability == "In Stock" and our_availability != "In Stock"


def _lowest_overall(row: dict) -> tuple:
    """Among OUR price and every competitor's price (whichever are valid
    numbers), return (price_str, website_label, link) for the cheapest,
    or ("", "", "") if nothing has a valid price. Previously this only
    compared competitors, so it could show a competitor as "lowest" even
    when our own price was actually lower - now "Us" wins fairly."""
    candidates = {"our": row["our"]}
    candidates.update({key: row[key] for key in COMPETITORS})

    best_price = None
    best_key = None
    for key, data in candidates.items():
        try:
            price = float(data.get("price", ""))
        except (TypeError, ValueError):
            continue
        if best_price is None or price < best_price:
            best_price = price
            best_key = key

    if best_key is None:
        return "", "", ""
    label = "Us" if best_key == "our" else COMPETITOR_LABELS[best_key]
    return f"{best_price:.2f}", label, candidates[best_key].get("link", "")


def write_results(rows: list):
    """
    rows: list of dicts, each:
    {
        "item": str,
        "our": {"price", "availability", "link", "sku"},
        "extra": {"price", "availability", "link"},
        "jarir": {"price", "availability", "link"},
        "qomra": {"price", "availability", "link"},
        "grandstores": {"price", "availability", "link"},
    }
    Writes in the same row order as the item appears in column B.
    """
    ws = get_worksheet()
    normalize_layout(ws)

    existing_items = _call("read column B", ws.col_values, 2)[1:]
    item_to_row = {name: idx + 2 for idx, name in enumerate(existing_items)}  # +2: header + 1-index

    now_uae = datetime.now(timezone.utc).astimezone(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")  # GitHub runners are UTC; sheet notes it's UTC

    updates = []
    formats = []
    for row in rows:
        item = row["item"]
        row_num = item_to_row.get(item)
        if not row_num:
            continue  # item not found in sheet (shouldn't happen)

        our = row["our"]
        our_price = our.get("price", "")
        our_avail = our.get("availability", "")

        values = [our.get("sku", ""), our_price, our_avail, our.get("link", "")]
        for key in COMPETITORS:
            comp = row[key]
            vs_us = _compare_to_us(comp.get("price", ""), our_price)
            values += [comp.get("price", ""), comp.get("availability", ""), comp.get("link", ""), vs_us]

            # Column letters for this competitor's block: price is the
            # first column, availability the second. Was hardcoded as
            # "3 + index*4", which only happened to work back when the
            # Our block was 3 columns wide starting at index 2 (should
            # have been 2+3=5, not 3) - silently misplacing every
            # highlight by 2 columns. Derived properly now so it can't
            # drift out of sync with the Our block's actual size again.
            block_start = OUR_BLOCK_START + OUR_BLOCK_SIZE + COMPETITORS.index(key) * 4
            price_col = _COLUMN_LETTERS[block_start]
            avail_col = _COLUMN_LETTERS[block_start + 1]

            # Red highlight: competitor price is cheaper than ours, or they
            # have stock we don't. Every cell gets an explicit format each
            # run (highlighted or cleared) so a highlight never lingers
            # once the condition it flagged is no longer true.
            formats.append({"range": f"{price_col}{row_num}", "format": RED_HIGHLIGHT if vs_us == "Lower" else NO_HIGHLIGHT})
            formats.append({
                "range": f"{avail_col}{row_num}",
                "format": RED_HIGHLIGHT if _they_have_stock_we_dont(comp.get("availability", ""), our_avail) else NO_HIGHLIGHT,
            })

        lowest_price, lowest_website, lowest_link = _lowest_overall(row)
        try:
            price_diff = f"{float(lowest_price) - float(our_price):.2f}"
        except (TypeError, ValueError):
            price_diff = "N/A"
        values += [lowest_price, lowest_website, lowest_link, price_diff]

        updates.append({"range": f"A{row_num}", "values": [[now_uae]]})
        last_col = _COLUMN_LETTERS[-1]
        updates.append({"range": f"C{row_num}:{last_col}{row_num}", "values": [values]})

    for i, chunk in enumerate(_chunked(updates, BATCH_CHUNK_SIZE), start=1):
        _call(f"write values (chunk {i})", ws.batch_update, chunk)
    for i, chunk in enumerate(_chunked(formats, BATCH_CHUNK_SIZE), start=1):
        _call(f"write formatting (chunk {i})", ws.batch_format, chunk)
