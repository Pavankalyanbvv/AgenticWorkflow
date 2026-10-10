from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.streaming import sse_response
from app.schemas import ErrorResponse, MessageRequest, MessageResponse
from app.services.agent import AgentService

router = APIRouter(prefix="/api/v1", tags=["messages"])


def get_agent(request: Request) -> AgentService:
    return request.app.state.agent


@router.post(
    "/messages",
    response_model=MessageResponse,
    responses={
        200: {
            "description": "JSON reply, or Server-Sent Events when STREAM_RESPONSES=true.",
            "content": {"text/event-stream": {}},
        },
        404: {"model": ErrorResponse},
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
) -> MessageResponse | StreamingResponse:
    if request.app.state.stream_responses:
        events = agent.stream(payload.message, payload.conversation_id)
        return await sse_response(events, request.state.request_id)
    reply = await agent.respond(payload.message, payload.conversation_id)
    return MessageResponse(
        request_id=request.state.request_id,
        conversation_id=reply.conversation_id,
        **reply.generation.__dict__,
    )
