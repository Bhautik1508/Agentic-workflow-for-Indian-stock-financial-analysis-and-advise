"""Structured run log: one JSON file per analysis, used as the foundation for
backtesting (Phase 6) and for debugging which inputs produced which verdict."""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from analysis_version import ANALYSIS_VERSION
from serialization import dump as json_dump

logger = logging.getLogger(__name__)

RUN_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".runlog")
os.makedirs(RUN_LOG_DIR, exist_ok=True)

IST = timezone(timedelta(hours=5, minutes=30))

# Run logs are the raw material for backtesting, so they are kept generously —
# but not forever. Render's disk is ephemeral and unbounded growth there is a
# slow-motion outage rather than a feature.
MAX_RUN_LOGS = int(os.environ.get("MAX_RUN_LOGS", "500") or 500)


def prune_run_logs(max_files: int = MAX_RUN_LOGS) -> int:
    """Keep the newest `max_files` run logs, delete the rest. Returns the count
    removed. Never raises: losing a log must not fail an analysis."""
    try:
        if not os.path.isdir(RUN_LOG_DIR):
            return 0
        entries = []
        for name in os.listdir(RUN_LOG_DIR):
            if not name.endswith(".json"):
                continue
            path = os.path.join(RUN_LOG_DIR, name)
            try:
                entries.append((path, os.path.getmtime(path)))
            except OSError:
                continue
        if len(entries) <= max_files:
            return 0
        entries.sort(key=lambda e: e[1], reverse=True)   # newest first
        removed = 0
        for path, _ in entries[max_files:]:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
        if removed:
            logger.info(f"[run-log] pruned {removed} old run logs (cap {max_files})")
        return removed
    except Exception as exc:
        logger.debug(f"[run-log] prune skipped: {exc}")
        return 0


def new_run_id() -> str:
    return f"run_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def read_run_log(run_id: str) -> Optional[dict]:
    """Look up a previously written run log by id. Returns None if not found.

    Run-log filenames are `{run_id}__{ticker}.json`, so we glob by prefix to
    avoid having to re-derive the ticker."""
    if not run_id:
        return None
    safe = _safe(run_id)
    try:
        for fname in os.listdir(RUN_LOG_DIR):
            if fname.startswith(f"{safe}__") and fname.endswith(".json"):
                with open(os.path.join(RUN_LOG_DIR, fname), "r") as f:
                    return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Failed to read run log {run_id}: {exc}")
    return None


def write_run_log(
    run_id: str,
    ticker: str,
    company_name: str,
    *,
    inputs_summary: Optional[dict] = None,
    analyst_reports: Optional[dict] = None,
    judge_payload: Optional[dict] = None,
    error: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    telemetry: Optional[dict] = None,
    data_quality: Optional[dict] = None,
    analytics: Optional[dict] = None,
) -> Optional[str]:
    """Write a self-contained JSON record. Best-effort — never raises."""
    payload: Dict[str, Any] = {
        "run_id": run_id,
        "ticker": ticker,
        "company_name": company_name,
        "timestamp_ist": datetime.now(IST).isoformat(),
        # Which engine produced this verdict. A hit-rate pooled across engines
        # measures neither of them — see analysis_version.py.
        "analysis_version": ANALYSIS_VERSION,
        "duration_seconds": duration_seconds,
        "error": error,
        "inputs_summary": inputs_summary or {},
        "analyst_reports": _scrub_reports(analyst_reports or {}),
        "judge": judge_payload or {},
        "telemetry": telemetry or {},
        "data_quality": data_quality or {},
        # relative_context / quality_metrics / extended_risk. Without these a
        # shared permalink lost all five phases of analytics the live page
        # shows — the thing the page exists to share.
        "analytics": analytics or {},
    }

    try:
        prune_run_logs()
        path = os.path.join(RUN_LOG_DIR, f"{_safe(run_id)}__{_safe(ticker)}.json")
        with open(path, "w") as f:
            json_dump(payload, f, indent=2)
        return path
    except Exception as exc:
        logger.warning(f"Failed to write run log for {run_id}: {exc}")
        return None


# The four scalars the comparison tiles read. Everything else in `data` is a
# regurgitation of upstream API responses, which is what the scrub exists to
# drop — but losing these made a shared permalink render four fewer tiles than
# the live page for no reason anyone would have noticed.
_KEEP_DATA_KEYS = (
    "pe_premium_discount_pct",   # financial  -> "vs Sector P/E"
    "beta_category",             # risk       -> "Beta profile"
    "trend",                     # technical  -> "Trend"
    "macro_environment",         # macro      -> "Macro setup"
)


def _scrub_reports(reports: dict) -> dict:
    """Keep the parts useful for backtesting and for re-rendering a frozen
    verdict; drop the bulky raw `data` blob when it's just a regurgitation of
    upstream API responses.

    `data_table` is display content, not raw payload — a handful of
    label/value/signal rows per agent. Dropping it made every analyst card on
    /verdict/{id} say "No signals returned"."""
    cleaned: Dict[str, Any] = {}
    for key, report in reports.items():
        if not isinstance(report, dict):
            cleaned[key] = report
            continue
        cleaned[key] = {
            "agent_name":   report.get("agent_name"),
            "status":       _str_status(report.get("status")),
            "score":        report.get("score"),
            "confidence":   report.get("confidence"),
            "summary":      report.get("summary"),
            "signal_line":  report.get("signal_line"),
            "key_findings": report.get("key_findings", []),
            "risk_flags":   report.get("risk_flags", []),
            "degraded":     report.get("degraded", False),
            "error":        report.get("error"),
            "data_table":   report.get("data_table") or [],
        }
        # Only when something survives the whitelist. A blob with nothing worth
        # keeping leaves no `data` key at all, so "the raw blob is not stored"
        # stays literally true rather than becoming "it is stored, but empty".
        kept = _keep_data(report.get("data"))
        if kept:
            cleaned[key]["data"] = kept
    return cleaned


def _keep_data(data: Any) -> Dict[str, Any]:
    """Whitelist the scalars the UI reads out of an agent's `data` blob."""
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in _KEEP_DATA_KEYS}


def _str_status(s: Any) -> str:
    if s is None:
        return "unknown"
    return getattr(s, "value", None) or str(s)
