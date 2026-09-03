"""
Sends a summary of "cheaper than us" items to the n8n "Instax Daily Price
Alert" workflow via its webhook, once per run:
    https://sherifelshamy123.app.n8n.cloud/workflow/vsVk3pdzIHCXxTvE

The n8n workflow itself builds the HTML email and decides whether to send
it (only if at least one item qualifies) - this module's only job is to
compute the item list and POST it. Recipients (To/CC) are configured
directly in the n8n workflow's Gmail node, not here.
"""
import os
from datetime import datetime, timezone

import requests

from sheets_writer import COMPETITORS, COMPETITOR_LABELS

WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")
REQUEST_TIMEOUT = 20


def build_cheaper_items(results: list) -> list:
    """
    From main.py's results list (each row has 'item', 'our', and one key
    per competitor), return one row per item for its single lowest
    competitor price - only when that price is lower than ours, and only
    when our own item is currently in stock (a price comparison isn't
    actionable for something we can't sell anyway):
    {item, site, price, our_price, our_link, diff, link}

    If two or more competitors tie at that lowest price, they're merged
    into one row (site becomes e.g. "Extra, Jarir"). A competitor with a
    higher (but still cheaper-than-us) price isn't shown at all - only
    the single best deal per item matters here.
    """
    items = []
    for row in results:
        our = row["our"]
        if our.get("availability") != "In Stock":
            continue

        try:
            our_price = float(our.get("price", ""))
        except (TypeError, ValueError):
            continue  # can't compare without a valid price of our own

        cheaper = []
        for key in COMPETITORS:
            comp = row[key]
            try:
                their_price = float(comp.get("price", ""))
            except (TypeError, ValueError):
                continue
            if their_price < our_price:
                cheaper.append({
                    "site": COMPETITOR_LABELS[key],
                    "price": their_price,
                    "link": comp.get("link", ""),
                })

        if not cheaper:
            continue

        lowest_price = min(c["price"] for c in cheaper)
        tied = [c for c in cheaper if round(c["price"], 2) == round(lowest_price, 2)]

        items.append({
            "item": row["item"],
            "site": ", ".join(c["site"] for c in tied),
            "price": f"{lowest_price:.2f}",
            "our_price": f"{our_price:.2f}",
            "our_link": our.get("link", ""),
            "diff": f"{lowest_price - our_price:.2f}",
            "link": tied[0]["link"],  # tied sites share a price; show the first one's link
        })
    return items


def send_alert(results: list):
    """POST the cheaper-item summary to the n8n webhook. Always posts
    (even with zero items) - the n8n workflow itself decides whether an
    empty list is worth emailing."""
    if not WEBHOOK_URL:
        print("[notify] N8N_WEBHOOK_URL not set - skipping price alert.", flush=True)
        return

    items = build_cheaper_items(results)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        resp = requests.post(WEBHOOK_URL, json={"date": date, "items": items}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        print(f"[notify] Sent alert webhook with {len(items)} cheaper item(s).", flush=True)
    except requests.RequestException as exc:
        print(f"[notify] Failed to send alert webhook: {exc}", flush=True)
