# Instax Price Monitor

Daily price/availability/link check for 54 Fujifilm Instax items (cameras,
printers, film) across **Extra.com (KSA)** and **Jarir.com (KSA)**, written
back into a Google Sheet.

- Sheet: column A holds the item descriptions (already populated).
  Columns B–H are written by the script: Extra Price / Availability / Link,
  Jarir Price / Availability / Link, Last Checked.
- Scraping goes through **ZenRows** (JS rendering + premium proxy) since
  both sites are bot-protected SPAs — plain requests get blocked/redirected.
- Runs automatically every day at **10:00 AM UAE time** via GitHub Actions
  (`.github/workflows/daily-scrape.yml`), and can also be triggered manually
  from the Actions tab ("Run workflow").

## One-time setup

### 1. Push this repo to GitHub
```bash
cd instax-price-monitor
git add -A
git commit -m "Initial Instax price monitor"
git branch -M main
git remote add origin https://github.com/<your-username>/instax-price-monitor.git
git push -u origin main
```

### 2. Add repo secrets
Go to **Settings → Secrets and variables → Actions → New repository secret**
and add:

| Secret name | Value |
|---|---|
| `ZENROWS_API_KEY` | Your ZenRows API key |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The **full contents** of your service-account JSON key file (paste the whole JSON) |
| `SHEET_ID` | `1x0ywQLO_QAp6sXesGGa44_99Bs2RtSjMLKiHgSIy_VA` |

The service account's `client_email` must already have **Editor** access on
the sheet (share the sheet with that email if you haven't).

### 3. Test it
From the repo's **Actions** tab, select "Daily Instax Price Check" →
**Run workflow** to trigger it manually and confirm the sheet updates.

## Running locally
```bash
pip install -r requirements.txt
export ZENROWS_API_KEY=...
export GOOGLE_SERVICE_ACCOUNT_FILE=service-account.json   # path to the key file
export SHEET_ID=1x0ywQLO_QAp6sXesGGa44_99Bs2RtSjMLKiHgSIy_VA
python main.py
```

## Notes / known limitations
- Both sites' product titles are matched to the sheet's item description with
  fuzzy matching (`common/matcher.py`). If a wrong product gets matched, tune
  the `threshold` in `best_match()` or add a manual override map.
- Extraction prefers each site's JSON-LD structured data over CSS selectors,
  since SPA class names change often — this should stay more resilient than
  a class-based scraper, but the *first real run* should be checked closely
  and selectors/thresholds adjusted for any items that come back "Not Found".
- GitHub-hosted runners are UTC; the "Last Checked" column is stored in UTC
  for consistency, with the run itself scheduled for 10:00 AM UAE (06:00 UTC).
