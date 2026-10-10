from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4000)
    # Omit to start a new conversation; only server-issued IDs can be continued.
    conversation_id: UUID | None = None


class TokenUsage(BaseModel):
    # Unknown usage is null, not fabricated as zero.
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class MessageResponse(BaseModel):
    request_id: UUID
    conversation_id: UUID
    reply: str
    provider: str
    model: str
    usage: TokenUsage


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: UUID


class ErrorResponse(BaseModel):
    error: ErrorDetail
