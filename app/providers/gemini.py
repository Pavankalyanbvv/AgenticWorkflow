from collections.abc import AsyncGenerator
from time import perf_counter

import httpx
import structlog
from google import genai
from google.genai import errors, types

from app.providers.llm import Generation, ProviderError, StreamEvent
from app.schemas import TokenUsage

logger = structlog.get_logger(__name__)

SAFE_ERROR_REASONS = {
    "API_KEY_INVALID",
    "API_KEY_EXPIRED",
    "API_KEY_REPORTED_LEAKED",
    "API_KEY_SERVICE_BLOCKED",
    "API_KEY_HTTP_REFERRER_BLOCKED",
    "API_KEY_IP_ADDRESS_BLOCKED",
    "SERVICE_DISABLED",
    "BILLING_DISABLED",
}


def _visible_text(response: types.GenerateContentResponse) -> str:
    # Read only visible text; do not return internal thinking or tool payloads.
    candidates = response.candidates or []
    content = candidates[0].content if candidates else None
    if not content:
        return ""
    return "".join(part.text for part in (content.parts or []) if part.text and not part.thought)


def _usage(response: types.GenerateContentResponse | None) -> TokenUsage:
    metadata = response.usage_metadata if response else None
    return TokenUsage(
        input_tokens=metadata.prompt_token_count if metadata else None,
        output_tokens=metadata.candidates_token_count if metadata else None,
    )


def _translate_error(exc: Exception) -> Exception:
    """Log a provider failure safely and return the sanitized exception to raise."""
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        logger.warning("llm.failed", provider="gemini", error_type=type(exc).__name__)
        return TimeoutError("Gemini request timed out.")
    if isinstance(exc, errors.APIError):
        # Only allowlisted codes are logged; upstream messages can contain private data.
        details = exc.details if isinstance(exc.details, dict) else {}
        details = details.get("error", details)
        error_details = details.get("details", []) if isinstance(details, dict) else []
        reasons = (
            {
                item.get("reason")
                for item in error_details
                if isinstance(item, dict) and isinstance(item.get("reason"), str)
            }
            if isinstance(error_details, list)
            else set()
        )
        logger.warning(
            "llm.failed",
            provider="gemini",
            error_type=type(exc).__name__,
            upstream_status_code=exc.code,
            upstream_reasons=sorted(reasons & SAFE_ERROR_REASONS),
        )
        return ProviderError("Gemini could not produce a response.")
    logger.warning("llm.failed", provider="gemini", error_type=type(exc).__name__)
    return ProviderError("Gemini could not produce a response.")


# Failures the adapter translates; anything else propagates as an internal error.
HANDLED_ERRORS = (
    httpx.TimeoutException,
    TimeoutError,
    errors.APIError,
    httpx.RequestError,
    ProviderError,
)


class GeminiProvider:
    """Shared asynchronous Gemini Developer API client."""

    def __init__(self, api_key: str, model: str, timeout_seconds: float, max_output_tokens: int):
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.client = genai.Client(
            api_key=api_key,
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    async def aclose(self) -> None:
        try:
            await self.client.aio.aclose()
        finally:
            self.client.close()

    def _config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            max_output_tokens=self.max_output_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def _log_completed(self, result: Generation, started: float, streaming: bool) -> None:
        logger.info(
            "llm.completed",
            provider="gemini",
            model=result.model,
            streaming=streaming,
            duration_ms=round((perf_counter() - started) * 1000, 2),
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )

    async def generate(self, message: str) -> Generation:
        started = perf_counter()
        logger.info("llm.started", provider="gemini", model=self.model, streaming=False)
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model, contents=message, config=self._config()
            )
            reply = _visible_text(response)
            if not reply.strip():
                raise ProviderError("Gemini returned no text response.")
            result = Generation(
                reply=reply,
                provider="gemini",
                model=response.model_version or self.model,
                usage=_usage(response),
            )
        except HANDLED_ERRORS as exc:
            raise _translate_error(exc) from None
        self._log_completed(result, started, streaming=False)
        return result

    async def stream(self, message: str) -> AsyncGenerator[StreamEvent, None]:
        started = perf_counter()
        logger.info("llm.started", provider="gemini", model=self.model, streaming=True)
        parts: list[str] = []
        last: types.GenerateContentResponse | None = None
        try:
            chunks = await self.client.aio.models.generate_content_stream(
                model=self.model, contents=message, config=self._config()
            )
            async for chunk in chunks:
                last = chunk
                text = _visible_text(chunk)
                if text:
                    parts.append(text)
                    yield text
            reply = "".join(parts)
            if not reply.strip():
                raise ProviderError("Gemini returned no text response.")
        except HANDLED_ERRORS as exc:
            raise _translate_error(exc) from None
        # The final chunk carries cumulative usage metadata for the whole response.
        result = Generation(
            reply=reply,
            provider="gemini",
            model=(last.model_version if last else None) or self.model,
            usage=_usage(last),
        )
        self._log_completed(result, started, streaming=True)
        yield result
