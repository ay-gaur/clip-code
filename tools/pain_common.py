"""pain_common.py — shared config, run-dir + IO helpers for the Painfinder pipeline.

Painfinder (D59, project with Robin): discover sellable ICP/offer pairs by mining
where B2B operators complain. Runs on python3.13 (llm_rest needs 3.10+).

Run state lives under clip/data/pain_runs/<run_id>/:
  meta.json  source_map.json  raw/<source>/*.json  pain_units.json
  problems.json  scored.json  icp_offers.{json,md,csv}  credits.json
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent                 # clip/
PAIN_DIR = BASE / "data" / "pain_runs"

SLICES = ("agencies", "d2c", "saas")

# Pain-signal phrases used to filter Reddit/forum/social pulls toward complaints.
PAIN_TERMS = [
    "hate", "frustrated", "frustrating", "workaround", "manual", "manually",
    "wish it", "wish there", "anyone else", "is there a tool", "is there a way",
    "switching from", "switched from", "alternative to", "fed up", "nightmare",
    "waste of time", "clunky", "broken", "doesn't work", "does not work",
    "struggle", "struggling", "tired of", "cancel", "refund", "overpaying",
    "so painful", "biggest headache", "how do you deal with",
]

# Websites that are directory/social profiles, not real (reused idea from find_clinic_leads).
DIRECTORY_DOMAINS = ("linktr.ee", "instagram.com", "facebook.com", "wa.me")

# Seed sources per slice. Stage 0 (pain_sources.py) EXPANDS + Tavily-verifies these;
# they are a grounded starting point, not the final list.
SEEDS = {
    "agencies": {
        "label": "marketing / dev / ops agencies, consultancies, DFY shops",
        "platforms": [  # tools agencies run on; review-mine the ones they gripe about
            "GoHighLevel", "HubSpot", "ClickUp", "Monday.com", "Asana", "Notion",
            "AgencyAnalytics", "DashThis", "Ahrefs", "Semrush", "Airtable", "Zapier",
        ],
        "review_targets": ["GoHighLevel", "ClickUp", "Monday.com", "AgencyAnalytics", "HubSpot", "DashThis"],
        "subreddits": [
            "agency", "PPC", "marketing", "digital_marketing", "Entrepreneur",
            "smallbusiness", "msp", "SEO", "FacebookAds", "advertising",
            "consulting", "freelance", "Emailmarketing",
        ],
        "job_terms": [
            "marketing agency automation", "agency client reporting", "white label agency",
            "agency operations", "agency account manager", "agency project manager",
        ],
        "social_queries": [
            "agency owner", "agency operations", "client reporting", "agency automation",
        ],
    },
    "d2c": {
        "label": "US/global D2C & e-commerce brands",
        "platforms": ["Shopify", "Klaviyo", "Gorgias", "Recharge", "Yotpo", "Attentive",
                      "Triple Whale", "Postscript", "Amazon Seller Central"],
        "review_targets": ["Klaviyo", "Gorgias", "Recharge", "Yotpo", "Triple Whale"],
        "subreddits": ["ecommerce", "shopify", "dtc", "PPC", "FulfillmentByAmazon",
                       "marketing", "Entrepreneur", "smallbusiness"],
        "job_terms": ["shopify automation", "ecommerce ops", "klaviyo email", "amazon ppc",
                      "dtc retention", "ecommerce customer service"],
        "social_queries": ["dtc founder", "ecommerce operator", "shopify brand", "cac problem"],
    },
    "saas": {
        "label": "SaaS / software companies",
        "platforms": ["Stripe", "HubSpot", "Intercom", "Zendesk", "Salesforce",
                      "Segment", "Mixpanel", "Chargebee"],
        "review_targets": ["Intercom", "Zendesk", "HubSpot", "Salesforce", "Chargebee"],
        "subreddits": ["SaaS", "startups", "Entrepreneur", "devops", "webdev",
                       "ExperiencedDevs", "msp", "sales"],
        "job_terms": ["saas onboarding", "customer success automation", "revenue ops",
                      "saas churn", "product analytics", "billing integration"],
        "social_queries": ["saas founder", "revops", "customer success", "churn problem"],
    },
}


# ---- run-dir helpers -------------------------------------------------------

def _run_ids():
    if not PAIN_DIR.exists():
        return []
    return sorted(d.name for d in PAIN_DIR.iterdir() if d.is_dir() and d.name.startswith("run_"))


def new_run_id() -> str:
    ids = _run_ids()
    if not ids:
        return "run_001"
    try:
        return "run_{:03d}".format(int(ids[-1].split("_")[1]) + 1)
    except (IndexError, ValueError):
        return "run_001"


def latest_run_id() -> str | None:
    ids = _run_ids()
    return ids[-1] if ids else None


def get_run_dir(run_id: str) -> Path:
    return PAIN_DIR / run_id


def init_run(slice_name: str, run_id: str | None = None, notes: str = "") -> Path:
    run_id = run_id or new_run_id()
    d = get_run_dir(run_id)
    for sub in ("raw", "raw/reddit", "raw/reviews", "raw/jobs", "raw/social", "errors"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    meta_path = d / "meta.json"
    if not meta_path.exists():
        write_json(meta_path, {
            "run_id": run_id, "slice": slice_name, "notes": notes,
            "started_at": datetime.now(timezone.utc).isoformat(), "status": "running",
        })
    return d


def make_tracker(run_dir: Path):
    """CreditTracker with an apify budget high enough for bulk scraping (spend-freely, still tracked)."""
    from tools.utils.run_config import CreditTracker
    return CreditTracker(run_dir=run_dir, budgets={"apify": 50000, "tavily": 500})


# ---- io --------------------------------------------------------------------

def read_json(path: Path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return default


def write_json(path: Path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def has_pain_term(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in PAIN_TERMS)
