"""LLM provider abstraction with automatic OpenAI to Gemini fallback."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from google import genai
from google.genai import types as genai_types
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)


logger = logging.getLogger(__name__)
PromptMessage = dict[str, str]


def _calculate_cost_microusd(
    input_tokens: int,
    output_tokens: int,
    input_price_microusd_per_1k: int,
    output_price_microusd_per_1k: int,
) -> int:
    """Calculate exact micro-USD cost from token usage."""

    input_cost = (Decimal(input_tokens) / Decimal(1000)) * Decimal(input_price_microusd_per_1k)
    output_cost = (Decimal(output_tokens) / Decimal(1000)) * Decimal(output_price_microusd_per_1k)
    return int((input_cost + output_cost).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _render_messages_for_gemini(messages: Sequence[PromptMessage]) -> tuple[str | None, str]:
    """Flatten chat messages into the simple text shape Gemini accepts."""

    system_instruction: str | None = None
    transcript_lines: list[str] = []
    for message in messages:
        role = message["role"]
        content = message["content"]
        if role == "system":
            system_instruction = content
            continue
        transcript_lines.append(f"{role.upper()}: {content}")

    return system_instruction, "\n\n".join(transcript_lines)


@dataclass(frozen=True)
class LLMResult:
    """Normalized response returned by every provider."""

    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_microusd: int


class LLMProviderError(Exception):
    """Structured provider error used by the fallback controller."""

    def __init__(self, message: str, provider: str, retryable: bool) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class LLMProvider(ABC):
    """Base interface for all model providers."""

    @abstractmethod
    async def generate(self, messages: Sequence[PromptMessage]) -> LLMResult:
        """Generate a response for the given chat messages."""

    async def aclose(self) -> None:
        """Close underlying network resources when the SDK supports it."""


class OpenAIProvider(LLMProvider):
    """Primary provider backed by the official OpenAI async SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: int,
        max_output_tokens: int,
        temperature: float,
        input_price_microusd_per_1k: int,
        output_price_microusd_per_1k: int,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, max_retries=0)
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._input_price_microusd_per_1k = input_price_microusd_per_1k
        self._output_price_microusd_per_1k = output_price_microusd_per_1k

    async def generate(self, messages: Sequence[PromptMessage]) -> LLMResult:
        try:
            completion = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=list(messages),
                    temperature=self._temperature,
                    max_tokens=self._max_output_tokens,
                ),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise LLMProviderError(str(exc), provider="openai", retryable=True) from exc
        except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
            raise LLMProviderError(str(exc), provider="openai", retryable=True) from exc
        except APIStatusError as exc:
            retryable = exc.status_code == 429 or exc.status_code >= 500
            raise LLMProviderError(str(exc), provider="openai", retryable=retryable) from exc
        except (AuthenticationError, BadRequestError) as exc:
            raise LLMProviderError(str(exc), provider="openai", retryable=False) from exc
        except Exception as exc:  # pragma: no cover - defensive guard for unknown SDK errors.
            raise LLMProviderError(str(exc), provider="openai", retryable=False) from exc

        text = completion.choices[0].message.content or ""
        usage = getattr(completion, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cost_microusd = _calculate_cost_microusd(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_price_microusd_per_1k=self._input_price_microusd_per_1k,
            output_price_microusd_per_1k=self._output_price_microusd_per_1k,
        )

        return LLMResult(
            text=text.strip(),
            provider="openai",
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_microusd=cost_microusd,
        )

    async def aclose(self) -> None:
        close_method = getattr(self._client, "close", None)
        if close_method is None:
            return
        result = close_method()
        if asyncio.iscoroutine(result):
            await result


class GeminiProvider(LLMProvider):
    """Fallback provider backed by the official Google Gen AI SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: int,
        max_output_tokens: int,
        temperature: float,
        input_price_microusd_per_1k: int,
        output_price_microusd_per_1k: int,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._input_price_microusd_per_1k = input_price_microusd_per_1k
        self._output_price_microusd_per_1k = output_price_microusd_per_1k

    async def generate(self, messages: Sequence[PromptMessage]) -> LLMResult:
        system_instruction, contents = _render_messages_for_gemini(messages)

        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        max_output_tokens=self._max_output_tokens,
                        temperature=self._temperature,
                    ),
                ),
                timeout=self._timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - SDK surfaces provider-specific errors.
            raise LLMProviderError(str(exc), provider="gemini", retryable=False) from exc

        usage = getattr(response, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        cost_microusd = _calculate_cost_microusd(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_price_microusd_per_1k=self._input_price_microusd_per_1k,
            output_price_microusd_per_1k=self._output_price_microusd_per_1k,
        )

        return LLMResult(
            text=(getattr(response, "text", "") or "").strip(),
            provider="gemini",
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_microusd=cost_microusd,
        )

    async def aclose(self) -> None:
        aio_client = getattr(self._client, "aio", None)
        close_method = getattr(aio_client, "aclose", None)
        if close_method is None:
            return
        result = close_method()
        if asyncio.iscoroutine(result):
            await result


class FallbackLLMEngine:
    """Try OpenAI first and transparently fall back to Gemini."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def generate(self, messages: Sequence[PromptMessage]) -> LLMResult:
        try:
            return await self._primary.generate(messages)
        except LLMProviderError as exc:
            if not exc.retryable:
                raise

            logger.warning(
                "primary_provider_failed_falling_back",
                extra={
                    "primary_provider": exc.provider,
                    "fallback_provider": "gemini",
                    "reason": str(exc),
                },
            )
            return await self._fallback.generate(messages)

    async def aclose(self) -> None:
        await self._primary.aclose()
        await self._fallback.aclose()
