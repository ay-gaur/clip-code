# tools/utils package — shared helpers across the job-search pipeline.
# Imports below give callers a flat namespace: `from tools.utils import api_retry, RateLimiter, ...`
from .rate_limiter import (
    RateLimiter,
    apollo_limiter,
    hunter_limiter,
    firecrawl_limiter,
    claude_limiter,
    tavily_limiter,
    apify_limiter,
)
from .retry import (
    with_retry,
    api_retry,
    claude_retry,
    scrape_retry,
)
from .run_config import (
    PROJECT_ROOT,
    TMP_DIR,
    get_run_id,
    new_run_id,
    get_run_dir,
    init_run,
    finalize_run,
    CreditTracker,
    get_tracker,
    set_tracker,
)
from .models import (
    Job,
    HiringManager,
    FitScore,
    TailoredResume,
    JobArtifacts,
    ApplyAttempt,
    ConnectionAttempt,
    save_result,
    load_result,
    result_exists,
)

__all__ = [
    "RateLimiter",
    "apollo_limiter", "hunter_limiter", "firecrawl_limiter",
    "claude_limiter", "tavily_limiter", "apify_limiter",
    "with_retry", "api_retry", "claude_retry", "scrape_retry",
    "PROJECT_ROOT", "TMP_DIR",
    "get_run_id", "new_run_id", "get_run_dir", "init_run", "finalize_run",
    "CreditTracker", "get_tracker", "set_tracker",
    "Job", "HiringManager", "FitScore", "TailoredResume",
    "JobArtifacts", "ApplyAttempt", "ConnectionAttempt",
    "save_result", "load_result", "result_exists",
]
