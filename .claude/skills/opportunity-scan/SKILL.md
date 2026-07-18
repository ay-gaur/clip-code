---
name: opportunity-scan
description: Alex's West→India opportunity scanner for CLIP. Use this skill when the user wants to see market opportunities, find products to replicate for India, research what's trending in the West, or asks things like "show me opportunities", "what's trending in the West?", "any good products to bring to India?", "run the opportunity scan", "what should I build next?". Trigger on /opportunity-scan or any request about market opportunities, West→India products, or what to research/build.
---

# opportunity-scan

You help Alex find validated Western products/tools with no strong Indian equivalent — potential build, partner, or replicate opportunities.

## How to run this skill

Follow `workflows/opportunity-scan.md` exactly.

**Step 1 — Check if fresh opportunities exist**

Read `data/opportunities.json`. Check for entries with `"status": "new"` and `"discovered"` within the last 7 days.

**Step 2 — If no recent opportunities (or Alex wants a fresh scan)**

Run:
```
python3 tools/opportunity_scan.py --no-email
```
Tell Alex how many new opportunities were found.

**Step 3 — Present the top opportunities**

Show the top 5 from `data/opportunities.json` (newest first):
- Product name
- Traction signal (1 line)
- India gap analysis
- Source URL

Ask: "Want to go deep on any of these? I can research the market size and what it would take to build."

## Going deep on an opportunity

If Alex picks one, use Tavily to search for:
- Market size for this product category
- Existing Indian competitors (if any)
- What the build would look like
- Revenue potential

Present a 1-page brief. Offer to save it as a research note.

## Reflexion log

```
python3 tools/log_entry.py --skill opportunity-scan --action [view|scan|research] --note "SUMMARY"
```
SUMMARY = "Showed X opportunities" or "Researched [Product] for India market"
