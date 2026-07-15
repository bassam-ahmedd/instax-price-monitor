"""
Extra.com KSA scraper.

Extra's storefront search is powered by Unbxd, a third-party search-as-a-
service whose API key/site key are shipped in the page for the *browser*
to call directly (ACC.config.unbxdSearchConfig). We call the same public
endpoint ourselves - no JS rendering or bot-detection workarounds needed,
and the response already contains price, stock, and the product URL.
"""
import requests

from common.matcher import best_match, clean_query

UNBXD_API_KEY = "21705619e273429e5767eea44ccb1ad5"
UNBXD_SITE_KEY = "ss-unbxd-auk-extra-saudi-en-prod11541714990488"
UNBXD_URL = f"https://search.unbxd.io/{UNBXD_API_KEY}/{UNBXD_SITE_KEY}/search"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
REQUEST_TIMEOUT = 20


def search_product(item_name: str) -> dict:
    """
    Search Extra (via Unbxd) for `item_name` and return the best-matching
    product as {price, availability, link}.
    """
    result = {"price": "", "availability": "Not Found", "link": ""}

    params = {"q": clean_query(item_name), "rows": 30}
    try:
        resp = requests.get(UNBXD_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"[extra] fetch error for '{item_name}': {exc}", flush=True)
        result["availability"] = "Fetch Error"
        return result

    products = [p for p in data.get("response", {}).get("products", []) if p.get("type") == "PRODUCT"]
    if not products:
        return result

    match, score = best_match(item_name, products, key=lambda p: p.get("title") or p.get("nameEn") or "")
    if not match:
        return result

    price = match.get("sellingPrice") or match.get("price")
    result["price"] = f"{float(price):.2f}" if price is not None else ""

    in_stock = match.get("inStockFlag")
    if in_stock is None:
        in_stock = match.get("available")
    result["availability"] = "In Stock" if in_stock else "Out of Stock"

    link = match.get("productUrl")
    if not link and match.get("urlEn"):
        link = "https://www.extra.com/en-sa" + match["urlEn"]
    result["link"] = link or ""

    return result
