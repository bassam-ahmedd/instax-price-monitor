"""
Best-effort extraction of product name / price / availability / url from
rendered HTML, preferring structured data (JSON-LD, Open Graph / product
meta tags) since it's far more stable than CSS class names on SPA sites.
"""
import json
import re
from bs4 import BeautifulSoup

PRICE_RE = re.compile(r"(?:SAR|SR|ر\.س)?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:SAR|SR|ر\.س)?")


def _walk_jsonld(node):
    """Yield every dict found in a JSON-LD blob, including @graph / lists."""
    if isinstance(node, dict):
        yield node
        if "@graph" in node and isinstance(node["@graph"], list):
            for item in node["@graph"]:
                yield from _walk_jsonld(item)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)


def extract_products_from_jsonld(html: str):
    """
    Returns a list of dicts: {name, price, currency, availability, url}
    pulled from any schema.org Product / ItemList JSON-LD on the page.
    """
    soup = BeautifulSoup(html, "html.parser")
    products = []

    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        for node in _walk_jsonld(data):
            node_type = node.get("@type", "")
            types = node_type if isinstance(node_type, list) else [node_type]

            if "Product" in types:
                offers = node.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                products.append({
                    "name": node.get("name"),
                    "price": offers.get("price"),
                    "currency": offers.get("priceCurrency"),
                    "availability": offers.get("availability"),
                    "url": node.get("url") or offers.get("url"),
                })

            if "ItemList" in types:
                for element in node.get("itemListElement", []):
                    item = element.get("item", element)
                    if isinstance(item, dict) and "name" in item:
                        offers = item.get("offers", {})
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        products.append({
                            "name": item.get("name"),
                            "price": offers.get("price"),
                            "currency": offers.get("priceCurrency"),
                            "availability": offers.get("availability"),
                            "url": item.get("url"),
                        })

    return products


def extract_meta_product(html: str, base_url: str):
    """Fallback: Open Graph / product meta tags on a single product page."""
    soup = BeautifulSoup(html, "html.parser")

    def meta(prop):
        tag = soup.find("meta", {"property": prop}) or soup.find("meta", {"name": prop})
        return tag.get("content") if tag else None

    name = meta("og:title") or (soup.title.string.strip() if soup.title else None)
    price = meta("product:price:amount") or meta("og:price:amount")
    currency = meta("product:price:currency") or meta("og:price:currency")
    availability = meta("product:availability") or meta("og:availability")

    if not price:
        # last resort: scan visible text for a SAR-looking number near "price"
        text = soup.get_text(" ", strip=True)
        match = PRICE_RE.search(text)
        price = match.group(1).replace(",", "") if match else None

    if name or price:
        return {
            "name": name,
            "price": price,
            "currency": currency or "SAR",
            "availability": availability,
            "url": base_url,
        }
    return None


def normalize_availability(raw) -> str:
    if not raw:
        return "Unknown"
    raw = str(raw).lower()
    if "instock" in raw or "in stock" in raw or raw == "true":
        return "In Stock"
    if "outofstock" in raw or "out of stock" in raw or raw == "false":
        return "Out of Stock"
    if "preorder" in raw:
        return "Pre-Order"
    return "Unknown"


def clean_price(raw) -> str:
    if raw is None:
        return ""
    s = str(raw).replace(",", "").strip()
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return s
