"""
config.py -- Arbiter Engine Configuration
Loads all settings from environment variables and/or a .env file
using pydantic-settings. A singleton `settings` object is exported
for use throughout the application.
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration for the Arbiter Engine.

    All fields can be overridden via environment variables or a .env file
    placed in the project root (or any directory that pydantic-settings
    searches for `.env`).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # API Keys                                                             #
    # ------------------------------------------------------------------ #
    GROQ_API_KEY: Optional[str] = Field(default=None, description="Groq API key")
    CEREBRAS_API_KEY: Optional[str] = Field(default=None, description="Cerebras API key")
    OPENROUTER_API_KEY: Optional[str] = Field(default=None, description="OpenRouter API key")

    # ------------------------------------------------------------------ #
    # Provider Base URLs                                                   #
    # ------------------------------------------------------------------ #
    GROQ_BASE_URL: str = Field(
        default="https://api.groq.com/openai/v1",
        description="Base URL for the Groq OpenAI-compatible endpoint",
    )
    CEREBRAS_BASE_URL: str = Field(
        default="https://api.cerebras.ai/v1",
        description="Base URL for the Cerebras OpenAI-compatible endpoint",
    )
    OPENROUTER_BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1",
        description="Base URL for the OpenRouter OpenAI-compatible endpoint",
    )

    # ------------------------------------------------------------------ #
    # Central LLM gateway                                                 #
    # ------------------------------------------------------------------ #
    LLM_PRIMARY_PROVIDER: str = Field(default="groq")
    LLM_FALLBACK_PROVIDER: str = Field(default="openrouter")
    # Supporting checks default to the same provider that produced the core
    # ruling.  A different provider can still be selected in .env, but an
    # unverified secondary stack must not make every post-ruling check fail.
    PRECEDENT_PROVIDER: str = Field(default="groq")
    SIMULATION_PROVIDER: str = Field(default="groq")
    LLM_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    # Provider fallback is more valuable than repeating the same failed
    # request.  Each provider receives one attempt by default, in order.
    LLM_MAX_RETRIES: int = Field(default=1, ge=1, le=5)
    LLM_RETRY_BACKOFF_SECONDS: float = Field(default=0.5, gt=0)
    LLM_CIRCUIT_BREAKER_FAILURES: int = Field(default=3, ge=1)
    LLM_PROVIDER_COOLDOWN_SECONDS: int = Field(default=30, ge=1)
    # A 429 is normally quota-wide, so bypass that provider immediately for
    # subsequent pipeline steps instead of consuming more failed requests.
    LLM_RATE_LIMIT_COOLDOWN_SECONDS: int = Field(default=60, ge=1)
    FRONTEND_ORIGIN: str = Field(default="http://localhost:3000")

    # ------------------------------------------------------------------ #
    # Authentication                                                       #
    # ------------------------------------------------------------------ #
    # Override this value in .env for every deployed environment. The
    # default keeps local demo sessions usable without committing a secret.
    JWT_SECRET_KEY: str = Field(default="arbiter-local-development-secret-change-me")
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_EXPIRATION_SECONDS: int = Field(default=8 * 60 * 60, gt=0)
    AUTH_PASSWORD: Optional[str] = Field(
        default=None,
        description="Optional local/demo password override; never commit a real password.",
    )
    USERS_CONFIG_PATH: str = Field(
        default="./data/users.json",
        description="JSON user account file containing salted password hashes.",
    )

    # ------------------------------------------------------------------ #
    # Agent Model Assignments                                              #
    # ------------------------------------------------------------------ #

    # Resolution Agent -- primary policy-reasoning LLM (Groq)
    RESOLUTION_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Model used by the Resolution Agent (Groq)",
    )

    # Checker Agent -- adversarial self-check.  gpt-oss uses part of its
    # completion budget for reasoning, so structured-review callers provide
    # a sufficiently large token budget below.
    CHECKER_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Model used by the Checker Agent (Groq)",
    )

    # Retrieval Agent -- embedding/retrieval ranking (Groq)
    RETRIEVAL_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Model used by the Retrieval Agent (Groq)",
    )

    # Sensitivity Agent -- decision boundary probing (Groq)
    SENSITIVITY_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Model used by the Sensitivity Agent (Groq); matches the core ruling contract",
    )

    # Scanner Agent -- policy corpus conflict scan (Groq)
    SCANNER_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Model used by the Scanner Agent (Groq)",
    )

    # Precedent Agent -- historical ruling lookup (Groq)
    PRECEDENT_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Model used by the Precedent Agent",
    )

    # Simulation Agent -- hypothetical policy change impact (Groq)
    SIMULATION_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Model used by the Simulation Agent",
    )

    # Fallback Model -- used when primary providers are unavailable (OpenRouter)
    FALLBACK_MODEL: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        description="Fallback model routed through OpenRouter",
    )

    # ------------------------------------------------------------------ #
    # Storage Paths                                                        #
    # ------------------------------------------------------------------ #
    SQLITE_PATH: str = Field(
        default="./arbiter.db",
        description="Path to the SQLite database file",
    )
    CHROMA_PATH: str = Field(
        default="./chroma_db",
        description="Path to the ChromaDB persistence directory",
    )
    POLICIES_DIR: str = Field(
        default="./data/policies",
        description="Directory containing raw policy documents",
    )
    PRECEDENTS_DIR: str = Field(
        default="./data/precedents",
        description="Directory for serialised historical rulings / precedents",
    )
    SYNTHETIC_DATA_DIR: str = Field(
        default="./data/synthetic/v1",
        description="Read-only location of the imported synthetic benchmark corpus",
    )

    # ------------------------------------------------------------------ #
    # ChromaDB                                                             #
    # ------------------------------------------------------------------ #
    CHROMA_COLLECTION_NAME: str = Field(
        default="arbiter_policies",
        description="ChromaDB collection name for the policy corpus",
    )
    CHROMA_PRECEDENT_COLLECTION: str = Field(
        default="arbiter_precedents",
        description="ChromaDB collection name for the precedent store",
    )

    # ------------------------------------------------------------------ #
    # Application Behaviour                                                #
    # ------------------------------------------------------------------ #
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Python logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    # Maximum rounds the Checker Agent may iterate to resolve objections
    MAX_CHECKER_ROUNDS: int = Field(
        default=2,
        description="Maximum adversarial checker rounds per ruling",
    )

    # ------------------------------------------------------------------ #
    # Convenience helpers                                                  #
    # ------------------------------------------------------------------ #

    def groq_client_kwargs(self) -> dict:
        """Return kwargs suitable for constructing an OpenAI client pointed at Groq."""
        return {
            "api_key": self.GROQ_API_KEY,
            "base_url": self.GROQ_BASE_URL,
        }

    def cerebras_client_kwargs(self) -> dict:
        """Return kwargs suitable for constructing an OpenAI client pointed at Cerebras."""
        return {
            "api_key": self.CEREBRAS_API_KEY,
            "base_url": self.CEREBRAS_BASE_URL,
        }

    def openrouter_client_kwargs(self) -> dict:
        """Return kwargs suitable for constructing an OpenAI client pointed at OpenRouter."""
        return {
            "api_key": self.OPENROUTER_API_KEY,
            "base_url": self.OPENROUTER_BASE_URL,
        }

    def provider_for_model(self, model_name: str) -> str:
        """
        Derive the default provider name for a configured model.  Explicit
        per-agent provider settings take precedence where they are supplied.

        Returns either 'groq' or 'openrouter'.
        """
        groq_models = {self.RESOLUTION_MODEL, self.CHECKER_MODEL,
                       self.RETRIEVAL_MODEL, self.SENSITIVITY_MODEL,
                       self.SCANNER_MODEL}
        # Precedent and simulation use the same reliable Groq route by
        # default.  This avoids an unverified secondary provider making
        # supporting checks unavailable after a successful ruling.
        groq_models.update({self.PRECEDENT_MODEL, self.SIMULATION_MODEL})

        if model_name in groq_models:
            return "groq"
        # Fallback model and anything else -> OpenRouter
        return "openrouter"


# ---------------------------------------------------------------------------
# Singleton -- import this everywhere instead of instantiating Settings again
# ---------------------------------------------------------------------------
settings: Settings = Settings()
