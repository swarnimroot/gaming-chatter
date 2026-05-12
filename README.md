# gaming-chatter

Personal weekly gaming-news aggregator. Daily ingest from a curated list of news sites, subreddits, and YouTube channels → Monday-morning exec summary + live dashboard covering biggest story, hottest games, industry risks, market momentum, WoW/MoM trends, community sentiment, and watch-list.

## Status

**Phase 3c.0.5 shipped (2026-05-12).** 988 items ingested · 887 Haiku-enriched + 13 preserved-qwen + 88 skipped · 900 re-embedded (768-dim) · 189 games tagged · 55 per-ISO-week clusters (W17/W18/W19). Per-item enrichment + game tagging now on **Anthropic Haiku 4.5**; embeddings stay on local Ollama; cluster labels + synthesis still pending (Phase 3c.4). See [`docs/TASKS.md`](docs/TASKS.md) for the phased plan and [`docs/SESSION_LOG.md`](docs/SESSION_LOG.md) for the latest handoff.

## Stack

Python · FastAPI · APScheduler · SQLite · HTMX + Jinja · Ollama (embeddings + legacy `label_cluster`) · Anthropic API (per-item enrichment via Haiku 4.5; synthesis via Opus 4.7 pending Phase 3c.4) · [scrapers-lib](../scrapers-lib) (ingest)

## Run

Prereqs: Python 3.11+, Ollama running locally with `nomic-embed-text` pulled (and `qwen2.5:7b` retained for `label_cluster()` pending the Phase 3c.4 Sonnet migration). Anthropic API key in a local `.env` at the repo root: `ANTHROPIC_API_KEY=sk-ant-...` — required for per-item enrichment as of Phase 3c.0.5.

```bash
# FastAPI app (dashboard, sources admin, /clusters view, /reports)
python -m uvicorn app.main:app --port 8765

# One-shot batch jobs (run alongside or instead of the app)
python scripts/run_enrich_batch.py             # enrich + embed pending items (uses Haiku)
python scripts/run_article_fetch.py            # Phase 2.5 body-fetch for skipped items
python scripts/rerun_enrichment.py             # re-enrich the full corpus with force=True
python scripts/sample_haiku_enrichment.py      # 10-item Haiku sample → md diff for review
python scripts/populate_games_dim.py           # tag unique games (lifecycle + live_service)
python scripts/run_cluster.py [--per-week]     # cluster + label + rank (no args = legacy week_id='all')
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
