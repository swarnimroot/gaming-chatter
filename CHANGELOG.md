# Changelog

## [Unreleased]

### Added — Phase 2.5 article body-fetch remediation (2026-05-07)
- `app/services/article_fetch.py` — `fetch_skipped_bodies()` re-fetches full article bodies for items whose enrichment status is `skipped`, via `scrapers_lib.tier1.article` (trafilatura). Updates `Item.body_text` only when the extracted body meets `ENRICH_BODY_CHAR_MIN`. Excludes YouTube items (transcript path handles those) and Reddit URLs (link-post pages return no extractable content — see DECISIONS 2026-05-07). 1s inter-request delay. Writes a `RunLog` row with `job_type='article_fetch'`.
- `scripts/run_article_fetch.py` — standalone runner that chains `fetch_skipped_bodies` → `enrich_pending(retry_failed=True)` → `embed_pending()` so the full Phase 2.5 pass runs unattended.

### Verified
- Full Phase 2.5 batch on the 173 skipped items: 95 attempted (after Reddit/YT exclusion), 94 fetched, 1 errored. Re-enrich produced 93 ok + 1 failed; embed top-up produced 93 new fp32 embeddings, 0 failed. Wall clock: 16m44s (fetch 2m12s, enrich 11m02s, embed 3m31s). **Final corpus: 988 items → 908 ok / 79 skipped / 1 failed. Coverage 82.5% → 91.9%.** 94/95 of the addressable subset recovered (98.9%).

### Added — Phase 2 local LLM enrichment + embeddings (2026-05-07)
- `app/services/ollama.py` — httpx client for `/api/generate` (JSON-mode) + `/api/embeddings`. Pydantic-validated `EnrichmentData` (tldr, entities, category, sentiment_score, sentiment_summary). Embeddings serialized as fp32 numpy bytes for SQLite BLOB storage. YouTube transcript fetch via `scrapers_lib.tier1.youtube` on-demand at enrichment time, with graceful fallback to ingest-time body when transcripts are unavailable / blocked.
- `app/services/enrich.py` — two-pass orchestration (`enrich_pending` then `embed_pending`) to avoid model swap thrash. Persists `status='ok' | 'failed' | 'skipped'`. Items below `ENRICH_BODY_CHAR_MIN` (default 200) are persisted as `skipped` rather than enriched from a useless title-only body.
- `app/routers/enrich.py` — `POST /enrich/pending` and `POST /embed/pending`, both with `?sync=true&limit=N` for sanity gates. Auto-chained after `POST /sources/ingest-all`.
- `enrichments` table: added `status` and `error` columns (idempotent SQLite ALTER in `app/db/init.py:_migrate_enrichments_columns`).
- Settings (`app/config.py`): `OLLAMA_HOST`, `OLLAMA_ENRICH_MODEL=qwen2.5:7b`, `OLLAMA_EMBED_MODEL=nomic-embed-text`, `OLLAMA_NUM_CTX=8192`, `OLLAMA_KEEP_ALIVE=24h`, `ENRICH_BODY_CHAR_CAP=24000`, `ENRICH_BODY_CHAR_MIN=200`.
- Dashboard renders TL;DR + category chip + sentiment per item, plus an "Enrich pending (N)" trigger.
- `scripts/run_enrich_batch.py` — standalone runner that chains `enrich_pending` → `embed_pending` for detached batch runs (used for the full-corpus backfill).

### Verified
- Full-corpus run on 988 items: **815 ok / 173 skipped / 0 failed** after fixes + retry pass. All 815 ok rows have 768-dim embeddings. Wall clock: ~1h55m (enrich 1h25m, embed 30m).

### Fixed
- `app/services/ollama.py`: added `'review'` to `_ALLOWED_CATEGORIES` and the SYSTEM_PROMPT — legitimate game/hardware review threads were being rejected. Added `@field_validator('games', 'companies', 'people', mode='before')` on `Entities` to normalize dict-shaped model output (`{name: {}}`) into the expected `list[str]`. Together these recovered all 13 batch failures.

### Deferred
- Phase 2.5 (article body-fetch via `scrapers_lib.tier1.article` for the 173 skipped items). Originally a "maybe" — promoted to **must-do before Phase 3** after observing skip composition included news-site RSS teasers, not just Reddit link-posts.

### Added — Phase 1 manual ingest end-to-end (2026-05-07)
- `app/services/scrapers.py` — thin wrappers around `scrapers_lib.tier1.rss` plus a YouTube `@handle` → channel-feed URL resolver (cached per-process).
- `app/services/ingest.py` — full ingest pipeline: dedup on `(source_id, mention_id)`, normalize RawMention → `items`, persist raw JSON to `raw_items`, fingerprint each item via `md5(normalized_title)`, update `sources.last_fetched_at` / `error_count` / `last_error`, log every run to `run_log`.
- `POST /sources/{id}/ingest` — synchronous per-source button.
- `POST /sources/ingest-all` — runs all enabled sources sequentially in a `BackgroundTasks` job.
- Dashboard now lists the latest 50 normalized items with source name, published date, title-link.
- Sources table now shows `last_fetched`, `error_count`, `last_error`, plus per-row Ingest button and an "Ingest all" button.

### Verified
- All 24 RSS feeds + 6 YouTube channels ingest cleanly under real network conditions on 2026-05-07. ~973 items in the first full run.
- Idempotency: re-running ingest on IGN twice keeps the items count at 20 (dedup confirmed).

### Fixed
- `sources.yaml`: corrected Gameranx YouTube handle from `@gameranx` (404) to `@GameranxTV`.

### Deferred
- YouTube transcript fetching via `tier1.youtube` — moves to Phase 2 enrichment. Phase 1 captures only video metadata (title, URL, channel, published).

### Added — Phase 0 skeleton (2026-05-07)
- `pyproject.toml` with FastAPI / SQLModel / APScheduler / HTMX-via-CDN / scrapers-lib (path dep) stack.
- `app/` package layout: `main.py`, `config.py`, `db/{models,session,init}.py`, `routers/{dashboard,sources}.py`, `utils/yaml_loader.py`, `templates/`, `static/`.
- All 7 SQLite tables defined as SQLModel: `sources`, `raw_items`, `items`, `enrichments`, `clusters`, `weekly_reports`, `run_log`.
- DB init via `SQLModel.metadata.create_all` + WAL + foreign-keys pragmas on connect.
- Idempotent seeder: loads `sources.yaml` into the `sources` table on startup.
- `GET /` placeholder dashboard and `GET /sources` read-only list view.
- Jinja base layout with HTMX 2.0.3 from unpkg.

### Pending
- UI template port from claude.ai/design (external delivery).
