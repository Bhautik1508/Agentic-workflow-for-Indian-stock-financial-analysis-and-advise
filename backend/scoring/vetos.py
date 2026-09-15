"""Hard veto rules. If any of these fire, the LLM's verdict is overridden.

These are the situations where the LLM's narrative reasoning is irrelevant —
the math says do not buy."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class VetoResult:
    triggered: bool
    forced_verdict: Optional[str]   # 'STRONG_SELL' | 'SELL' | 'HOLD' | None
    forced_confidence: Optional[float]
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "triggered": self.triggered,
            "forced_verdict": self.forced_verdict,
            "forced_confidence": self.forced_confidence,
            "reasons": self.reasons,
        }


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN guard


def evaluate_vetos(
    *,
    fundamental_data: Optional[Dict] = None,
    governance_data: Optional[Dict] = None,
    nse_data: Optional[Dict] = None,
    risk_report: Optional[Dict] = None,
) -> VetoResult:
    """Examine all known structural red flags. Severity escalates from
    SELL → STRONG_SELL based on how many independent vetos fire."""
    reasons: List[str] = []
    severity = 0

    fundamental_data = fundamental_data or {}
    governance_data = governance_data or {}
    nse_data = nse_data or {}
    risk_report = risk_report or {}

    # 1. Altman Z — bankruptcy distress.
    #
    # The threshold is the one belonging to the variant actually computed. This
    # used to hardcode 1.8, the distress line of the ORIGINAL 1968 model, while
    # nothing wrote the field at all. The emerging-market Z'' now computed puts
    # distress below 1.1; comparing a Z'' score to 1.8 would flag healthy
    # companies as distressed.
    #
    # `altman_veto_eligible` is False for financials and for unknown sectors,
    # where a Z-score is not meaningful and a forced SELL would be wrong.
    altman = _safe_float(fundamental_data.get("altman_z_score"))
    altman_zone = fundamental_data.get("altman_zone")
    altman_eligible = fundamental_data.get("altman_veto_eligible", True)
    if altman is not None and altman_eligible and altman_zone == "distress":
        variant = fundamental_data.get("altman_variant", "z")
        reasons.append(
            f"Altman Z-score {altman:.2f} ({variant}) in the distress zone — "
            f"balance-sheet stress"
        )
        severity += 2

    # 2. Promoter pledging — looked up under a few common keys
    pledge_pct = (
        _safe_float(governance_data.get("promoter_pledge_pct"))
        or _safe_float(governance_data.get("promoter_pledging_pct"))
        or _safe_float(governance_data.get("pledged_pct"))
    )
    if pledge_pct is not None and pledge_pct > 50:
        reasons.append(f"Promoter pledge {pledge_pct:.1f}% (> 50%) — solvency / ownership risk")
        severity += 2

    # 3. NSE surveillance status (ASM/GSM Stage 2+)
    surveillance = (nse_data.get("surveillance_flag") or "").upper()
    if any(tag in surveillance for tag in ("STAGE 2", "STAGE 3", "STAGE 4", "GSM", "ASM-II", "ASM II")):
        reasons.append(f"NSE surveillance flag: {surveillance} — operator-driven price action risk")
        severity += 2

    # 4. Going-concern qualification in audit report
    gc_flag = governance_data.get("going_concern_qualified")
    if gc_flag is True or (isinstance(gc_flag, str) and gc_flag.lower() in ("yes", "true", "qualified")):
        reasons.append("Auditor flagged going-concern qualification")
        severity += 3

    # 5. Risk agent score < 3.0 (extreme risk per the risk pillar)
    risk_score = _safe_float(risk_report.get("score") if isinstance(risk_report, dict) else None)
    if risk_score is not None and risk_score < 3.0:
        reasons.append(f"Risk pillar score {risk_score:.1f} (< 3.0) — extreme-risk territory")
        severity += 1

    if severity == 0:
        return VetoResult(triggered=False, forced_verdict=None, forced_confidence=None, reasons=[])

    if severity >= 3:
        return VetoResult(
            triggered=True,
            forced_verdict="STRONG_SELL",
            forced_confidence=0.85,
            reasons=reasons,
        )
    return VetoResult(
        triggered=True,
        forced_verdict="SELL",
        forced_confidence=0.70,
        reasons=reasons,
    )
