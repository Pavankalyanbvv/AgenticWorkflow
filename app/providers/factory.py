from app.config import Settings
from app.providers.llm import LLMProvider, MockProvider


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Select the provider adapter, SDK and model from application settings."""
    match settings.llm_provider:
        case "mock":
            return MockProvider()
        case "gemini":
            if (
                not settings.gemini_api_key
                or not settings.gemini_api_key.get_secret_value().strip()
            ):
                raise ValueError("Set GEMINI_API_KEY in .env before enabling LLM_PROVIDER=gemini.")

            # Import the SDK adapter only when its provider is selected.
            from app.providers.gemini import GeminiProvider

            return GeminiProvider(
                api_key=settings.gemini_api_key.get_secret_value(),
                model=settings.gemini_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_output_tokens=settings.llm_max_output_tokens,
            )
        case _:
            raise ValueError("Unsupported LLM provider configured.")
