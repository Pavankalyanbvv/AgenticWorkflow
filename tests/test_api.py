import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.llm import Generation, ProviderError


@pytest.fixture
def client():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        yield client


def test_health(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    UUID(response.headers["X-Request-ID"])


def test_message_is_explicitly_mocked(client):
    response = client.post("/api/v1/messages", json={"message": "  Hello  "})
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "mock"
    assert data["reply"] == "[Mock response — no LLM called] Received: Hello"
    assert data["usage"] == {"input_tokens": None, "output_tokens": None}
    assert data["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"message": ""},
        {"message": "   "},
        {"message": "a" * 4001},
        {"message": 123},
        {"message": "hi", "unexpected": True},
    ],
)
def test_invalid_requests_have_safe_errors(client, body):
    response = client.post("/api/v1/messages", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "input" not in response.json()["error"]


class BrokenProvider:
    async def generate(self, message):
        raise ProviderError("secret credential in upstream error")


class SlowProvider:
    async def generate(self, message):
        await asyncio.sleep(0.1)
        return Generation("late", "test", "test")


class UnexpectedFailureProvider:
    async def generate(self, message):
        raise RuntimeError("private message content")


@pytest.mark.parametrize(
    "provider,status,code",
    [
        (BrokenProvider(), 502, "provider_error"),
        (SlowProvider(), 504, "provider_timeout"),
        (UnexpectedFailureProvider(), 500, "internal_error"),
    ],
)
def test_failures_are_sanitized(provider, status, code):
    settings = Settings(_env_file=None, llm_timeout_seconds=0.01)
    with TestClient(create_app(settings, provider)) as client:
        response = client.post("/api/v1/messages", json={"message": "hello"})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "secret" not in response.text
    assert "private" not in response.text


def test_request_ids_are_unique_and_server_owned(client):
    responses = [
        client.get("/health/live", headers={"X-Request-ID": "untrusted"}) for _ in range(2)
    ]
    ids = [response.headers["X-Request-ID"] for response in responses]
    assert ids[0] != ids[1]
    for request_id in ids:
        UUID(request_id)


def test_logs_correlate_without_message_content(client, caplog):
    import json

    with caplog.at_level("INFO"):
        response = client.post("/api/v1/messages", json={"message": "sensitive-message"})
    records = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    assert {r["event"] for r in records} >= {
        "request.received",
        "agent.started",
        "agent.completed",
        "request.completed",
    }
    assert all(r["request_id"] == response.headers["X-Request-ID"] for r in records)
    assert "sensitive-message" not in caplog.text
