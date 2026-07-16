"""
Daily price-check run.

Fetches AMT's (ours), Extra's, and Jarir's complete Fuji Instax catalogs
once each, then matches every item in column B of the Google Sheet against
those fixed catalogs locally - rather than issuing a fresh search per item
per site, which risks missing a product that exists but doesn't surface
well under a guessed query phrasing. sheets_writer.write_results() also
computes whether each competitor is priced higher/lower/same as us.

Env vars required (see README):
    ZENROWS_API_KEY               (AMT only - Extra/Jarir don't need it)
    GOOGLE_SERVICE_ACCOUNT_JSON   (or GOOGLE_SERVICE_ACCOUNT_FILE for local runs)
    SHEET_ID                      (defaults to the Instax sheet)
"""
import sys

from scrapers import amt_scraper, jarir_scraper, extra_scraper
from sheets_writer import read_items, write_results


def _fetch(label: str, fetch_fn):
    print(f"Fetching {label}'s Fuji catalog...", flush=True)
    try:
        catalog = fetch_fn()
        print(f"  {len(catalog)} products.", flush=True)
        return catalog
    except Exception as exc:
        print(f"  {label} catalog fetch failed: {exc}", flush=True)
        return []


def run():
    items = read_items()
    if not items:
        print("No items found in column B of the sheet — nothing to do.", flush=True)
        return

    amt_catalog = _fetch("AMT (ours)", amt_scraper.fetch_catalog)
    extra_catalog = _fetch("Extra", extra_scraper.fetch_catalog)
    jarir_catalog = _fetch("Jarir (includes a page fetch per product)", jarir_scraper.fetch_catalog)

    print(f"Matching {len(items)} items against all three catalogs...", flush=True)
    results = []

    for i, item in enumerate(items, start=1):
        try:
            our_result = amt_scraper.match_item(item, amt_catalog)
        except Exception as exc:
            print(f"  AMT match error for '{item}': {exc}", flush=True)
            our_result = {"price": "", "availability": "Error", "link": ""}

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
            f"Us: {our_result['availability']} {our_result['price']} | "
            f"Extra: {extra_result['availability']} {extra_result['price']} | "
            f"Jarir: {jarir_result['availability']} {jarir_result['price']}",
            flush=True,
        )

        results.append({"item": item, "our": our_result, "extra": extra_result, "jarir": jarir_result})

    print("Writing results back to the sheet...", flush=True)
    write_results(results)
    print("Done.", flush=True)


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)
