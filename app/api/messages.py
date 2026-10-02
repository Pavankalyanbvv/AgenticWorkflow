from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.schemas import ErrorResponse, MessageRequest, MessageResponse
from app.services.agent import AgentService

router = APIRouter(prefix="/api/v1", tags=["messages"])


def get_agent(request: Request) -> AgentService:
    return request.app.state.agent


@router.post(
    "/messages",
    response_model=MessageResponse,
    responses={
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def create_message(
    payload: MessageRequest,
    request: Request,
    agent: Annotated[AgentService, Depends(get_agent)],
) -> MessageResponse:
    result = await agent.respond(payload.message)
    return MessageResponse(request_id=request.state.request_id, **result.__dict__)
