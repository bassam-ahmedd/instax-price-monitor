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
    per competitor), return a list of dicts for every competitor price
    that's strictly lower than ours - skipping items that aren't
    currently in stock on our own site, since a price comparison isn't
    actionable for something we can't sell anyway:
    {item, site, price, our_price, our_link, diff, link}
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

        for key in COMPETITORS:
            comp = row[key]
            try:
                their_price = float(comp.get("price", ""))
            except (TypeError, ValueError):
                continue
            if their_price < our_price:
                items.append({
                    "item": row["item"],
                    "site": COMPETITOR_LABELS[key],
                    "price": f"{their_price:.2f}",
                    "our_price": f"{our_price:.2f}",
                    "our_link": our.get("link", ""),
                    "diff": f"{their_price - our_price:.2f}",
                    "link": comp.get("link", ""),
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
