#!/usr/bin/env python3
"""
gap_draft.py — Phase 5: LinkedIn connection note + priority dossier.

Voice rules are enforced DETERMINISTICALLY after the LLM, not just requested in the
prompt: no em-dashes, no emojis, no banned phrases, mandatory "noticed publicly"
hedge (detection is ~70-80% accurate so we never assert "you don't have X").

The founder's name is templated in LOCALLY (a {{first}} slot) so it is never sent
to Gemini's free tier (which trains on data). Drafting prefers Groq regardless.

Usage:
  python3 tools/gap_draft.py --company "Acme" --domain acme.in --gap "no WhatsApp BSP"
"""

import argparse
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
from tools.utils.llm_rest import call_llm
from tools.utils.tech_signatures import summarize_gaps
from tools.utils.gap_models import first_name

# Same phrases encoded in linkedin_post_generate.py + memory voice rules.
BANNED_PHRASES = [
    "i'm thrilled to share", "thrilled to share", "in today's fast-paced",
    "in today's fast-paced ai landscape", "leverage", "synergy", "thoughts?",
    "what do you think?", "delve into", "in the realm of", "embark on",
    "unlock the power", "moving the needle", "game changer", "game-changer",
    "10x", "passionate about", "love to hear your thoughts", "circle back",
    "at the end of the day", "boost your", "supercharge", "skyrocket",
    "bsp", "crm", "collaboration opportunities", "collaboration opportunity",
]
HEDGE_MARKERS = ("from what i could see", "from the outside", "looks like",
                 "noticed", "publicly", "from outside", "seems like", "came across")
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F02F\U00002190-\U000021FF\U00002B00-\U00002BFF️]",
    flags=re.UNICODE,
)


def voice_violations(text: str) -> list[str]:
    """Report voice-rule violations (for tests / QA)."""
    out = []
    low = text.lower()
    if "—" in text or "–" in text:
        out.append("em/en-dash")
    if _EMOJI_RE.search(text):
        out.append("emoji")
    for p in BANNED_PHRASES:
        if p in low:
            out.append(f"banned:{p}")
    return out


def voice_lint(text: str) -> str:
    """Deterministically scrub em-dashes, emojis, and banned phrases."""
    text = text.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ").replace("–", ", ")
    text = _EMOJI_RE.sub("", text)
    for p in BANNED_PHRASES:
        text = re.sub(re.escape(p), "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).replace(" ,", ",").replace(" .", ".").strip()
    return text


def _truncate_words(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(",. ") + "."


def _ensure_hedge(text: str) -> str:
    if any(m in text.lower() for m in HEDGE_MARKERS):
        return text
    return "Noticed from the outside, " + text[0].lower() + text[1:]


def _plain_gap(infra: dict) -> str:
    """Founder-friendly gap phrasing — NO jargon/acronyms like 'BSP'."""
    parts = []
    if infra.get("bsp") is None:
        parts.append("no automated WhatsApp follow-ups after someone buys")
    if infra.get("email_capture") is None:
        parts.append("no email signup to catch visitors who don't buy yet")
    if infra.get("subscription") is None:
        parts.append("no subscribe-and-save for repeat orders")
    if infra.get("loyalty") is None:
        parts.append("no loyalty or rewards to pull buyers back")
    return "; ".join(parts) if parts else "the core repeat-purchase pieces look in place"


def draft_linkedin_note(lead: dict, infra: dict, max_chars: int = 300) -> str:
    """≤max_chars connection note. Name templated locally; voice-linted; hedged."""
    company = lead.get("company", "the brand")
    gap = _plain_gap(infra)
    fname = first_name(lead.get("contact_name", ""))

    prompt = f"""You are Alex, co-founder of "Acme" (we build the WhatsApp/email
response + retention layer for early-stage Indian D2C brands). Write a SHORT LinkedIn
connection-request note TO the founder of "{company}" (a brand you'd like as a client).

The greeting MUST be exactly "Hi {{first}}," — that token is the RECIPIENT (the {company}
founder). Never write "Alex" or any other name in the greeting; you are the sender.

Pick the SINGLE sharpest thing they're missing (phrase as something you noticed from outside,
never as a certain fact). Their gaps, in plain language: {gap}

Write ONLY THE BODY — NO greeting, NO "Hi", NO name, NO sign-off. Start directly with the
observation. Under 200 characters. Write like one founder messaging another: warm, plain,
specific to {company}. NO marketing jargon or acronyms (never write "BSP", "CRM", "funnel",
"retention layer", "engagement tools", "solution"). NO em-dashes, no emojis. Do NOT use:
leverage, synergy, thrilled, game changer, moving the needle, collaboration opportunities,
"thoughts?". End with a light, human reason to connect, not a pitch. Return ONLY the body."""
    body = call_llm(prompt, prefer="groq", max_tokens=200, temperature=0.6, scrub=True)

    if not body or len(body.strip()) < 30:  # empty/truncated -> deterministic fallback
        top = gap.split(";")[0]
        body = (f"came across {company} while researching early D2C brands in India. From what "
                f"I could see publicly, looks like room on the {top} side. That's the layer we "
                f"build at Acme. Open to connecting?")

    body = body.strip().strip('"')
    # strip any greeting the model added anyway (we control the greeting to avoid invented names)
    body = re.sub(r"^(hi|hey|hello)\b[^,]*,\s*", "", body, flags=re.IGNORECASE).strip()
    note = f"Hi {fname}, " + body[0].lower() + body[1:] if body else f"Hi {fname},"
    note = voice_lint(note)
    note = _ensure_hedge(note)
    return _truncate_words(note, max_chars)


def draft_dossier(lead: dict, infra: dict, score: dict) -> str:
    """Markdown brief for a priority-band lead."""
    company = lead.get("company", "?")
    gap = summarize_gaps(infra)
    detected = ", ".join(
        f"{k}={infra.get(k)}" for k in ("platform", "bsp", "email_capture", "subscription", "loyalty", "reviews")
    )
    fname = first_name(lead.get("contact_name", ""))

    prompt = f"""Brief for Alex (Acme) on prospect "{company}".
Detected gaps: {gap}. Persona: {score.get('persona')}. Ability-to-pay signal: meta_ads_active={lead.get('meta_ads_active')}.
Write TWO short things, no em-dashes, no emojis, no buzzwords:
1) ANGLE: 2-3 lines on the single sharpest reason they need the response/retention layer.
2) FIRST_MESSAGE: a 2-3 line opener Alex could send (start "Hi {{first}},"), hedged as a public observation.
Return as:
ANGLE: ...
FIRST_MESSAGE: ..."""
    body = call_llm(prompt, prefer="groq", max_tokens=400, temperature=0.5, scrub=True)
    if body:
        body = voice_lint(body.replace("{{first}}", fname).replace("{first}", fname))
    else:
        body = f"ANGLE: {company} is running on a vanilla stack ({gap}). Likely losing repeat revenue.\nFIRST_MESSAGE: Hi {fname}, came across {company}. From what I could see publicly, looks like the post-purchase flow is wide open. That's what we build at Acme."

    return f"""# {company} — gap dossier

- **Domain:** {lead.get('domain','?')}
- **Band / score:** {score.get('band')} / {score.get('gap_score')}
- **Persona:** {score.get('persona')}
- **Founder:** {lead.get('contact_name') or '(unknown)'} | {lead.get('contact_linkedin') or 'no LinkedIn yet'}
- **Detected stack:** {detected}
- **Missing:** {gap}
- **Meta ads active (IN):** {lead.get('meta_ads_active')}
- **Evidence:** {infra.get('evidence', {})}

{body}

> Detection is ~70-80% accurate. Confirm the gap before any hard claim. Run the manual reply-speed test (DM + time the response) before outreach.
"""


def main():
    ap = argparse.ArgumentParser(description="Draft a LinkedIn note (debug)")
    ap.add_argument("--company", required=True)
    ap.add_argument("--domain", default="")
    ap.add_argument("--gap", default="")
    ap.add_argument("--name", default="")
    args = ap.parse_args()
    infra = {"bsp": None, "static_wa_link": True, "email_capture": None,
             "subscription": None, "loyalty": None, "reviews": None}
    lead = {"company": args.company, "domain": args.domain, "contact_name": args.name}
    note = draft_linkedin_note(lead, infra)
    print(f"[{len(note)} chars] {note}")
    print("violations:", voice_violations(note))


if __name__ == "__main__":
    main()
