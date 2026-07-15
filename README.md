# Instax Price Monitor

Daily price/availability/link check for 54 Fujifilm Instax items (cameras,
printers, film) across **Extra.com (KSA)** and **Jarir.com (KSA)**, written
back into a Google Sheet.

- Sheet layout: **A**=Last Checked, **B**=Item Description (your item codes,
  e.g. "INSTAX SQR SQ1 ORG"), **C-E**=Extra (Price/Availability/Link),
  **F-H**=Jarir (Price/Availability/Link). Header row is frozen.
- Runs automatically every day at **10:00 AM UAE time** via GitHub Actions
  (`.github/workflows/daily-scrape.yml`), and can also be triggered manually
  from the Actions tab ("Run workflow").

## How it works

Both retailers' storefronts are JS-heavy SPAs, but each exposes a public
search API that their own frontend calls from the browser - so this project
talks to those APIs directly instead of rendering pages with a headless
browser or scraping service:

- **Extra**: [Unbxd](https://unbxd.com) search-as-a-service (`scrapers/extra_scraper.py`).
- **Jarir**: [Constructor.io](https://constructor.io) search (`scrapers/jarir_scraper.py`),
  then a plain HTTP fetch of each product's page - Jarir's product pages are
  server-rendered with full schema.org JSON-LD (price + `InStock`/`OutOfStock`).

Rather than issuing a fresh search per sheet item (54 separate guesses at
query phrasing per site), `main.py` fetches each retailer's **complete Fuji
Instax catalog once** - confirmed complete by cross-checking that several
different broad queries ("fuji", "instax", "fujifilm instax") all return the
same result set (37 products on Extra, 20 on Jarir) - and matches every
sheet item against that fixed local list. Faster, and immune to a specific
item's query phrasing happening to miss a product that does exist.

`common/matcher.py` matches our abbreviated item codes (see below) against
each site's product titles, with several hard gates that must all pass
before a text-similarity score is even considered:
- **Brand gate**: candidate must be Fuji/Instax branded (closes off
  collisions like "TP-LINK" routers matching a "Link" printer query, or
  Canon/Epson printers matching a generic "printer" query).
- **Category gate**: camera / film / printer never cross-match.
- **Model-number gate**: e.g. "SQ1" never matches "SQ40" (digit runs must
  overlap). Careful not to over-match "SQ" itself here - see the code
  comment on the SQ6-accessory collision below.
- **Content-word gate**: every meaningful word in the query (product line
  like "square", sub-model like "evo"/"liplay", pattern name like
  "rainbow") must literally appear in the candidate. This is what actually
  prevents false matches once the catalog is small - *something* always has
  the highest fuzzy score even when it's wrong.
- **Color gate**: if the query names a color, the candidate must share it.

### The sheet's abbreviated codes

The live sheet uses codes like "INSTAX SQR SQ1 ORG" and "MINI HRT
SKTCH-SINGLE FILM", not full product names. `ABBREVIATIONS` in
`common/matcher.py` expands these (confirmed against the original sourcing
spreadsheet as the answer key) - e.g. `SQR`→square, `ORG`→orange,
`BL`→blue, `BK`→black, `HRT SKTCH`→heart sketch. It also fixes two retailer-
specific naming quirks: Extra lists the "Macaron" film pattern as "Macron"
(their typo), and lists the Pink Evo as "Rose".

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

### 2. Migrate the sheet layout (one-time, only if your sheet still has
the old column order)
From the repo's **Actions** tab, select "Migrate Sheet Layout" → **Run
workflow**. It moves "Last Checked" to column A, shifts your item codes to
column B, and freezes the header row. Safe to run more than once - it's a
no-op if already migrated, and aborts without changes if it doesn't
recognize the current layout.

### 3. Test it
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
- A "Not Found" result means the item genuinely isn't in that retailer's
  catalog under this brand search (verified by dumping and manually
  reviewing both complete catalogs) - not a matching failure. As of this
  writing Jarir's entire Fuji Instax catalog is only ~20 products, so most
  SQ-series, PAL, and printer items are correctly absent there.
- The matching gates above are intentionally strict, trading coverage for
  accuracy - a wrong price/link in the sheet is worse than a blank one.
- Extra's API returns stock status as the **string** `"true"`/`"false"`,
  not a real boolean - `extra_scraper.py` parses it explicitly. A naive
  truthy check on that field would silently mark everything "In Stock".
- Jarir's product pages are large (~3MB), so that fetch has a generous
  timeout with one retry; if it still fails, price falls back to
  Constructor.io's own price field and availability is marked "Unknown".
- Both search APIs are called directly with their existing public keys
  (shipped in each site's own frontend JS) - no authentication or scraping
  credentials of ours involved.
