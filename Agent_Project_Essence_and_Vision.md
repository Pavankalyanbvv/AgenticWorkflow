# Agent Project Essence Vision and Execution

A personal AI agent that can act across everyday digital services

## 1. Project Essence

The project starts with a practical, tool-using personal agent connected to a small set of MCP servers. Instead of building an agent that only answers questions, the goal is to build an agent that can understand a user's intent, select the appropriate capability, execute actions through tools, maintain context and memory, and safely complete multi-step tasks.

The initial experience should cover useful everyday workflows such as email, messaging and food ordering. The architecture should deliberately be designed so that new MCP servers and tools can be added without redesigning the core agent.

## 2. Starting Point

- Build a single agent with a small number of MCP servers.

- Connect practical services such as email, WhatsApp/messaging and food-ordering workflows through appropriate tools/integrations.

- Start with approximately 5–10 useful tools/capabilities.

- Make tool invocation observable and evaluable from day one.

- Keep the architecture modular so the tool ecosystem can grow over time.

## 3. Example User Experience

- Email: “Find the latest email from X and summarize it.” / “Draft a reply to this email.”

- Messaging: “Send a WhatsApp message to X saying I’ll reach in 20 minutes.”

- Food ordering: “Order my usual dinner from a nearby restaurant.” / “Find vegetarian options under ₹500.”

- Multi-tool task: “Check my calendar, message X that I’m running late, and order dinner for 8 PM.”

- Information + action: “Find good options, compare them, then place the order after I approve.”

The examples are intentionally action-oriented. The key capability is not simply generating a response; it is deciding what should happen, selecting the right tool(s), executing safely, and reporting the result.

## 4. Core Architecture

The initial architecture should be a single-agent system with MCP as the capability boundary. The agent should not contain service-specific business logic wherever that logic can live behind a tool/server.

1. User → input guardrail

1. Agent/orchestrator → understand intent and plan the task

1. Tool discovery / tool selection → identify relevant MCP tools

1. Authorization / tool guardrail → verify permissions and risky actions

1. MCP server → execute service-specific operation

1. Tool result → validate and return to agent

1. Memory → retain relevant session and long-term information

1. Output guardrail → validate the final response

1. Observability → trace every important step

## 5. Technical Stack

A team of two to three developers will build a single-agent application with production engineering as the learning goal. FastAPI, LangGraph, Langfuse Cloud and PostgreSQL form the selected foundation. Supporting library and hosting choices below are implementation recommendations. Start with managed free services and local development tools; increase capacity when measured usage requires it.

| Layer | Technology | Responsibility |
| --- | --- | --- |
| API server | FastAPI | HTTP endpoints, request validation and application lifecycle. |
| Agent orchestration | LangGraph | Explicit state, routing, tool loops, approval pauses and checkpoints. |
| AI observability | Langfuse Cloud | Agent traces, individual LLM generations, tool spans, prompts and evaluation scores. |
| Primary database | PostgreSQL | Application records and persistent LangGraph execution state. |
| Model access | Provider SDK | One shared LLM client; provider and initial model still to be selected. |
| Database hosting | Neon recommended | Managed PostgreSQL free tier for shared development; local PostgreSQL for isolated tests. |
| Database libraries | SQLAlchemy and psycopg | Async application queries, transactions and bounded connection pools. |
| Schema migrations | Alembic | Versioned application schema changes; LangGraph owns checkpoint table setup. |
| Logs and monitoring | structlog and Grafana Cloud | JSON application logs, server metrics, dashboards and alerts. |
| Telemetry and tests | OpenTelemetry, Alloy, pytest | Instrument the API, forward telemetry, and verify behavior locally and in CI. |

LangGraph runs as a library inside the application. Langfuse is the managed tracing backend. Neither requires a separate paid agent hosting platform. Grafana Alloy is a local forwarding process; observability storage remains managed in the cloud.

### LLM Calls and Trace Structure

All model requests go through the shared LLM client, including agent decisions, standalone generation and evaluator calls. The client owns model configuration, timeouts, controlled retries, streaming and usage extraction. The provider SDK sends requests to the model API; Langfuse observes those requests.

Each agent run has a parent trace with child observations for context loading, LLM generations, policy checks, tool execution and response validation. LLM-proposed tool calls and actual tool executions are recorded separately. Raw provider SDK calls require a provider integration or explicit generation observation; graph callbacks alone do not guarantee their capture.

Record model and prompt versions, sanitized inputs and outputs, token usage, latency, estimated cost, status and retry attempts. Preserve trace context across worker boundaries, avoid duplicate instrumentation, and verify retry visibility. Attach request, task and conversation identifiers to correlate traces with application logs. Telemetry export must use bounded buffering and must not prevent a user request from completing.

### Database Responsibilities

Use one PostgreSQL database initially, with application tables separated from LangGraph-managed checkpoint tables. SQL columns and constraints represent ownership and relationships; JSONB holds flexible tool payloads and metadata. Every conversation and graph thread must be authorized for its owner before access.

Application records include users, conversations, messages, agent runs, approvals, an action ledger and explicit user preferences. User-facing message history and execution checkpoints have distinct purposes and a defined synchronization policy. Store Langfuse trace references in agent runs; detailed telemetry remains in Langfuse.

Use AsyncPostgresSaver for persistent graph state. Checkpoints preserve execution progress but do not make external writes atomic. The action ledger, stable action identifiers and provider reconciliation must prevent duplicate operations. Apply checkpoint retention, connection limits, backup and restore verification before wider deployment.

### Evaluation and Initial Delivery

Run Python evaluators locally and in CI against versioned datasets. Use deterministic checks for schemas, permissions, tool arguments and outcomes. Use LLM judges for semantic quality, with human calibration. Publish scores to Langfuse and trace judge calls separately with purpose=evaluation. Sampled production evaluation runs asynchronously and has its own token and cost budget.

The first milestone is a FastAPI health endpoint and validated message endpoint, one instrumented model call, structured logs and tests with a fake provider. Next add PostgreSQL records, persistent graph checkpoints and one read-only MCP tool. Add approvals and external writes after execution reliability has been verified.

### Free Plan Constraints and Remaining Choices

As checked on 2 October 2026, Langfuse Hobby includes two users, 50,000 units per month and 30-day data access. A third shared-workspace user requires a different plan. Neon Free lists 0.5 GB database storage and 100 CU-hours per project per month. Grafana Cloud Free lists 50 GB of logs per month and 14-day retention. These are development allowances, not production capacity guarantees; confirm current limits at setup. Model API and judge calls may incur separate charges.

Still to select: initial model provider and model, MCP client implementation, authentication provider, application hosting and durable worker/job system. Introduce a cache or specialized retrieval database only when measured requirements justify it.

### References

LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/add-memory

Langfuse tracing integration: https://langfuse.com/integrations/frameworks/langchain

Langfuse plans: https://langfuse.com/pricing

Neon free plan: https://neon.com/blog/neon-backend-is-ga

Grafana Cloud plans: https://grafana.com/pricing/

## 6. MCP Server Strategy

Start with a small ecosystem and expand progressively:

| Capability | Initial role | Example tools | Risk level |
| --- | --- | --- | --- |
| Email | Read/search/draft | search_mail, read_mail, draft_reply | Low–Medium |
| Messaging | Send messages | find_contact, send_message | Medium |
| Food ordering | Search/cart/order | search_restaurants, search_menu, add_to_cart, place_order | High for final purchase |
| Calendar | Read/create/update events | find_events, create_event, update_event | Medium |
| Files/Docs | Search/read/create | search_files, read_doc, create_doc | Medium |
| Web/Search | Research/current information | search, fetch_page | Medium |

Important: real service integrations should use official APIs or permitted integrations. The MCP layer should expose safe, typed operations rather than browser automation by default.

## 7. Growth Path — From 10 Tools to a Tool Ecosystem

- Phase 1: 5–10 tools; manually curated tool definitions.

- Phase 2: 20–50 tools; stronger schemas, permissions and evaluation.

- Phase 3: 50–100+ tools; introduce tool search and deferred loading.

- Phase 4: multiple MCP servers; discover capabilities dynamically.

- Phase 5: optimize tool selection, context size, cost and latency.

- Phase 6: add specialized agents only where a clear boundary is useful.

## 8. Safety Model for Real-World Actions

Because the project can perform real-world actions, safety must be part of the architecture rather than an afterthought.

- Read-only actions can generally execute automatically when authorized.

- Reversible actions can execute with appropriate checks.

- Financial purchases, destructive actions and other consequential actions should require explicit confirmation where appropriate.

- Tool arguments must be validated before execution.

- User identity, authorization and service permissions must be enforced outside the model.

- Tool results must be treated as untrusted data and must not automatically override system-level instructions.

- Secrets, tokens and sensitive information must never be exposed to the model unnecessarily.

## 9. Memory Vision

The agent should gradually become personalized without storing everything.

- Short-term memory: current conversation, active task, tool results and intermediate state.

- Long-term memory: stable preferences, frequently used choices and useful user-provided facts.

- Task memory: what the agent has already done during a long-running workflow.

- Preference examples: preferred food types, recurring restaurants, communication preferences and common workflows.

- Memory must have explicit write, retrieval, update and deletion policies.

## 10. Voice Agent Extension

Once the text-based agent is reliable, add a voice interface on top of the same agent/tool layer. Voice should be treated as another interface, not as a separate intelligence stack.

1. Voice input → speech recognition/streaming ASR

1. Conversation/session state → shared agent runtime

1. Agent → same MCP/tool ecosystem

1. Tool execution → existing guardrails and approvals

1. Agent response → streaming TTS

1. Voice-specific UX → interruption/barge-in, confirmation and concise spoken responses

Example: “Order my usual dinner.” The voice agent should retrieve the user's preference, search the food-ordering tools, present the important choices, obtain confirmation before purchase when required, and execute the same workflow used by the text interface.

## 11. Evaluation Vision

- Did the agent understand the user's intent?

- Did it select the correct MCP server/tool?

- Were tool arguments correct?

- Did it call unnecessary tools?

- Did it miss a required tool?

- Was the multi-step trajectory sensible?

- Did the requested real-world action actually happen?

- Was the final answer accurate and grounded in tool results?

- Did memory help or hurt the decision?

- Was the interaction within acceptable cost and latency?

## 12. Production Learning Loop

1. Capture traces from production.

1. Sample a configurable percentage of requests (for example, ~5%).

1. Use an LLM judge for semantic evaluation of tool choice, trajectory and answer quality.

1. Send uncertain or failed cases for human verification.

1. Convert verified failures into the offline evaluation set.

1. Run regression tests whenever prompts, models, tools or routing change.

1. Deploy using versioning, canary/rollback and production metric comparison.

## 13. What Success Looks Like

The end goal is a personal, extensible agent that can operate across multiple digital services instead of being tied to one application. A user should be able to express an outcome naturally, while the system handles the decomposition, capability discovery, tool selection, execution, memory, safety checks and final response.

The project should demonstrate production-grade agent engineering: MCP-based integrations, dynamic tool use, guardrails, memory, evaluation, observability, reliability, cost/latency optimization and continuous improvement.

## 14. Two-Month Milestone Alignment

| Milestone | Target |
| --- | --- |
| Weeks 1–2 | Core agent + initial MCP servers + 5–10 tools + reliable tool contracts |
| Week 3 | Guardrails, permissions and approval flow |
| Week 4 | Offline evaluation and trace-based testing |
| Week 5 | Short- and long-term memory |
| Week 6 | More tools + tool search + deferred loading |
| Week 7 | Cost, latency, reliability and observability |
| Week 8 | Production deployment + sampled LLM-as-judge + continuous improvement |
| After 2 months | Expand MCP ecosystem and introduce voice interface using the same agent core |

## 15. Project North Star

Build one agent that can move from “answering my question” to “safely getting things done for me” — across an expanding ecosystem of MCP-powered capabilities.
