# gaming-chatter

Personal weekly gaming-news aggregator. Daily ingest from a curated list of news sites, subreddits, and YouTube channels → Monday-morning exec summary + live dashboard covering biggest story, hottest games, industry risks, market momentum, WoW/MoM trends, community sentiment, and watch-list.

## Status

**Design phase.** Architecture locked, no code yet. See [`docs/TASKS.md`](docs/TASKS.md) for current phase and next steps.

## Stack

Python · FastAPI · APScheduler · SQLite · HTMX + Jinja · Ollama (local LLM) · Anthropic API (synthesis) · [scrapers-lib](../scrapers-lib) (ingest)

## Run

_TBD — populated at end of Phase 0._

## Docs

- [`docs/PRD.md`](docs/PRD.md) — what + why + scope + non-goals
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, data flow, data model
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — locked decisions w/ rationale (append-only)
- [`docs/TASKS.md`](docs/TASKS.md) — phased build plan
- [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) — unresolved items
- [`docs/SESSION_LOG.md`](docs/SESSION_LOG.md) — session-by-session handoff log
- [`CLAUDE.md`](CLAUDE.md) — instructions for Claude sessions
