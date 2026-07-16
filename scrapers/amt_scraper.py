"""
AMT (ksa.amt.tv) scraper - this is "our" site, used as the price baseline
that Extra/Jarir get compared against.

Unlike Extra/Jarir (which have public search APIs their frontends call
directly), AMT's Magento storefront is behind Cloudflare bot protection,
so this goes through ZenRows with JS rendering. Prefers JSON-LD structured
data when present, falling back to Magento's typical product-grid markup.
"""
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from common.zenrows_client import fetch_rendered_html
from common.extract import extract_products_from_jsonld, normalize_availability, clean_price
from common.matcher import best_match

SEARCH_URL = "https://ksa.amt.tv/catalogsearch/result/index/?p={page}&q={query}"
MAX_PAGES = 4


def _extract_from_html(html: str) -> list:
    """Fallback: parse Magento's typical product-grid markup directly when
    no JSON-LD is present on the page."""
    soup = BeautifulSoup(html, "html.parser")
    products = []

    for item in soup.select(".product-item"):
        link_tag = item.select_one("a.product-item-link")
        if not link_tag:
            continue
        name = " ".join(link_tag.get_text(" ", strip=True).split())
        link = link_tag.get("href")

        price_tag = item.select_one("[data-price-amount]")
        price = price_tag.get("data-price-amount") if price_tag else None

        out_of_stock = bool(item.select_one(".stock.unavailable, .out-of-stock"))
        availability = "OutOfStock" if out_of_stock else "InStock"

        products.append({"name": name, "price": price, "availability": availability, "url": link})

    return products


def fetch_catalog() -> list:
    """
    Fetch AMT's Instax search results, paginating a few pages if present.
    Returns a list of dicts: {title, price, availability, link}.
    """
    catalog = []
    seen_links = set()

    for page in range(1, MAX_PAGES + 1):
        url = SEARCH_URL.format(page=page, query=quote_plus("instax"))
        html = fetch_rendered_html(url)
        if not html:
            break

        raw_products = extract_products_from_jsonld(html) or _extract_from_html(html)
        if not raw_products:
            break

        new_count = 0
        for p in raw_products:
            link = p.get("url")
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            catalog.append({
                "title": p.get("name") or "",
                "price": clean_price(p.get("price")),
                "availability": normalize_availability(p.get("availability")),
                "link": link,
            })
            new_count += 1

        if new_count == 0:
            break  # nothing new on this page - stop paginating

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
