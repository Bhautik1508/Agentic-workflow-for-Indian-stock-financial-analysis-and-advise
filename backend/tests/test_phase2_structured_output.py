"""Phase 2 — structured outputs, schema/prompt drift, and the prompt diet."""

import json
import re
from pathlib import Path

import pytest

from agents.base_agent import estimate_tokens, parse_and_validate, validate_report
from data.screener_summary import (
    clean_value,
    compute_cagr,
    find_row,
    normalize_key,
    summarize_screener,
)
from llm.providers import to_gemini_schema
from models.reports import (
    SCHEMA_BY_AGENT,
    FinancialReport,
    JudgeVerdict,
    MacroGovernanceReport,
    RiskReport,
    SentimentReport,
    TechnicalReport,
)

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
ALL_SCHEMAS = [FinancialReport, SentimentReport, TechnicalReport,
               RiskReport, MacroGovernanceReport, JudgeVerdict]


# ─────────────────────────────────────────────────────────────────────────────
# Gemini schema sanitisation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("schema", ALL_SCHEMAS, ids=lambda s: s.__name__)
def test_gemini_schema_has_no_unsupported_constructs(schema):
    """Gemini rejects `additionalProperties` outright and chokes on a dangling
    `$ref` with a bare KeyError. Both were real failures against the live API."""
    blob = json.dumps(to_gemini_schema(schema))
    assert "additionalProperties" not in blob
    assert "$ref" not in blob
    assert "$defs" not in blob


@pytest.mark.parametrize("schema", ALL_SCHEMAS, ids=lambda s: s.__name__)
def test_gemini_schema_is_a_usable_object(schema):
    built = to_gemini_schema(schema)
    assert built["type"] == "object"
    assert built["properties"], "schema must describe properties"
    assert "summary" in built["properties"]


def test_optional_nested_model_is_inlined_and_nullable():
    """Optional[GovernanceScoreDetail] arrives as anyOf[$ref, null]; the $ref
    must be resolved, not passed through."""
    built = to_gemini_schema(MacroGovernanceReport)
    detail = built["properties"]["governance_score_detail"]
    assert detail.get("nullable") is True
    assert "promoter_holding" in detail["properties"]


def test_sanitizer_handles_a_cyclic_schema():
    cyclic = {"type": "object", "properties": {"self": {"$ref": "#/$defs/Node"}},
              "$defs": {"Node": {"$ref": "#/$defs/Node"}}}
    assert to_gemini_schema(cyclic)  # must terminate, not hang


# ─────────────────────────────────────────────────────────────────────────────
# Validation policy: coerce vocabulary, fail on structure
# ─────────────────────────────────────────────────────────────────────────────

def test_vocabulary_drift_is_coerced_not_rejected():
    out = validate_report(
        {"summary": "s", "score": 7, "valuation_verdict": "Under-Valued",
         "financial_health": "EXCELLENT"},
        FinancialReport, "Financial Analyst")
    assert out["valuation_verdict"] == "undervalued"
    assert out["financial_health"] == "excellent"


def test_out_of_range_score_is_clamped_not_rejected():
    """A 10.5 should not cost the judge an entire pillar."""
    assert validate_report({"summary": "s", "score": 65}, RiskReport, "Risk")["score"] == 10.0
    assert validate_report({"summary": "s", "score": -4}, RiskReport, "Risk")["score"] == 0.0


def test_percentage_confidence_is_rescaled():
    out = validate_report({"summary": "s", "score": 7, "confidence": 85},
                          FinancialReport, "Financial Analyst")
    assert out["confidence"] == 0.85


@pytest.mark.parametrize("missing", ["summary", "score"])
def test_missing_load_bearing_field_raises(missing):
    """Structural failures must raise so agent_with_fallback degrades the
    report (score=None) rather than the judge weighing a fabricated number."""
    payload = {"summary": "s", "score": 7.0}
    payload.pop(missing)
    with pytest.raises(ValueError, match="failed schema validation"):
        validate_report(payload, FinancialReport, "Financial Analyst")


def test_unparseable_json_raises():
    with pytest.raises(ValueError):
        parse_and_validate("not json at all", FinancialReport, "Financial Analyst")


def test_parse_and_validate_strips_markdown_fences():
    out = parse_and_validate('```json\n{"summary":"s","score":6.0}\n```',
                             FinancialReport, "Financial Analyst")
    assert out["score"] == 6.0


def test_judge_action_is_normalised_to_upper_case():
    out = validate_report({"summary": "s", "action": "strong buy", "score": 8.0},
                          JudgeVerdict, "Judge Analyst")
    assert out["action"] == "STRONG_BUY"


# ─────────────────────────────────────────────────────────────────────────────
# Prompt <-> schema drift
# ─────────────────────────────────────────────────────────────────────────────

def top_level_prompt_keys(source: str) -> set:
    """Top-level keys of the JSON block a prompt asks the model to return.

    Scanned by brace depth, not by a flat regex: a regex also picks up Python
    dict literals elsewhere in the module and keys of nested objects such as
    `governance_score_detail`, none of which are top-level contract fields.

    The depth counter keys off DOUBLED braces. Prompts are `str.format`
    templates, so a real JSON brace is written `{{` while `{pe_ratio}` is a
    placeholder — counting single braces starts the scan inside the first
    placeholder and terminates immediately.
    """
    keys: set = set()
    token_re = re.compile(r'\{\{|\}\}|"([a-z_][a-z0-9_]*)"\s*:')
    for block in re.findall(r'"""(.*?)"""', source, re.DOTALL):
        if '"summary"' not in block:
            continue
        depth = 0
        started = False
        for match in token_re.finditer(block):
            token = match.group(0)
            if token == "{{":
                depth += 1
                started = True
            elif token == "}}":
                depth -= 1
                if started and depth <= 0:
                    break
            elif depth == 1 and match.group(1):
                keys.add(match.group(1))
    return keys


AGENT_FILES = {
    "Financial Analyst": "financial_analyst.py",
    "Sentiment Analyst": "sentiment_analyst.py",
    "Technical Analyst": "technical_analyst.py",
    "Risk Analyst": "risk_analyst.py",
    "Macro & Governance Analyst": "macro_governance_analyst.py",
    "Judge Analyst": "judge_analyst.py",
}


@pytest.mark.parametrize("agent,filename", sorted(AGENT_FILES.items()))
def test_every_key_the_prompt_asks_for_exists_on_the_schema(agent, filename):
    """The prompts still carry their JSON block because it also conveys *content*
    guidance ("cite the exact FII number") that a JSON Schema cannot. The risk
    of keeping both is drift — so this asserts every key the prompt requests is
    modelled. If they diverge, the build fails instead of a field silently
    vanishing during validation."""
    source = (AGENTS_DIR / filename).read_text()
    schema = SCHEMA_BY_AGENT[agent]

    declared = top_level_prompt_keys(source)
    assert declared, f"no JSON schema block found in {filename}"
    modelled = set(schema.model_fields)
    missing = declared - modelled
    assert not missing, (
        f"{filename} prompt asks for {sorted(missing)} but {schema.__name__} does not "
        f"model them — they would be silently dropped."
    )


@pytest.mark.parametrize("agent,filename", sorted(AGENT_FILES.items()))
def test_agent_passes_its_schema_to_the_router(agent, filename):
    source = (AGENTS_DIR / filename).read_text()
    assert f"response_schema={SCHEMA_BY_AGENT[agent].__name__}" in source
    assert "parse_and_validate(" in source


# ─────────────────────────────────────────────────────────────────────────────
# Prompt diet
# ─────────────────────────────────────────────────────────────────────────────

SCREENER_SAMPLE = {
    "Market Cap": "₹\n   7,96,269\n\n  Cr.",
    "Stock P/E": "14.8",
    "pl_Sales\xa0+": {f"Mar {y}": f"{100+y}" for y in range(2014, 2027)},
    "pl_Operating Profit": {f"Mar {y}": f"{50+y}" for y in range(2014, 2027)},
    "ratio_ROCE %": {f"Mar {y}": f"{40+y%10}%" for y in range(2015, 2027)},
    "noise_row": {f"Mar {y}": "x" * 40 for y in range(2014, 2027)},
}


def test_normalize_key_folds_nbsp_and_trailing_markers():
    """`pl_Sales\\xa0+` is what Screener actually returns; the old exact-match
    lookup never hit it, so Revenue CAGR was "N/A" in every prompt ever sent."""
    assert normalize_key("pl_Sales\xa0+") == normalize_key("pl_Sales")
    assert normalize_key("ratio_ROCE %") == normalize_key("ratio_ROCE")


def test_find_row_matches_despite_nbsp():
    assert find_row(SCREENER_SAMPLE, "pl_Sales") is not None


def test_cagr_computes_where_it_previously_returned_na():
    assert compute_cagr(find_row(SCREENER_SAMPLE, "pl_Sales"), 5) != "N/A"


def test_clean_value_collapses_scrape_whitespace():
    assert clean_value("₹\n   7,96,269\n\n  Cr.") == "₹ 7,96,269 Cr."


def test_summary_is_far_smaller_than_the_raw_dump():
    raw = json.dumps(SCREENER_SAMPLE, indent=2)
    summary = summarize_screener(SCREENER_SAMPLE)
    assert len(summary) < len(raw) / 2


def test_summary_caps_years_and_drops_unlisted_rows():
    summary = summarize_screener(SCREENER_SAMPLE, max_years=3)
    assert "2014" not in summary          # capped
    assert "noise_row" not in summary     # not decision-relevant
    assert "Sales:" in summary


def test_summary_handles_empty_input():
    assert summarize_screener({}) == "No Screener data."
    assert summarize_screener(None) == "No Screener data."


def test_prompt_budget_estimator_is_monotonic():
    small = estimate_tokens([{"content": "x" * 100}])
    large = estimate_tokens([{"content": "x" * 10000}])
    assert large > small > 0


def test_financial_agent_no_longer_dumps_the_whole_screener_payload():
    source = (AGENTS_DIR / "financial_analyst.py").read_text()
    assert "json.dumps(screener" not in source
    assert "summarize_screener(" in source


def test_provider_protocol_accepts_the_router_keywords():
    """The router calls complete() with every optional keyword; a provider that
    omits one fails at runtime, not at import. Checked by signature so the stub
    in test_llm_providers.py cannot mask a real omission."""
    import inspect

    from llm.providers import GeminiProvider, OpenAICompatProvider

    required = {"model", "temperature", "json_mode", "max_output_tokens",
                "response_schema", "thinking_budget"}
    for provider in (GeminiProvider, OpenAICompatProvider):
        params = set(inspect.signature(provider.complete).parameters)
        missing = required - params
        assert not missing, f"{provider.__name__}.complete is missing {sorted(missing)}"
