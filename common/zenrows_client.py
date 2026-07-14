"""
Thin wrapper around the ZenRows API for fetching JS-rendered pages.

Both extra.com and jarir.com are JS-rendered SPAs with bot protection,
so every request goes through ZenRows with js_render + premium_proxy.
"""
import os
import time
import requests

ZENROWS_API_KEY = os.environ.get("ZENROWS_API_KEY", "")
ZENROWS_ENDPOINT = "https://api.zenrows.com/v1/"

DDEFAULT_TIMEOUT = 30
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 3


def fetch_rendered_html(url: str, wait_for: str | None = None, wait_ms: int = 3000) -> str | None:
    """
    Fetch a URL through ZenRows with JS rendering enabled.
    Returns the rendered HTML string, or None if all retries failed.
    """
    if not ZENROWS_API_KEY:
        raise RuntimeError(
            "ZENROWS_API_KEY is not set. Export it or add it as a GitHub Actions secret."
        )

    params = {
        "apikey": ZENROWS_API_KEY,
        "url": url,
        "js_render": "true",
        "premium_proxy": "true",
        "wait": str(wait_ms),
    }
    if wait_for:
        params["wait_for"] = wait_for

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(ZENROWS_ENDPOINT, params=params, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except requests.RequestException as exc:
            last_error = str(exc)

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    print(f"[zenrows] giving up on {url} -> {last_error}")
    return None
