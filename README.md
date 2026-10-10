# Personal Agent API

A personal project for a team of two to three engineers, built one layer at a
time toward production readiness. The selected architecture uses FastAPI,
LangGraph, Langfuse Cloud and PostgreSQL.

## Implemented foundation, Gemini, Langfuse tracing, LangGraph and PostgreSQL

`HTTP request → validation → agent service → workflow (LangGraph) → Gemini or mock provider → typed response`

- `GET /health/live`: process liveness.
- `POST /api/v1/messages`: validated message with a 4,000-character limit.
- Server-generated request IDs in responses and structured JSON application logs.
- Configurable provider timeout and sanitized validation/provider/internal errors.
- Provider injection for tests; no credentials, database or external service needed.
- Real async Gemini calls through the official `google-genai` SDK, with a shared
  client closed at application shutdown.
- Model and output token limits configured through environment variables.
- `create_llm_provider(settings)` centralizes provider and model selection.
  Gemini selects the `google-genai` SDK adapter; mock mode needs no SDK client.
  The application closes factory-created providers at shutdown; callers own
  explicitly injected providers. New providers belong in the factory and their
  own adapters, without changing FastAPI handlers or the agent service.
- Separate `llm.started`, `llm.completed` and `llm.failed` JSON events without
  prompts, responses or credentials.
- Optional response streaming: with `STREAM_RESPONSES=true`, `POST /api/v1/messages`
  returns Server-Sent Events from Gemini's streaming API instead of one JSON body.
- Optional Langfuse Cloud tracing: one parent trace per request with a span per
  graph node and a generation per model call; prompt and reply capture is off by default.
- A minimal LangGraph workflow (`generate → validate_response`) behind a
  graph-agnostic `Workflow` contract; see [Agent workflows](#agent-workflows).
- PostgreSQL (Neon) storage: conversations, messages and agent runs, plus LangGraph
  checkpoints; see [Database](#database). `GET /health/ready` checks the database.

Responses identify the provider and model, and include provider-reported input
and output token counts when available. Output tokens represent generated answer
tokens; Gemini thinking tokens are not included in this field, so these two counts
alone should not be used to estimate total billing. Mock usage remains `null`.
Conversations are stored but there is no conversation memory or authentication yet:
the model sees only the current message. Bind to localhost.

## Run locally

Install Python 3.12–3.14 and uv, then run these commands from this folder:

```bash
export UV_CACHE_DIR="$PWD/.uv-cache"
uv sync
cp .env.example .env
```

Edit `.env` and replace the placeholder in `GEMINI_API_KEY` with your Google AI
Studio key and set `DATABASE_URL` (see [Database](#database)) before starting the
server. Keep `.env` private; it is ignored by Git. If `.env` already exists, edit
it directly instead of copying over it.

```bash
uv run python -m app.db.migrate
uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

The app is built by the `create_app` factory, so importing `app.main` does not
connect to anything. The server refuses to start without `DATABASE_URL`.

`.env.example` selects `LLM_PROVIDER=gemini` and `GEMINI_MODEL=gemini-3.5-flash`.
Change the model to a supported model available to your key as needed. For offline
development, set `LLM_PROVIDER=mock`; without configuration the default is mock.
The legacy `GOOGLE_GEMINI_API_KEY` and `GOOGLE_API_KEY` names are also accepted;
prefer `GEMINI_API_KEY`. Missing credentials in Gemini mode fail at startup.

`LLM_TIMEOUT_SECONDS` bounds the request (30 seconds in the example), and
`LLM_MAX_OUTPUT_TOKENS` bounds generated output (1,024 by default, including
Gemini's thinking budget). The SDK makes up to three attempts on 408, 429 and 5xx
responses with short backoff; `LLM_TIMEOUT_SECONDS` still bounds the total time.
Blocked or empty text responses and upstream errors produce a sanitized 502;
timeouts produce a 504. Model calls use your key's quota and applicable billing.

SDK reference: [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/).

If a call returns 502, inspect the `llm.failed` log event. Gemini API errors include
`upstream_status_code` and allowlisted `upstream_reasons`, without the raw error
message or credentials. `API_KEY_INVALID` means Google rejected the configured
key: replace `GEMINI_API_KEY` in `.env` with a valid Gemini Developer API key from
Google AI Studio and restart the server. If you export `GEMINI_API_KEY` in your
shell, that value overrides `.env`; update or unset it as well. Automatic SDK
function calling is disabled for this text-only layer.

### Langfuse tracing

Create a project in [Langfuse Cloud](https://cloud.langfuse.com) and set
`LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in `.env`. Tracing is enabled only
when both are present, so tests and offline mock mode need no Langfuse account.
`LANGFUSE_BASE_URL` defaults to the EU cloud; use your region's URL if different.

Each request becomes one trace:

```
agent.run                      (agent: request_id, streaming; input/output if captured)
 ├─ node.generate              (span)
 │   └─ llm.generate | llm.stream   (generation: model, usage, cost, time to first token)
 └─ node.validate_response     (span)
```

Failed observations have an `ERROR` level with only the exception type. Application logs for the request include its
`trace_id`. Prompts and replies are not sent unless
`LANGFUSE_CAPTURE_CONTENT=true`; enable that only where storing message content in
Langfuse is acceptable. Spans are flushed at application shutdown.

### Agent workflows

Requests run through a `Workflow` (`app/agent/workflow.py`): `run()` returns a
`Generation` and `stream()` yields text chunks then a final `Generation`. The agent
service, API, SSE layer and providers depend only on this contract, `WorkflowInput`
and `RunContext`, never on graph state.

- `app/agent/graphs/basic.py` owns the graph: its `State`, nodes, edges and the
  `to_state`/`to_generation` mappings. Change the graph here without touching the
  rest of the application.
- `app/agent/langgraph_runner.py` adapts any compiled LangGraph graph to the
  contract. Register nodes with `traced_node(name, fn)` to get a `node.<name>`
  span, `node.started`/`node.completed`/`node.failed` logs and, when content
  capture is on, the node's input state and returned update. Nodes stream text
  with `emit_text()`.
- `app/agent/factory.py` selects the workflow. Add a graph as a new module under
  `app/agent/graphs/` and select it there.
- Only `app/agent/` imports LangGraph and only `app/observability.py` imports
  Langfuse. There is no checkpointer yet; state lasts for one request.

### Database

The server requires PostgreSQL. Development uses a [Neon](https://neon.com) free
project (Postgres 18). In Neon, open **Connect**, turn **connection pooling off**
and copy the direct connection string into `.env`:

```
DATABASE_URL=postgresql://<role>:<password>@ep-xxxx.<region>.aws.neon.tech/<db>?sslmode=require
```

The direct endpoint (no `-pooler` in the host) is required: LangGraph's checkpointer
and Alembic need session features that the pooled endpoint does not reliably
support. `DB_POOL_SIZE` (default 5) bounds each of the two connection pools. Neon's
free compute suspends when idle, so the first request afterwards is slower.

Apply schema changes explicitly; the app never changes the schema at startup:

```bash
uv run python -m app.db.migrate   # Alembic upgrade head + LangGraph checkpoint tables
```

Tables (Alembic, `migrations/`): `conversations`, `messages` (user and assistant
text) and `agent_runs` (status, error type, model, token counts, Langfuse
`trace_id`). LangGraph's `AsyncPostgresSaver` owns the `checkpoint*` tables.

`POST /api/v1/messages` accepts an optional `conversation_id`. Omit it to start a
new conversation; the server creates the ID and returns it in the JSON response and
the SSE `done` event. Only server-issued IDs can be continued; an unknown ID returns
`404 conversation_not_found`. Each request stores the user message and a `running`
run, then the assistant reply and a `completed` run, or marks the run `failed` or
`cancelled` with only the exception type; partial streamed replies are not stored.
The checkpoint thread is the conversation, and the graph resets per-turn state so
earlier turns are not sent to the model. Checkpointed graph state holds only plain
values.

The `messages` table stores message content. Treat the database as user data and
add authentication, per-conversation authorization and retention before real users.
Tests inject `MemoryPersistence` and need no database.

### Streaming responses

Set `STREAM_RESPONSES=true` in `.env` (default `false`) and restart the server. The
request body is unchanged; the response is `text/event-stream` with these events:

- `delta`: `{"text": "..."}`, a chunk of visible reply text, in order.
- `done`: `{"request_id", "provider", "model", "usage"}` once the reply is complete.
- `error`: the usual sanitized `{"error": {...}}` body if the model fails mid-stream.

Failures before the first chunk still return the normal JSON 502/504 status. Once
streaming starts the status is 200, so clients must handle a final `error` event.
`LLM_TIMEOUT_SECONDS` bounds the whole stream. The `request.completed` log is
written when headers are sent; `agent.completed` marks the end of the stream.

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{"message":"Write a short paragraph about rivers."}'
```

Open <http://127.0.0.1:8000/docs> for the interactive API documentation.

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
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
document is not a runtime prompt. The current provider sends only the submitted
message; it does not load or send either file.

For future design changes, keep the Markdown and Word versions aligned. README
records implementation status; the design document describes the target system.

## Next layers

1. Add conversation memory: send earlier messages of a conversation to the model.
2. Add one read-only MCP tool, then permission checks and action approvals.
3. Add durable workers, evaluation gates and Grafana monitoring as workflows grow.

Grafana is planned but not connected yet.
