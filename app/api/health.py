import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/health", tags=["health"])
logger = structlog.get_logger(__name__)


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", responses={503: {"description": "The database is unreachable."}})
async def ready(request: Request) -> JSONResponse:
    try:
        await request.app.state.persistence.ping()
    except Exception as exc:
        logger.warning("health.database_unavailable", error_type=type(exc).__name__)
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "error"})
    return JSONResponse(content={"status": "ok", "database": "ok"})
