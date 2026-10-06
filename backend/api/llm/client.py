"""LLM client: DeepSeek V4.1 Flash via OpenRouter (OpenAI-compatible API)."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

import httpx
import openai
from openai import AsyncOpenAI

from api.config import get_settings

log = logging.getLogger(__name__)

Message = dict[str, str]
RETRYABLE = (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError,
             openai.InternalServerError)


class LLMClient(Protocol):
    def stream(
        self, messages: list[Message], on_retry: Callable[[int, Exception], Awaitable[None]] | None = None,
        max_tokens: int = 400,
    ) -> AsyncIterator[str]: ...

    async def complete_json(self, messages: list[Message]) -> str: ...


class OpenRouterLLM:
    def __init__(self, max_attempts: int = 3) -> None:
        s = get_settings()
        self.model = s.llm_model
        self.providers = [p.strip() for p in s.llm_providers.split(",") if p.strip()]
        self.max_attempts = max_attempts
        self.client = AsyncOpenAI(
            api_key=s.openrouter_api_key or "missing",
            base_url=s.openrouter_base_url,
            default_headers={"X-Title": "English Interview Trainer"},
            # a hung connection must fail fast so the retry happens while the candidate waits
            timeout=httpx.Timeout(60.0, connect=3.0),
            max_retries=2,
        )

    async def stream(
        self, messages: list[Message], on_retry: Callable[[int, Exception], Awaitable[None]] | None = None,
        max_tokens: int = 400,
    ) -> AsyncIterator[str]:
        """Yield content deltas. Retries with backoff only before the first token.

        Cancelling the consuming task closes the HTTP stream (aborts the request), which
        is how barge-in stops generation and billing.
        """
        self._check_key()
        # no hidden reasoning in the conversation: it costs 3–6 s before the first token
        extra_body = {**self._extra_body(), "reasoning": {"enabled": False}}
        for attempt in range(1, self.max_attempts + 1):
            started = False
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model, messages=messages, stream=True, temperature=0.7,
                    max_tokens=max_tokens, extra_body=extra_body,
                )
                async with stream:
                    async for chunk in stream:
                        delta = chunk.choices[0].delta.content if chunk.choices else None
                        if delta:
                            started = True
                            yield delta
                return
            except RETRYABLE as exc:
                if started or attempt == self.max_attempts:
                    raise
                log.warning("LLM attempt %d failed: %r", attempt, exc)
                if on_retry:
                    await on_retry(attempt, exc)
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))

    async def complete_json(self, messages: list[Message]) -> str:
        """Non-streaming call in JSON mode; returns the JSON text (caller validates).

        Reasoning is off here too: some providers put the model's reasoning inside the content,
        which breaks the JSON (seen on Together/DeepInfra with V4.1 Flash)."""
        self._check_key()
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model, messages=messages, temperature=0.1, max_tokens=4000,
                    response_format={"type": "json_object"},
                    extra_body={**self._extra_body(), "reasoning": {"enabled": False}},
                )
                return extract_json(response.choices[0].message.content or "")
            except RETRYABLE as exc:
                if attempt == self.max_attempts:
                    raise
                log.warning("LLM JSON attempt %d failed: %r", attempt, exc)
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    def _check_key(self) -> None:
        if self.client.api_key == "missing":
            raise RuntimeError("OPENROUTER_API_KEY is not set in .env")

    def _extra_body(self) -> dict:
        provider: dict = {"data_collection": "deny"}  # never route to providers that train on our data
        if self.providers:
            provider |= {"order": self.providers, "allow_fallbacks": True}
        return {"provider": provider}


def extract_json(text: str) -> str:
    """The outermost JSON object in ``text`` (tolerates prose or code fences around it)."""
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    start, end = stripped.find("{"), stripped.rfind("}")
    return stripped[start : end + 1] if 0 <= start < end else stripped


_shared: OpenRouterLLM | None = None


def get_llm() -> LLMClient:
    """FastAPI dependency (overridden in tests). One client for the whole app, so its HTTPS
    connections stay warm between turns and sessions (a fresh TLS handshake per interview
    cost seconds when a connection stalled)."""
    global _shared
    if _shared is None:
        _shared = OpenRouterLLM()
    return _shared
