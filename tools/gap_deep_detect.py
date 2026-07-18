#!/usr/bin/env python3
"""
gap_deep_detect.py — optional "deep detect" mode for find-gap-leads.

Upgrade over the fast substring matcher (tools/gap_detect.py): renders the page
with a real headless browser (Playwright, via ScrapeGraphAI) and uses an LLM to
read the funnel/retention stack + founder + products in ONE pass. This catches
tools injected by Google Tag Manager / server-side that never appear in raw HTML
(the ~70-80%-accuracy blind spot of substring matching), and fills founder names
the regex can't.

$0 to run: ScrapeGraphAI is MIT / open-source and is pointed at the project's
free Groq key (llama-3.3-70b-versatile) — NOT the paid ScrapeGraphAI hosted API.

Heavyweight + OPTIONAL: needs `pip install scrapegraphai && playwright install
chromium`. If scrapegraphai is not importable, `deep_detect_available()` returns
False and the orchestrator silently falls back to the fast substring detector —
the skill keeps working with zero new dependencies.

Usage (standalone smoke test):
  python3 tools/gap_deep_detect.py --domain loveofindia.com
"""

import argparse
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
from tools.utils.gap_models import normalize_domain
from tools.utils.llm_rest import load_env, GROQ_MODEL

# import guard — scrapegraphai is a heavy OPTIONAL dependency
try:
    from scrapegraphai.graphs import SmartScraperGraph
    _IMPORT_OK = True
    _IMPORT_ERR = None
except Exception as e:  # ImportError or transitive dep failure
    _IMPORT_OK = False
    _IMPORT_ERR = f"{type(e).__name__}: {e}"


def deep_detect_available() -> bool:
    """True only if scrapegraphai imported AND a Groq key is present."""
    load_env()
    return _IMPORT_OK and bool(os.environ.get("GROQ_API_KEY"))


def unavailable_reason() -> str:
    if not _IMPORT_OK:
        return f"scrapegraphai not installed ({_IMPORT_ERR})"
    if not os.environ.get("GROQ_API_KEY"):
        return "GROQ_API_KEY missing"
    return ""


# Ask for explicit booleans + named vendors so the map back to infra is clean.
_PROMPT = (
    "You are auditing an Indian D2C e-commerce website for its marketing / retention stack. "
    "Consider the FULLY RENDERED page including scripts, embedded apps and chat/popup widgets. "
    "Report ONLY what is actually present as on-page evidence (do not guess). Return JSON with keys: "
    "email_capture (bool: any email / newsletter signup or popup, e.g. Klaviyo / Mailchimp / Omnisend), "
    "email_vendor (string or null), "
    "whatsapp_bsp (bool: a MANAGED WhatsApp business widget such as AiSensy / Interakt / Wati / "
    "Gallabox / Bik — NOT a plain wa.me click-to-chat link), "
    "whatsapp_vendor (string or null), "
    "static_wa_link (bool: a plain wa.me or api.whatsapp.com click-to-chat link), "
    "subscription (bool: subscribe-and-save / auto-replenish, e.g. Recharge / Loop / Appstle / Skio), "
    "subscription_vendor (string or null), "
    "loyalty (bool: a rewards / points / loyalty program, e.g. Smile / LoyaltyLion / Rivo / Growave), "
    "loyalty_vendor (string or null), "
    "reviews_vendor (string or null: Judge.me / Loox / Yotpo / Stamped / Okendo if present), "
    "platform (string: shopify / woocommerce / wix / magento / custom), "
    "founder_name (string or null: any founder / owner named on the page), "
    "founder_social (string or null: a LinkedIn or Instagram URL for the founder if shown), "
    "products (array of up to 5 product or category names)."
)


def _cat(present, vendor) -> str | None:
    """Map (bool present, vendor name) -> the match_signatures() cell value."""
    if not present:
        return None
    if isinstance(vendor, str) and vendor.strip():
        return vendor.strip().lower()
    return "detected"


def _to_infra(d: dict) -> dict:
    """Map ScrapeGraphAI's JSON read into the match_signatures() infra shape so the
    deep read is a drop-in for the substring detector, plus founder/product extras."""
    bsp = _cat(d.get("whatsapp_bsp"), d.get("whatsapp_vendor"))
    reviews = d.get("reviews_vendor")
    return {
        "bsp": bsp,
        "email_capture": _cat(d.get("email_capture"), d.get("email_vendor")),
        "subscription": _cat(d.get("subscription"), d.get("subscription_vendor")),
        "loyalty": _cat(d.get("loyalty"), d.get("loyalty_vendor")),
        "reviews": str(reviews).lower() if reviews else None,
        "platform": str(d["platform"]).lower() if d.get("platform") else None,
        "pixels": [],  # deep read doesn't enumerate pixels — left to the substring pass
        "static_wa_link": bool(d.get("static_wa_link") and not bsp),
        "evidence": {"deep": "scrapegraphai+groq rendered read"},
        # extras the regex cannot get:
        "founder_name": d.get("founder_name") or None,
        "founder_social": d.get("founder_social") or None,
        "products": d.get("products") or [],
        "deep_detect": True,
    }


def deep_detect(domain: str, *, headless: bool = True) -> dict | None:
    """Render + LLM-read a brand site. Returns an infra dict, or None on
    unavailable / failure (caller falls back to the substring result)."""
    if not deep_detect_available():
        return None
    dom = normalize_domain(domain)
    if not dom:
        return None
    config = {
        "llm": {
            "api_key": os.environ["GROQ_API_KEY"],
            "model": f"groq/{GROQ_MODEL}",
            "temperature": 0,
        },
        "headless": headless,
        "verbose": False,
    }
    try:
        graph = SmartScraperGraph(prompt=_PROMPT, source=f"https://{dom}", config=config)
        result = graph.run()
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict):
            return None
        # ScrapeGraphAI wraps the answer in a {"content": {...}} envelope
        if "content" in result and isinstance(result["content"], dict):
            result = result["content"]
        return _to_infra(result)
    except Exception as e:
        print(f"[gap_deep_detect] {dom} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def merge_infra(fast: dict, deep: dict | None) -> dict:
    """Union the fast substring result with the deep read: a retention tool counts
    as PRESENT if EITHER source saw it (kills false-negatives), and the deep read
    adds founder/products. Pixels + named platform stay from the precise substring
    pass when it already found them."""
    if not deep:
        return fast
    merged = dict(fast)
    for cat in ("bsp", "email_capture", "subscription", "loyalty", "reviews"):
        if not merged.get(cat) and deep.get(cat):
            merged[cat] = deep[cat]
            merged.setdefault("evidence", {})[f"{cat}:deep"] = "rendered LLM read"
    merged["static_wa_link"] = bool(
        (merged.get("static_wa_link") or deep.get("static_wa_link")) and not merged.get("bsp"))
    if not merged.get("platform") and deep.get("platform"):
        merged["platform"] = deep["platform"]
    for k in ("founder_name", "founder_social", "products"):
        if deep.get(k):
            merged[k] = deep[k]
    merged["deep_detect"] = True
    return merged


def main():
    ap = argparse.ArgumentParser(description="Deep (rendered + LLM) tech-stack detect for one domain")
    ap.add_argument("--domain", required=True)
    ap.add_argument("--show-browser", action="store_true", help="run non-headless (debug)")
    args = ap.parse_args()

    load_env()
    if not deep_detect_available():
        print(f"deep detect unavailable: {unavailable_reason()}")
        print("install: pip install scrapegraphai && playwright install chromium")
        sys.exit(2)

    infra = deep_detect(args.domain, headless=not args.show_browser)
    if infra is None:
        print("deep detect returned nothing (see stderr).")
        sys.exit(1)
    print(json.dumps(infra, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
