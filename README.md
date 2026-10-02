# Personal Agent API

A personal project for a team of two to three engineers, built one layer at a
time toward production readiness. The selected architecture uses FastAPI,
LangGraph, Langfuse Cloud and PostgreSQL.

## Implemented layer 1

`HTTP request → validation → agent service → mock provider → typed response`

- `GET /health/live`: process liveness.
- `POST /api/v1/messages`: validated message with a 4,000-character limit.
- Server-generated request IDs in responses and structured JSON application logs.
- Configurable provider timeout and sanitized validation/provider/internal errors.
- Provider injection for tests; no credentials, database or external service needed.

Responses explicitly identify the mock provider. No real LLM is called, and token
usage is unknown (`null`). There is no conversation persistence or authentication
yet. Bind to localhost while developing this initial layer.

## Run locally

Install Python 3.12–3.14 and uv, then run these commands from this folder:

```bash
export UV_CACHE_DIR="$PWD/.uv-cache"
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs> for the interactive API documentation.

```bash
curl http://127.0.0.1:8000/health/live
curl -X POST http://127.0.0.1:8000/api/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{"message":"Help me draft a meeting request."}'
```

## Verify

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Documentation and model context

`Agent_Project_Essence_and_Vision.md` is the Markdown counterpart of the Word
design document. It includes the longer-term vision and selected stack.
`AGENTS.md` tells coding assistants to consult it before architectural changes.

A Markdown file is not automatically sent to application LLM calls. Our runtime
will explicitly construct each model request from its system instructions,
relevant conversation context, tool schemas and tool results. The project design
document is not a runtime prompt. Layer 1 does not load or send either file.

For future design changes, keep the Markdown and Word versions aligned. README
records implementation status; the design document describes the target system.

## Next layers

1. Select a model provider; implement the real client and Langfuse generation tracing.
2. Add a minimal LangGraph workflow and parent/child traces.
3. Add PostgreSQL application tables, migrations and persistent graph checkpoints.
4. Add one read-only MCP tool, then permission checks and action approvals.
5. Add durable workers, evaluation gates and Grafana monitoring as workflows grow.

LangGraph, Langfuse, PostgreSQL and Grafana are planned but not connected in layer 1.
