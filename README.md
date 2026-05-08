# gaming-chatter

Personal weekly gaming-news aggregator. Daily ingest from a curated list of news sites, subreddits, and YouTube channels → Monday-morning exec summary + live dashboard covering biggest story, hottest games, industry risks, market momentum, WoW/MoM trends, community sentiment, and watch-list.

## Status

**Phase 3b shipped (2026-05-08).** 988 items ingested · 908 ok-enriched + embedded · 63 clusters ranked by cross-source × volume × recency. Next: Phase 3c (Anthropic synthesis) + 3d (report UI). See [`docs/TASKS.md`](docs/TASKS.md) for the phased plan and [`docs/SESSION_LOG.md`](docs/SESSION_LOG.md) for the latest session handoff.

## Stack

Python · FastAPI · APScheduler · SQLite · HTMX + Jinja · Ollama (local LLM) · Anthropic API (synthesis) · [scrapers-lib](../scrapers-lib) (ingest)

## Run

Prereqs: Python 3.11+, Ollama running locally with `qwen2.5:7b` and `nomic-embed-text` pulled. Anthropic API key in env (only needed once Phase 3c lands; ingest/enrich/cluster don't require it).

```bash
# FastAPI app (dashboard, sources admin, /clusters view)
python -m uvicorn app.main:app --port 8765

# One-shot batch jobs (run alongside or instead of the app)
python scripts/run_enrich_batch.py        # enrich + embed pending items
python scripts/run_article_fetch.py       # Phase 2.5 body-fetch for skipped items
python scripts/run_cluster.py [week_id]   # cluster + label + rank (default week_id='all')
python scripts/inspect_cluster_ranking.py [N]  # dump top-N clusters by score
```

Dashboard: `http://localhost:8765/` · Cluster view: `/clusters` · Sources admin: `/sources`.

## Docs

- [`docs/PRD.md`](docs/PRD.md) — what + why + scope + non-goals
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, data flow, data model
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — locked decisions w/ rationale (append-only)
- [`docs/TASKS.md`](docs/TASKS.md) — phased build plan
- [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) — unresolved items
- [`docs/SESSION_LOG.md`](docs/SESSION_LOG.md) — session-by-session handoff log
- [`CLAUDE.md`](CLAUDE.md) — instructions for Claude sessions
