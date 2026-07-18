"""Data models for the job-search pipeline.

Pattern mirrors the B2B classification pipeline:
- Dataclasses with .to_dict() / .from_dict() (asdict-based)
- save_result(obj, output_dir, key_field) writes JSON keyed by an attribute
- load_result(key, output_dir) returns the dict or None
- result_exists(key, output_dir) returns True iff JSON exists and is valid
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


def _filter_dataclass_kwargs(cls, d):
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}


@dataclass
class Job:
    """A discovered job posting (across all sources)."""
    job_id: str  # sha1(normalized_company + normalized_title + normalized_location)
    source: str  # "linkedin_apify" | "hn_who_hiring" | "yc_work_at_startup" | "wellfound" | "firecrawl_careers"
    company: str
    title: str
    url: str = ""
    location: Optional[str] = None
    remote_policy: Optional[str] = None  # "remote" | "hybrid" | "onsite" | "unknown"
    raw_jd: str = ""
    posted_at: Optional[str] = None  # ISO-8601 date if known
    discovered_at: str = ""  # ISO-8601 when our pipeline saw it
    # Phase 2 enrichment fields (populated by job_enrich.py)
    role_bucket: Optional[str] = None  # "apm" | "product_analyst" | "ai_engineer" | "solutions" | "other"
    seniority: Optional[str] = None    # "intern" | "entry" | "mid" | "senior" | "staff" | "lead"
    comp_band_usd: Optional[str] = None  # "<50k" | "50-80k" | "80-120k" | "120k+" | "unknown"
    tech_stack: list = field(default_factory=list)
    growth_stage: Optional[str] = None  # "pre-seed" | "seed" | "series-a" | "series-b" | "series-c+" | "public" | "unknown"
    company_size: Optional[str] = None  # "<10" | "10-50" | "50-200" | "200-1k" | "1k+" | "unknown"
    must_haves: list = field(default_factory=list)
    nice_to_haves: list = field(default_factory=list)
    apply_method: Optional[str] = None  # "easy_apply" | "external_ats" | "email" | "company_form" | "unknown"
    apply_url: Optional[str] = None
    ats_platform: Optional[str] = None  # "greenhouse" | "lever" | "ashby" | "workday" | "smartrecruiters" | etc.
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_filter_dataclass_kwargs(cls, d))


@dataclass
class HiringManager:
    """A decision-maker identified for a specific job (Phase 3 output)."""
    job_id: str
    company: str
    name: str = ""
    title: str = ""
    seniority_rank: int = 0  # higher = more senior (founder=10, vp=8, director=6, head=7, manager=4, ic=1)
    linkedin_url: Optional[str] = None
    email: Optional[str] = None
    email_verified: bool = False
    apollo_person_id: Optional[str] = None
    role_match_reason: str = ""  # why this person was picked for this role bucket
    source: str = "apollo"  # "apollo" | "hunter" | "manual"
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_filter_dataclass_kwargs(cls, d))


@dataclass
class FitScore:
    """Phase 4 fit-score result."""
    job_id: str
    score: int = 0  # 1-10
    reasoning: str = ""
    recommended_variant: str = ""  # "apm" | "product_analyst" | "ai_engineer"
    bucket: str = ""  # "auto_tailor" (>=7) | "borderline" (4-6) | "skip" (<4)
    green_flags: list = field(default_factory=list)
    red_flags: list = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_filter_dataclass_kwargs(cls, d))


@dataclass
class TailoredResume:
    """Phase 5 result — per-job tailored .tex + (optional) .pdf."""
    job_id: str
    variant_used: str = ""
    tex_path: str = ""     # absolute path to tailored.tex
    pdf_path: Optional[str] = None  # None if compile failed or pdflatex unavailable
    diff_summary: str = ""  # short description of what changed vs variant
    compile_ok: bool = False
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_filter_dataclass_kwargs(cls, d))


@dataclass
class JobArtifacts:
    """Phase 6 — drafts for apply forms + LinkedIn outreach."""
    job_id: str
    cover_paragraph: str = ""  # ~100 words, for ATS "why this role" fields
    screener_answers_per_job: dict = field(default_factory=dict)  # answers Claude generated specifically for this JD
    connect_note: str = ""  # ≤300 chars for LinkedIn connection request
    follow_up_dm: str = ""  # full DM with resume link, sent on connection acceptance
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_filter_dataclass_kwargs(cls, d))


@dataclass
class ApplyAttempt:
    """Phase 7a — one Easy Apply submission via Claude in Chrome MCP."""
    job_id: str
    attempted_at: str = ""  # ISO-8601
    status: str = "pending"  # "submitted" | "rejected_by_user" | "form_error" | "skipped_external_ats" | "captcha_halt" | "duplicate"
    screenshot_path: Optional[str] = None
    reason: Optional[str] = None
    submit_url: Optional[str] = None
    outreach_sent_at: Optional[str] = None  # set when Phase 7b processes this entry

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_filter_dataclass_kwargs(cls, d))


@dataclass
class ConnectionAttempt:
    """Phase 7b/7c — LinkedIn connection request + follow-up DM tracking."""
    connection_id: str  # sha1(manager_name + company)
    job_id: str
    manager_name: str
    manager_linkedin_url: str = ""
    sent_at: str = ""
    note_text: str = ""
    status: str = "pending"  # "pending" | "accepted" | "withdrawn" | "rejected"
    accepted_at: Optional[str] = None
    dm_sent: bool = False
    dm_sent_at: Optional[str] = None
    dm_text: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_filter_dataclass_kwargs(cls, d))


# ---------- Persistence helpers ----------

def save_result(result, output_dir: Path, key_field: str = "job_id"):
    """Save a dataclass result as JSON to the output directory, named by its key.

    For Job/FitScore/etc., key_field = 'job_id'. For ConnectionAttempt, 'connection_id'.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    key = getattr(result, key_field)
    path = output_dir / f"{key}.json"
    with open(path, "w") as f:
        json.dump(result.to_dict(), f, indent=2, default=str)
    return path


def load_result(key: str, output_dir: Path) -> Optional[dict]:
    """Load a previously saved result. Returns None if not found / corrupt."""
    path = Path(output_dir) / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def result_exists(key: str, output_dir: Path) -> bool:
    """Check whether a non-empty JSON for `key` already exists (for resumability)."""
    path = Path(output_dir) / f"{key}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
        return isinstance(data, dict) and len(data) > 0
    except (json.JSONDecodeError, OSError):
        return False
