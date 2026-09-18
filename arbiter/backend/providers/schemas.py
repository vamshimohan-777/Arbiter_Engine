"""Typed contracts for model-provider calls.

These types deliberately distinguish an unavailable verification from a
successful verification.  Agents must inspect ``success`` before consuming a
payload.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class LLMErrorType(str, Enum):
    TIMEOUT = "LLM_TIMEOUT"
    CONNECTION_ERROR = "LLM_CONNECTION_ERROR"
    RATE_LIMIT = "LLM_RATE_LIMIT"
    AUTH_ERROR = "LLM_AUTH_ERROR"
    SERVER_ERROR = "LLM_SERVER_ERROR"
    REQUEST_ERROR = "LLM_REQUEST_ERROR"
    INVALID_RESPONSE = "LLM_INVALID_RESPONSE"
    SCHEMA_ERROR = "LLM_SCHEMA_ERROR"
    PROVIDER_UNAVAILABLE = "LLM_PROVIDER_UNAVAILABLE"
    UNKNOWN_ERROR = "LLM_UNKNOWN_ERROR"


class ProviderHealth(BaseModel):
    available: bool = True
    consecutive_failures: int = 0
    last_failure_type: Optional[LLMErrorType] = None
    last_success_at: Optional[float] = None
    last_latency_ms: Optional[int] = None
    cooldown_until: Optional[float] = None


class LLMGatewayResult(BaseModel):
    """A complete, auditable result from a provider call."""

    success: bool
    request_id: str
    provider_used: Optional[str] = None
    model_used: Optional[str] = None
    attempts: int = 0
    fallback_used: bool = False
    latency_ms: Optional[int] = None
    payload: Optional[Dict[str, Any]] = None
    error_type: Optional[LLMErrorType] = None
    error_message: Optional[str] = None
