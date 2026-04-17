"""Business logic for session initialization and CV/JD advice conversations."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from app.cost_guard import BudgetSnapshot, RedisCostGuard
from app.llm_engine import FallbackLLMEngine, LLMResult, PromptMessage
from app.rate_limiter import RedisSlidingWindowRateLimiter


logger = logging.getLogger(__name__)

JOB_HUNTER_SYSTEM_PROMPT = """
You are Agentic Job Hunter, a production-grade CV refinement assistant.

Your job is to compare the candidate CV against the target job description and
return actionable, truthful advice. Follow these rules:
- Ground every recommendation in the supplied CV and JD.
- Never invent experience, metrics, or technologies the candidate did not provide.
- Prefer concrete rewrites, gaps, prioritization, and interview-oriented advice.
- Be concise but useful, with bullet points when that improves clarity.
- If the user asks follow-up questions, keep using the stored CV and JD as context.
""".strip()

GENERAL_CHAT_SYSTEM_PROMPT = """
You are Agentic Job Hunter, a helpful career assistant.

If the user has not uploaded a CV and job description yet, answer the question
directly while keeping conversation history consistent across turns. When it is
relevant, remind the user that uploading a CV and job description will unlock
tailored refinement advice.
""".strip()


class SessionNotInitializedError(Exception):
    """Raised when a chat session is requested before CV and JD are stored."""


class SessionAccessDeniedError(Exception):
    """Raised when a session_id belongs to a different user."""


@dataclass(frozen=True)
class SessionContext:
    """Complete Redis-backed state needed to answer a chat request."""

    session_id: str
    user_id: str
    cv_text: str
    jd_text: str
    history: list[dict[str, Any]]

    @property
    def has_job_context(self) -> bool:
        return bool(self.cv_text.strip() and self.jd_text.strip())


class SessionInitRequest(BaseModel):
    """Request body for CV/JD bootstrap."""

    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(min_length=1)
    cv_text: str = Field(min_length=1, validation_alias=AliasChoices("cv_text", "cv"))
    jd_text: str = Field(min_length=1, validation_alias=AliasChoices("jd_text", "jd"))
    session_id: str | None = None


class SessionInitResponse(BaseModel):
    """Response body returned after CV/JD bootstrap."""

    session_id: str
    status: str
    message: str


class AskRequest(BaseModel):
    """User request body for interactive advice."""

    user_id: str | None = None
    question: str = Field(min_length=1)
    session_id: str | None = None


class TokenUsageResponse(BaseModel):
    """Usage metadata returned to the client."""

    input_tokens: int
    output_tokens: int


class BudgetResponse(BaseModel):
    """Current monthly budget state for the caller."""

    spent_microusd: int
    reserved_microusd: int
    monthly_budget_microusd: int


class AskResponse(BaseModel):
    """Normalized API response for chat answers."""

    answer: str
    session_id: str
    provider: str
    model: str
    usage: TokenUsageResponse
    cost_microusd: int
    budget: BudgetResponse
    request_id: str


class SessionStore:
    """Small Redis repository for session state and transcript history."""

    def __init__(self, redis: Redis, session_ttl_seconds: int, history_max_messages: int) -> None:
        self._redis = redis
        self._session_ttl_seconds = session_ttl_seconds
        self._history_max_messages = history_max_messages

    def resolve_session_id(self, user_id: str, session_id: str | None = None) -> str:
        """Use the supplied session_id or derive a deterministic default."""

        if session_id:
            return session_id
        digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
        return f"session-{digest}"

    async def initialize_session(
        self,
        *,
        user_id: str,
        cv_text: str,
        jd_text: str,
        session_id: str | None,
    ) -> str:
        """Store or replace the user CV/JD pair in Redis."""

        resolved_session_id = self.resolve_session_id(user_id=user_id, session_id=session_id)
        profile_key = self._profile_key(resolved_session_id)
        history_key = self._history_key(resolved_session_id)
        timestamp = self._now_iso()

        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.delete(history_key)
            pipeline.hset(
                profile_key,
                mapping={
                    "user_id": user_id,
                    "cv_text": cv_text,
                    "jd_text": jd_text,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_cost_microusd": 0,
                    "session_mode": "job_hunter",
                },
            )
            pipeline.expire(profile_key, self._session_ttl_seconds)
            pipeline.expire(history_key, self._session_ttl_seconds)
            await pipeline.execute()

        return resolved_session_id

    async def ensure_general_session(self, *, user_id: str, session_id: str | None) -> SessionContext:
        """Create a Redis-backed session for general chat when CV/JD are absent."""

        resolved_session_id = self.resolve_session_id(user_id=user_id, session_id=session_id)
        profile_key = self._profile_key(resolved_session_id)
        history_key = self._history_key(resolved_session_id)
        timestamp = self._now_iso()

        profile = await self._redis.hgetall(profile_key)
        if profile:
            if profile.get("user_id") != user_id:
                raise SessionAccessDeniedError("The supplied session does not belong to this user.")

            history_items = await self._redis.lrange(history_key, 0, -1)
            history = [json.loads(item) for item in history_items]
            await self._touch(profile_key=profile_key, history_key=history_key)
            return SessionContext(
                session_id=resolved_session_id,
                user_id=user_id,
                cv_text=profile.get("cv_text", ""),
                jd_text=profile.get("jd_text", ""),
                history=history,
            )

        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.hset(
                profile_key,
                mapping={
                    "user_id": user_id,
                    "cv_text": "",
                    "jd_text": "",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_cost_microusd": 0,
                    "session_mode": "general",
                },
            )
            pipeline.expire(profile_key, self._session_ttl_seconds)
            pipeline.expire(history_key, self._session_ttl_seconds)
            await pipeline.execute()

        return SessionContext(
            session_id=resolved_session_id,
            user_id=user_id,
            cv_text="",
            jd_text="",
            history=[],
        )

    async def get_session_context(self, *, user_id: str, session_id: str | None) -> SessionContext:
        """Load session data and verify the session belongs to the caller."""

        resolved_session_id = self.resolve_session_id(user_id=user_id, session_id=session_id)
        profile_key = self._profile_key(resolved_session_id)
        history_key = self._history_key(resolved_session_id)

        profile = await self._redis.hgetall(profile_key)
        if not profile:
            raise SessionNotInitializedError("No CV/JD has been stored for this session.")
        if profile.get("user_id") != user_id:
            raise SessionAccessDeniedError("The supplied session does not belong to this user.")

        history_items = await self._redis.lrange(history_key, 0, -1)
        history = [json.loads(item) for item in history_items]

        await self._touch(profile_key=profile_key, history_key=history_key)

        return SessionContext(
            session_id=resolved_session_id,
            user_id=user_id,
            cv_text=profile["cv_text"],
            jd_text=profile["jd_text"],
            history=history,
        )

    async def append_exchange(
        self,
        *,
        session_id: str,
        question: str,
        result: LLMResult,
    ) -> None:
        """Persist the user question and assistant answer after success."""

        profile_key = self._profile_key(session_id)
        history_key = self._history_key(session_id)
        now = self._now_iso()
        user_turn = json.dumps(
            {
                "role": "user",
                "content": question,
                "created_at": now,
            }
        )
        assistant_turn = json.dumps(
            {
                "role": "assistant",
                "content": result.text,
                "provider": result.provider,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_microusd": result.cost_microusd,
                "created_at": now,
            }
        )

        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.rpush(history_key, user_turn, assistant_turn)
            pipeline.ltrim(history_key, -self._history_max_messages, -1)
            pipeline.hincrby(profile_key, "total_input_tokens", result.input_tokens)
            pipeline.hincrby(profile_key, "total_output_tokens", result.output_tokens)
            pipeline.hincrby(profile_key, "total_cost_microusd", result.cost_microusd)
            pipeline.hset(profile_key, mapping={"updated_at": now})
            pipeline.expire(profile_key, self._session_ttl_seconds)
            pipeline.expire(history_key, self._session_ttl_seconds)
            await pipeline.execute()

    def _profile_key(self, session_id: str) -> str:
        return f"session:{session_id}:profile"

    def _history_key(self, session_id: str) -> str:
        return f"session:{session_id}:history"

    async def _touch(self, *, profile_key: str, history_key: str) -> None:
        await self._redis.expire(profile_key, self._session_ttl_seconds)
        await self._redis.expire(history_key, self._session_ttl_seconds)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class JobHunterAgent:
    """Coordinates Redis state, guardrails, and model execution."""

    def __init__(
        self,
        *,
        session_store: SessionStore,
        rate_limiter: RedisSlidingWindowRateLimiter,
        cost_guard: RedisCostGuard,
        llm_engine: FallbackLLMEngine,
    ) -> None:
        self._session_store = session_store
        self._rate_limiter = rate_limiter
        self._cost_guard = cost_guard
        self._llm_engine = llm_engine

    async def initialize_session(self, payload: SessionInitRequest) -> SessionInitResponse:
        session_id = await self._session_store.initialize_session(
            user_id=payload.user_id,
            cv_text=payload.cv_text,
            jd_text=payload.jd_text,
            session_id=payload.session_id,
        )

        logger.info(
            "session_initialized",
            extra={
                "user_id": payload.user_id,
                "session_id": session_id,
            },
        )

        return SessionInitResponse(
            session_id=session_id,
            status="initialized",
            message="CV and job description stored successfully.",
        )

    async def ask(self, payload: AskRequest, *, request_id: str) -> AskResponse:
        if not payload.user_id:
            raise ValueError("user_id is required for authenticated chat requests.")

        await self._rate_limiter.check(payload.user_id)
        try:
            context = await self._session_store.get_session_context(
                user_id=payload.user_id,
                session_id=payload.session_id,
            )
        except SessionNotInitializedError:
            context = await self._session_store.ensure_general_session(
                user_id=payload.user_id,
                session_id=payload.session_id,
            )

        messages = self._build_messages(
            context=context,
            question=payload.question,
        )

        # The cost guard intentionally reserves budget before any provider call.
        # Once the provider returns real token counts, the reservation is settled
        # to actual spend so fallback behavior remains budget-safe.
        reservation = await self._cost_guard.reserve(payload.user_id)

        try:
            result = await self._llm_engine.generate(messages)
        except Exception:
            await self._cost_guard.release(reservation)
            raise

        budget_snapshot = await self._cost_guard.settle(
            reservation,
            actual_cost_microusd=result.cost_microusd,
        )
        await self._session_store.append_exchange(
            session_id=context.session_id,
            question=payload.question,
            result=result,
        )

        logger.info(
            "chat_completed",
            extra={
                "request_id": request_id,
                "user_id": payload.user_id,
                "session_id": context.session_id,
                "provider": result.provider,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_microusd": result.cost_microusd,
            },
        )

        return AskResponse(
            answer=result.text,
            session_id=context.session_id,
            provider=result.provider,
            model=result.model,
            usage=TokenUsageResponse(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            ),
            cost_microusd=result.cost_microusd,
            budget=BudgetResponse(
                spent_microusd=budget_snapshot.spent_microusd,
                reserved_microusd=budget_snapshot.reserved_microusd,
                monthly_budget_microusd=budget_snapshot.monthly_budget_microusd,
            ),
            request_id=request_id,
        )

    def _build_messages(
        self,
        *,
        context: SessionContext,
        question: str,
    ) -> list[PromptMessage]:
        if context.has_job_context:
            messages: list[PromptMessage] = [
                {"role": "system", "content": JOB_HUNTER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Candidate CV:\n"
                        f"{context.cv_text}\n\n"
                        "Target Job Description:\n"
                        f"{context.jd_text}\n\n"
                        "Use the CV and job description above as the source of truth for"
                        " every answer in this conversation."
                    ),
                },
            ]
        else:
            messages = [{"role": "system", "content": GENERAL_CHAT_SYSTEM_PROMPT}]

        for turn in context.history:
            role = turn.get("role")
            content = turn.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": question})
        return messages
