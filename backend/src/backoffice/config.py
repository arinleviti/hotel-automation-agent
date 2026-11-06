"""App settings, read from environment variables or the .env file at the repo root."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # e.g. postgresql://overlook:<password>@localhost:5433/overlook
    database_url: str

    model_config = SettingsConfigDict(
        # Looked up relative to where the command runs: works from the repo root and from backend/.
        env_file=(".env", "../.env"),
        # .env also holds the container's POSTGRES_* values; this app doesn't need them.
        extra="ignore",
    )


def get_settings() -> Settings:
    """Read the settings. Raises a clear validation error if DATABASE_URL is missing."""
    return Settings()
