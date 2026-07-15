"""
Extra.com KSA scraper.

Extra's storefront search is powered by Unbxd, a third-party search-as-a-
service whose API key/site key are shipped in the page for the *browser*
to call directly (ACC.config.unbxdSearchConfig). We call the same public
endpoint ourselves - no JS rendering or bot-detection workarounds needed.

Rather than issuing a separate search per sheet item (54 API calls, each
hoping the query phrasing surfaces the right product), we fetch Extra's
*entire* Fuji catalog once - confirmed complete at 37 products by cross-
checking that "fujifilm", "instax", and "fujifilm instax" all return the
same 37 results - and match every sheet item against that fixed list
locally. Faster, and guarantees we're not missing a product due to a bad
query guess.
"""
import requests

from common.matcher import best_match

UNBXD_API_KEY = "21705619e273429e5767eea44ccb1ad5"
UNBXD_SITE_KEY = "ss-unbxd-auk-extra-saudi-en-prod11541714990488"
UNBXD_URL = f"https://search.unbxd.io/{UNBXD_API_KEY}/{UNBXD_SITE_KEY}/search"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
REQUEST_TIMEOUT = 20


def fetch_catalog() -> list:
    """Fetch the complete Fuji Instax catalog from Extra (~37 products)."""
    params = {"q": "fujifilm instax", "rows": 100}
    resp = requests.get(UNBXD_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return [p for p in data.get("response", {}).get("products", []) if p.get("type") == "PRODUCT"]


def match_item(item_name: str, catalog: list) -> dict:
    """Match one sheet item against a pre-fetched catalog. Returns
    {price, availability, link}."""
    result = {"price": "", "availability": "Not Found", "link": ""}

    if not catalog:
        result["availability"] = "Fetch Error"
        return result

    match, score = best_match(item_name, catalog, key=lambda p: p.get("title") or p.get("nameEn") or "")
    if not match:
        return result

    price = match.get("sellingPrice") or match.get("price")
    result["price"] = f"{float(price):.2f}" if price is not None else ""

    in_stock = match.get("inStockFlag")
    if in_stock is None:
        in_stock = match.get("available")
    # The API returns this as the STRING "true"/"false", not a real JSON
    # boolean - a naive truthy check would treat every non-empty string
    # (including the string "false") as in-stock. Handle both string and
    # real-boolean forms explicitly.
    if isinstance(in_stock, str):
        in_stock = in_stock.strip().lower() == "true"
    result["availability"] = "In Stock" if in_stock else "Out of Stock"

    link = match.get("productUrl")
    if not link and match.get("urlEn"):
        link = "https://www.extra.com/en-sa" + match["urlEn"]
    result["link"] = link or ""

    return result
