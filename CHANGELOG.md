# Changelog

## [Unreleased]

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
