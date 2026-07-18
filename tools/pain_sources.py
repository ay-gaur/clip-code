#!/usr/bin/env python3.13
"""pain_sources.py — Painfinder Stage 0: seed & source discovery.

Answers "what platforms do they use" + "where do they talk". Starts from the
seed set in pain_common.SEEDS, asks the LLM to EXPAND it (more tools, subreddits,
forums/communities, gig terms, social pain-queries), merges + dedupes, optionally
Tavily-verifies the fuzzy community list, and writes source_map.json into a run dir.

Usage (python3.13):
  python3.13 tools/pain_sources.py --slice agencies
  python3.13 tools/pain_sources.py --slice agencies --verify        # Tavily-check communities
  python3.13 tools/pain_sources.py --slice agencies --run-id run_003 # write into an existing run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import pain_common as pc
from tools.utils.llm_rest import call_llm_json


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        k = pc.norm(x if isinstance(x, str) else x.get("name", "") + x.get("url", ""))
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def expand_with_llm(slice_name: str, seed: dict) -> dict:
    prompt = f"""You are a B2B go-to-market researcher. We are hunting for PAINFUL, PAYABLE problems that {seed['label']} have with the tools/platforms they use, so we can find where they complain online.

Here is a SEED set for the "{slice_name}" slice:
- platforms/tools: {seed['platforms']}
- subreddits: {seed['subreddits']}
- job/gig search terms: {seed['job_terms']}
- social pain queries: {seed['social_queries']}

Expand it. Return JSON with these keys (add NEW, real, well-known entries beyond the seed; do not repeat the seed verbatim but you may include the best of it):
- "platforms": array of tool/platform names this segment actually pays for and complains about (aim 12-20 total).
- "review_targets": array of 6-10 of those platforms whose G2/Trustpilot 1-3 star reviews would best reveal switch-intent and missing features.
- "subreddits": array of subreddit names (no "r/") where these operators post candid complaints (aim 12-18).
- "communities": array of objects {{"name","url","type","why"}} for NON-reddit venues where they talk — forums, IndieHackers, Slack/Discord communities, LinkedIn/Facebook groups, niche communities (aim 8-14). type in [forum, indiehackers, slack, discord, linkedin_group, facebook_group, x_community, other].
- "job_terms": array of 8-14 Upwork/LinkedIn search terms that surface GIGS or ROLES for this pain (a posted gig = a problem with a budget).
- "social_queries": array of 8-14 short LinkedIn/X search phrases operators use when venting about these tools.

Only real, currently-active sources. Return JSON only."""
    out = call_llm_json(prompt, prefer="groq", max_tokens=2000, temperature=0.3)
    return out if isinstance(out, dict) else {}


def verify_communities(communities: list, tracker) -> list:
    """Light Tavily check that each community URL/name resolves to something live."""
    try:
        from tools.find_leads import search_tavily
    except Exception as e:
        print(f"[sources] Tavily unavailable, skipping verify: {e}", file=sys.stderr)
        return communities
    verified = []
    for c in communities:
        q = c.get("url") or f"{c.get('name','')} {c.get('type','')} community"
        hits = search_tavily(q, max_results=2)
        if tracker:
            tracker.track("tavily", calls=1)
        c["verified"] = bool(hits)
        if hits and not c.get("url"):
            c["url"] = hits[0].get("url", "")
        verified.append(c)
    return verified


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slice", required=True, choices=pc.SLICES)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--verify", action="store_true", help="Tavily-verify discovered communities (costs a few calls)")
    args = ap.parse_args()

    seed = pc.SEEDS[args.slice]
    run_dir = pc.init_run(args.slice, run_id=args.run_id, notes=f"stage0 sources {args.slice}")
    tracker = pc.make_tracker(run_dir)

    print(f"[sources] slice={args.slice} run={run_dir.name} — expanding seed via LLM...", file=sys.stderr)
    exp = expand_with_llm(args.slice, seed)
    if not exp:
        print("[sources] LLM expansion returned nothing; falling back to seeds only", file=sys.stderr)

    # Merge seed + expansion, dedupe.
    platforms = _dedupe(list(seed["platforms"]) + list(exp.get("platforms", [])))
    review_targets = _dedupe(list(seed["review_targets"]) + list(exp.get("review_targets", [])))
    subreddits = _dedupe(list(seed["subreddits"]) + list(exp.get("subreddits", [])))
    job_terms = _dedupe(list(seed["job_terms"]) + list(exp.get("job_terms", [])))
    social_queries = _dedupe(list(seed["social_queries"]) + list(exp.get("social_queries", [])))
    communities = _dedupe([c for c in exp.get("communities", []) if isinstance(c, dict) and c.get("name")])

    if args.verify and communities:
        print(f"[sources] Tavily-verifying {len(communities)} communities...", file=sys.stderr)
        communities = verify_communities(communities, tracker)

    source_map = {
        "slice": args.slice,
        "label": seed["label"],
        "platforms": platforms,
        "review_targets": review_targets,
        "subreddits": subreddits,
        "communities": communities,          # the "find sites they talk on" output
        "job_terms": job_terms,
        "social_queries": social_queries,
    }
    pc.write_json(run_dir / "source_map.json", source_map)
    tracker.save()

    import json
    print(json.dumps({
        "run": run_dir.name,
        "slice": args.slice,
        "counts": {k: len(v) for k, v in source_map.items() if isinstance(v, list)},
        "communities_preview": [c.get("name") for c in communities[:8]],
        "source_map": str(run_dir / "source_map.json"),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
