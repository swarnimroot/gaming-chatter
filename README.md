# gaming-chatter

Personal weekly gaming-news aggregator. Daily ingest from a curated list of news sites, subreddits, and YouTube channels → Monday-morning exec summary + live dashboard covering biggest story, hottest games, industry risks, market momentum, WoW/MoM trends, community sentiment, and watch-list.

## Status

**Phase 3c.23 shipped (2026-05-19).** 1597 items · 1412 Haiku-enriched + embedded (768-dim `nomic-embed-text`) · 184 games tagged · 286 authoritative game release dates from pcgamer (Phase 3c.18 `game_releases` table) · 247 per-ISO-week clusters with Sonnet-4.6 labels · 4 `weekly_reports` rows (W17–W20, all Opus-4.7-synthesized + critic-passed; W20 re-synthed under the 3c.22 watch[]-with-category schema). Weekly read-out live at `/` with exec-summary 1-pager + HTML/PDF export, date-range picker on `/stories` + `/clusters` (vendored flatpickr, replaces the ISO-week dropdown), bidirectional Trends card (top-5 rising + top-5 declining per tab), per-category sentiment view at `/sentiment` with right-drawer drill-in, source-failure alert banner when any source's `error_count > 3`, region tabs on `/`/`/stories`/`/clusters`, watch-list category chips on the Watch card. Cumulative LLM spend: ~$11.38. See [`CLAUDE.md`](CLAUDE.md) for per-phase history and [`docs/SESSION_LOG.md`](docs/SESSION_LOG.md) for the latest handoff.

## Stack

Python · FastAPI (single process, `root_path`-aware for Tailscale Funnel) · APScheduler (pending Phase 4) · SQLite · HTMX + Jinja · Ollama (embeddings via `nomic-embed-text`) · Anthropic API (Haiku 4.5 per-item enrichment, Sonnet 4.6 cluster labels, Opus 4.7 synthesis + critic) · [scrapers-lib](../scrapers-lib) v1.7.0+ (ingest + YouTube audio-fallback transcripts)

## Run

Prereqs: Python 3.11+, Ollama running locally with `nomic-embed-text` pulled. Anthropic API key in `.env` at repo root: `ANTHROPIC_API_KEY=sk-ant-...`. For YouTube audio-fallback transcripts: install scrapers-lib with the optional extra — `pip install -e "../scrapers-lib[youtube-audio]"` — which pulls `yt-dlp` + `faster-whisper` + `PyAV` (no system `ffmpeg` needed). Optional: `GC_ROOT_PATH=/gaming-chatter` in `.env` for Tailscale Funnel sub-path deploy (leave unset for local dev).

```bash
# FastAPI app (weekly read-out at /, dashboard at /stories, /clusters, /sources)
python -m uvicorn app.main:app --port 8001 --reload

# One-shot batch jobs (run alongside or instead of the app)
python scripts/run_enrich_batch.py             # enrich + embed pending items (uses Haiku)
python scripts/run_article_fetch.py            # Phase 2.5 body-fetch for skipped items
python scripts/rerun_enrichment.py             # re-enrich the full corpus with force=True
python scripts/sample_haiku_enrichment.py      # 10-item Haiku sample → md diff for review
python scripts/populate_games_dim.py           # tag unique games (lifecycle + live_service)
python scripts/run_cluster.py [--per-week]     # cluster + label + rank (no args = legacy week_id='all')
python scripts/inspect_cluster_ranking.py [N]  # dump top-N clusters by score
```

Weekly read-out: `http://localhost:8001/` · Stories: `/stories` · Clusters: `/clusters` · Sentiment: `/sentiment` · Sources admin: `/sources`.

## Docs

- [`docs/PRD.md`](docs/PRD.md) — what + why + scope + non-goals
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, data flow, data model
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — locked decisions w/ rationale (append-only)
- [`docs/TASKS.md`](docs/TASKS.md) — phased build plan
- [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) — unresolved items
- [`docs/SESSION_LOG.md`](docs/SESSION_LOG.md) — session-by-session handoff log
- [`CLAUDE.md`](CLAUDE.md) — instructions for Claude sessions
