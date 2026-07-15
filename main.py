"""
Daily price-check run.

Fetches each retailer's complete Fuji Instax catalog once (a couple of
requests total), then matches every item in column A of the Google Sheet
against those fixed catalogs locally - rather than issuing a fresh search
per item per site, which risks missing a product that exists but doesn't
surface well under a guessed query phrasing.

Env vars required (see README):
    GOOGLE_SERVICE_ACCOUNT_JSON   (or GOOGLE_SERVICE_ACCOUNT_FILE for local runs)
    SHEET_ID                      (defaults to the Instax sheet)
"""
import sys

from scrapers import jarir_scraper, extra_scraper
from sheets_writer import read_items, write_results


def run():
    items = read_items()
    if not items:
        print("No items found in column A of the sheet — nothing to do.", flush=True)
        return

    print("Fetching Extra's Fuji catalog...", flush=True)
    try:
        extra_catalog = extra_scraper.fetch_catalog()
        print(f"  {len(extra_catalog)} products.", flush=True)
    except Exception as exc:
        print(f"  Extra catalog fetch failed: {exc}", flush=True)
        extra_catalog = []

    print("Fetching Jarir's Fuji catalog (includes a page fetch per product)...", flush=True)
    try:
        jarir_catalog = jarir_scraper.fetch_catalog()
        print(f"  {len(jarir_catalog)} products.", flush=True)
    except Exception as exc:
        print(f"  Jarir catalog fetch failed: {exc}", flush=True)
        jarir_catalog = []

    print(f"Matching {len(items)} items against both catalogs...", flush=True)
    results = []

    for i, item in enumerate(items, start=1):
        try:
            extra_result = extra_scraper.match_item(item, extra_catalog)
        except Exception as exc:
            print(f"  Extra match error for '{item}': {exc}", flush=True)
            extra_result = {"price": "", "availability": "Error", "link": ""}

        try:
            jarir_result = jarir_scraper.match_item(item, jarir_catalog)
        except Exception as exc:
            print(f"  Jarir match error for '{item}': {exc}", flush=True)
            jarir_result = {"price": "", "availability": "Error", "link": ""}

        print(
            f"[{i}/{len(items)}] {item} | "
            f"Extra: {extra_result['availability']} {extra_result['price']} | "
            f"Jarir: {jarir_result['availability']} {jarir_result['price']}",
            flush=True,
        )

        results.append({"item": item, "extra": extra_result, "jarir": jarir_result})

    print("Writing results back to the sheet...", flush=True)
    write_results(results)
    print("Done.", flush=True)


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)
