from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Personal Agent API"
    environment: str = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    llm_timeout_seconds: float = Field(default=15, gt=0, le=120)
    llm_provider: Literal["mock", "gemini"] = "mock"
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )
    gemini_model: str = Field(default="gemini-3.5-flash", min_length=1)
    llm_max_output_tokens: int = Field(default=1024, gt=0, le=8192)
    # Stream message replies to clients as Server-Sent Events instead of one JSON body.
    stream_responses: bool = False
    # Langfuse tracing is enabled only when both keys are set.
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "LANGFUSE_HOST"),
    )
    # Prompts and replies are sent to Langfuse only when explicitly enabled.
    langfuse_capture_content: bool = False
    # PostgreSQL connection (Neon direct endpoint); required to run the server.
    database_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, gt=0, le=20)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(
            self.langfuse_public_key
            and self.langfuse_public_key.strip()
            and self.langfuse_secret_key
            and self.langfuse_secret_key.get_secret_value().strip()
        )
