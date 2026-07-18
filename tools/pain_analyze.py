#!/usr/bin/env python3.13
"""pain_analyze.py — Painfinder Stages 2-6: extract -> cluster -> score -> kill -> cards.

Reads raw/all_items.json from a run, then:
  2. EXTRACT   each raw item -> a structured pain unit (LLM, batched)
  3. CLUSTER   pain units -> distinct problems + evidence profile (LLM)
  4. SCORE     "big enough to pay to solve" (deterministic gates + rubric + LLM)
  5. VALIDATE  adversarial skeptic refutes each top candidate (LLM)
  6. REPORT    ICP/offer cards -> icp_offers.{json,md,csv}

Every LLM stage degrades to a deterministic heuristic on None, so a run never
hard-fails. Runs on python3.13.

Usage:
  python3.13 tools/pain_analyze.py --run-id run_001
  python3.13 tools/pain_analyze.py --run-id run_001 --refute-votes 3
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import pain_common as pc
from tools.utils.llm_rest import call_llm_json

BUDGET_WORDS = ("pay", "paying", "paid", "pricing", "price", "overpay", "overpricing",
                "expensive", "cost us", "per month", "/mo", "budget", "quote", "invoice",
                "$", "subscription", "switch", "cancel")

# Free-tier LLMs are TOKENS-per-minute limited (Groq ~12k TPM, Gemini ~1M TPM).
# Pace every call and retry on 429/None so a big run degrades gracefully instead
# of cascading into the deterministic fallback.
_LAST = [0.0]
_MIN_GAP = 4.5
EXTRACT_CAP = 220  # cap items sent to the LLM extractor (balanced across sources)


def _llm(prompt, *, prefer="groq", max_tokens=1500, temperature=0.2, tries=4):
    for attempt in range(tries):
        gap = _MIN_GAP - (time.monotonic() - _LAST[0])
        if gap > 0:
            time.sleep(gap)
        _LAST[0] = time.monotonic()
        out = call_llm_json(prompt, prefer=prefer, max_tokens=max_tokens, temperature=temperature)
        if out is not None:
            return out
        time.sleep(3.0 * (attempt + 1))  # backoff on rate-limit/None
    return None


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _cap_balanced(items, cap):
    """Keep up to `cap` items, balanced across source types so no single source dominates extract."""
    if len(items) <= cap:
        return items
    by_src = {}
    for it in items:
        by_src.setdefault(it["source_type"], []).append(it)
    per = max(1, cap // max(1, len(by_src)))
    out = []
    for src, lst in by_src.items():
        out.extend(lst[:per])
    return out[:cap]


# ---- Stage 2: extract ------------------------------------------------------

def extract_units(items: list) -> list:
    regular = [it for it in items if it["source_type"] != "trustpilot_insight"]
    insights = [it for it in items if it["source_type"] == "trustpilot_insight"]
    regular = _cap_balanced(regular, EXTRACT_CAP)
    units = []

    for batch in _chunks(regular, 7):
        payload = [{"id": it["id"], "src": it["source_type"], "tool": it.get("tool", ""),
                    "text": it["text"][:900], "meta": it.get("meta", {})} for it in batch]
        prompt = f"""You extract PAYABLE B2B pain from raw items (reddit posts, product reviews, freelance gigs).
For each item, decide if it expresses a real BUSINESS / OPERATIONAL / SOFTWARE problem that a company would pay to solve. Return JSON {{"units":[...]}}, one object per input id:
{{"id","is_pain"(bool),"problem_canonical"(short tool-agnostic problem statement),"tool"(product involved or ""),"who_has_it"(role/business-type),"quote"(<=25 words verbatim),"budget_signal"(explicit $/rate/"we pay"/switch-intent or ""),"pain_1_5"(int),"urgency_1_5"(int)}}
is_pain=true ONLY for business/operational/tooling pain (workflows, software, ops, marketing, billing, reporting, integrations). Set is_pain=false for generic praise, spam, personal/health/relationship/consumer-product/gaming content, or anything a business would not pay to fix. Items:
{json.dumps(payload, ensure_ascii=False)}
Return JSON only."""
        out = _llm(prompt, prefer="gemini", max_tokens=2200, temperature=0.2)
        got = out.get("units", []) if isinstance(out, dict) else (out if isinstance(out, list) else [])
        by_id = {it["id"]: it for it in batch}
        if got:
            for u in got:
                src = by_id.get(u.get("id"))
                if not src or not u.get("is_pain"):
                    continue
                units.append(_unit_from(u, src))
        else:  # deterministic fallback: keep the item as a coarse unit
            for it in batch:
                units.append(_unit_from({"problem_canonical": it["title"] or it["text"][:80],
                                         "tool": it.get("tool", ""), "who_has_it": "",
                                         "quote": it["text"][:140], "pain_1_5": 3, "urgency_1_5": 3,
                                         "budget_signal": _heuristic_budget(it)}, it))

    # insight rows: expand each into up to 5 theme-units
    for it in insights:
        prompt = f"""This is a pain-point analysis of real reviews for the tool "{it.get('tool','')}".
Extract up to 5 distinct complaint THEMES as JSON {{"units":[{{"problem_canonical","who_has_it","quote","pain_1_5","urgency_1_5"}}]}}.
Data: {it['text'][:1500]}
Return JSON only."""
        out = _llm(prompt, prefer="gemini", max_tokens=1200, temperature=0.2)
        got = out.get("units", []) if isinstance(out, dict) else []
        for u in got:
            u["tool"] = it.get("tool", "")
            u["budget_signal"] = "review-based switch/complaint"
            units.append(_unit_from(u, it))
    return units


def _heuristic_budget(it):
    t = it["text"].lower()
    if it["source_type"] == "upwork":
        m = it.get("meta", {})
        return f"gig budget={m.get('budget')} hourly={m.get('hourly')} client_spent={m.get('client_spent')}"
    return "mentions cost/switch" if any(w in t for w in BUDGET_WORDS) else ""


def _unit_from(u: dict, src: dict) -> dict:
    return {
        "unit_id": src["id"], "source_type": src["source_type"], "source_url": src.get("source_url", ""),
        "problem_canonical": (u.get("problem_canonical") or "").strip()[:200],
        "tool": (u.get("tool") or src.get("tool") or "").strip(),
        "who_has_it": (u.get("who_has_it") or "").strip(),
        "quote": (u.get("quote") or "").strip()[:300],
        "budget_signal": (u.get("budget_signal") or "").strip(),
        "pain_1_5": int(u.get("pain_1_5") or 3), "urgency_1_5": int(u.get("urgency_1_5") or 3),
    }


# ---- Stage 3: cluster ------------------------------------------------------

def cluster_units(units: list) -> list:
    if not units:
        return []
    ranked = sorted(units, key=lambda u: (u["pain_1_5"] + u["urgency_1_5"]), reverse=True)[:120]
    payload = [{"i": idx, "p": u["problem_canonical"], "tool": u["tool"], "who": u["who_has_it"]}
               for idx, u in enumerate(ranked)]
    prompt = f"""Group these B2B problems into DISTINCT problem clusters (same underlying pain = same cluster).
Return JSON {{"clusters":[{{"label"(short name),"problem"(1 sentence),"members"(array of i indices)}}]}}. Aim 6-15 clusters.
Items: {json.dumps(payload, ensure_ascii=False)}
Return JSON only."""
    out = _llm(prompt, prefer="gemini", max_tokens=2500, temperature=0.2)
    raw = out.get("clusters", []) if isinstance(out, dict) else []
    clusters = []
    if not raw:  # fallback: cluster by tool
        by_tool = {}
        for idx, u in enumerate(ranked):
            by_tool.setdefault(u["tool"] or "general", []).append(idx)
        raw = [{"label": t, "problem": f"issues with {t}", "members": ids} for t, ids in by_tool.items()]
    for cid, c in enumerate(raw):
        members = [ranked[i] for i in c.get("members", []) if isinstance(i, int) and 0 <= i < len(ranked)]
        if not members:
            continue
        clusters.append({"cluster_id": cid, "label": c.get("label", f"cluster {cid}"),
                         "problem": c.get("problem", ""), "members": members,
                         "evidence": _evidence(members)})
    return clusters


def _evidence(members: list) -> dict:
    src_types = sorted({m["source_type"] for m in members})
    budget_hits = [m["budget_signal"] for m in members if m["budget_signal"]]
    return {
        "mentions": len(members),
        "source_types": src_types, "n_source_types": len(set(
            "reviews" if s in ("trustpilot", "trustpilot_insight", "g2") else s for s in src_types)),
        "distinct_urls": len({m["source_url"] for m in members if m["source_url"]}),
        "budget_signals": budget_hits[:6], "n_budget_signals": len(budget_hits),
        "avg_pain": round(sum(m["pain_1_5"] for m in members) / len(members), 2),
        "tools": sorted({m["tool"] for m in members if m["tool"]})[:6],
    }


# ---- Stage 4: score --------------------------------------------------------

def score_cluster(c: dict) -> dict:
    ev = c["evidence"]
    # deterministic components
    freq = min(20, ev["mentions"] * 2) * (1.0 if ev["n_source_types"] >= 2 else 0.6)
    pain = (ev["avg_pain"] / 5.0) * 20
    reach = 15 if ev["n_source_types"] >= 1 else 5
    # LLM fuzzy components: ability-to-pay + wedge + offer/angle
    prompt = f"""B2B problem: "{c.get('problem') or c.get('label')}".
Tools involved: {ev['tools']}. Evidence: {ev['mentions']} mentions across {ev['source_types']}; budget signals: {ev['budget_signals']}.
Judge for a small team wanting to sell a solution. Return JSON:
{{"ability_to_pay_0_30"(int; high only if real budget/spend/switch-intent),"wedge_0_15"(int; can a small team build+sell this, not enterprise-only),"candidate_offer"(<=20 words, what to sell),"first_touch_angle"(<=20 words),"one_line_problem"(<=18 words)}}
Return JSON only."""
    out = _llm(prompt, prefer="groq", max_tokens=500, temperature=0.3) or {}
    pay = float(out.get("ability_to_pay_0_30", 15 if ev["n_budget_signals"] else 5))
    wedge = float(out.get("wedge_0_15", 8))
    score = round(freq + pain + reach + pay + wedge, 1)
    # hard gates
    gate = ""
    if ev["n_source_types"] < 2:
        score = min(score, 64); gate = "single-source (triangulation gate)"
    if ev["n_budget_signals"] == 0:
        score = min(score, 55); gate = (gate + "; " if gate else "") + "no budget signal"
    band = "priority" if score >= 80 else "shortlist" if score >= 65 else "watchlist" if score >= 50 else "drop"
    c.update({
        "score": score, "band": band, "gate": gate,
        "components": {"frequency": round(freq, 1), "pain": round(pain, 1), "reachability": reach,
                       "ability_to_pay": pay, "wedge": wedge},
        "candidate_offer": out.get("candidate_offer", ""), "first_touch_angle": out.get("first_touch_angle", ""),
        "one_line_problem": out.get("one_line_problem", c.get("problem", "")),
    })
    return c


# ---- Stage 5: adversarial validate ----------------------------------------

def refute(c: dict, votes: int) -> dict:
    kills = 0
    reasons = []
    for _ in range(votes):
        prompt = f"""Be a skeptical investor. Try to REFUTE this as a payable opportunity for a small team.
Problem: {c.get('one_line_problem')}. Offer idea: {c.get('candidate_offer')}. Evidence: {c['evidence']['mentions']} mentions across {c['evidence']['source_types']}, budget signals {c['evidence']['budget_signals']}.
Is it already solved by a cheap happy incumbent? Is the budget aspirational not real? Is the buyer undefinable/unreachable? Is it a vitamin not a painkiller?
Return JSON {{"refuted"(bool; default true if genuinely weak),"reason"(<=25 words)}}. Return JSON only."""
        out = _llm(prompt, prefer="groq", max_tokens=200, temperature=0.5) or {}
        if out.get("refuted"):
            kills += 1
            reasons.append(out.get("reason", ""))
    c["refute"] = {"votes": votes, "kills": kills, "reasons": reasons[:2]}
    if kills > votes / 2:  # majority refute -> demote one band
        order = ["drop", "watchlist", "shortlist", "priority"]
        i = order.index(c["band"])
        c["band"] = order[max(0, i - 1)]
        c["refute"]["demoted"] = True
    return c


# ---- Stage 6: report -------------------------------------------------------

def build_cards(clusters: list, sm: dict) -> list:
    cards = []
    for c in clusters:
        ev = c["evidence"]
        quotes = [{"quote": m["quote"], "src": m["source_type"], "url": m["source_url"]}
                  for m in c["members"] if m["quote"]][:4]
        cards.append({
            "band": c["band"], "score": c["score"], "problem": c.get("one_line_problem") or c["problem"],
            "label": c["label"], "icp": _icp_line(c, sm),
            "candidate_offer": c["candidate_offer"], "first_touch_angle": c["first_touch_angle"],
            "pay_signal": ev["budget_signals"][:4] or ["(none captured)"],
            "evidence": {"mentions": ev["mentions"], "source_types": ev["source_types"],
                         "n_source_types": ev["n_source_types"], "tools": ev["tools"]},
            "quotes": quotes,
            "venues_for_kesh": {"subreddits": sm.get("subreddits", [])[:6],
                                "communities": [x.get("name") for x in sm.get("communities", [])][:5],
                                "gig_terms": sm.get("job_terms", [])[:5]},
            "components": c["components"], "gate": c.get("gate", ""), "refute": c.get("refute", {}),
        })
    order = {"priority": 0, "shortlist": 1, "watchlist": 2, "drop": 3}
    cards.sort(key=lambda x: (order.get(x["band"], 9), -x["score"]))
    return cards


def _icp_line(c, sm):
    whos = sorted({m["who_has_it"] for m in c["members"] if m["who_has_it"]})
    return (", ".join(whos[:3]) if whos else sm.get("label", "")) + f" ({sm.get('slice')})"


def write_report(cards: list, run_dir: Path, sm: dict):
    pc.write_json(run_dir / "icp_offers.json", cards)
    # CSV
    with (run_dir / "icp_offers.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["band", "score", "problem", "icp", "candidate_offer", "n_mentions",
                    "source_types", "pay_signal", "first_touch_angle", "gate"])
        for c in cards:
            w.writerow([c["band"], c["score"], c["problem"], c["icp"], c["candidate_offer"],
                        c["evidence"]["mentions"], "|".join(c["evidence"]["source_types"]),
                        " ; ".join(c["pay_signal"]), c["first_touch_angle"], c["gate"]])
    # Markdown brief
    lines = [f"# Painfinder ICP/offer cards — {sm.get('slice')} ({run_dir.name})", ""]
    for band in ("priority", "shortlist", "watchlist", "drop"):
        group = [c for c in cards if c["band"] == band]
        if not group:
            continue
        lines.append(f"## {band.upper()} ({len(group)})\n")
        for c in group:
            lines += [
                f"### {c['problem']}  ·  score {c['score']}",
                f"- **ICP:** {c['icp']}",
                f"- **Offer:** {c['candidate_offer']}",
                f"- **Pay signal:** {' ; '.join(c['pay_signal'])}",
                f"- **Evidence:** {c['evidence']['mentions']} mentions across {', '.join(c['evidence']['source_types'])} "
                f"({c['evidence']['n_source_types']} source types); tools: {', '.join(c['evidence']['tools']) or '—'}",
                f"- **First touch:** {c['first_touch_angle']}",
                f"- **Venues for Robin:** r/{', r/'.join(c['venues_for_kesh']['subreddits'][:4])}",
            ]
            if c.get("gate"):
                lines.append(f"- **Gate:** {c['gate']}")
            if c.get("refute", {}).get("reasons"):
                lines.append(f"- **Skeptic:** {c['refute']['kills']}/{c['refute']['votes']} refuted — {'; '.join(c['refute']['reasons'])}")
            for q in c["quotes"][:3]:
                lines.append(f"  > \"{q['quote']}\" — {q['src']}")
            lines.append("")
    (run_dir / "icp_offers.md").write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--refute-votes", type=int, default=1, help="skeptic votes per top candidate (1 or 3)")
    ap.add_argument("--validate-bands", default="priority,shortlist")
    args = ap.parse_args()

    run_id = args.run_id or pc.latest_run_id()
    run_dir = pc.get_run_dir(run_id)
    items = pc.read_json(run_dir / "raw" / "all_items.json", [])
    sm = pc.read_json(run_dir / "source_map.json", {})
    if not items:
        sys.exit(f"[analyze] no raw/all_items.json in {run_dir} — run pain_capture.py first")

    print(f"[analyze] {len(items)} raw items -> extracting...", file=sys.stderr)
    units = extract_units(items)
    pc.write_json(run_dir / "pain_units.json", units)

    print(f"[analyze] {len(units)} pain units -> clustering...", file=sys.stderr)
    clusters = cluster_units(units)

    print(f"[analyze] {len(clusters)} clusters -> scoring...", file=sys.stderr)
    clusters = [score_cluster(c) for c in clusters]

    val_bands = set(args.validate_bands.split(","))
    for c in clusters:
        if c["band"] in val_bands:
            refute(c, args.refute_votes)
    pc.write_json(run_dir / "problems.json",
                  [{k: v for k, v in c.items() if k != "members"} for c in clusters])

    cards = build_cards(clusters, sm)
    write_report(cards, run_dir, sm)

    bands = {}
    for c in cards:
        bands[c["band"]] = bands.get(c["band"], 0) + 1
    print(json.dumps({
        "run": run_id, "slice": sm.get("slice"),
        "funnel": {"raw_items": len(items), "pain_units": len(units), "clusters": len(clusters)},
        "bands": bands,
        "top": [{"band": c["band"], "score": c["score"], "problem": c["problem"]} for c in cards[:6]],
        "outputs": [str(run_dir / "icp_offers.md"), str(run_dir / "icp_offers.csv")],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
