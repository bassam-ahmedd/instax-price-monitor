"""
Jarir Bookstore KSA scraper.

Jarir's search-as-you-type is powered by Constructor.io, whose public
autocomplete/search key ships in the page for the browser to call
directly. We use that to find the right product's URL slug, then fetch
the product page itself with a plain HTTP request - Jarir product pages
are server-rendered and include full schema.org JSON-LD (price +
availability), so no JS rendering is needed anywhere in this flow.
"""
import requests

from common.extract import extract_products_from_jsonld, normalize_availability, clean_price
from common.matcher import best_match, clean_query

CONSTRUCTOR_KEY = "key_KcSYfmQTEwRpBnd9"
CONSTRUCTOR_URL = "https://ac.cnstrc.com/search/{query}"
BASE_URL = "https://www.jarir.com/sa-en/"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
REQUEST_TIMEOUT = 20


def _search_candidates(item_name: str) -> list:
    url = CONSTRUCTOR_URL.format(query=requests.utils.quote(clean_query(item_name)))
    params = {
        "key": CONSTRUCTOR_KEY,
        "c": "ciojs-client-2.51.0",
        "i": "instax-price-monitor",
        "s": "1",
        "num_results_per_page": 30,
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", {}).get("results", [])


def search_product(item_name: str) -> dict:
    """
    Search Jarir (via Constructor.io) for `item_name`, then fetch the
    matched product page for authoritative price/availability. Returns
    {price, availability, link}.
    """
    result = {"price": "", "availability": "Not Found", "link": ""}

    try:
        candidates = _search_candidates(item_name)
    except (requests.RequestException, ValueError) as exc:
        print(f"[jarir] search error for '{item_name}': {exc}", flush=True)
        result["availability"] = "Fetch Error"
        return result

    if not candidates:
        return result

    def title_of(c):
        meta = c.get("data", {}).get("metadata", {})
        return meta.get("name") or c.get("value") or c.get("data", {}).get("description") or ""

    match, score = best_match(item_name, candidates, key=title_of)
    if not match:
        return result

    slug = match.get("data", {}).get("url")
    if not slug:
        return result
    product_url = BASE_URL + slug

    html = None
    for attempt in range(2):
        try:
            resp = requests.get(product_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            html = resp.text
            break
        except requests.RequestException as exc:
            print(f"[jarir] product page fetch error for '{item_name}' (attempt {attempt + 1}): {exc}", flush=True)

    if html is None:
        # Fall back to the search API's own price if the page fetch fails
        price = match.get("data", {}).get("price")
        result["price"] = clean_price(price)
        result["link"] = product_url
        result["availability"] = "Unknown"
        return result

    jsonld_products = extract_products_from_jsonld(html)
    if jsonld_products:
        p = jsonld_products[0]
        result["price"] = clean_price(p.get("price")) or clean_price(match.get("data", {}).get("price"))
        result["availability"] = normalize_availability(p.get("availability"))
    else:
        result["price"] = clean_price(match.get("data", {}).get("price"))
        result["availability"] = "Unknown"

    result["link"] = product_url
    return result
