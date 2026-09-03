"""
Qomra (qomra.pro) scraper.

Qomra runs on Salla (a Saudi e-commerce platform). Product cards are Salla
web components (<salla-product-card>) that only get populated with data
client-side after JS runs - the plain HTML has no product data at all.
After JS execution though, Salla itself injects a clean schema.org
ItemList (id="salla-product-schema-script") for SEO, which is exactly
what common/extract.py's JSON-LD parser already handles. So: ZenRows for
JS rendering, then the same generic JSON-LD extraction used elsewhere.

Note: the category page originally suggested
(qomra.pro/en/category/QQGwgR?filters[category_id]=335997161) is a broad
"Instant Cameras" category dominated by Lomography (a different brand) -
only 1 of 14 products there are Instax. Searching "instax" directly is far
more relevant and was used instead; Qomra's real Instax catalog is small
(~7 products) but genuine, confirmed across several query phrasings.
"""
from urllib.parse import quote_plus

from common.zenrows_client import fetch_rendered_html
from common.extract import extract_products_from_jsonld, normalize_availability, clean_price
from common.matcher import best_match

SEARCH_URL = "https://qomra.pro/en/search?q={query}"


def fetch_catalog() -> list:
    """
    Fetch Qomra's Instax search results. Returns a list of dicts:
    {title, price, availability, link}.
    """
    url = SEARCH_URL.format(query=quote_plus("instax"))
    # Salla's web-component hydration time is inconsistent - a 90s budget
    # wasn't always enough. fetch_rendered_html already retries internally
    # (see common/zenrows_client.py), so just give each attempt more room.
    html = fetch_rendered_html(url, wait_ms=8000, timeout=150)
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
