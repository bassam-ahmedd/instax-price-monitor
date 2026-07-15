"""
One-time migration: reorder the sheet from the old layout
(A=Item Description ... H=Last Checked (UAE Time)) to the new layout
(A=Last Checked, B=Item Description, C-H=Extra/Jarir columns), and freeze
the header row.

Safe to run more than once - it's a no-op if the sheet is already in the
new layout. Aborts without changing anything if the header doesn't match
either the expected old or new layout, so it never risks corrupting data
it doesn't recognize.

Run via the "Migrate Sheet Layout" GitHub Action (Actions tab -> Run
workflow), or locally the same way as main.py:
    export GOOGLE_SERVICE_ACCOUNT_FILE=service-account.json
    export SHEET_ID=...
    python migrate_sheet_layout.py
"""
from sheets_writer import get_worksheet, HEADER as NEW_HEADER

OLD_HEADER = [
    "Item Description",
    "Extra Price (SAR)", "Extra Availability", "Extra Link",
    "Jarir Price (SAR)", "Jarir Availability", "Jarir Link",
    "Last Checked (UAE Time)",
]


def migrate():
    ws = get_worksheet()
    all_values = ws.get_all_values()

    if not all_values:
        print("Sheet is empty - nothing to migrate.")
        return

    header = all_values[0]

    if header == NEW_HEADER:
        print("Already in the new layout.")
        ws.freeze(rows=1)
        print("Header row frozen.")
        return

    if header != OLD_HEADER:
        print(f"Header doesn't match the expected old layout.\nFound:    {header!r}\nExpected: {OLD_HEADER!r}")
        print("Aborting without changes to avoid corrupting data you may have edited by hand.")
        return

    new_rows = [NEW_HEADER]
    for row in all_values[1:]:
        row = row + [""] * (8 - len(row))  # pad any short rows
        item, ex_p, ex_a, ex_l, ja_p, ja_a, ja_l, last_checked = row[:8]
        new_rows.append([last_checked, item, ex_p, ex_a, ex_l, ja_p, ja_a, ja_l])

    ws.clear()
    ws.update("A1", new_rows)
    ws.freeze(rows=1)

    print(f"Migrated {len(new_rows) - 1} rows to the new layout and froze the header row.")


if __name__ == "__main__":
    migrate()
