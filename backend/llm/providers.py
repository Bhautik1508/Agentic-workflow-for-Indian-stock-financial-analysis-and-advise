"""Provider adapters for the LLM router.

Why this layer exists
---------------------
The router used to take a single Groq client and call
`client.chat.completions.create(...)` directly. That coupled us to one vendor's
wire format, so "add a second provider" meant rewriting the router. It also made
a whole class of outage invisible: when Groq decommissioned
`llama-3.3-70b-versatile`, every call 404'd and there was no other provider to
fall through to.

Each provider here normalises one vendor onto a single `complete()` coroutine
returning a `CompletionResult`. The router only ever sees that shape, so adding
or reordering vendors is config, not code.

Message format is OpenAI-shaped (`[{"role": "system"|"user"|"assistant",
"content": str}]`) because that is what every agent already builds. Providers
that speak a different dialect (Gemini) translate on the way in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class CompletionResult:
    """Normalised response shape every provider returns."""
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMProvider(Protocol):
    """Minimal contract the router depends on."""

    name: str

    def is_configured(self) -> bool:
        """True when the credentials this provider needs are present."""
        ...

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.1,
        json_mode: bool = True,
        max_output_tokens: Optional[int] = None,
    ) -> CompletionResult:
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Gemini (google-genai SDK)
# ─────────────────────────────────────────────────────────────────────────────

def _split_system(messages: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
    """Gemini takes the system prompt out-of-band, not as a message role."""
    system_parts: List[str] = []
    rest: List[Dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(str(m.get("content", "")))
        else:
            rest.append(m)
    return "\n\n".join(p for p in system_parts if p), rest


class GeminiProvider:
    """Google Gemini via the `google-genai` SDK.

    Thinking is disabled by default (`GEMINI_THINKING_BUDGET=0`). Every agent
    here does structured extraction over a large, fully-supplied context rather
    than open-ended reasoning, so thinking tokens mostly buy latency. Raise the
    budget if you want the judge to deliberate — see docs in IMPROVEMENTS.md.
    """

    name = "gemini"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key if api_key is not None else os.environ.get("GOOGLE_API_KEY", "")
        self._client = None

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self):
        if self._client is None:
            from google import genai  # imported lazily so the app boots without the SDK
            if not self._api_key:
                raise ValueError("GOOGLE_API_KEY is not set — Gemini provider unavailable.")
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.1,
        json_mode: bool = True,
        max_output_tokens: Optional[int] = None,
    ) -> CompletionResult:
        from google.genai import types

        client = self._get_client()
        system_instruction, chat_messages = _split_system(messages)

        contents = [
            types.Content(
                # Gemini's assistant role is "model"; everything else maps to "user".
                role="model" if m.get("role") == "assistant" else "user",
                parts=[types.Part(text=str(m.get("content", "")))],
            )
            for m in chat_messages
        ]

        config_kwargs: Dict[str, Any] = {"temperature": temperature}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        if max_output_tokens:
            config_kwargs["max_output_tokens"] = max_output_tokens

        thinking_budget = _int_env("GEMINI_THINKING_BUDGET", 0)
        if thinking_budget >= 0:
            # 2.5-pro ignores a 0 budget (thinking is always on there); harmless.
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        text = _gemini_text(response)
        prompt_tokens, completion_tokens = _gemini_usage(response)
        return CompletionResult(text=text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)


def _gemini_text(response) -> str:
    """Pull text out, turning empty/blocked/truncated responses into errors.

    Returning '' here would surface as a JSON parse failure three layers up with
    no hint of the real cause, and — worse — would not trigger provider
    failover. Raising lets the router move to the next provider.
    """
    text = None
    try:
        text = response.text
    except (AttributeError, ValueError):
        text = None

    if text:
        return text.strip()

    finish_reason = None
    try:
        finish_reason = str(response.candidates[0].finish_reason)
    except (AttributeError, IndexError, TypeError):
        pass

    feedback = getattr(response, "prompt_feedback", None)
    raise RuntimeError(
        f"Gemini returned no text (finish_reason={finish_reason}, prompt_feedback={feedback})"
    )


def _gemini_usage(response) -> tuple[int, int]:
    try:
        usage = response.usage_metadata
        prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
        completion = int(getattr(usage, "candidates_token_count", 0) or 0)
        # Thinking tokens are billed as output; count them so cost reporting is honest.
        completion += int(getattr(usage, "thoughts_token_count", 0) or 0)
        return prompt, completion
    except (AttributeError, TypeError):
        return 0, 0


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI-shaped providers (Groq, and any OpenAI-compatible endpoint)
# ─────────────────────────────────────────────────────────────────────────────

class OpenAICompatProvider:
    """Wraps any client exposing `client.chat.completions.create(...)`.

    Used for Groq, and for tests that inject a hand-rolled fake client.
    """

    def __init__(self, client, name: str = "openai_compat"):
        self.name = name
        self._client = client

    def is_configured(self) -> bool:
        return self._client is not None

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.1,
        json_mode: bool = True,
        max_output_tokens: Optional[int] = None,
    ) -> CompletionResult:
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"} if json_mode else None,
        }
        response = await self._client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content
        prompt_tokens, completion_tokens = _openai_usage(response)
        return CompletionResult(
            text=(text or "").strip(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


class GroqProvider(OpenAICompatProvider):
    """Groq via the official AsyncGroq SDK. Kept as the fallback tier."""

    name = "groq"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key if api_key is not None else os.environ.get("GROQ_API_KEY", "")
        super().__init__(client=None, name="groq")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _ensure_client(self):
        if self._client is None:
            from groq import AsyncGroq
            if not self._api_key:
                raise ValueError("GROQ_API_KEY is not set — Groq provider unavailable.")
            self._client = AsyncGroq(api_key=self._api_key)
        return self._client

    async def complete(self, messages, **kwargs) -> CompletionResult:
        self._ensure_client()
        return await super().complete(messages, **kwargs)


def _openai_usage(response) -> tuple[int, int]:
    try:
        usage = response.usage
        return (
            int(getattr(usage, "prompt_tokens", 0) or 0),
            int(getattr(usage, "completion_tokens", 0) or 0),
        )
    except (AttributeError, TypeError):
        return 0, 0


# ─────────────────────────────────────────────────────────────────────────────
# Chain construction
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Attempt:
    """One (provider, model) the router may try, in order."""
    provider: Any
    model: str

    def __repr__(self) -> str:  # keeps log lines readable
        return f"{self.provider.name}:{self.model}"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


# Defaults are env-overridable so a model decommission is a dashboard change,
# not a redeploy. Groq's llama-3.x models were retired from the API; the
# gpt-oss pair below is what the account actually serves today.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_GROQ_FALLBACK_MODEL = "openai/gpt-oss-20b"


def build_default_chain() -> List[Attempt]:
    """Gemini primary, Groq fallback — skipping any tier that has no API key.

    Set `LLM_PRIMARY_PROVIDER=groq` to invert the order without touching code.
    """
    gemini_model = os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
    groq_model = os.environ.get("GROQ_MODEL") or DEFAULT_GROQ_MODEL
    groq_fallback = os.environ.get("GROQ_FALLBACK_MODEL") or DEFAULT_GROQ_FALLBACK_MODEL

    gemini = GeminiProvider()
    groq = GroqProvider()

    gemini_tier: List[Attempt] = []
    if gemini.is_configured():
        # One in-provider retry: a 429 on Gemini is usually a short burst, and
        # retrying the good model beats dropping a tier for a transient blip.
        gemini_tier = [Attempt(gemini, gemini_model)] * (1 + _int_env("GEMINI_RETRIES", 1))

    groq_tier: List[Attempt] = []
    if groq.is_configured():
        groq_tier = [Attempt(groq, groq_model), Attempt(groq, groq_fallback)]

    if (os.environ.get("LLM_PRIMARY_PROVIDER") or "gemini").strip().lower() == "groq":
        return groq_tier + gemini_tier
    return gemini_tier + groq_tier
