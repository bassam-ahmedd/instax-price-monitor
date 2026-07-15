# Instax Price Monitor

Daily price/availability/link check for 54 Fujifilm Instax items (cameras,
printers, film) across **Extra.com (KSA)** and **Jarir.com (KSA)**, written
back into a Google Sheet.

- Sheet: column A holds the item descriptions (already populated).
  Columns B–H are written by the script: Extra Price / Availability / Link,
  Jarir Price / Availability / Link, Last Checked.
- Runs automatically every day at **10:00 AM UAE time** via GitHub Actions
  (`.github/workflows/daily-scrape.yml`), and can also be triggered manually
  from the Actions tab ("Run workflow").

## How it works

Both retailers' storefronts are JS-heavy SPAs, but each exposes a public
search API that their own frontend calls from the browser - so this project
talks to those APIs directly instead of rendering pages with a headless
browser or scraping service:

- **Extra**: [Unbxd](https://unbxd.com) search-as-a-service (`scrapers/extra_scraper.py`).
  The response already includes price, stock, and the product URL.
- **Jarir**: [Constructor.io](https://constructor.io) search (`scrapers/jarir_scraper.py`)
  to find the matching product's URL, then a plain HTTP fetch of that
  product page - Jarir's product pages are server-rendered with full
  schema.org JSON-LD (price + `InStock`/`OutOfStock`).

No JS rendering, no third-party scraping proxy, no bot-detection workarounds
- both are plain, fast HTTP requests. `common/matcher.py` fuzzy-matches our
item descriptions against each site's results, with two hard gates on top
of the text score: a **category** gate (camera / film / printer never
cross-match) and a **model-number** gate (e.g. "SQ1" never matches "SQ40").

## One-time setup

### 1. Add repo secrets
Go to **Settings → Secrets and variables → Actions → New repository secret**
and add:

| Secret name | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The **full contents** of your service-account JSON key file (paste the whole JSON) |
| `SHEET_ID` | `1x0ywQLO_QAp6sXesGGa44_99Bs2RtSjMLKiHgSIy_VA` |

The service account's `client_email` must already have **Editor** access on
the sheet (share the sheet with that email if you haven't).

### 2. Test it
From the repo's **Actions** tab, select "Daily Instax Price Check" →
**Run workflow** to trigger it manually and confirm the sheet updates.

## Running locally
```bash
pip install -r requirements.txt
export GOOGLE_SERVICE_ACCOUNT_FILE=service-account.json   # path to the key file
export SHEET_ID=1x0ywQLO_QAp6sXesGGa44_99Bs2RtSjMLKiHgSIy_VA
python main.py
```

## Notes / known limitations
- Some items legitimately aren't carried by one or both retailers (a
  specific colorway, a discontinued SKU) - those correctly show "Not Found"
  rather than a wrong match. The category/model-number gates are
  intentionally strict to avoid false matches; this trades a bit of
  coverage for accuracy.
- Jarir's product pages are large (~3MB), so that fetch has a generous
  timeout with one retry; if it still fails, price falls back to
  Constructor.io's own price field and availability is marked "Unknown".
- Both search APIs are called directly with their existing public keys
  (shipped in each site's own frontend JS) - no authentication or scraping
  credentials of ours involved.
