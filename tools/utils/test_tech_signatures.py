#!/usr/bin/env python3
"""Offline unit test for match_signatures — no network. Run: python3 tools/utils/test_tech_signatures.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.utils.tech_signatures import match_signatures, summarize_gaps

# A brand that LACKS what Acme sells: static wa.me link, no BSP, no subs/loyalty.
WA_ONLY = """
<html><head>
<script src="https://static.klaviyo.com/onsite/js/abcd12/klaviyo.js"></script>
<script>connect.facebook.net/en_US/fbevents.js; fbq('init','123')</script>
</head><body>
<a href="https://wa.me/919372682623">Chat with us on WhatsApp</a>
<div data-shopify>cdn.shopify.com/s/files</div>
<div id="judgeme_product_reviews"></div>
</body></html>
"""

# A mature brand that already HAS the stack: real BSP, subscription, loyalty.
FULL_STACK = """
<html><head>
<script src="https://widget.gallabox.com/widget.js"></script>
<script src="https://static.klaviyo.com/onsite/js/xx/klaviyo.js"></script>
<script src="https://cdn.smile.io/v1/smile.js"></script>
<script src="https://www.rechargecdn.com/checkout.js"></script>
<script src="https://googletagmanager.com/gtag/js?id=G-XXX"></script>
</head><body>cdn.shopify.com</body></html>
"""


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1
check.failed = 0


def main():
    a = match_signatures(WA_ONLY)
    print("WA_ONLY (early brand, missing retention layer):")
    check("BSP not detected", a["bsp"] is None)
    check("static_wa_link flagged (THE gap signal)", a["static_wa_link"] is True)
    check("klaviyo email capture detected", a["email_capture"] == "klaviyo")
    check("no subscription", a["subscription"] is None)
    check("no loyalty", a["loyalty"] is None)
    check("judge.me reviews detected", a["reviews"] == "judgeme")
    check("meta pixel detected", "meta" in a["pixels"])
    check("shopify platform detected", a["platform"] == "shopify")
    check("evidence recorded for wa link", "wa_link" in a["evidence"])
    print("  gaps:", summarize_gaps(a))

    b = match_signatures(FULL_STACK)
    print("\nFULL_STACK (mature brand, already has the layer):")
    check("BSP = gallabox", b["bsp"] == "gallabox")
    check("static_wa_link NOT flagged (BSP present)", b["static_wa_link"] is False)
    check("subscription = recharge", b["subscription"] == "recharge")
    check("loyalty = smile", b["loyalty"] == "smile")
    print("  gaps:", summarize_gaps(b))

    c = match_signatures("")
    print("\nEMPTY:")
    check("empty html -> no crash, bsp None", c["bsp"] is None)
    check("empty html -> static_wa_link False", c["static_wa_link"] is False)

    print(f"\n{'ALL TESTS PASSED' if check.failed == 0 else str(check.failed) + ' TEST(S) FAILED'}")
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
