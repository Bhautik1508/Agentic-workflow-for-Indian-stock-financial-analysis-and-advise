"""Regression tests for present-but-None fields in upstream payloads.

`dict.get(key, default)` returns the default only when the key is ABSENT.
yfinance routinely returns the key with an explicit None — and when it is
rate-limited (which it is from Render's IPs) that is the common case, not the
edge case. `fundamental.get("sector", "Unknown").lower()` therefore crashed the
Macro & Governance analyst on every production run.
"""

import re
from pathlib import Path

import pytest

from agents.base_agent import str_field

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


def test_str_field_handles_missing_key():
    assert str_field({}, "sector", "Unknown") == "Unknown"


def test_str_field_handles_explicit_none():
    """The case that actually broke production."""
    assert str_field({"sector": None}, "sector", "Unknown") == "Unknown"


def test_str_field_returns_real_value():
    assert str_field({"sector": "Technology"}, "sector", "Unknown") == "Technology"


def test_str_field_coerces_non_strings():
    assert str_field({"x": 42}, "x", "unknown") == "42"


def test_str_field_survives_a_non_dict():
    assert str_field(None, "sector", "Unknown") == "Unknown"
    assert str_field([], "sector", "Unknown") == "Unknown"


def test_str_field_result_supports_string_methods():
    """The whole point: the result must be safe to call .lower()/.upper() on."""
    assert str_field({"sector": None}, "sector", "Unknown").lower() == "unknown"
    assert str_field({"t": None}, "t", "no_data").replace("_", " ").upper() == "NO DATA"


UNSAFE = re.compile(
    r'\.get\([^)]*,\s*"[^"]*"\)\.(lower|upper|replace|strip|split|title)\('
)


@pytest.mark.parametrize(
    "agent_file",
    sorted(p.name for p in AGENTS_DIR.glob("*.py") if p.name != "base_agent.py"),
)
def test_no_agent_calls_string_methods_on_a_raw_get(agent_file):
    """Guards the whole class of bug, not just the one instance that fired.

    16 of these existed across 4 agents; `sector` was simply the field that
    happened to be None first. Use `str_field(...)` instead.
    """
    source = (AGENTS_DIR / agent_file).read_text()
    offenders = [
        line.strip()
        for line in source.splitlines()
        if UNSAFE.search(line) and not line.strip().startswith(("#", "*"))
    ]
    assert not offenders, (
        f"{agent_file} calls a string method on a raw .get() result, which dies "
        f"when the key is present-but-None. Use str_field(). Offending: {offenders}"
    )
