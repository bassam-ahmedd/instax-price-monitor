"""
Jarir Bookstore KSA scraper.

Jarir's search-as-you-type is powered by Constructor.io, whose public
search key ships in the page for the browser to call directly.

Rather than issuing a separate search per sheet item, we fetch Jarir's
entire Fuji catalog once with a broad "fuji" query (confirmed complete:
"fuji", "instax", and "fujifilm instax" all top out around the same ~20
real Instax products - the couple of extra hits for bare "fuji" are
unrelated "Mount Fuji" puzzles, filtered out below) and match every sheet
item against that fixed list locally.

Jarir's product pages are plain server-rendered HTML with full schema.org
JSON-LD (price + availability), so for each unique product in the catalog
we fetch its page once and cache the authoritative price/stock - much
cheaper than doing that per sheet item when several items share a
product.
"""
import requests

from common.extract import extract_products_from_jsonld, normalize_availability, clean_price
from common.matcher import best_match

CONSTRUCTOR_KEY = "key_KcSYfmQTEwRpBnd9"
CONSTRUCTOR_URL = "https://ac.cnstrc.com/search/{query}"
BASE_URL = "https://www.jarir.com/sa-en/"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
REQUEST_TIMEOUT = 20
PRODUCT_PAGE_TIMEOUT = 30


def fetch_catalog() -> list:
    """
    Fetch the complete Fuji Instax catalog from Jarir. Each entry is
    enriched with authoritative price/availability/link fetched from its
    own product page (title is kept from the search result for matching).
    """
    url = CONSTRUCTOR_URL.format(query=requests.utils.quote("fuji"))
    params = {
        "key": CONSTRUCTOR_KEY, "c": "ciojs-client-2.51.0",
        "i": "instax-price-monitor", "s": "1", "num_results_per_page": 100,
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    raw_results = resp.json().get("response", {}).get("results", [])

    catalog = []
    for r in raw_results:
        meta = r.get("data", {}).get("metadata", {})
        title = meta.get("name") or r.get("value") or ""
        slug = r.get("data", {}).get("url")
        if not title or not slug or "instax" not in title.lower():
            continue  # drop unrelated "Mount Fuji" puzzles etc.

        product_url = BASE_URL + slug
        entry = {"title": title, "link": product_url, "price": "", "availability": "Unknown"}

        html = None
        for attempt in range(2):
            try:
                resp2 = requests.get(product_url, headers=HEADERS, timeout=PRODUCT_PAGE_TIMEOUT)
                resp2.raise_for_status()
                html = resp2.text
                break
            except requests.RequestException as exc:
                print(f"[jarir] product page fetch error for '{title}' (attempt {attempt + 1}): {exc}", flush=True)

        if html:
            jsonld_products = extract_products_from_jsonld(html)
            if jsonld_products:
                p = jsonld_products[0]
                entry["price"] = clean_price(p.get("price")) or clean_price(r.get("data", {}).get("price"))
                entry["availability"] = normalize_availability(p.get("availability"))
            else:
                entry["price"] = clean_price(r.get("data", {}).get("price"))
        else:
            entry["price"] = clean_price(r.get("data", {}).get("price"))

        catalog.append(entry)

    return catalog


def match_item(item_name: str, catalog: list) -> dict:
    """Match one sheet item against a pre-fetched, pre-enriched catalog.
    Returns {price, availability, link}."""
    result = {"price": "", "availability": "Not Found", "link": ""}

    if not catalog:
        result["availability"] = "Fetch Error"
        return result

    match, score = best_match(item_name, catalog, key=lambda c: c["title"])
    if not match:
        return result

    result["price"] = match["price"]
    result["availability"] = match["availability"]
    result["link"] = match["link"]
    return result
