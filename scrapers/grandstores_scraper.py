"""
GrandStores (grandstores.sa) scraper.

GrandStores runs on Shopify, which exposes a public, paginated
/products.json endpoint - plain HTTP, no JS rendering or bot-detection
workaround needed (confirmed richer and more complete than Shopify's
/search/suggest.json, which is an autocomplete endpoint capped at ~10
results).

GrandStores bundles heavily: cameras sold with extra film packs ("+ 20
Pack Film"), gift boxes, "Joy Pack"/"Bee Happy Pack" bundles, printers
bundled with a Mini Pal camera as a "Gift", "Photo Kit" combos, etc. None
of our sheet items are bundles, so any candidate showing bundle signals
is excluded outright before matching even runs - a bundle's price/SKU
doesn't correspond to any single item on our sheet, and matching it would
silently misrepresent the price comparison. Also note: essentially all of
GrandStores' *film* listings are 50/100/120-sheet bulk packs rather than
the standard single (10-sheet) or twin (20-sheet) pack our sheet expects
- common/matcher.py's pack-size gate already treats these as a distinct
"bulk" size that won't match single/twin queries.
"""
import time

import requests

from common.matcher import best_match

PRODUCTS_URL = "https://grandstores.sa/products.json"
PAGE_LIMIT = 250
MAX_PAGES = 5
PAGE_RETRIES = 3
RETRY_BACKOFF_SECONDS = 3

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
REQUEST_TIMEOUT = 20

# Any of these appearing in a title means "this isn't a standalone
# product our sheet has an equivalent for" - reject outright. A literal
# "+" is the strongest signal (every legitimate standalone title in this
# catalog is plus-free; every bundle uses it to join camera+film,
# printer+camera, etc.).
BUNDLE_SIGNALS = ["+", "gift", "bundle", "joy pack", "happy pack", "craft box", "photo kit"]


def _is_bundle(title: str) -> bool:
    t = title.lower()
    return any(signal in t for signal in BUNDLE_SIGNALS)


def _fetch_page(page: int):
    """GET one page of products.json, retrying transient server errors.
    Returns the product list, or None if all retries failed."""
    for attempt in range(1, PAGE_RETRIES + 1):
        try:
            resp = requests.get(
                PRODUCTS_URL, params={"limit": PAGE_LIMIT, "page": page},
                headers=HEADERS, timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("products", [])
        except requests.RequestException as exc:
            print(f"[grandstores] page {page} attempt {attempt}/{PAGE_RETRIES} failed: {exc}", flush=True)
            if attempt < PAGE_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    return None


def fetch_catalog() -> list:
    """
    Fetch GrandStores' complete Instax catalog (paginating until a short
    page signals the end), excluding bundles. Returns a list of dicts:
    {title, price, availability, link}.

    A page that fails even after retries stops pagination but keeps
    whatever earlier pages already succeeded - a transient 500 on a later
    page shouldn't discard a perfectly good earlier page's worth of data.
    """
    catalog = []

    for page in range(1, MAX_PAGES + 1):
        products = _fetch_page(page)
        if products is None:
            print(f"[grandstores] giving up on page {page} - keeping {len(catalog)} products found so far.", flush=True)
            break
        if not products:
            break

        for p in products:
            title = p.get("title", "")
            if "instax" not in title.lower():
                continue
            if _is_bundle(title):
                continue

            variant = (p.get("variants") or [{}])[0]
            catalog.append({
                "title": title,
                "price": str(variant.get("price", "")),
                "availability": "In Stock" if variant.get("available") else "Out of Stock",
                "link": "https://grandstores.sa/products/" + p.get("handle", ""),
            })

        if len(products) < PAGE_LIMIT:
            break  # last page

    return catalog


def match_item(item_name: str, catalog: list) -> dict:
    """Match one sheet item against a pre-fetched catalog. Returns
    {price, availability, link}."""
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
