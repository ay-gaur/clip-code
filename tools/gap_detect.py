#!/usr/bin/env python3
"""
gap_detect.py — Phase 2: polite website fetch + tech-stack signature detection.

Fetches a brand's homepage + one product page + /cart with `requests` (raw HTML —
NOT the WebFetch harness, which strips source), then runs the pure
`match_signatures()` from tools/utils/tech_signatures.py to detect what
funnel/retention infra they have or lack.

Politeness: real User-Agent, best-effort robots.txt, <=3 pages/domain, delay
between hits. Accuracy ~70-80% — "no signature" is PROBABILISTIC, never a public
"you don't have X" claim. Every hit carries an evidence string.

Usage:
  python3 tools/gap_detect.py --domain acme.in
"""

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
from tools.utils.tech_signatures import match_signatures, summarize_gaps
from tools.utils.gap_models import normalize_domain

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}
_SLUG_RE = re.compile(r'href=["\'](/products?/[a-z0-9\-]+)["\']', re.IGNORECASE)


def render_html(url: str, timeout: int = 20000, headless: bool = True) -> str:
    """Render a page with a real headless browser so JS- / tag-manager-injected
    widgets (Klaviyo, WhatsApp BSPs, loyalty) appear in the DOM that the substring
    matcher reads. FREE: uses Playwright + Chromium, no LLM, no API. Returns '' if
    Playwright isn't installed or the render fails (caller falls back to requests)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page(user_agent=UA)
            # "load" is reliable; networkidle hangs on sites with chat/analytics that
            # never go quiet. Then a short best-effort idle wait (capped) lets async
            # widgets (Klaviyo popup, loyalty) inject without risking a long stall.
            page.goto(url, timeout=timeout, wait_until="load")
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
            return html or ""
    except Exception as e:
        print(f"[gap_detect] render {url} failed: {type(e).__name__}", file=sys.stderr)
        return ""


def fetch_page(url: str, timeout: int = 15, render: bool = False) -> str:
    """GET a page, return HTML text or '' on any failure (never raises).

    render=True renders with a headless browser first (catches JS-injected stacks),
    falling back to a plain requests GET if the render yields nothing."""
    if render:
        html = render_html(url)
        if html:
            return html
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and resp.text:
            return resp.text
    except Exception as e:
        # broad on purpose: malformed ad "domains" raise LocationParseError /
        # InvalidURL (not RequestException) and must never crash the batch.
        print(f"[gap_detect] fetch {url} failed: {type(e).__name__}", file=sys.stderr)
    return ""


def _robots_disallows(base_url: str) -> list[str]:
    """Best-effort: return Disallow path prefixes for User-agent: * (empty on error)."""
    txt = fetch_page(base_url.rstrip("/") + "/robots.txt", timeout=8)
    if not txt:
        return []
    disallows, applies = [], False
    for line in txt.splitlines():
        line = line.strip()
        low = line.lower()
        if low.startswith("user-agent:"):
            applies = low.split(":", 1)[1].strip() in ("*",)
        elif applies and low.startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                disallows.append(path)
    return disallows


def _disallowed(path: str, disallows: list[str]) -> bool:
    return any(path.startswith(d) for d in disallows)


def find_product_slug(html: str) -> str | None:
    m = _SLUG_RE.search(html or "")
    return m.group(1) if m else None


def detect_infra(domain: str, *, delay: float = 2.0, cache_dir: Path | None = None,
                 render: bool = False, deep: bool = False) -> dict:
    """Fetch up to 3 pages and detect the tech stack. Returns the infra dict.

    render=True  -> render pages with Playwright first (free, no LLM) so JS- /
                    tag-manager-injected stacks are visible to the substring matcher.
    deep=True    -> additionally run the ScrapeGraphAI + Groq rendered LLM read and
                    union it in (catches what regex can't + extracts founder/products).
                    No-op + silent fallback if scrapegraphai isn't installed.
    """
    dom = normalize_domain(domain)
    if not dom:
        return {**match_signatures(""), "homepage_ok": False, "pages_fetched": [],
                "fetch_error": "no domain"}

    base = f"https://{dom}"
    home = fetch_page(base, render=render) or fetch_page(f"http://{dom}", render=render)
    if not home:
        return {**match_signatures(""), "homepage_ok": False, "pages_fetched": [],
                "fetch_error": "homepage fetch failed"}

    disallows = _robots_disallows(base)
    htmls, fetched = [home], ["/"]

    candidates = []
    slug = find_product_slug(home)
    if slug:
        candidates.append(slug)
    candidates.append("/cart")

    for path in candidates:
        if len(fetched) >= 3:
            break
        if _disallowed(path, disallows):
            continue
        time.sleep(delay)
        h = fetch_page(base + path, render=render)
        if h:
            htmls.append(h)
            fetched.append(path)

    combined = "\n".join(htmls)
    if cache_dir:
        try:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            (Path(cache_dir) / f"{dom}.html").write_text(combined[:500_000])
        except OSError:
            pass

    infra = match_signatures(combined)
    infra.update({"homepage_ok": True, "pages_fetched": fetched, "fetch_error": None})

    if deep:
        try:
            from tools.gap_deep_detect import deep_detect, merge_infra
            infra = merge_infra(infra, deep_detect(dom))
        except Exception as e:
            print(f"[gap_detect] deep merge skipped: {type(e).__name__}", file=sys.stderr)

    return infra


def main():
    ap = argparse.ArgumentParser(description="Detect D2C funnel/retention tech stack")
    ap.add_argument("--domain", required=True)
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--render", action="store_true",
                    help="render with Playwright first (free, catches JS-injected stacks)")
    ap.add_argument("--deep", action="store_true",
                    help="also run ScrapeGraphAI+Groq rendered LLM read (needs scrapegraphai)")
    args = ap.parse_args()

    infra = detect_infra(args.domain, delay=args.delay, render=args.render, deep=args.deep)
    print(f"homepage_ok : {infra.get('homepage_ok')}")
    print(f"pages       : {infra.get('pages_fetched')}")
    print(f"platform    : {infra.get('platform')}")
    print(f"BSP         : {infra.get('bsp')}  (static wa.me only: {infra.get('static_wa_link')})")
    print(f"email       : {infra.get('email_capture')}")
    print(f"subscription: {infra.get('subscription')}")
    print(f"loyalty     : {infra.get('loyalty')}")
    print(f"reviews     : {infra.get('reviews')}")
    print(f"pixels      : {infra.get('pixels')}")
    if infra.get("deep_detect"):
        print(f"founder     : {infra.get('founder_name')}  ({infra.get('founder_social')})")
        print(f"products    : {infra.get('products')}")
    print(f"GAPS        : {summarize_gaps(infra)}")


if __name__ == "__main__":
    main()
