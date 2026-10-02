# Project instructions

Read `Agent_Project_Essence_and_Vision.md` before making architectural changes.
Use it as the project design reference. It describes both selected technologies
and future work; consult `README.md` for what is actually implemented.

- Keep all project code, documentation, and configuration under this folder.
- Build incrementally: FastAPI foundation, real model and Langfuse tracing,
  LangGraph orchestration, PostgreSQL persistence, then MCP tools and approvals.
- Selected foundation: Python, FastAPI, LangGraph, Langfuse Cloud, PostgreSQL.
- Do not introduce paid services or new infrastructure without a concrete need.
- Keep API handlers thin, model access behind a provider interface, and secrets
  in environment variables. Never log message bodies or credentials by default.
- Project documentation is coding context, not an application system prompt.
  Do not automatically send this document or AGENTS.md to runtime model calls.
- Do not write new tests or expand existing tests during development unless
  explicitly requested by the user, to reduce token spending. Preserve existing tests.
- Run relevant existing tests with `uv run pytest` and run
  `uv run ruff check .` for relevant code changes.
- Update README.md when implementation status or setup instructions change.
