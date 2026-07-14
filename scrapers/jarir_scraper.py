"""
Jarir Bookstore KSA scraper.

Jarir runs Vue Storefront (Magento-based). Search results and product
pages are client-rendered, so we fetch through ZenRows with js_render,
then prefer JSON-LD structured data over CSS selectors (class names on
Vue Storefront builds change frequently).
"""
from urllib.parse import quote_plus

from common.zenrows_client import fetch_rendered_html
from common.extract import extract_products_from_jsonld, extract_meta_product, normalize_availability, clean_price
from common.matcher import best_match

SEARCH_URL = "https://www.jarir.com/sa-en/catalogsearch/result/?q={query}"
SEARCH_WAIT_FOR = ".product-item-link, .product-card, [class*='product-item']"


def search_product(item_name: str) -> dict:
    """
    Search Jarir for `item_name` and return the best-matching product as:
    {price, availability, link} or {price: "", availability: "Not Found", link: ""}
    """
    result = {"price": "", "availability": "Not Found", "link": ""}

    query = quote_plus(item_name)
    url = SEARCH_URL.format(query=query)

    html = fetch_rendered_html(url, wait_for=SEARCH_WAIT_FOR, wait_ms=4000)
    if not html:
        result["availability"] = "Fetch Error"
        return result

    candidates = extract_products_from_jsonld(html)

    if not candidates:
        # Fallback: this single page might itself be a product page
        # (Jarir sometimes redirects a very specific query straight to it).
        single = extract_meta_product(html, url)
        if single:
            candidates = [single]

    if not candidates:
        return result

    match, score = best_match(item_name, candidates, key=lambda c: c.get("name") or "")
    if not match:
        return result

    result["price"] = clean_price(match.get("price"))
    result["availability"] = normalize_availability(match.get("availability"))
    result["link"] = match.get("url") or url

    # If we matched via ItemList but got no price, fetch the product page itself.
    if not result["price"] and result["link"] and result["link"] != url:
        product_html = fetch_rendered_html(result["link"], wait_for=".price, [class*='price']", wait_ms=3000)
        if product_html:
            candidates2 = extract_products_from_jsonld(product_html) or []
            single = candidates2[0] if candidates2 else extract_meta_product(product_html, result["link"])
            if single:
                result["price"] = clean_price(single.get("price")) or result["price"]
                if single.get("availability"):
                    result["availability"] = normalize_availability(single.get("availability"))

    return result
