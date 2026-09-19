"""Request-scoped, non-sensitive telemetry for the result UI."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Dict, List


_provider_calls: ContextVar[List[Dict[str, Any]] | None] = ContextVar(
    "arbiter_provider_calls", default=None
)


def begin_request_trace() -> Token[List[Dict[str, Any]] | None]:
    """Start a trace isolated to the current async request."""
    return _provider_calls.set([])


def current_request_trace() -> List[Dict[str, Any]]:
    """Return a copy so callers cannot mutate the request-local trace."""
    return list(_provider_calls.get() or [])


def end_request_trace(token: Token[List[Dict[str, Any]] | None]) -> None:
    """Clear a request trace, including after exceptions."""
    _provider_calls.reset(token)


def record_provider_call(
    *,
    role: str,
    provider: str | None,
    model: str | None,
    success: bool,
    fallback_used: bool,
) -> None:
    """Store provider metadata only; never retain prompts or responses."""
    trace = _provider_calls.get()
    if trace is None:
        return
    trace.append(
        {
            "role": role,
            "provider": provider or "Unavailable",
            "model": model,
            "success": success,
            "fallback_used": fallback_used,
        }
    )
