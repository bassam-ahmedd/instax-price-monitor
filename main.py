"""
Daily price-check run.

For every item in column A of the Google Sheet, search Extra and Jarir,
extract price / availability / link, and write the results back.

Env vars required (see README):
    ZENROWS_API_KEY
    GOOGLE_SERVICE_ACCOUNT_JSON   (or GOOGLE_SERVICE_ACCOUNT_FILE for local runs)
    SHEET_ID                      (defaults to the Instax sheet)
"""
import sys
import time

from scrapers import jarir_scraper, extra_scraper
from sheets_writer import read_items, write_results

SLEEP_BETWEEN_ITEMS_SECONDS = 1  # be polite / avoid rate limits


def run():
    items = read_items()
    if not items:
        print("No items found in column A of the sheet — nothing to do.")
        return

    print(f"Checking {len(items)} items across Extra and Jarir...")
    results = []

    for i, item in enumerate(items, start=1):
        print(f"[{i}/{len(items)}] {item}")

        try:
            extra_result = extra_scraper.search_product(item)
        except Exception as exc:  # keep going even if one site/item fails
            print(f"  Extra error: {exc}")
            extra_result = {"price": "", "availability": "Error", "link": ""}

        try:
            jarir_result = jarir_scraper.search_product(item)
        except Exception as exc:
            print(f"  Jarir error: {exc}")
            jarir_result = {"price": "", "availability": "Error", "link": ""}

        print(f"  Extra: {extra_result['availability']} {extra_result['price']}")
        print(f"  Jarir: {jarir_result['availability']} {jarir_result['price']}")

        results.append({"item": item, "extra": extra_result, "jarir": jarir_result})
        time.sleep(SLEEP_BETWEEN_ITEMS_SECONDS)

    print("Writing results back to the sheet...")
    write_results(results)
    print("Done.")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)
