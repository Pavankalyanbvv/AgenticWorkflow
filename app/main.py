import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.agent.factory import create_workflow
from app.api import health, messages
from app.config import Settings
from app.db.persistence import Persistence, PostgresPersistence
from app.db.store import ConversationNotFoundError
from app.observability import create_tracer
from app.providers.factory import create_llm_provider
from app.providers.llm import LLMProvider, ProviderError
from app.providers.tracing import TracedProvider
from app.services.agent import AgentService


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def create_app(
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    persistence: Persistence | None = None,
) -> FastAPI:
    """Build the app. Callers own injected providers and persistence (e.g. in tests)."""
    settings = settings or Settings()
    configure_logging(settings.log_level)
    managed_persistence = None
    if persistence is None:
        if not settings.database_url or not settings.database_url.get_secret_value().strip():
            raise ValueError("Set DATABASE_URL in .env before starting the server.")
        persistence = PostgresPersistence(
            settings.database_url.get_secret_value().strip(), settings.db_pool_size
        )
        managed_persistence = persistence
    managed_provider = None
    if provider is None:
        provider = create_llm_provider(settings)
        managed_provider = provider
    tracer = create_tracer(settings)
    traced_provider = TracedProvider(provider, tracer)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if managed_persistence is not None:
            await managed_persistence.open()
        try:
            # Built here because the checkpointer exists only once persistence is open.
            workflow = create_workflow(traced_provider, persistence.checkpointer)
            app.state.agent = AgentService(
                workflow, tracer, persistence.store, settings.llm_timeout_seconds
            )
            yield
        finally:
            try:
                if managed_provider is not None:
                    await managed_provider.aclose()
            finally:
                try:
                    await tracer.shutdown()
                finally:
                    if managed_persistence is not None:
                        await managed_persistence.close()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.persistence = persistence
    app.state.stream_responses = settings.stream_responses
    logger = structlog.get_logger(__name__)

    def error(request: Request, status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": code, "message": message, "request_id": request.state.request_id}
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not expose rejected input or echo request bodies in errors.
        return error(request, 422, "invalid_request", "Request body is invalid.")

    @app.exception_handler(ConversationNotFoundError)
    async def conversation_not_found(
        request: Request, exc: ConversationNotFoundError
    ) -> JSONResponse:
        return error(request, 404, "conversation_not_found", "The conversation does not exist.")

    @app.exception_handler(ProviderError)
    async def provider_error(request: Request, exc: ProviderError) -> JSONResponse:
        return error(request, 502, "provider_error", "The model provider could not respond.")

    @app.exception_handler(TimeoutError)
    async def provider_timeout(request: Request, exc: TimeoutError) -> JSONResponse:
        return error(request, 504, "provider_timeout", "The model request timed out.")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        # Generate server-owned IDs rather than logging arbitrary client header values.
        request.state.request_id = str(uuid4())
        clear_contextvars()
        bind_contextvars(request_id=request.state.request_id, environment=settings.environment)
        started = perf_counter()
        logger.info("request.received", method=request.method)
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                # Exception messages may contain credentials or user data.
                logger.error("request.failed", error_type=type(exc).__name__)
                response = error(request, 500, "internal_error", "An unexpected error occurred.")
            response.headers["X-Request-ID"] = request.state.request_id
            route = request.scope.get("route")
            logger.info(
                "request.completed",
                route=getattr(route, "path", "unmatched"),
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            return response
        finally:
            clear_contextvars()

    app.include_router(health.router)
    app.include_router(messages.router)
    return app
