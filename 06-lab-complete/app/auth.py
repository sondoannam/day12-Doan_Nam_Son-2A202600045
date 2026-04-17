"""API key authentication helpers."""

from __future__ import annotations

from secrets import compare_digest

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings


async def require_api_key(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate the shared API key from the X-API-Key header.

    The endpoint bodies are intentionally tolerant so that unauthenticated
    requests fail with 401 instead of FastAPI returning a 422 validation error.
    """

    api_key = request.headers.get("X-API-Key")
    if not api_key or not compare_digest(api_key, settings.agent_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )

    request.state.api_key = api_key
    return api_key
