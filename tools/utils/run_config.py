"""Run configuration — versioned job-search run directories + credit tracking.

Adapted from the B2B repo for the CLIP job-search subsystem.
Per-run state lives in `data/job_runs/run_XXX/`.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent  # /Users/user/Desktop/clip2.0/clip
TMP_DIR = PROJECT_ROOT / "data" / "job_runs"


def get_run_id() -> str:
    """Get the current run ID from env var or auto-detect the latest existing one.

    Env var: JOB_RUN_ID overrides everything.
    Default: 'run_001' if nothing exists yet, else the highest existing.
    """
    run_id = os.getenv("JOB_RUN_ID", "")
    if run_id:
        return run_id

    if not TMP_DIR.exists():
        return "run_001"

    existing = sorted([
        d.name for d in TMP_DIR.iterdir()
        if d.is_dir() and d.name.startswith("run_")
    ])
    if not existing:
        return "run_001"
    return existing[-1]


def new_run_id() -> str:
    """Allocate the next sequential run ID (run_NNN)."""
    if not TMP_DIR.exists():
        return "run_001"
    existing = sorted([
        d.name for d in TMP_DIR.iterdir()
        if d.is_dir() and d.name.startswith("run_")
    ])
    if not existing:
        return "run_001"
    last = existing[-1]
    try:
        n = int(last.split("_")[1])
        return f"run_{n + 1:03d}"
    except (IndexError, ValueError):
        return "run_001"


def get_run_dir(run_id: str = None) -> Path:
    """Return the directory for a specific run."""
    if run_id is None:
        run_id = get_run_id()
    return TMP_DIR / run_id


def init_run(run_id: str = None, notes: str = "") -> Path:
    """Initialize a new run directory with subdirectories + meta.json.

    Subdirs: jobs/, enrichment/, managers/, fits/, resumes/, drafts/, errors/, apply/, connections/
    """
    if run_id is None:
        run_id = new_run_id()
    run_dir = get_run_dir(run_id)

    for subdir in [
        "jobs", "enrichment", "managers", "fits",
        "resumes", "drafts", "errors", "apply", "connections",
    ]:
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)

    meta = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "status": "running",
    }
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
    return run_dir


def finalize_run(run_id: str = None, summary: dict = None):
    """Mark a run complete + write summary to meta.json."""
    run_dir = get_run_dir(run_id)
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text())
    meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    meta["status"] = "completed"
    if summary:
        meta["summary"] = summary
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)


class CreditTracker:
    """Track API credit + browser-action usage across a job-search run.

    Tracks two distinct kinds of state:
      - Lifetime credits per external service (dollar/call-budgeted)
      - Daily activity counters that reset per UTC day (LinkedIn-safety caps)
    """

    def __init__(self, run_dir: Path = None, budgets: dict = None):
        self.run_dir = run_dir
        self.usage = {
            # External APIs (lifetime credits, run-scoped)
            "apollo":            {"calls": 0, "budget": 200, "service": "Apollo.io",          "est_cost_per_call": 0.50},
            "hunter":            {"calls": 0, "budget": 50,  "service": "Hunter.io",           "est_cost_per_call": 0.20},
            "firecrawl":         {"calls": 0, "budget": 500, "service": "Firecrawl"},
            "apify":             {"calls": 0, "budget": 100, "service": "Apify LinkedIn Jobs", "est_cost_per_call": 0.0003},
            "tavily":            {"calls": 0, "budget": 200, "service": "Tavily"},
            "anthropic_haiku":   {"calls": 0, "service": "Claude Haiku",  "est_cost_per_call": 0.001},
            "anthropic_sonnet":  {"calls": 0, "service": "Claude Sonnet", "est_cost_per_call": 0.015},

            # LinkedIn-safety daily counters (reset on UTC date change)
            "linkedin_easy_apply":  {"calls": 0, "daily_cap": 10, "service": "LinkedIn Easy Apply (auto)", "daily_reset": True},
            "linkedin_invites":     {"calls": 0, "daily_cap": 10, "service": "LinkedIn Connection Requests", "daily_reset": True, "weekly_cap": 70},
            "linkedin_dms":         {"calls": 0, "daily_cap": 20, "service": "LinkedIn DMs (post-accept)", "daily_reset": True},
            "browser_actions":      {"calls": 0, "service": "Claude in Chrome MCP actions", "daily_reset": True},
        }
        if budgets:
            for k, v in budgets.items():
                if k in self.usage:
                    if "budget" in self.usage[k]:
                        self.usage[k]["budget"] = v
                    elif "daily_cap" in self.usage[k]:
                        self.usage[k]["daily_cap"] = v

    def track(self, service: str, calls: int = 1):
        """Record API calls for a service."""
        if service not in self.usage:
            print(f"[credits] WARN: unknown service '{service}' tracked", flush=True)
            return
        self.usage[service]["calls"] += calls
        info = self.usage[service]

        if "budget" in info and info["calls"] >= info["budget"] * 0.8:
            pct = info["calls"] / info["budget"] * 100
            print(f"⚠ {info['service']} credit warning: {info['calls']}/{info['budget']} ({pct:.0f}%)")

        if info.get("daily_reset") and "daily_cap" in info:
            if info["calls"] >= info["daily_cap"]:
                print(f"🛑 {info['service']} daily cap hit: {info['calls']}/{info['daily_cap']} — pausing for the day")

    def can_use(self, service: str) -> bool:
        """Return True if there's still budget / cap headroom for this service."""
        info = self.usage.get(service)
        if not info:
            return True
        if "daily_cap" in info and info["calls"] >= info["daily_cap"]:
            return False
        if "budget" in info and info["calls"] >= info["budget"]:
            return False
        return True

    def summary(self) -> dict:
        """Generate credit usage summary."""
        result = {}
        for key, info in self.usage.items():
            entry = {"calls": info["calls"], "service": info["service"]}
            if "budget" in info:
                entry["budget"] = info["budget"]
                entry["remaining"] = info["budget"] - info["calls"]
            if "daily_cap" in info:
                entry["daily_cap"] = info["daily_cap"]
                entry["daily_remaining"] = max(0, info["daily_cap"] - info["calls"])
            if "weekly_cap" in info:
                entry["weekly_cap"] = info["weekly_cap"]
            if "est_cost_per_call" in info:
                entry["est_cost_usd"] = round(info["calls"] * info["est_cost_per_call"], 4)
            result[key] = entry
        return result

    def save(self):
        """Save credit usage to the run directory."""
        if self.run_dir:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            path = self.run_dir / "credits.json"
            with open(path, "w") as f:
                json.dump(self.summary(), f, indent=2)


# Global tracker — initialized by orchestrator or tools
_tracker = None


def get_tracker() -> CreditTracker:
    """Get the global credit tracker (creates one if needed)."""
    global _tracker
    if _tracker is None:
        _tracker = CreditTracker()
    return _tracker


def set_tracker(tracker: CreditTracker):
    """Set the global credit tracker (called by orchestrator)."""
    global _tracker
    _tracker = tracker
