"""apify.py — shared Apify REST wrapper (stdlib only, 3.9-safe).

Promoted from the copies duplicated across job_discover_apify.py,
find_clinic_leads.py, gap_discover_ads.py and swipe_scan.py. Import from here
instead of adding a 5th copy:

    from tools.utils.apify import run_apify_actor, run_apify_sync, apify_load_env

Uses urllib (no requests dependency) so it imports on any Python the repo runs,
including the system 3.9. Actor IDs may use "/" or "~" — both are normalized.

Requires APIFY_API_TOKEN in clip/.env.
"""

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.utils.retry import api_retry

APIFY_BASE = "https://api.apify.com"
_ENV_PATH = Path(__file__).parent.parent.parent / ".env"


def apify_load_env():
    """Populate os.environ from clip/.env (idempotent, never overrides)."""
    import os
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def get_token():
    """Read the Apify token (checks both common env names)."""
    import os
    apify_load_env()
    return os.environ.get("APIFY_API_TOKEN", "") or os.environ.get("APIFY_TOKEN", "")


@api_retry
def apify_post(endpoint, body, token, timeout=30):
    url = "{}{}?token={}".format(APIFY_BASE, endpoint, token)
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


@api_retry
def apify_get(endpoint, token, timeout=30):
    url = "{}{}?token={}".format(APIFY_BASE, endpoint, token)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _norm_actor(actor_id):
    return actor_id.replace("/", "~")


def run_apify_actor(actor_id, run_input, token, poll_interval=6.0, timeout=900.0,
                    tracker=None, label=""):
    """Start an actor run, poll until done, return dataset items (list of dicts).

    Raises on run failure or timeout. If `tracker` (a CreditTracker) is passed,
    records one 'apify' call per returned item.
    """
    actor = _norm_actor(actor_id)
    tag = label or actor
    print("[apify] start {}".format(tag), file=sys.stderr)
    start = apify_post("/v2/acts/{}/runs".format(actor), run_input, token)
    run = start.get("data", {})
    run_id, dataset_id = run.get("id"), run.get("defaultDatasetId")
    if not run_id or not dataset_id:
        raise RuntimeError("Apify malformed start response: {}".format(start))
    print("[apify]   run={} dataset={}".format(run_id, dataset_id), file=sys.stderr)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        status = apify_get("/v2/actor-runs/{}".format(run_id), token, timeout=15).get("data", {}).get("status")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError("Apify run {} status={}".format(run_id, status))
        print("[apify]   {} status={}".format(tag, status), file=sys.stderr)
    else:
        raise TimeoutError("Apify run {} did not finish in {}s".format(run_id, timeout))

    items = _fetch_items(dataset_id, token)
    if tracker is not None:
        try:
            tracker.track("apify", calls=len(items))
        except Exception:
            pass
    return items


def run_apify_sync(actor_id, run_input, token, timeout=300, tracker=None, label=""):
    """One-shot run via run-sync-get-dataset-items (no polling). Best for small pulls.

    Falls back to the empty list on non-200. Returns list of dicts.
    """
    actor = _norm_actor(actor_id)
    url = "{}/v2/acts/{}/run-sync-get-dataset-items?token={}".format(APIFY_BASE, actor, token)
    req = urllib.request.Request(
        url, data=json.dumps(run_input).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    print("[apify] sync {}".format(label or actor), file=sys.stderr)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            items = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print("[apify] sync HTTP {}: {}".format(e.code, e.read()[:300]), file=sys.stderr)
        return []
    if not isinstance(items, list):
        items = items.get("items", items.get("data", []))
    if tracker is not None:
        try:
            tracker.track("apify", calls=len(items))
        except Exception:
            pass
    return items


def _fetch_items(dataset_id, token):
    items = apify_get("/v2/datasets/{}/items".format(dataset_id), token, timeout=60)
    if isinstance(items, list):
        return items
    return items.get("items", items.get("data", []))
