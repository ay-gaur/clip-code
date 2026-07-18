"""gap_models.py — data model for the find-gap-leads pipeline.

Mirrors the dataclass + to_dict/from_dict pattern in tools/utils/models.py.
A GapLead flattens directly into the existing data/leads.json shape (so legacy
0-10 `fit_score` consumers keep working) while adding the gap-scoring fields.
"""

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from urllib.parse import urlparse


def _filter_kwargs(cls, d):
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}


def normalize_domain(url_or_domain: str) -> str:
    """Reduce a URL or host to a bare registrable-ish domain (lowercase, no www)."""
    if not url_or_domain:
        return ""
    s = url_or_domain.strip().lower()
    if "://" not in s:
        s = "http://" + s
    host = urlparse(s).netloc or ""
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def stable_id(domain: str, company: str = "", source_url: str = "") -> str:
    """Deterministic 10-char id. Domain-first so re-runs map to the same record."""
    seed = normalize_domain(domain) or (company.strip().lower() + "|" + source_url.strip().lower())
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


@dataclass
class GapLead:
    # ---- identity / provenance ----
    id: str = ""                       # sha1(domain) — stable across runs
    company: str = ""
    domain: str = ""
    source_url: str = ""
    gap_source: str = "find-gap-leads"  # distinguishes from find_leads.py rows
    discovered: str = ""               # YYYY-MM-DD

    # ---- contact (LinkedIn primary; email opportunistic) ----
    contact_name: str = ""
    contact_linkedin: str = ""
    contact_email: str = ""
    enriched: bool = False

    # ---- detection + scoring ----
    infra_detected: dict = field(default_factory=dict)
    meta_ads_active: bool | None = None
    persona: str = ""                  # d2c_founder | info_product | coach | consultant
    gap_score: int = 0                 # 0-100
    score_components: dict = field(default_factory=dict)
    band: str = "drop"                 # priority | shortlist | watchlist | drop
    hard_gate: str | None = None       # too_early | too_late | None
    partner_flag: bool = False         # consultant -> partner track
    audience_flag: bool = False        # too_early -> nurture/education audience
    reply_speed_test_pending: bool = False
    reasoning: str = ""

    # ---- legacy-compatible fields (read by lead-scan/pipeline-status/outreach) ----
    fit_score: int = 0                 # round(gap_score/10)
    pain_signal: str = ""              # missing-infra one-liner
    status: str = "new"

    # ---- drafted output ----
    linkedin_note: str = ""

    def sync_legacy(self):
        """Keep the legacy 0-10 fit_score + pain_signal in sync with gap fields."""
        self.fit_score = round(self.gap_score / 10)
        if not self.pain_signal:
            from tools.utils.tech_signatures import summarize_gaps
            self.pain_signal = summarize_gaps(self.infra_detected or {})
        return self

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_filter_kwargs(cls, d))

    @classmethod
    def from_candidate(cls, cand: dict):
        """Build a fresh GapLead from a discovery candidate dict."""
        domain = normalize_domain(cand.get("domain") or cand.get("source_url", ""))
        return cls(
            id=stable_id(domain, cand.get("company", ""), cand.get("source_url", "")),
            company=cand.get("company", "").strip(),
            domain=domain,
            source_url=cand.get("source_url", ""),
            contact_name=cand.get("contact_name", ""),
            contact_linkedin=cand.get("contact_linkedin", ""),
            meta_ads_active=cand.get("meta_ads_active"),  # True if found via Meta Ad Library
            discovered=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )


def first_name(full_name: str) -> str:
    """Best-effort first name for note templating (avoids sending names to Gemini)."""
    if not full_name:
        return "there"
    tok = re.split(r"\s+", full_name.strip())
    return tok[0] if tok and tok[0] else "there"
