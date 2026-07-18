#!/usr/bin/env python3
"""
gap_score.py — Phase 3: qualification scoring (the core IP).

Hybrid model: deterministic everywhere possible, one Groq JSON call per lead for
the fuzzy parts only (persona, product category, stage, early-stage fit, retention
likelihood). If the LLM is unavailable, a keyword heuristic keeps scoring
deterministic so the pipeline never hard-fails.

Hard gates sort every lead into a bucket FIRST:
  - consultant      -> partner track   (partner_flag, not client-scored)
  - too_early       -> audience/nurture (audience_flag, future client + edu audience)
  - too_late        -> drop            (already has the full retention layer)
Only un-gated leads get the 0-100 weighted score.

Weighted rubric (max 100):
  early_stage_fit   20  (LLM)
  missing_infra     30  (deterministic from detected stack — the literal thesis)
  ability_to_pay    20  (deterministic: active Meta ads, real store, pixels)
  retention_likely  20  (LLM: consumable/repeat category, founder-led)
  reachability      10  (deterministic: founder name + LinkedIn present)
Bands: >=80 priority | 65-79 shortlist | 50-64 watchlist | <50 drop.
Persona multiplier: d2c 1.0 | info_product 0.95 | coach 0.85.
"""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
from tools.utils.llm_rest import call_llm_json
from tools.utils.tech_signatures import summarize_gaps
from tools.find_leads import search_tavily

PERSONA_MULT = {"d2c_founder": 1.0, "info_product": 0.95, "coach": 0.85, "consultant": 0.0}
_CONSUMABLE_HINTS = ["skin", "hair", "beauty", "cosmet", "coffee", "tea", "snack", "food",
                     "supplement", "nutrition", "protein", "pet", "candle", "fragrance",
                     "serum", "oil", "wellness", "vitamin", "soap", "perfume", "gummies"]


def funding_context(company: str) -> str:
    """One Tavily search for funding/maturity signals. Empty string on failure.

    This is the fix for the run-#1 failure where funded brands (Pilgrim $50M, Plum
    Series C, Nykaa-owned Dot & Key) scored as 'early' because the classifier never
    saw their funding. We feed real funding evidence into the classifier so the
    too_late gate fires correctly.
    """
    if not company:
        return ""
    from tools.utils.llm_rest import load_env
    load_env()  # ensure TAVILY_API_KEY is present even for standalone callers
    # Tavily does poorly with boolean OR / quotes — keep the query short + natural.
    try:
        res = search_tavily(f"{company} India brand funding raised crore valuation", max_results=4)
    except Exception:  # noqa: BLE001
        res = []
    return " | ".join(f"{r.get('title','')}: {r.get('content','')[:160]}" for r in res)[:1400]


def classify_llm(lead: dict, infra: dict, funding_ctx: str = "") -> dict | None:
    """One Groq JSON call for fuzzy judgment. No PII (company-level only)."""
    gaps = summarize_gaps(infra)
    prompt = f"""You qualify B2B leads for "Acme", an agency that builds the
WhatsApp/email response + retention automation layer for EARLY-STAGE Indian D2C
brands and online coaches. We want clients who are EARLY ENOUGH to still lack this
infra (so we build from the ground up) but PAST the survival valley (real product +
some traction). We deprioritize businesses that already have the full retention
stack, and we treat solo consultants as referral partners, not clients.

CRITICAL: any brand that is FUNDED beyond a small angel round (seed+/Series A+),
ACQUIRED, owned by a larger company, or that appeared on Shark Tank with a deal, is
"established" = NOT our customer (they have in-house teams). Default established here.

Classify this business from public info. Do NOT invent facts.

Company: {lead.get('company','?')}
Domain: {lead.get('domain','?')}
Context: {lead.get('source_url','')}
Detected infra gaps: {gaps}
Detected platform: {infra.get('platform')}
Funding / maturity signals (from web search; "" means none found = likely bootstrapped):
{funding_ctx or '(none found)'}

Return ONLY this JSON:
{{
  "persona": "d2c_founder | info_product | coach | consultant",
  "category": "consumable | durable | service | digital | unknown",
  "stage": "pre_product | early_traction | growth | mature | unknown",
  "established": <true if funded(seed+)/acquired/owned-by-larger-co/Shark-Tank-deal/clearly-large, else false>,
  "early_stage_fit_0_20": <int 0-20, peak ~1-3yr bootstrapped brands with traction; 0 if pre-product or established>,
  "retention_likelihood_0_20": <int 0-20, high for repeat-purchase consumables + founder-led>,
  "rationale": "<one short line, no PII>"
}}"""
    out = call_llm_json(prompt, prefer="groq", max_tokens=700, temperature=0.2, scrub=True)
    if not isinstance(out, dict):
        return None
    return out


def _heuristic_classify(lead: dict, infra: dict) -> dict:
    """Deterministic fallback when the LLM is unavailable."""
    name = (lead.get("company", "") + " " + lead.get("source_url", "")).lower()
    consumable = any(h in name for h in _CONSUMABLE_HINTS)
    return {
        "persona": "d2c_founder",
        "category": "consumable" if consumable else "unknown",
        "stage": "unknown",
        "early_stage_fit_0_20": 10,
        "retention_likelihood_0_20": 15 if consumable else 8,
        "rationale": "heuristic fallback (LLM unavailable)",
    }


def _score_missing_infra(infra: dict, category: str) -> int:
    pts = 0
    if infra.get("bsp") is None:
        pts += 10  # no managed WhatsApp = the headline gap
    if infra.get("email_capture") is None:
        pts += 8
    if infra.get("subscription") is None and category in ("consumable", "unknown"):
        pts += 7
    if infra.get("loyalty") is None and infra.get("reviews") is None:
        pts += 5  # vanilla stack
    return min(pts, 30)


def _score_ability(infra: dict, meta_ads_active) -> int:
    pts = 0
    if meta_ads_active is True:
        pts += 12  # actively spending on ads = exact ICP + can pay
    if infra.get("platform") in ("shopify", "woocommerce"):
        pts += 4
    if infra.get("pixels"):
        pts += 4
    return min(pts, 20)


def _score_reachability(lead: dict) -> int:
    pts = 0
    if lead.get("contact_name"):
        pts += 5
    if lead.get("contact_linkedin"):
        pts += 5
    return pts


def _band(score: int) -> str:
    if score >= 80:
        return "priority"
    if score >= 65:
        return "shortlist"
    if score >= 50:
        return "watchlist"
    return "drop"


def score_lead(lead: dict, infra: dict, signals: dict | None = None, use_llm: bool = True) -> dict:
    """Score one lead. Returns the scoring dict (also see GapLead fields)."""
    signals = signals or {}
    meta_ads_active = signals.get("meta_ads_active", lead.get("meta_ads_active"))

    fund_ctx = funding_context(lead.get("company", "")) if use_llm else ""
    cls = (classify_llm(lead, infra, fund_ctx) if use_llm else None) or _heuristic_classify(lead, infra)
    persona = cls.get("persona", "d2c_founder")
    category = cls.get("category", "unknown")
    stage = cls.get("stage", "unknown")
    established = bool(cls.get("established", False))

    base = {
        "persona": persona, "score_components": {}, "gap_score": 0, "band": "drop",
        "hard_gate": None, "partner_flag": False, "audience_flag": False,
        "reply_speed_test_pending": False, "reasoning": cls.get("rationale", ""),
        "meta_ads_active": meta_ads_active,
    }

    # ---- Hard gates ----
    if persona == "consultant":
        base.update(partner_flag=True, reasoning="Consultant -> partner/referral track, not client-scored.")
        return base

    full_stack = infra.get("bsp") and infra.get("subscription") and infra.get("loyalty")
    if established or stage == "mature" or full_stack:
        why = ("Funded/acquired/established (per funding signals) -> not our customer."
               if established else "Mature / already has the retention layer -> skip.")
        base.update(hard_gate="too_late", reasoning=why)
        return base

    if stage == "pre_product":
        base.update(hard_gate="too_early", audience_flag=True,
                    reasoning="Pre-product/no traction -> Audience/nurture list (future client).")
        return base

    # ---- Weighted score ----
    comp = {
        "early_stage_fit": max(0, min(20, int(cls.get("early_stage_fit_0_20", 10)))),
        "missing_infra": _score_missing_infra(infra, category),
        "ability_to_pay": _score_ability(infra, meta_ads_active),
        "retention_likelihood": max(0, min(20, int(cls.get("retention_likelihood_0_20", 10)))),
        "reachability": _score_reachability(lead),
    }
    raw = sum(comp.values())
    score = round(raw * PERSONA_MULT.get(persona, 1.0))
    band = _band(score)

    base.update(
        score_components=comp, gap_score=score, band=band,
        reply_speed_test_pending=(band in ("priority", "shortlist")),
    )
    return base


def main():
    ap = argparse.ArgumentParser(description="Score one lead (debug)")
    ap.add_argument("--company", required=True)
    ap.add_argument("--domain", default="")
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    from tools.gap_detect import detect_infra
    infra = detect_infra(args.domain) if args.domain else {}
    lead = {"company": args.company, "domain": args.domain, "contact_name": "", "contact_linkedin": ""}
    result = score_lead(lead, infra, use_llm=not args.no_llm)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
