"""Redis-backed monthly budget tracking and reservation logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from redis.asyncio import Redis


RESERVE_BUDGET_LUA = """
local key = KEYS[1]
local monthly_budget = tonumber(ARGV[1])
local reserve_amount = tonumber(ARGV[2])
local ttl_seconds = tonumber(ARGV[3])

local spent = tonumber(redis.call('HGET', key, 'spent_microusd') or '0')
local reserved = tonumber(redis.call('HGET', key, 'reserved_microusd') or '0')

if spent + reserved + reserve_amount > monthly_budget then
  return {0, spent, reserved}
end

redis.call('HINCRBY', key, 'reserved_microusd', reserve_amount)
redis.call('EXPIRE', key, ttl_seconds)
return {1, spent, reserved + reserve_amount}
"""

SETTLE_BUDGET_LUA = """
local key = KEYS[1]
local reserved_amount = tonumber(ARGV[1])
local actual_amount = tonumber(ARGV[2])
local ttl_seconds = tonumber(ARGV[3])

local current_reserved = tonumber(redis.call('HGET', key, 'reserved_microusd') or '0')
if reserved_amount > current_reserved then
  reserved_amount = current_reserved
end

redis.call('HINCRBY', key, 'reserved_microusd', -reserved_amount)
redis.call('HINCRBY', key, 'spent_microusd', actual_amount)
redis.call('EXPIRE', key, ttl_seconds)

local spent = tonumber(redis.call('HGET', key, 'spent_microusd') or '0')
local reserved = tonumber(redis.call('HGET', key, 'reserved_microusd') or '0')
return {spent, reserved}
"""

RELEASE_BUDGET_LUA = """
local key = KEYS[1]
local reserved_amount = tonumber(ARGV[1])
local ttl_seconds = tonumber(ARGV[2])

local current_reserved = tonumber(redis.call('HGET', key, 'reserved_microusd') or '0')
if reserved_amount > current_reserved then
  reserved_amount = current_reserved
end

redis.call('HINCRBY', key, 'reserved_microusd', -reserved_amount)
redis.call('EXPIRE', key, ttl_seconds)

local spent = tonumber(redis.call('HGET', key, 'spent_microusd') or '0')
local reserved = tonumber(redis.call('HGET', key, 'reserved_microusd') or '0')
return {spent, reserved}
"""


class BudgetExceededError(Exception):
    """Raised when the user exceeds the configured monthly budget."""


@dataclass(frozen=True)
class BudgetReservation:
    """Represents a provisional per-request budget allocation."""

    user_id: str
    month_key: str
    reserved_microusd: int


@dataclass(frozen=True)
class BudgetSnapshot:
    """Current budget state for a user."""

    spent_microusd: int
    reserved_microusd: int
    monthly_budget_microusd: int


class RedisCostGuard:
    """Keep monthly user spend in Redis and enforce a hard budget cap."""

    def __init__(
        self,
        redis: Redis,
        monthly_budget_microusd: int,
        request_reserve_microusd: int,
    ) -> None:
        self._redis = redis
        self._monthly_budget_microusd = monthly_budget_microusd
        self._request_reserve_microusd = request_reserve_microusd

    async def reserve(self, user_id: str) -> BudgetReservation:
        """Reserve budget before an LLM call starts.

        Reserving before the provider call prevents multiple concurrent requests
        from collectively overspending the same monthly budget.
        """

        month_key = self._budget_key(user_id=user_id)
        ttl_seconds = self._ttl_until_month_rollover()
        allowed, _, _ = await self._redis.eval(
            RESERVE_BUDGET_LUA,
            1,
            month_key,
            self._monthly_budget_microusd,
            self._request_reserve_microusd,
            ttl_seconds,
        )

        if int(allowed) == 0:
            raise BudgetExceededError("Monthly token budget exceeded.")

        return BudgetReservation(
            user_id=user_id,
            month_key=month_key,
            reserved_microusd=self._request_reserve_microusd,
        )

    async def settle(self, reservation: BudgetReservation, actual_cost_microusd: int) -> BudgetSnapshot:
        """Convert a provisional reservation into actual spend."""

        ttl_seconds = self._ttl_until_month_rollover()
        spent_microusd, reserved_microusd = await self._redis.eval(
            SETTLE_BUDGET_LUA,
            1,
            reservation.month_key,
            reservation.reserved_microusd,
            max(0, actual_cost_microusd),
            ttl_seconds,
        )

        return BudgetSnapshot(
            spent_microusd=int(spent_microusd),
            reserved_microusd=int(reserved_microusd),
            monthly_budget_microusd=self._monthly_budget_microusd,
        )

    async def release(self, reservation: BudgetReservation) -> BudgetSnapshot:
        """Release a reservation when no provider call succeeded."""

        ttl_seconds = self._ttl_until_month_rollover()
        spent_microusd, reserved_microusd = await self._redis.eval(
            RELEASE_BUDGET_LUA,
            1,
            reservation.month_key,
            reservation.reserved_microusd,
            ttl_seconds,
        )

        return BudgetSnapshot(
            spent_microusd=int(spent_microusd),
            reserved_microusd=int(reserved_microusd),
            monthly_budget_microusd=self._monthly_budget_microusd,
        )

    async def get_status(self, user_id: str) -> BudgetSnapshot:
        """Fetch current spend for response metadata and debugging."""

        values = await self._redis.hgetall(self._budget_key(user_id=user_id))
        return BudgetSnapshot(
            spent_microusd=int(values.get("spent_microusd", 0)),
            reserved_microusd=int(values.get("reserved_microusd", 0)),
            monthly_budget_microusd=self._monthly_budget_microusd,
        )

    def _budget_key(self, user_id: str) -> str:
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        return f"cost:{user_id}:{current_month}"

    def _ttl_until_month_rollover(self) -> int:
        now = datetime.now(timezone.utc)
        if now.month == 12:
            rollover = datetime(year=now.year + 1, month=1, day=1, tzinfo=timezone.utc)
        else:
            rollover = datetime(year=now.year, month=now.month + 1, day=1, tzinfo=timezone.utc)
        return max(60, int((rollover - now).total_seconds()))
