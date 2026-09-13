"""Application settings related files."""

from functools import cache

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

    redaction: str = "none"
    """``presidio`` to redact personal data from a transcript before it is written. Needs the
    redaction extra. See ``agentic_base.redaction.presidio`` for the modes."""
    redaction_gliner_model: str = ""
    """A GLiNER PII model on the Hugging Face hub, for names and places in mixed-language text."""
    redaction_gliner_revision: str = ""
    """The model revision to load. Unpinned is allowed and says so on every record."""
    redaction_spacy_models: str = ""
    """``language=model`` pairs, comma separated, for example ``en=en_core_web_lg``."""
    redaction_entities: str = ""
    """Comma-separated Presidio entity types. Empty means the adapter's default list."""
    redaction_allow_list: str = ""
    """Comma-separated terms never redacted: the site's cluster, partition and service names."""


@cache
def get_settings() -> Settings:
    """Retrieve the application settings."""

    return Settings()
