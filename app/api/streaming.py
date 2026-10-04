import json
from collections.abc import AsyncGenerator

from fastapi.responses import StreamingResponse

from app.providers.llm import Generation, ProviderError, StreamEvent


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _encode(item: StreamEvent, request_id: str) -> str:
    if isinstance(item, Generation):
        # The full reply was already sent as deltas; the done event carries metadata only.
        return _sse(
            "done",
            {
                "request_id": request_id,
                "provider": item.provider,
                "model": item.model,
                "usage": item.usage.model_dump(),
            },
        )
    return _sse("delta", {"text": item})


def _error(request_id: str, code: str, message: str) -> str:
    return _sse("error", {"error": {"code": code, "message": message, "request_id": request_id}})


async def sse_response(
    events: AsyncGenerator[StreamEvent, None], request_id: str
) -> StreamingResponse:
    """Stream deltas, then a done event; failures after headers become an error event."""
    # Pull the first event before sending headers so early upstream failures keep their
    # HTTP status (502/504) through the normal exception handlers.
    first = await anext(events, None)

    async def body():
        try:
            if first is not None:
                yield _encode(first, request_id)
            async for item in events:
                yield _encode(item, request_id)
        # The status line is already sent; report the same sanitized errors as events.
        except ProviderError:
            yield _error(request_id, "provider_error", "The model provider could not respond.")
        except TimeoutError:
            yield _error(request_id, "provider_timeout", "The model request timed out.")
        except Exception:
            yield _error(request_id, "internal_error", "An unexpected error occurred.")
        finally:
            await events.aclose()

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
