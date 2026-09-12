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
import random
import re
import time

import requests

from common.matcher import best_match

PRODUCTS_URL = "https://grandstores.sa/products.json"
PAGE_LIMIT = 250
MAX_PAGES = 5
PAGE_RETRIES = 3
RETRY_BACKOFF_SECONDS = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
REQUEST_TIMEOUT = 20

# Any of these appearing in a title means "this isn't a standalone
# product our sheet has an equivalent for" - reject outright. A literal
# "+" is the strongest signal (every legitimate standalone title in this
# catalog is plus-free; every bundle uses it to join camera+film,
# printer+camera, etc.).
# Any of these appearing in a title means "this isn't a standalone
# product our sheet has an equivalent for" - reject outright. A spaced
# "+" (e.g. "Camera + Film") is the strongest signal - every legitimate
# standalone title in this catalog either has no "+" or uses it attached
# to a word as part of the product's own name (e.g. "LiPlay+", Fuji's
# real "Plus" model - not a bundle join). An attached "+" is deliberately
# NOT treated as a bundle signal for that reason.
PLAIN_BUNDLE_SIGNALS = ["gift", "bundle", "joy pack", "happy pack", "craft box", "photo kit"]
SPACED_PLUS_RE = re.compile(r"\s\+\s")


def _is_bundle(title: str) -> bool:
    t = title.lower()
    if any(signal in t for signal in PLAIN_BUNDLE_SIGNALS):
        return True
    return bool(SPACED_PLUS_RE.search(title))


def _fetch_page(page: int):
    """GET one page of products.json, retrying transient server errors.
    Returns the product list, or None if all retries failed."""
    for attempt in range(1, PAGE_RETRIES + 1):
        try:
            resp = requests.get(
                PRODUCTS_URL,
                params={"limit": PAGE_LIMIT, "page": page, "_cb": random.randint(1, 10_000_000)},
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

    Some products (e.g. "Instax Mini 12 Instant Film Camera") group every
    color as a *variant* of one listing with a shared, color-neutral
    title - the color only appears in each variant's own "title"/"option1"
    field. Others (most SQ1/PAL listings) give each color its own separate
    product with the color already baked into the title, where Shopify
    uses the placeholder variant title "Default Title". Every variant is
    expanded into its own catalog entry, with the variant's own title
    appended only when it's real color info (not "Default Title") and not
    already present in the base title - otherwise only the first color
    variant's price/availability was ever captured and every other color
    silently vanished (couldn't match on color at all, since the shared
    title has no color word in it).
    """
    catalog = []
    total_raw_products = 0

    for page in range(1, MAX_PAGES + 1):
        products = _fetch_page(page)
        if products is None:
            print(f"[grandstores] giving up on page {page} - keeping {len(catalog)} products found so far.", flush=True)
            break
        if not products:
            break

        total_raw_products += len(products)
        print(f"[grandstores] page {page}: {len(products)} raw products.", flush=True)

        for p in products:
            title = p.get("title", "")
            if "instax" not in title.lower():
                continue
            if _is_bundle(title):
                continue

            base_url = "https://grandstores.sa/products/" + p.get("handle", "")

            variants = p.get("variants") or [{}]
            if p.get("handle") == "instax-mini-12-instant-film-camera":
                # Diagnostic: this exact product's variant count differed
                # between a local test (5 variants, correct) and the last
                # two real GitHub Actions runs (behaved like 1 variant) -
                # confirming whether that's still happening here.
                print(f"[grandstores] DIAGNOSTIC instax-mini-12-instant-film-camera: {len(variants)} variant(s) -> {[v.get('title') for v in variants]}", flush=True)

            for variant in variants:
                variant_title = (variant.get("title") or "").strip()
                if variant_title and variant_title != "Default Title" and variant_title.lower() not in title.lower():
                    full_title = f"{title} {variant_title}"
                else:
                    full_title = title

                variant_id = variant.get("id")
                link = f"{base_url}?variant={variant_id}" if variant_id else base_url

                catalog.append({
                    "title": full_title,
                    "price": str(variant.get("price", "")),
                    "availability": "In Stock" if variant.get("available") else "Out of Stock",
                    "link": link,
                })

        if len(products) < PAGE_LIMIT:
            break  # last page

    print(f"[grandstores] {total_raw_products} raw products scanned, {len(catalog)} Instax catalog entries built.", flush=True)
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
