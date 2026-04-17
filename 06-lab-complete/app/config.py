"""Application configuration loaded from environment variables."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _usd_to_microusd(value: Decimal) -> int:
    """Convert a USD decimal amount to integer micro-USD units."""

    return int((value * Decimal("1000000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class Settings(BaseSettings):
    """Centralized runtime settings for the service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Agentic Job Hunter"
    environment: str = "development"
    log_level: str = "INFO"
    port: int = 8000

    redis_url: str = "redis://redis:6379/0"
    agent_api_key: str
    openai_api_key: str
    gemini_api_key: str

    openai_model: str = "gpt-4o-mini"
    gemini_model: str = "gemini-2.5-flash"
    model_temperature: float = 0.2
    openai_timeout_seconds: int = 30
    gemini_timeout_seconds: int = 30
    openai_max_output_tokens: int = 800
    gemini_max_output_tokens: int = 800

    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60

    monthly_budget_usd: Decimal = Field(default=Decimal("10.00"))
    request_reserve_usd: Decimal = Field(default=Decimal("0.25"))

    session_ttl_seconds: int = 60 * 60 * 24 * 7
    history_max_messages: int = 20
    graceful_shutdown_timeout_seconds: int = 20

    openai_input_price_per_1k_usd: Decimal = Field(default=Decimal("0.00015"))
    openai_output_price_per_1k_usd: Decimal = Field(default=Decimal("0.00060"))
    gemini_input_price_per_1k_usd: Decimal = Field(default=Decimal("0.00010"))
    gemini_output_price_per_1k_usd: Decimal = Field(default=Decimal("0.00040"))

    @property
    def monthly_budget_microusd(self) -> int:
        """Return the monthly user budget in integer micro-USD."""

        return _usd_to_microusd(self.monthly_budget_usd)

    @property
    def request_reserve_microusd(self) -> int:
        """Return the pessimistic per-request reservation in integer micro-USD."""

        return _usd_to_microusd(self.request_reserve_usd)

    @property
    def openai_input_price_microusd_per_1k(self) -> int:
        return _usd_to_microusd(self.openai_input_price_per_1k_usd)

    @property
    def openai_output_price_microusd_per_1k(self) -> int:
        return _usd_to_microusd(self.openai_output_price_per_1k_usd)

    @property
    def gemini_input_price_microusd_per_1k(self) -> int:
        return _usd_to_microusd(self.gemini_input_price_per_1k_usd)

    @property
    def gemini_output_price_microusd_per_1k(self) -> int:
        return _usd_to_microusd(self.gemini_output_price_per_1k_usd)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Memoize settings so the same values are reused across the app."""

    return Settings()
