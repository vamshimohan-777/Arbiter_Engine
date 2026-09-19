"""Central, failure-safe LLM provider gateway.

All calls receive bounded retries, timeout handling, provider fallback, output
parsing/validation, structured logs, and lightweight in-process health state.
The gateway never manufactures a successful payload after a provider failure.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Type

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from config import settings
from utils import parse_llm_json
from .execution_trace import record_provider_call
from .schemas import LLMErrorType, LLMGatewayResult, ProviderHealth

logger = logging.getLogger(__name__)


class LLMGateway:
    """Single-VM provider gateway with a small per-provider circuit breaker."""

    # Gateways are constructed per agent, but provider health must survive
    # across those agent instances within one API process.
    _shared_health: Dict[str, ProviderHealth] = {}

    def __init__(self) -> None:
        self._health = self._shared_health

    def health(self) -> Dict[str, ProviderHealth]:
        return dict(self._health)

    def generate(
        self,
        *,
        role: str,
        messages: List[Dict[str, Any]],
        model: str,
        primary_provider: Optional[str] = None,
        fallback_provider: Optional[str] = None,
        response_schema: Optional[Type[BaseModel]] = None,
        max_tokens: int = 1024,
        temperature: float = 0.1,
        timeout_seconds: Optional[float] = None,
    ) -> LLMGatewayResult:
        request_id = str(uuid.uuid4())
        primary = (primary_provider or settings.LLM_PRIMARY_PROVIDER).lower()
        fallback = (fallback_provider or settings.LLM_FALLBACK_PROVIDER).lower()
        providers = [primary] + ([fallback] if fallback != primary else [])
        timeout = timeout_seconds or settings.LLM_TIMEOUT_SECONDS
        attempts = 0
        last_failure: Optional[LLMGatewayResult] = None

        for provider_index, provider in enumerate(providers):
            if self._in_cooldown(provider):
                last_failure = self._failure(
                    request_id, provider, model, attempts, provider_index > 0,
                    LLMErrorType.PROVIDER_UNAVAILABLE,
                    "Provider is in a temporary cooldown after repeated failures.",
                )
                continue

            key = self._api_key(provider)
            if not key:
                last_failure = self._failure(
                    request_id, provider, model, attempts, provider_index > 0,
                    LLMErrorType.AUTH_ERROR,
                    f"No API key is configured for provider '{provider}'.",
                )
                continue

            for attempt in range(1, settings.LLM_MAX_RETRIES + 1):
                attempts += 1
                started = time.perf_counter()
                try:
                    client = self._client(provider, key, timeout)
                    response = client.chat.completions.create(
                        model=model if provider_index == 0 else settings.FALLBACK_MODEL,
                        messages=messages,  # type: ignore[arg-type]
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=timeout,
                    )
                    content = response.choices[0].message.content or ""
                    payload = parse_llm_json(content)
                    if not payload:
                        raise ValueError("Provider response did not contain a JSON object.")
                    if response_schema is not None:
                        payload = response_schema.model_validate(payload).model_dump(mode="json")

                    latency = int((time.perf_counter() - started) * 1000)
                    self._record_success(provider, latency)
                    logger.info(
                        "llm_call request_id=%s role=%s provider=%s model=%s attempts=%d fallback=%s latency_ms=%d status=success",
                        request_id, role, provider, model, attempts, provider_index > 0, latency,
                    )
                    result = LLMGatewayResult(
                        success=True,
                        request_id=request_id,
                        provider_used=provider,
                        model_used=model if provider_index == 0 else settings.FALLBACK_MODEL,
                        attempts=attempts,
                        fallback_used=provider_index > 0,
                        latency_ms=latency,
                        payload=payload,
                    )
                    record_provider_call(
                        role=role,
                        provider=result.provider_used,
                        model=result.model_used,
                        success=result.success,
                        fallback_used=result.fallback_used,
                    )
                    return result
                except Exception as exc:
                    error_type = self._classify_error(exc)
                    latency = int((time.perf_counter() - started) * 1000)
                    # A malformed completion or a bad model/request is local
                    # to this call.  It must not trip the provider-wide
                    # circuit breaker and make unrelated checks unavailable.
                    if error_type in {
                        LLMErrorType.TIMEOUT,
                        LLMErrorType.CONNECTION_ERROR,
                        LLMErrorType.RATE_LIMIT,
                        LLMErrorType.SERVER_ERROR,
                        LLMErrorType.PROVIDER_UNAVAILABLE,
                    }:
                        self._record_failure(provider, error_type)
                    last_failure = self._failure(
                        request_id, provider, model, attempts, provider_index > 0,
                        error_type, self._safe_error_message(exc), latency,
                    )
                    logger.warning(
                        "llm_call request_id=%s role=%s provider=%s model=%s attempt=%d fallback=%s latency_ms=%d status=failed error_type=%s detail=%s",
                        request_id, role, provider, model, attempt, provider_index > 0, latency,
                        error_type.value, self._safe_error_message(exc),
                    )
                    # Provider failures are not improved by immediately
                    # repeating the same request. Move linearly to the next
                    # configured provider; the gateway remains the sole
                    # owner of this fallback chain.
                    if error_type in {
                        LLMErrorType.RATE_LIMIT,
                        LLMErrorType.CONNECTION_ERROR,
                        LLMErrorType.TIMEOUT,
                        LLMErrorType.SERVER_ERROR,
                        LLMErrorType.PROVIDER_UNAVAILABLE,
                    }:
                        break
                    if not self._is_retryable(error_type) or attempt == settings.LLM_MAX_RETRIES:
                        break
                    time.sleep(settings.LLM_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))

        result = last_failure or self._failure(
            request_id, None, model, attempts, False,
            LLMErrorType.PROVIDER_UNAVAILABLE, "No LLM provider was available.",
        )
        record_provider_call(
            role=role,
            provider=result.provider_used,
            model=result.model_used,
            success=result.success,
            fallback_used=result.fallback_used,
        )
        return result

    def _client(self, provider: str, api_key: str, timeout_seconds: float) -> OpenAI:
        urls = {
            "groq": settings.GROQ_BASE_URL,
            "cerebras": settings.CEREBRAS_BASE_URL,
            "openrouter": settings.OPENROUTER_BASE_URL,
        }
        if provider not in urls:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        # Disable the SDK's implicit retries.  They may honor a long
        # Retry-After header and hide the failure from the gateway, delaying
        # fallback by tens of seconds or more.
        return OpenAI(
            api_key=api_key,
            base_url=urls[provider],
            timeout=timeout_seconds,
            max_retries=0,
        )

    def _api_key(self, provider: str) -> Optional[str]:
        return {
            "groq": settings.GROQ_API_KEY,
            "cerebras": settings.CEREBRAS_API_KEY,
            "openrouter": settings.OPENROUTER_API_KEY,
        }.get(provider)

    def _in_cooldown(self, provider: str) -> bool:
        health = self._health.get(provider)
        return bool(health and health.cooldown_until and health.cooldown_until > time.time())

    def _record_success(self, provider: str, latency_ms: int) -> None:
        self._health[provider] = ProviderHealth(
            available=True, consecutive_failures=0, last_success_at=time.time(), last_latency_ms=latency_ms,
        )

    def _record_failure(self, provider: str, error_type: LLMErrorType) -> None:
        previous = self._health.get(provider, ProviderHealth())
        failures = previous.consecutive_failures + 1
        # Rate limits apply to the whole provider/model quota, not merely to
        # the one call.  Start cooling down after the first 429 so later
        # agents move directly to the next provider in the linear chain.
        if error_type == LLMErrorType.RATE_LIMIT:
            cooldown = time.time() + settings.LLM_RATE_LIMIT_COOLDOWN_SECONDS
        else:
            cooldown = (
                time.time() + settings.LLM_PROVIDER_COOLDOWN_SECONDS
                if failures >= settings.LLM_CIRCUIT_BREAKER_FAILURES else None
            )
        self._health[provider] = ProviderHealth(
            available=False, consecutive_failures=failures, last_failure_type=error_type,
            last_latency_ms=previous.last_latency_ms, cooldown_until=cooldown,
        )

    @staticmethod
    def _is_retryable(error_type: LLMErrorType) -> bool:
        return error_type in {
            LLMErrorType.TIMEOUT, LLMErrorType.CONNECTION_ERROR,
            LLMErrorType.RATE_LIMIT, LLMErrorType.SERVER_ERROR,
            LLMErrorType.PROVIDER_UNAVAILABLE,
        }

    @staticmethod
    def _classify_error(exc: Exception) -> LLMErrorType:
        if isinstance(exc, APITimeoutError):
            return LLMErrorType.TIMEOUT
        if isinstance(exc, APIConnectionError):
            return LLMErrorType.CONNECTION_ERROR
        if isinstance(exc, RateLimitError):
            return LLMErrorType.RATE_LIMIT
        if isinstance(exc, APIStatusError):
            if exc.status_code in (401, 403):
                return LLMErrorType.AUTH_ERROR
            if 400 <= exc.status_code < 500:
                return LLMErrorType.REQUEST_ERROR
            if exc.status_code >= 500:
                return LLMErrorType.SERVER_ERROR
        if isinstance(exc, ValidationError):
            return LLMErrorType.SCHEMA_ERROR
        if isinstance(exc, ValueError):
            return LLMErrorType.INVALID_RESPONSE
        if isinstance(exc, APIError):
            return LLMErrorType.PROVIDER_UNAVAILABLE
        return LLMErrorType.UNKNOWN_ERROR

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        # Provider exceptions can contain request headers; never pass those to
        # a response or log secrets.  A short exception type/message is enough.
        return f"{type(exc).__name__}: {str(exc)[:240]}"

    @staticmethod
    def _failure(
        request_id: str, provider: Optional[str], model: str, attempts: int,
        fallback_used: bool, error_type: LLMErrorType, error_message: str,
        latency_ms: Optional[int] = None,
    ) -> LLMGatewayResult:
        return LLMGatewayResult(
            success=False, request_id=request_id, provider_used=provider,
            model_used=model, attempts=attempts, fallback_used=fallback_used,
            latency_ms=latency_ms, error_type=error_type, error_message=error_message,
        )
