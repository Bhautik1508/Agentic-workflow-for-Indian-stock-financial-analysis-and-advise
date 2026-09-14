"""Pluggable data-source interfaces.

The previous plan proposed this and never built it. It matters because
`yfinance` is currently load-bearing *and* unreliable: it is rate-limited from
Render's IPs, which is why production runs show `fundamental_completeness` of
0.2 and why thinly-covered tickers abort the data-quality gate entirely.

Defining the seam is the precondition for swapping in a paid feed (Tickertape,
Tijori) without touching the agents. It is intentionally a `Protocol` rather
than a base class: `YFinanceFundamentals` below already satisfies it by virtue
of its shape, so nothing existing had to be rewritten to adopt it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class IFundamentalsProvider(Protocol):
    """A source of company fundamentals for one ticker."""

    name: str

    async def fetch(self, ticker: str) -> Dict[str, Any]:
        """Return a fundamentals dict, or `{}` when unavailable.

        Must not raise for an unknown ticker — return `{}` so the caller can
        fall through to the next provider. `data_quality.evaluate_data_quality`
        decides whether what came back is enough to render a verdict.
        """
        ...


@runtime_checkable
class INewsProvider(Protocol):
    name: str

    async def fetch(self, company_name: str, ticker: str = "") -> List[Dict[str, str]]:
        ...


class YFinanceFundamentals:
    """The current default, wrapping the existing fetch path."""

    name = "yfinance"

    async def fetch(self, ticker: str) -> Dict[str, Any]:
        from data.market_data import fetch_all_market_data

        payload = await fetch_all_market_data(ticker)
        return (payload or {}).get("fundamental_data", {}) or {}


class FallbackChain:
    """Try providers in order; first non-empty result wins.

    Mirrors how the LLM router already handles vendors, and for the same
    reason: one source being down should degrade the run, not end it.
    """

    name = "chain"

    def __init__(self, *providers: IFundamentalsProvider):
        self.providers = list(providers)

    async def fetch(self, ticker: str) -> Dict[str, Any]:
        import logging

        logger = logging.getLogger(__name__)
        for provider in self.providers:
            try:
                result = await provider.fetch(ticker)
            except Exception as exc:
                logger.warning(f"[data] provider '{provider.name}' raised: {str(exc)[:120]}")
                continue
            if result:
                return result
            logger.info(f"[data] provider '{provider.name}' returned nothing for {ticker}")
        return {}


def default_fundamentals_provider() -> IFundamentalsProvider:
    """The chain the app uses. Add a paid feed ahead of yfinance here."""
    return FallbackChain(YFinanceFundamentals())
