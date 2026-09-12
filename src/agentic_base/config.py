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


@cache
def get_settings() -> Settings:
    """Retrieve the application settings."""

    return Settings()
