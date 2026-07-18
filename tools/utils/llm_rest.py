"""llm_rest.py — free-tier LLM calls over plain REST (no SDK).

Alex's ANTHROPIC_API_KEY is broken (401), so this module deliberately avoids the
Anthropic SDK every other tool uses. Two free providers, mutual fallback:

  - Groq (Llama 3.3 70B): bulk SCORING. Free, no card, ~1000 req/day, does NOT
    train on prompts. Preferred for anything structured/high-volume.
  - Gemini 2.5 Flash: PROSE drafts. Key already in .env, ~250 req/day, 1M context.
    WARNING: free tier TRAINS on prompts — scrub PII before sending.

`call_llm(...)` returns the model's text, or None if neither key is present or
both providers error (callers must degrade to a deterministic path on None).

Verified live June 2026. Endpoints:
  Groq:   POST https://api.groq.com/openai/v1/chat/completions  (OpenAI-shaped)
  Gemini: POST https://generativelanguage.googleapis.com/v1beta/models/<m>:generateContent
"""

import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.utils.retry import with_retry

BASE = Path(__file__).parent.parent.parent

GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.5-flash"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# PII scrub patterns (applied on the Gemini path only — it trains on free-tier data)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?91[\-\s]?)?\b\d{10}\b")


def load_env() -> None:
    """Populate os.environ from the project .env (idempotent, never overrides)."""
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _scrub_pii(text: str, extra_terms: list[str] | None = None) -> str:
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    for term in (extra_terms or []):
        if term and term.strip():
            text = re.sub(re.escape(term.strip()), "[NAME]", text, flags=re.IGNORECASE)
    return text


def _available() -> dict:
    return {
        # Paid, reliable, no free-tier rate caps. OpenAI-compatible, so it also
        # covers paid Groq, OpenRouter, Together, etc. via OPENAI_BASE_URL.
        # Drop OPENAI_API_KEY (+ optional OPENAI_BASE_URL / OPENAI_MODEL) in .env
        # to make the whole pipeline self-serve at volume.
        "openai": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "groq": bool(os.environ.get("GROQ_API_KEY", "").strip()),
        "gemini": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
    }


@with_retry(max_attempts=3, base_wait=2.0, max_wait=20.0,
            exceptions=(requests.RequestException,), name="groq")
def _call_groq(prompt: str, json_mode: bool, max_tokens: int, temperature: float) -> str | None:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return None
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body, timeout=45,
    )
    if resp.status_code == 429:
        print("[llm_rest] Groq 429 rate-limited", file=sys.stderr)
        return None
    if resp.status_code >= 400:
        print(f"[llm_rest] Groq {resp.status_code}: {resp.text[:400]}", file=sys.stderr)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


@with_retry(max_attempts=3, base_wait=2.0, max_wait=20.0,
            exceptions=(requests.RequestException,), name="gemini")
def _call_gemini(prompt: str, json_mode: bool, max_tokens: int, temperature: float) -> str | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    # 2.5 Flash is a thinking model; thinking tokens eat maxOutputTokens and
    # truncate the output (JSON or prose). We use Flash for speed/cost, not deep
    # reasoning, so disable thinking on every call.
    gen_cfg = {"temperature": temperature, "maxOutputTokens": max_tokens,
               "thinkingConfig": {"thinkingBudget": 0}}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"
    resp = requests.post(
        GEMINI_URL.format(model=GEMINI_MODEL),
        params={"key": key},
        headers={"Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_cfg},
        timeout=45,
    )
    if resp.status_code == 429:
        print("[llm_rest] Gemini 429 rate-limited", file=sys.stderr)
        return None
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return None


@with_retry(max_attempts=3, base_wait=2.0, max_wait=20.0,
            exceptions=(requests.RequestException,), name="openai")
def _call_openai(prompt: str, json_mode: bool, max_tokens: int, temperature: float) -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body, timeout=60,
    )
    if resp.status_code == 429:
        print("[llm_rest] OpenAI 429 rate-limited", file=sys.stderr)
        return None
    if resp.status_code >= 400:
        print(f"[llm_rest] OpenAI {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_llm(prompt: str, *, prefer: str = "groq", json_mode: bool = False,
             max_tokens: int = 1500, temperature: float = 0.3,
             scrub: bool = True, scrub_terms: list[str] | None = None) -> str | None:
    """Call the preferred free LLM, falling back to the other on failure.

    prefer: "groq" (scoring/structured) or "gemini" (prose).
    scrub:  when the resolved provider is Gemini, redact emails/phones (+ scrub_terms)
            from the prompt before sending, since Gemini's free tier trains on data.
            Groq is never scrubbed (no training).
    Returns text, or None if no provider is available / both error.
    """
    load_env()
    avail = _available()
    if not any(avail.values()):
        print("[llm_rest] No GROQ_API_KEY or GEMINI_API_KEY set", file=sys.stderr)
        return None

    # Paid OpenAI-compatible provider always goes first when present (no rate caps).
    free = ["groq", "gemini"] if prefer == "groq" else ["gemini", "groq"]
    order = (["openai"] if avail["openai"] else []) + free
    order = [p for p in order if avail[p]]

    for provider in order:
        try:
            if provider == "openai":
                out = _call_openai(prompt, json_mode, max_tokens, temperature)
            elif provider == "groq":
                out = _call_groq(prompt, json_mode, max_tokens, temperature)
            else:
                gem_prompt = _scrub_pii(prompt, scrub_terms) if scrub else prompt
                out = _call_gemini(gem_prompt, json_mode, max_tokens, temperature)
            if out:
                return out
        except Exception as e:  # noqa: BLE001 — fall through to next provider
            print(f"[llm_rest] {provider} failed: {type(e).__name__}: {e}", file=sys.stderr)
            continue
    return None


def _strip_code_fence(text: str) -> str:
    """Reuse the find_leads.py code-fence stripping convention."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def call_llm_json(prompt: str, *, prefer: str = "groq", max_tokens: int = 1500,
                  temperature: float = 0.2, scrub: bool = True,
                  scrub_terms: list[str] | None = None):
    """call_llm with JSON-mode + robust parsing. Returns dict/list or None."""
    import json
    raw = call_llm(prompt, prefer=prefer, json_mode=True, max_tokens=max_tokens,
                   temperature=temperature, scrub=scrub, scrub_terms=scrub_terms)
    if not raw:
        return None
    try:
        return json.loads(_strip_code_fence(raw))
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[llm_rest] JSON parse failed: {e}", file=sys.stderr)
        return None


def call_llm_list(prompt: str, *, prefer: str = "groq", max_tokens: int = 1800,
                  temperature: float = 0.2, scrub: bool = True,
                  scrub_terms: list[str] | None = None):
    """Like call_llm_json but always returns a LIST.

    JSON-object mode (required by Groq) wraps arrays in an object, e.g.
    {"leads": [...]}. This coerces that back to the list. Returns None on failure.
    """
    obj = call_llm_json(prompt, prefer=prefer, max_tokens=max_tokens,
                        temperature=temperature, scrub=scrub, scrub_terms=scrub_terms)
    if obj is None:
        return None
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in ("leads", "items", "results", "candidates", "brands", "data", "array", "list"):
            if isinstance(obj.get(k), list):
                return obj[k]
        for v in obj.values():
            if isinstance(v, list):
                return v
        return [obj]  # a single object -> one-element list
    return None


def provider_status() -> str:
    load_env()
    a = _available()
    bits = []
    bits.append("OpenAI-compat ✓ (paid, preferred)" if a["openai"] else "OpenAI-compat ✗ (add OPENAI_API_KEY for self-serve at volume)")
    bits.append("Groq ✓" if a["groq"] else "Groq ✗ (add free GROQ_API_KEY)")
    bits.append("Gemini ✓" if a["gemini"] else "Gemini ✗")
    return " | ".join(bits)


if __name__ == "__main__":
    print("[llm_rest] providers:", provider_status())
    out = call_llm("Reply with exactly: OK", prefer="groq", max_tokens=10)
    print("[llm_rest] test call ->", repr(out))
