"""Application settings related files."""

from functools import cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings for this service."""

    log_level: str = "INFO"
    log_json_format: bool = False
    log_plain_traceback: bool = False
    project_name: str = "Agentic Platform"
    metrics_port: int = 9000
    database_url: str = "sqlite:///./agentic-base.db"
    """PostgreSQL in every deployed environment; SQLite locally so the service runs with no infrastructure."""

    auth: str = "tokens"
    """``tokens`` requires a bearer token from ``api_tokens`` on every data route; ``none`` turns the
    check off, for local development only. See src/agentic_base/auth.py."""
    api_tokens: SecretStr = SecretStr("")
    """JSON: ``{"<token>": ["tenant", ...]}``, ``"*"`` for every tenant. From the platform's secret
    management, never a file in the image. With ``auth=tokens`` and none set, data routes refuse."""

    redaction: str = "none"
    """``none``; ``patterns`` for credentials, contact details, bank numbers and identifiers only;
    ``names`` to add people and places, with the detectors below. See docs/architecture/redaction.md."""
    redaction_llm_url: str = ""
    """An OpenAI-compatible endpoint, for example a Willma base URL ending in ``/v1``."""
    redaction_llm_api_key: SecretStr = SecretStr("")
    redaction_llm_model: str = ""
    redaction_llm_timeout_s: float = 300.0
    """Per request. Match the endpoint's proxy read timeout: waiting longer only receives its 504."""
    redaction_llm_chunk_words: int = 1500
    redaction_llm_concurrency: int = 4
    redaction_llm_cooldown_s: float = 60.0
    """After a failure, how long writes go straight to the fallback without trying the model."""
    redaction_gliner_model: str = ""
    """The fallback. Needs gliner and torch installed in the image."""
    redaction_gliner_revision: str = ""
    redaction_gliner_device: str = "auto"
    """``auto`` is the GPU when torch sees one, else the CPU; or ``cpu``, ``cuda``, ``cuda:N``."""
    redaction_entities: str = ""
    """Comma-separated entity types. Empty means every type the redactor knows."""
    redaction_allow_list: str = ""
    """Comma-separated terms never redacted: the site's cluster, partition and service names."""


@cache
def get_settings() -> Settings:
    """Retrieve the application settings."""

    return Settings()
