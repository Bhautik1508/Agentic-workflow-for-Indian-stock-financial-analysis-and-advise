"""Tests for Phase 2 — verdict engine upgrade.

Covers:
- Grounded pricing math (fundamental, technical, ATR stop, position size)
- Reconciliation precedence (blended → fundamental → technical → analyst → LLM-capped → none)
- Investor profiles (weights, bands, profile selection)
- band_for_score covers all five verdict bands per profile
- Veto rules fire on each individual trigger AND escalate when stacked
- _build_grounded_targets pulls the right fields from a typical state shape
"""

import pytest

from scoring import (
    INVESTOR_PROFILES,
    DEFAULT_PROFILE,
    band_for_score,
    compute_atr_stop,
    compute_fundamental_target,
    compute_position_size_modifier,
    compute_technical_target,
    evaluate_vetos,
    get_profile,
    profile_bands,
    profile_weights,
    reconcile_targets,
)


# ─────────────────────────────────────────────────────────────────────────────
# compute_fundamental_target
# ─────────────────────────────────────────────────────────────────────────────

def test_fundamental_target_basic_math():
    # forward EPS 100, sector PE 22 → target 2200
    assert compute_fundamental_target(100, 22) == 2200.0


def test_fundamental_target_handles_string_inputs():
    assert compute_fundamental_target("100", "22.5") == 2250.0


def test_fundamental_target_returns_none_on_missing_inputs():
    assert compute_fundamental_target(None, 22) is None
    assert compute_fundamental_target(100, None) is None
    assert compute_fundamental_target(100, 0) is None       # zero PE
    assert compute_fundamental_target(100, -5) is None      # negative PE


def test_fundamental_target_falls_back_to_implied_eps():
    # forward EPS missing → derive from price=2000 / pe=20 = EPS 100 → target = 100 × 22 = 2200
    target = compute_fundamental_target(
        forward_eps=None,
        sector_median_pe=22,
        fallback_eps_from_pe=(2000, 20),
    )
    assert target == 2200.0


def test_fundamental_target_handles_nan_and_inf():
    assert compute_fundamental_target(float("nan"), 22) is None
    assert compute_fundamental_target(float("inf"), 22) is None


# ─────────────────────────────────────────────────────────────────────────────
# compute_technical_target
# ─────────────────────────────────────────────────────────────────────────────

def test_technical_target_uses_median_of_levels_above_price():
    # Current 100; levels 110, 120, 130 → median 120
    target = compute_technical_target(
        100,
        week_52_high=110,
        fib_1618=120,
        nearest_resistance=130,
    )
    assert target == 120.0


def test_technical_target_filters_out_levels_below_price():
    # Levels 95 and 90 are *below* current 100 → ignored. Only 120 counts.
    target = compute_technical_target(
        100,
        week_52_high=95,
        fib_1618=90,
        nearest_resistance=120,
    )
    assert target == 120.0


def test_technical_target_returns_none_when_all_levels_below_price():
    target = compute_technical_target(
        100,
        week_52_high=95,
        fib_1618=90,
        nearest_resistance=85,
    )
    assert target is None


def test_technical_target_returns_none_for_invalid_price():
    assert compute_technical_target(None, week_52_high=120) is None
    assert compute_technical_target(0, week_52_high=120) is None


def test_technical_target_robust_to_one_outlier():
    # Three sane levels around 110, one wild 1000 — median (110, 115, 120, 1000) = 117.5
    target = compute_technical_target(
        100,
        week_52_high=110,
        fib_1618=115,
        nearest_resistance=120,
        analyst_target=1000,
    )
    assert target == 117.5


# ─────────────────────────────────────────────────────────────────────────────
# compute_atr_stop
# ─────────────────────────────────────────────────────────────────────────────

def test_atr_stop_basic():
    # entry 100, ATR 2 → 100 - 2*2 = 96
    assert compute_atr_stop(100, 2.0) == 96.0


def test_atr_stop_clamps_to_floor_when_atr_is_huge():
    # entry 100, ATR 50 → raw stop -100; ceiling_pct=15% → bounded at 85
    stop = compute_atr_stop(100, 50.0)
    assert stop == pytest.approx(85.0, abs=0.01)


def test_atr_stop_clamps_to_ceiling_when_atr_is_tiny():
    # entry 100, ATR 0.1 → raw stop 99.8; floor_pct=3% → bounded at 97.0
    stop = compute_atr_stop(100, 0.1)
    assert stop == pytest.approx(97.0, abs=0.01)


def test_atr_stop_falls_back_to_5pct_when_atr_missing():
    assert compute_atr_stop(100, None) == 95.0
    assert compute_atr_stop(100, 0) == 95.0


def test_atr_stop_returns_none_for_invalid_entry():
    assert compute_atr_stop(None, 2.0) is None
    assert compute_atr_stop(0, 2.0) is None


# ─────────────────────────────────────────────────────────────────────────────
# compute_position_size_modifier
# ─────────────────────────────────────────────────────────────────────────────

def test_position_size_full_when_low_volatility():
    # 20% vol → 1.0
    assert compute_position_size_modifier(20.0) == 1.0


def test_position_size_half_at_moderate_volatility():
    # 40% vol → ~0.6
    assert compute_position_size_modifier(40.0) == pytest.approx(0.6, abs=0.01)


def test_position_size_floors_at_high_volatility():
    assert compute_position_size_modifier(80.0) == 0.1


def test_position_size_respects_profile_max():
    # Aggressive profile allows 1.5×
    size = compute_position_size_modifier(20.0, profile_max=1.5)
    assert size == 1.5


def test_position_size_default_when_volatility_missing():
    size = compute_position_size_modifier(None)
    assert 0.1 <= size <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# reconcile_targets
# ─────────────────────────────────────────────────────────────────────────────

def test_reconcile_blends_fundamental_and_technical():
    g = reconcile_targets(
        current_price=100,
        fundamental_target=120,
        technical_target=110,
        atr_14=2,
        volatility_1y_pct=20,
    )
    assert g.target_price == 115.0  # average
    assert g.method == "blended_fundamental_technical"
    assert g.upside_pct == 15.0


def test_reconcile_uses_fundamental_only_when_technical_missing():
    g = reconcile_targets(
        current_price=100,
        fundamental_target=120,
        technical_target=None,
        atr_14=2,
    )
    assert g.target_price == 120.0
    assert g.method == "fundamental_only"


def test_reconcile_falls_back_to_analyst_then_llm():
    g = reconcile_targets(
        current_price=100,
        fundamental_target=None,
        technical_target=None,
        analyst_target=130,
        llm_target=999,  # ignored — analyst wins
    )
    assert g.target_price == 130.0
    assert g.method == "analyst_consensus"


def test_reconcile_caps_llm_target_at_25pct():
    """Last-resort LLM number must be capped to ±25 % of current price."""
    g = reconcile_targets(
        current_price=100,
        fundamental_target=None,
        technical_target=None,
        analyst_target=None,
        llm_target=500,  # absurd
    )
    assert g.target_price == 125.0
    assert g.method == "llm_capped"


def test_reconcile_returns_none_target_when_all_inputs_missing():
    g = reconcile_targets(
        current_price=100,
        fundamental_target=None,
        technical_target=None,
        analyst_target=None,
        llm_target=None,
    )
    assert g.target_price is None
    assert g.method == "none"


def test_reconcile_computes_reward_to_risk():
    g = reconcile_targets(
        current_price=100,
        fundamental_target=120,
        technical_target=110,
        atr_14=2,  # stop = 96 → 4% downside
    )
    # upside 15%, downside 4% → R/R ≈ 3.75
    assert g.upside_pct == 15.0
    assert g.downside_pct == 4.0
    assert g.reward_to_risk == pytest.approx(3.75, abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# Profiles
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["conservative", "balanced", "aggressive"])
def test_profile_weights_sum_to_one(name):
    weights = profile_weights(name)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert set(weights) == {"financial", "technical", "risk", "sentiment", "macro_gov"}


def test_conservative_weights_risk_higher_than_balanced():
    cons = profile_weights("conservative")
    bal = profile_weights("balanced")
    assert cons["risk"] > bal["risk"]
    assert cons["sentiment"] < bal["sentiment"]


def test_aggressive_weights_technical_higher_than_balanced():
    agg = profile_weights("aggressive")
    bal = profile_weights("balanced")
    assert agg["technical"] > bal["technical"]
    assert agg["risk"] < bal["risk"]


def test_unknown_profile_falls_back_to_default():
    name, spec = get_profile("yolo")
    assert name == DEFAULT_PROFILE
    assert spec is INVESTOR_PROFILES[DEFAULT_PROFILE]


def test_empty_profile_falls_back_to_default():
    name, _ = get_profile("")
    assert name == DEFAULT_PROFILE


@pytest.mark.parametrize("name", ["conservative", "balanced", "aggressive"])
def test_profile_bands_cover_all_five_verdicts(name):
    bands = profile_bands(name)
    assert set(bands) == {"STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"}
    # Bands should be monotonically descending
    assert bands["STRONG_BUY"] > bands["BUY"] > bands["HOLD"] > bands["SELL"] > bands["STRONG_SELL"]


def test_band_for_score_strong_buy():
    assert band_for_score(9.0, "balanced") == "STRONG_BUY"


def test_band_for_score_buy_threshold():
    bands = profile_bands("balanced")
    assert band_for_score(bands["BUY"], "balanced") == "BUY"
    assert band_for_score(bands["BUY"] - 0.01, "balanced") == "HOLD"


def test_band_for_score_strong_sell_floor():
    assert band_for_score(0.0, "balanced") == "STRONG_SELL"


def test_conservative_needs_higher_score_for_buy_than_aggressive():
    """The same 6.0 score is BUY under aggressive but HOLD under conservative."""
    assert band_for_score(6.0, "aggressive") == "BUY"
    assert band_for_score(6.0, "conservative") == "HOLD"


# ─────────────────────────────────────────────────────────────────────────────
# Vetos
# ─────────────────────────────────────────────────────────────────────────────

def test_no_red_flags_no_veto():
    v = evaluate_vetos(fundamental_data={"altman_z_score": 4.0})
    assert v.triggered is False
    assert v.forced_verdict is None
    assert v.reasons == []


def test_altman_distress_zone_triggers_sell():
    """The veto now keys off the model's own zone rather than a bare number.

    It previously compared against 1.8 — the distress line of the ORIGINAL 1968
    Z-score — while the field was never populated at all. The emerging-market
    Z'' now computed puts distress below 1.1, so a raw 1.8 comparison would flag
    healthy companies."""
    v = evaluate_vetos(fundamental_data={
        "altman_z_score": 0.9, "altman_zone": "distress", "altman_veto_eligible": True,
    })
    assert v.triggered is True
    assert v.forced_verdict == "SELL"
    assert any("Altman" in r for r in v.reasons)


def test_altman_grey_zone_does_not_veto():
    v = evaluate_vetos(fundamental_data={
        "altman_z_score": 1.9, "altman_zone": "grey", "altman_veto_eligible": True,
    })
    assert v.triggered is False


def test_altman_does_not_veto_when_not_eligible():
    """Financials and unknown sectors must not force a SELL: a Z-score is not
    meaningful for a bank, and a wrong forced SELL is worse than no signal."""
    v = evaluate_vetos(fundamental_data={
        "altman_z_score": 0.4, "altman_zone": "distress", "altman_veto_eligible": False,
    })
    assert v.triggered is False


def test_altman_absent_does_not_veto():
    v = evaluate_vetos(fundamental_data={"altman_z_score": None, "altman_zone": None})
    assert v.triggered is False


def test_promoter_pledge_triggers_sell():
    v = evaluate_vetos(governance_data={"promoter_pledge_pct": 60})
    assert v.triggered is True
    assert v.forced_verdict == "SELL"
    assert any("pledge" in r.lower() for r in v.reasons)


def test_nse_stage_2_triggers_sell():
    v = evaluate_vetos(nse_data={"surveillance_flag": "ASM Stage 2"})
    assert v.triggered is True
    # The veto canonicalises the flag to upper-case in its reason string
    assert any("STAGE 2" in r for r in v.reasons)


def test_going_concern_triggers_strong_sell_alone():
    """Going concern alone has severity 3 → STRONG_SELL even without other flags."""
    v = evaluate_vetos(governance_data={"going_concern_qualified": True})
    assert v.triggered is True
    assert v.forced_verdict == "STRONG_SELL"


def test_risk_score_below_three_triggers_sell():
    v = evaluate_vetos(risk_report={"score": 2.5})
    assert v.triggered is True
    assert v.forced_verdict == "SELL"


def test_multiple_severe_vetos_escalate_to_strong_sell():
    v = evaluate_vetos(
        fundamental_data={"altman_z_score": 0.8, "altman_zone": "distress",
                          "altman_veto_eligible": True},               # +2
        governance_data={"promoter_pledge_pct": 70},   # +2
    )
    assert v.triggered is True
    assert v.forced_verdict == "STRONG_SELL"
    assert len(v.reasons) >= 2


def test_veto_handles_missing_data_gracefully():
    """No crash when no data of any kind is provided."""
    v = evaluate_vetos()
    assert v.triggered is False


def test_veto_safe_to_string_score():
    v = evaluate_vetos(risk_report={"score": "2.0"})
    assert v.triggered is True


# ─────────────────────────────────────────────────────────────────────────────
# Judge integration — non-LLM helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_build_grounded_targets_with_realistic_state():
    from agents.judge_analyst import _build_grounded_targets

    state = {
        "fundamental_data": {
            "forward_eps": 50,
            "pe_ratio": 25,
            "analyst_target_price": 1300,
        },
        "price_data": {
            "current_price": 1200,
            "week_52_high": 1280,
        },
        "risk_data": {
            "atr_14": 24,
            "volatility_1y": 22,
        },
        "technical_data": {
            "fib_1618": 1320,
            "nearest_resistance": 1290,
        },
        "peer_data": {
            "sector_median_pe": 28,
        },
    }
    g = _build_grounded_targets(state, "balanced", llm_target=1500)
    assert g.target_price is not None
    assert g.method in (
        "blended_fundamental_technical",
        "fundamental_only",
        "technical_only",
        "analyst_consensus",
    )
    assert g.stop_loss is not None
    assert g.stop_loss < state["price_data"]["current_price"]
    assert 0.1 <= g.position_size_modifier <= 1.0


def test_build_grounded_targets_handles_empty_state():
    """If price/fundamental data is entirely missing, function still returns a
    GroundedTargets object — just with everything None except position_size."""
    from agents.judge_analyst import _build_grounded_targets

    g = _build_grounded_targets({}, "balanced")
    assert g.target_price is None
    assert g.stop_loss is None
    assert g.method == "none"


# ─────────────────────────────────────────────────────────────────────────────
# Routes accept the profile query param
# ─────────────────────────────────────────────────────────────────────────────

def test_routes_signature_accepts_profile_param():
    """Smoke check that the FastAPI route surfaces ?profile= as expected."""
    import inspect
    from api import routes
    sig = inspect.signature(routes.analyze_stock)
    assert "profile" in sig.parameters
    assert sig.parameters["profile"].default == "balanced"
