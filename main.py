"""
Daily price-check run.

Fetches AMT's (ours), Extra's, Jarir's, and Qomra's complete Fuji Instax
catalogs once each, then matches every item in column B of the Google
Sheet against those fixed catalogs locally - rather than issuing a fresh
search per item per site, which risks missing a product that exists but
doesn't surface well under a guessed query phrasing.
sheets_writer.write_results() also computes whether each competitor is
priced higher/lower/same as us, and highlights cells accordingly. After
writing, notify.send_alert() posts any cheaper-than-us items to the n8n
"Instax Daily Price Alert" workflow, which emails a summary if any exist.

Env vars required (see README):
    ZENROWS_API_KEY               (AMT and Qomra only - Extra/Jarir don't need it)
    GOOGLE_SERVICE_ACCOUNT_JSON   (or GOOGLE_SERVICE_ACCOUNT_FILE for local runs)
    SHEET_ID                      (defaults to the Instax sheet)
    N8N_WEBHOOK_URL                (optional - price alert is skipped if unset)
"""
import sys

import notify
from scrapers import amt_scraper, extra_scraper, jarir_scraper, qomra_scraper
from sheets_writer import COMPETITORS, read_items, write_results

# Maps sheets_writer.COMPETITORS keys to their scraper module.
COMPETITOR_SCRAPERS = {
    "extra": extra_scraper,
    "jarir": jarir_scraper,
    "qomra": qomra_scraper,
}


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
    competitor_catalogs = {
        key: _fetch(key.capitalize(), COMPETITOR_SCRAPERS[key].fetch_catalog)
        for key in COMPETITORS
    }

    print(f"Matching {len(items)} items against all catalogs...", flush=True)
    results = []

    for i, item in enumerate(items, start=1):
        try:
            our_result = amt_scraper.match_item(item, amt_catalog)
        except Exception as exc:
            print(f"  AMT match error for '{item}': {exc}", flush=True)
            our_result = {"price": "", "availability": "Error", "link": ""}

        row = {"item": item, "our": our_result}
        summary = f"Us: {our_result['availability']} {our_result['price']}"

        for key in COMPETITORS:
            try:
                result = COMPETITOR_SCRAPERS[key].match_item(item, competitor_catalogs[key])
            except Exception as exc:
                print(f"  {key.capitalize()} match error for '{item}': {exc}", flush=True)
                result = {"price": "", "availability": "Error", "link": ""}
            row[key] = result
            summary += f" | {key.capitalize()}: {result['availability']} {result['price']}"

        print(f"[{i}/{len(items)}] {item} | {summary}", flush=True)
        results.append(row)

    print("Writing results back to the sheet...", flush=True)
    write_results(results)

    print("Sending price alert...", flush=True)
    notify.send_alert(results)

    print("Done.", flush=True)


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)
