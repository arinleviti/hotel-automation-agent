"""App settings, read from environment variables or the .env file at the repo root."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # e.g. postgresql://overlook:<password>@localhost:5433/overlook
    database_url: str

    # API key for Claude (the contextual labels in step 6.3; the graph from step 8).
    # SecretStr: Pydantic's type for secrets. Printing it shows "**********" instead of the key,
    # so it can't leak into logs or error messages by accident; .get_secret_value() reads it.
    # Optional here (None if missing), so code that only needs the database still works without it;
    # the code that calls Claude checks it and gives a clear error.
    anthropic_api_key: SecretStr | None = None

    # API key for Voyage AI (embeddings: step 6.4 for chunks, step 7 for questions). Same rules.
    voyage_api_key: SecretStr | None = None

    # Langfuse (tracing, step 8.4). Langfuse's own SDK only reads ENVIRONMENT variables, not the
    # .env file, so we read them here and hand them to Langfuse explicitly (see tracing.py).
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    # Switch tracing off (the tests do this, so test runs don't fill Langfuse with fake traces).
    tracing_enabled: bool = True

    model_config = SettingsConfigDict(
        # Looked up relative to where the command runs: works from the repo root and from backend/.
        env_file=(".env", "../.env"),
        # .env also holds the container's POSTGRES_* values and other keys; this app ignores them.
        extra="ignore",
    )


def get_settings() -> Settings:
    """Read the settings. Raises a clear validation error if DATABASE_URL is missing."""
    return Settings()
