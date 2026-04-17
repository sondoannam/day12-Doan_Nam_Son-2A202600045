"""FastAPI entrypoint for the Agentic Job Hunter backend."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.agent import (
    AskRequest,
    AskResponse,
    JobHunterAgent,
    SessionAccessDeniedError,
    SessionInitRequest,
    SessionInitResponse,
    SessionNotInitializedError,
    SessionStore,
)
from app.auth import require_api_key
from app.config import Settings, get_settings
from app.cost_guard import BudgetExceededError, RedisCostGuard
from app.llm_engine import FallbackLLMEngine, GeminiProvider, LLMProviderError, OpenAIProvider
from app.rate_limiter import RateLimitExceededError, RedisSlidingWindowRateLimiter


LOG_RESERVED_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for structured production logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key not in LOG_RESERVED_FIELDS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(log_level: str) -> None:
    """Configure the root logger once with JSON output."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())


def error_response(
    *,
    request_id: str,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Create a consistent JSON error payload."""

    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
        "request_id": request_id,
    }
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def get_agent(request: Request) -> JobHunterAgent:
    return request.app.state.agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared clients once and wait for in-flight requests on exit."""

    settings = get_settings()
    configure_logging(settings.log_level)

    redis_client = Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

    session_store = SessionStore(
        redis=redis_client,
        session_ttl_seconds=settings.session_ttl_seconds,
        history_max_messages=settings.history_max_messages,
    )
    rate_limiter = RedisSlidingWindowRateLimiter(
        redis=redis_client,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    cost_guard = RedisCostGuard(
        redis=redis_client,
        monthly_budget_microusd=settings.monthly_budget_microusd,
        request_reserve_microusd=settings.request_reserve_microusd,
    )
    llm_engine = FallbackLLMEngine(
        primary=OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.openai_timeout_seconds,
            max_output_tokens=settings.openai_max_output_tokens,
            temperature=settings.model_temperature,
            input_price_microusd_per_1k=settings.openai_input_price_microusd_per_1k,
            output_price_microusd_per_1k=settings.openai_output_price_microusd_per_1k,
        ),
        fallback=GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.gemini_timeout_seconds,
            max_output_tokens=settings.gemini_max_output_tokens,
            temperature=settings.model_temperature,
            input_price_microusd_per_1k=settings.gemini_input_price_microusd_per_1k,
            output_price_microusd_per_1k=settings.gemini_output_price_microusd_per_1k,
        ),
    )
    agent = JobHunterAgent(
        session_store=session_store,
        rate_limiter=rate_limiter,
        cost_guard=cost_guard,
        llm_engine=llm_engine,
    )

    app.state.settings = settings
    app.state.redis = redis_client
    app.state.agent = agent
    app.state.llm_engine = llm_engine
    app.state.shutting_down = False
    app.state.inflight_requests = 0
    app.state.inflight_lock = asyncio.Lock()
    app.state.inflight_drained = asyncio.Event()
    app.state.inflight_drained.set()

    logging.getLogger(__name__).info(
        "application_started",
        extra={"environment": settings.environment},
    )

    try:
        yield
    finally:
        app.state.shutting_down = True
        try:
            await asyncio.wait_for(
                app.state.inflight_drained.wait(),
                timeout=settings.graceful_shutdown_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logging.getLogger(__name__).warning(
                "graceful_shutdown_timeout",
                extra={"timeout_seconds": settings.graceful_shutdown_timeout_seconds},
            )

        await llm_engine.aclose()
        close_method = getattr(redis_client, "aclose", None)
        if close_method is not None:
            await close_method()

        logging.getLogger(__name__).info("application_stopped")


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Attach request IDs, log every request, and track in-flight work."""

    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id

    if request.app.state.shutting_down and request.url.path not in {"/health", "/ready"}:
        return error_response(
            request_id=request_id,
            status_code=503,
            code="service_unavailable",
            message="Service is shutting down and cannot accept new work.",
        )

    async with request.app.state.inflight_lock:
        request.app.state.inflight_requests += 1
        request.app.state.inflight_drained.clear()

    start = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        status_code = response.status_code if response else 500

        async with request.app.state.inflight_lock:
            request.app.state.inflight_requests -= 1
            if request.app.state.inflight_requests == 0:
                request.app.state.inflight_drained.set()

        logger = logging.getLogger("app.requests")
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": duration_ms,
            },
        )

        if response is not None:
            response.headers["X-Request-ID"] = request_id


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return error_response(
        request_id=getattr(request.state, "request_id", str(uuid4())),
        status_code=exc.status_code,
        code="http_error",
        message=str(exc.detail),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(
        request_id=getattr(request.state, "request_id", str(uuid4())),
        status_code=422,
        code="validation_error",
        message="Request validation failed.",
        details=exc.errors(),
    )


@app.exception_handler(RateLimitExceededError)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceededError) -> JSONResponse:
    return error_response(
        request_id=getattr(request.state, "request_id", str(uuid4())),
        status_code=429,
        code="rate_limited",
        message="Too many requests.",
        details={"retry_after_seconds": exc.retry_after_seconds},
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


@app.exception_handler(BudgetExceededError)
async def budget_exception_handler(request: Request, _: BudgetExceededError) -> JSONResponse:
    return error_response(
        request_id=getattr(request.state, "request_id", str(uuid4())),
        status_code=402,
        code="budget_exceeded",
        message="Monthly budget exceeded for this user.",
    )


@app.exception_handler(SessionNotInitializedError)
async def session_not_found_exception_handler(request: Request, exc: SessionNotInitializedError) -> JSONResponse:
    return error_response(
        request_id=getattr(request.state, "request_id", str(uuid4())),
        status_code=404,
        code="session_not_initialized",
        message=str(exc),
    )


@app.exception_handler(SessionAccessDeniedError)
async def session_forbidden_exception_handler(request: Request, exc: SessionAccessDeniedError) -> JSONResponse:
    return error_response(
        request_id=getattr(request.state, "request_id", str(uuid4())),
        status_code=403,
        code="session_access_denied",
        message=str(exc),
    )


@app.exception_handler(LLMProviderError)
async def llm_exception_handler(request: Request, exc: LLMProviderError) -> JSONResponse:
    return error_response(
        request_id=getattr(request.state, "request_id", str(uuid4())),
        status_code=503,
        code="llm_unavailable",
        message=f"LLM provider {exc.provider} is unavailable.",
    )


@app.exception_handler(RedisError)
async def redis_exception_handler(request: Request, exc: RedisError) -> JSONResponse:
    return error_response(
        request_id=getattr(request.state, "request_id", str(uuid4())),
        status_code=503,
        code="redis_unavailable",
        message="Redis dependency is unavailable.",
        details=str(exc),
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: the process is up."""

    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness probe: verify Redis connectivity before receiving traffic."""

    if request.app.state.shutting_down:
        return JSONResponse(status_code=503, content={"status": "shutting_down"})

    try:
        await request.app.state.redis.ping()
    except RedisError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "dependency": "redis",
                "error": str(exc),
            },
        )

    return JSONResponse(status_code=200, content={"status": "ready"})


@app.post(
    "/session/init",
    response_model=SessionInitResponse,
    dependencies=[Depends(require_api_key)],
)
async def initialize_session(
    payload: SessionInitRequest,
    request: Request,
    agent: JobHunterAgent = Depends(get_agent),
) -> SessionInitResponse:
    """Store the user CV and target job description under a session_id."""

    return await agent.initialize_session(payload)


@app.post(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(require_api_key)],
)
async def ask(
    payload: AskRequest,
    request: Request,
    agent: JobHunterAgent = Depends(get_agent),
) -> AskResponse:
    """Answer a user question using the Redis-backed CV/JD session context."""

    try:
        return await agent.ask(payload, request_id=request.state.request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/chat",
    response_model=AskResponse,
    dependencies=[Depends(require_api_key)],
)
async def chat_alias(
    payload: AskRequest,
    request: Request,
    agent: JobHunterAgent = Depends(get_agent),
) -> AskResponse:
    """Convenience alias for /ask."""

    try:
        return await agent.ask(payload, request_id=request.state.request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc