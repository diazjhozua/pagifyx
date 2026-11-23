"""Runtime settings, read from environment variables and an optional local .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the LLM endpoint and local output.

    Any OpenAI-compatible Chat Completions endpoint works: switching providers
    means editing LLM_BASE_URL, LLM_API_KEY and LLM_MODEL in .env.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_base_url: str
    llm_api_key: SecretStr
    llm_model: str
    output_dir: Path = Path("output")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, loading them on first use."""
    return Settings()  # type: ignore[call-arg]
