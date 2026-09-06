"""
Qomra (qomra.pro) scraper.

Qomra runs on Salla (a Saudi e-commerce platform). The search *listing*
is built from <salla-product-card> web components with no server-rendered
product data, which is why this originally went through ZenRows for JS
rendering. That route turned out to be both slow (45-200s) and flaky -
ZenRows intermittently answers 422 RESP001 ("Could not get content"),
which silently produced an empty catalog and a whole column of
"Fetch Error" in the sheet.

Salla exposes the same data through the public storefront API its own
frontend uses (api.salla.dev, keyed by the store identifier), which needs
no JS rendering and answers in well under a second. The search endpoint
returns name/price/url but not stock, so availability comes from each
product page's server-rendered schema.org JSON-LD - also plain HTML, no
JS. That's 8 fast requests instead of one 200s browser render.

ZenRows is kept as a fallback for the case where the API shape changes or
the runner's IP gets blocked outright.

Note: Qomra's real Instax catalog is small (7 products) but genuine -
the API and the old ZenRows route agree exactly on that set. The broad
"Instant Cameras" category is mostly Lomography, a different brand, which
is why this searches "instax" rather than scraping that category.
"""
from urllib.parse import quote_plus

import requests

from common.zenrows_client import fetch_rendered_html
from common.extract import extract_products_from_jsonld, normalize_availability, clean_price
from common.matcher import best_match

SEARCH_URL = "https://qomra.pro/en/search?q={query}"

# Salla storefront API - the same endpoint qomra.pro's own frontend calls.
SALLA_SEARCH_API = "https://api.salla.dev/store/v1/products/search"
SALLA_STORE_ID = "11866705"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
API_TIMEOUT = 30
PRODUCT_PAGE_TIMEOUT = 25


def _product_availability(url: str) -> str:
    """Read stock status off a product page's server-rendered JSON-LD."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=PRODUCT_PAGE_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[qomra] availability lookup failed for {url}: {exc}", flush=True)
        return "Unknown"

    for product in extract_products_from_jsonld(resp.text):
        if product.get("availability"):
            return normalize_availability(product["availability"])
    return "Unknown"


def _fetch_via_api() -> list:
    """Primary route: Salla's public storefront search API."""
    resp = requests.get(
        SALLA_SEARCH_API,
        params={"query": "instax", "per_page": 50},
        headers={
            "store-identifier": SALLA_STORE_ID,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        timeout=API_TIMEOUT,
    )
    resp.raise_for_status()
    items = resp.json().get("data", [])

    catalog = []
    seen_links = set()
    for item in items:
        name = item.get("name") or ""
        link = item.get("url") or ""
        if not name or not link or link in seen_links:
            continue
        if "instax" not in name.lower():
            continue
        seen_links.add(link)
        catalog.append({
            "title": name,
            "price": clean_price(item.get("price")),
            "availability": _product_availability(link),
            "link": link,
        })
    return catalog


def fetch_catalog() -> list:
    """
    Fetch Qomra's Instax search results. Returns a list of dicts:
    {title, price, availability, link}.
    """
    try:
        catalog = _fetch_via_api()
        if catalog:
            return catalog
        print("[qomra] API returned no Instax products - falling back to ZenRows.", flush=True)
    except (requests.RequestException, ValueError) as exc:
        print(f"[qomra] API route failed ({exc}) - falling back to ZenRows.", flush=True)

    url = SEARCH_URL.format(query=quote_plus("instax"))
    # Salla's web-component hydration time is highly inconsistent - a
    # single attempt has been observed taking anywhere from ~45s to over
    # 100s. Use a generous per-attempt timeout with only 2 retries rather
    # than the default 3, since more short-timeout attempts don't help
    # when the bottleneck is per-attempt latency, not attempt count.
    html = fetch_rendered_html(url, wait_ms=8000, timeout=200, max_retries=2)
    if not html:
        return []

    raw_products = extract_products_from_jsonld(html)

    catalog = []
    seen_links = set()
    for p in raw_products:
        name = p.get("name") or ""
        link = p.get("url")
        if not name or not link or link in seen_links:
            continue
        if "instax" not in name.lower():
            continue  # drop unrelated brands (mostly Lomography) that share the "instant camera" search space
        seen_links.add(link)
        catalog.append({
            "title": name,
            "price": clean_price(p.get("price")),
            "availability": normalize_availability(p.get("availability")),
            "link": link,
        })

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
