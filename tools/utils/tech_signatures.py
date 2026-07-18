"""tech_signatures.py — D2C tech-stack signature library + pure detector.

Pure data + a network-free `match_signatures(html)` function so detection logic
is unit-testable offline. `gap_detect.py` handles the actual HTTP fetching and
calls `match_signatures()` on the concatenated raw HTML.

Detection is lowercase-substring matching against raw page source. Accuracy is
~70-80% (misses tools loaded via tag managers or server-side), so EVERY positive
detection carries an `evidence` string and the absence of a signature is treated
as PROBABILISTIC — never assert "they don't have X" publicly. Outreach copy must
hedge ("from what I could see publicly").

Signatures sourced from the HTTPArchive/Wappalyzer fingerprint DB + vendor docs
(June 2026). Indian WhatsApp BSPs (AiSensy/Interakt/Wati/Gallabox) are NOT in the
mainstream Wappalyzer DB, so those substrings come from vendor widget docs and
carry slightly lower confidence.
"""

# category -> vendor -> list of lowercase substrings that prove the vendor is present
SIGNATURES: dict[str, dict[str, list[str]]] = {
    # WhatsApp Business Solution Providers — the key India retention layer
    "bsp": {
        "aisensy":  ["app.aisensy.com", "aisensy-widget", "aisensywidget"],
        "interakt": ["cdn.interakt.ai", "app.interakt.ai", "interakt-widget"],
        "wati":     ["wati.io/widget", "live-server.wati.io", "wati_widget", "clare.ai"],
        "gallabox": ["widget.gallabox.com", "cdn.gallabox.com", "gallaboxwidget"],
        "haptik":   ["haptikapi.com", "haptiksdk", "haptikinitsettings"],
        "verloop":  ["livechat.verloop.io", "verloop-widget", "verloop.io"],
        "yellow":   ["cdn.yellowmessenger.com", "ymconfig", "yellow.ai"],
        "bik":      ["bik.ai", "bikwidget"],
        "limechat": ["limechat.ai"],
    },
    # Email / SMS capture + marketing automation
    "email_capture": {
        "klaviyo":  ["static.klaviyo.com/onsite/js", "klaviyo.js", "klaviyosubscribe"],
        "mailmodo": ["mailmodo.com", "mailmodo-widget"],
        "wigzo":    ["wigzo.com"],
        "privy":    ["privy.com", "privymarketing"],
        "omnisend": ["omnisend.com", "omnisend"],
        "mailchimp":["chimpstatic.com/mcjs-connected", "mc-validate.js"],
        "brevo":    ["sibforms.com", "sibautomation.com"],
    },
    # Subscription / auto-replenish (Shopify)
    "subscription": {
        "recharge": ["rechargecdn.com", "rechargeapps", "recharge-checkout"],
        "loop":     ["loopwork.co", "loop_subscriptions", "loopsubscriptionswidget"],
        "appstle":  ["appstle", "appstle-subscription"],
        "skio":     ["skio.com/sdk", "skiosubscriptions", "cdn.skio.com"],
        "bold":     ["sub.boldapps.net", "bold.subscriptions"],
        "awtomic":  ["awtomic.com", "awtomic-widget"],
    },
    # Loyalty / rewards
    "loyalty": {
        "smile":        ["cdn.smile.io", "smile.io"],
        "yotpo_loyalty":["cdn-loyalty.yotpo.com", "swellrewards.com", "swellconfig"],
        "loyaltylion":  ["sdk.loyaltylion.net", "loyaltylion"],
        "rivo":         ["rivo.io/widget", "rivo-loyalty", "cdn.rivo.io"],
        "growave":      ["growave.io", "cdn.growave.io"],
        "joy":          ["joy.avada.io", "joy-loyalty"],
    },
    # Reviews / UGC
    "reviews": {
        "judgeme":      ["judge.me", "jdgm", "judgeme"],
        "loox":         ["loox.io/widget", "loox_global_hash"],
        "yotpo_reviews":["staticw2.yotpo.com", "yotpo.com/v1/widget"],
        "stamped":      ["stamped-io.com", "stamped.io/widget"],
        "okendo":       ["okendo.io", "okewidgetapi", "okendoreviews"],
        "junip":        ["juniphq.com", "juniploaded"],
    },
    # Ad pixels — proxy for active paid-ad spend (ability-to-pay)
    "pixels": {
        "meta":     ["connect.facebook.net", "fbevents.js", "fbq('init'", "fbq(\"init\""],
        "ga4":      ["googletagmanager.com/gtag/js", "gtag('config', 'g-", "gtag(\"config\", \"g-"],
        "gads":     ["gtag('config', 'aw-", "googleads.g.doubleclick"],
        "tiktok":   ["analytics.tiktok.com", "tiktokanalyticsobject"],
        "pinterest":["s.pinimg.com/ct", "pintrk('load'"],
        "snap":     ["sc-static.net/scevent.min.js", "snaptr('init'"],
    },
    # Storefront platform
    "platform": {
        "shopify":     ["cdn.shopify.com", "shopify.shop", "myshopify.com"],
        "woocommerce": ["wp-content/plugins/woocommerce", "woocommerce"],
        "wix":         ["wixstatic.com", "wix.com"],
        "magento":     ["mage/cookies", "magento"],
        "custom":      [],  # nothing matched -> likely custom/headless
    },
}

# WhatsApp click-to-chat without a BSP = the headline "missing what we sell" signal
_WA_LINK_SUBSTRINGS = ["wa.me/", "api.whatsapp.com/send", "whatsapp.com/send?"]

# Categories where a single vendor result makes sense (vs. pixels which is a list)
_SINGLE = ["bsp", "email_capture", "subscription", "loyalty", "reviews", "platform"]


def _first_match(html_lower: str, category: str) -> tuple[str | None, str | None]:
    """Return (vendor, matched_substring) for the first vendor whose signature appears."""
    for vendor, subs in SIGNATURES[category].items():
        for s in subs:
            if s and s in html_lower:
                return vendor, s
    return None, None


def _all_matches(html_lower: str, category: str) -> tuple[list[str], dict]:
    hits, ev = [], {}
    for vendor, subs in SIGNATURES[category].items():
        for s in subs:
            if s and s in html_lower:
                hits.append(vendor)
                ev[vendor] = s
                break
    return hits, ev


def match_signatures(html: str) -> dict:
    """Pure, network-free tech-stack detection over concatenated raw HTML.

    Returns a dict with detected vendors per category, the headline
    `static_wa_link` gap signal, and an `evidence` map (vendor -> matched string)
    used to keep outreach copy honest/hedged.
    """
    h = (html or "").lower()
    evidence: dict[str, str] = {}

    result: dict = {}
    for cat in _SINGLE:
        vendor, matched = _first_match(h, cat)
        result[cat] = vendor
        if vendor and matched:
            evidence[f"{cat}:{vendor}"] = matched

    pixels, pixel_ev = _all_matches(h, "pixels")
    result["pixels"] = pixels
    for v, s in pixel_ev.items():
        evidence[f"pixels:{v}"] = s

    has_wa = any(s in h for s in _WA_LINK_SUBSTRINGS)
    # static click-to-chat link present but no managed BSP detected
    result["static_wa_link"] = bool(has_wa and result["bsp"] is None)
    if has_wa:
        evidence["wa_link"] = next((s for s in _WA_LINK_SUBSTRINGS if s in h), "wa.me/")

    result["evidence"] = evidence
    return result


def summarize_gaps(infra: dict) -> str:
    """One-line human summary of what's MISSING (for sheet/pain_signal column)."""
    gaps = []
    if infra.get("bsp") is None:
        gaps.append("no WhatsApp BSP" + (" (static wa.me only)" if infra.get("static_wa_link") else ""))
    if infra.get("email_capture") is None:
        gaps.append("no email capture")
    if infra.get("subscription") is None:
        gaps.append("no subscription")
    if infra.get("loyalty") is None:
        gaps.append("no loyalty")
    return "; ".join(gaps) if gaps else "core retention stack present"
