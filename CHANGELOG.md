# Changelog

## [Unreleased]

### Added — Phase 3c.0 tagging foundation: schema + structured-output enrichment + per-week cluster scaffolding (2026-05-12)
- **Schema migration.** `app/db/init.py:_migrate_enrichments_columns` extended idempotently with `genres TEXT`, `platforms TEXT`, `event TEXT` columns on the `enrichments` table; new `games` dim table created (`name TEXT PRIMARY KEY`, `lifecycle TEXT`, `live_service INTEGER`). `Game` SQLModel class added to `app/db/models.py`. Verified via PRAGMA + a double-call `init_db()` for idempotency.
- **Ollama enrichment switched to structured-output (JSON schema) mode.** `app/services/ollama.py` SYSTEM_PROMPT restructured to demand `genres[]` / `platforms[]` / `event`; `EnrichmentData.model_json_schema()` passed directly as the Ollama `format` parameter (replacing `format:"json"` which silently omitted the new fields). `required` override on the schema forces the 3 new fields to appear despite their Pydantic defaults. Pydantic field validators drop out-of-taxonomy values; genres capped at 3. Locked taxonomies: 12 genres / 6 platforms / 12 events + Other-showcase.
- **`tag_game()` + `GameTagData` + `_game_tag_json_schema()`** added to `app/services/ollama.py` for the per-game `lifecycle` / `live_service` pass (separate from per-item enrichment so a game referenced by N clusters is tagged once consistently). Dedicated `GAME_TAG_SYSTEM_PROMPT` with the locked fuzzy rules.
- **`scripts/populate_games_dim.py` (new)** — extracts unique game names from `enrichments.entities` via `json_each`, filters to ≥2 mentions (configurable), idempotent INSERT into the `games` dim. Flags: `--limit`, `--sample`, `--min-mentions`.
- **`scripts/run_cluster.py` rewritten** with argparse + `--per-week` mode that iterates ISO weeks via `datetime.fromisocalendar()`, calling `cluster_window()` per week to replace the prior `week_id='all'` global clustering. Backward compat preserved (no args → legacy `"all"`).
- **`scripts/rerun_enrichment.py` (new)** — backfill driver for the re-enrichment pass.

### Aborted / blocked
- **908-item re-enrichment run was aborted mid-run.** Killed after ~25 items: structured-output mode pushed qwen2.5:7b to ~26s/item (~7-hour ETA vs the ~45-min estimate); a 10-item sample exposed quality issues that the prompt restructure did not fix (Reddit username `Responsible_Box_2422` leaked into `entities.people`; the movie *Minions & Monsters* was tagged with `Indie/Roguelike`). User decision: pivot per-item enrichment to **Anthropic Haiku 4.5** before retrying the backfill — overrides the "Ollama-only for per-item work" architectural lock. See DECISIONS 2026-05-12 (later). DB state: ~25–30 items now hold partial qwen rewrites; next-session Haiku rerun will overwrite all 988 uniformly, no rollback needed.
- **`scripts/populate_games_dim.py` + `scripts/run_cluster.py --per-week`** both have code staged but execution is blocked on the Haiku backfill (they need to run against a uniformly-tagged corpus, not the qwen partial).

### Locked (2026-05-12, later)
- **Override of "Ollama-only for per-item work" lock.** Per-item enrichment now uses Anthropic Haiku 4.5. Cluster labels move to Anthropic Sonnet 4.6. Synthesis gains a critic / editor pass via a second Opus 4.7 call. Embeddings stay on local Ollama (`nomic-embed-text` 768-dim). Estimated total Anthropic spend ~$210–310/yr — inside the user's $500/yr ceiling. See DECISIONS 2026-05-12 (later) for the concrete-evidence rationale (qwen quality ceiling + structured-output runtime + budget headroom).

### Added — claude.ai/design weekly read-out ported to `/reports` (2026-05-11)
- `app/templates/reports.html` — standalone HTML doc (does NOT extend `base.html` — the design has its own full-bleed sidebar + main shell). Renders all 13 cards from the design's `cards.jsx` in default order with placeholder data verbatim from `data.jsx`. Locked variants: grid layout (3-col, biggest spans 2), comfortable spacing, light theme, orange accent `#D9682B` (editorial amber).
- `app/templates/_components.html` — Jinja macros mirroring `primitives.jsx`: `eyebrow`, `source_pill`, `source_row`, `freshness`, `meter`, `signal_cluster`, `mini_bar`, `delta`, `dot`, `sparkline`, `card_header`.
- `app/routers/reports.py` — `GET /reports?week=...` route (3 sample weeks selectable: `2026-W18` default, `2026-W17`, `2026-W16`); placeholder `WEEKS_RAW` mirroring `data.jsx` shape; `sparkline_path()` helper that reproduces the JSX sparkline geometry in Python; `SOURCES_META` / `NAV_ITEMS` / `USER` constants.
- `app/static/app.css` — rewritten. Legacy `body / table / .cluster*` rules preserved on top so Dashboard/Sources/Clusters keep working unchanged. Below: `:root` CSS variables (locked palette + spacing + motion tokens) and `.gc-*` namespace for sidebar, header, grid, card, signal cluster, source pills, sparkline, meters, delta, severity badges, risk/drama callouts, all row layouts.
- `app/static/img/alienware-head-light.svg` — sidebar logo, copied from the bundle.
- `app/main.py` — one-line additive: mount `reports.router`.
- `app/templates/base.html` — one-line additive: `Reports` nav link.

### Locked (2026-05-11)
- **Phase 3c industry-risks rubric:** layoffs/closures + regulation/legal/policy. Excludes broader market structural shifts and consumer-side pressures. See DECISIONS 2026-05-11.
- **Phase 3c community-sentiment rubric:** Reddit-only hybrid — numeric `mean(sentiment_score)` over Reddit-source cluster members + 2–3 `sentiment_summary` excerpts passed to Anthropic. See DECISIONS 2026-05-11.
- **Phase 3c synthesis model:** Opus 4.7 (`claude-opus-4-7`). ~$15/yr at weekly cadence. See DECISIONS 2026-05-11.
- **WoW-Trends section deferred** entirely from Phase 3c; when it lands later it will be WoW only (no MoM). Trends needs schema additions or a synthesis-time tagging pass for platform/genre/live-service/lifecycle dimensions. See DECISIONS 2026-05-11.

### Verified
- `GET /reports` smoke-tested: HTTP 200, ~40KB response. 54× `gc-card` class refs in markup, 5× `<polyline>` (biggest card + 4 momentum cells), 11× `data-lucide` icons, 4× `is-active` markers. Headline + week selector + all 13 card sections render. Other 2 weeks selectable via `?week=` query.

### Implementation simplifications vs the React/JSX prototype
- Dropped: drag-to-reorder cards, Tweaks panel, layout/density/theme runtime toggles (kept as static visual buttons in the header since variants are locked), exec-summary modal, SourceDrawer side panel.
- Sidebar nav items beyond "Weekly read-out" are `href="#"` visual placeholders pending the next-session walkthrough.
- Lucide icon CDN kept (`unpkg.com/lucide@latest`); React 18 + ReactDOM + Babel-standalone runtime stripped.

### Added — Phase 3b cluster ranking heuristic (2026-05-08)
- `clusters` table: three new columns (`source_count INTEGER`, `latest_published_at TIMESTAMP`, `score REAL`), added via idempotent SQLite ALTER in `app/db/init.py:_migrate_clusters_columns`. `Cluster` SQLModel updated.
- `app/services/cluster.py:cluster_window` now computes and persists per-cluster `source_count` (distinct member sources), `latest_published_at` (max member `published_at`), and `score = source_count * member_count / (1 + days_since_latest)` alongside the existing label/centroid/member fields. See DECISIONS 2026-05-08 for formula rationale.
- `app/routers/clusters.py:clusters_view` sorts by `score DESC NULLS LAST, member_count DESC` (was: `member_count DESC`).
- `app/templates/clusters.html` cluster card now shows `score N.N` and `latest YYYY-MM-DD` alongside member/source counts. Minor `.cluster-meta .score` weight bump in `app/static/app.css`.
- `scripts/inspect_cluster_ranking.py` — one-off script to dump top-N clusters by score for ranking review.

### Verified
- Re-ran `cluster_window(week_id='all')` on the 908-item corpus: 63 clusters / 157 items / 63 labelled / 0 failures. 186.0s wall clock.
- Top of ranked list: Mixtape coming-of-age review (5×5, today) 12.79; Griffin Gaming Partners $100M indie fund (4×5) 10.02; Take-Two/BioShock disappointment (4×4) 7.75; Star Fox 64 Switch 2 remake (4×4) 6.76; Valve restocks Steam Controller (4×4, 1d) 5.97. All 14 single-source long-tail clusters (YongYea / VG247 / Fallout walkthroughs / Game Informer weekly picks) scored <1.0 and sank to the bottom — the demotion the prior session called for.
- `GET /clusters?week_id=all` smoke-tested: HTTP 200, 88KB, score + latest date rendering on each card.

### Added — Phase 3a clustering + cluster labels (2026-05-08)
- `app/services/cluster.py` — `cluster_window(start, end, week_id)`: cosine connected-components clustering at `CLUSTER_THRESHOLD=0.85` (locked after corpus exploration; see DECISIONS 2026-05-07) over fp32 768-dim TL;DR embeddings. Persists per-cluster centroid (BLOB), member item IDs (JSON in TEXT), label, member_count to the `clusters` table keyed by `week_id`. Idempotent: re-runs delete prior rows for the same `week_id`. Writes a `RunLog` row with `job_type='cluster'`.
- `app/services/ollama.py` — `label_cluster(titles, tldrs)` helper: qwen2.5:7b in JSON-mode, returns a one-line cluster label. ~3s per call. System prompt with 5 worked examples.
- `app/routers/clusters.py` — `POST /clusters/run?week_id=&sync=` (manual trigger) and `GET /clusters?week_id=` (HTML view of clusters with per-member item links and source counts).
- `app/templates/clusters.html` + cluster card CSS in `app/static/app.css`. Nav link added to base layout.
- `scripts/run_cluster.py` — standalone runner (matches `run_enrich_batch.py` / `run_article_fetch.py` pattern). Optional `week_id` arg.
- `scripts/explore_clustering.py` — utility for re-tuning the threshold against the live corpus (kept around; not on the runtime path).
- Settings (`app/config.py`): `CLUSTER_THRESHOLD=0.85`, `CLUSTER_MIN_SIZE=2`, `CLUSTER_LABEL_SAMPLE=8`.

### Verified
- First production run on the 908-item corpus (`week_id='all'`): **63 clusters, 157 items grouped (17.3% of corpus), 63/63 labelled, 0 failures.** Wall clock 178.8s. Centroid blobs verified at 3072 bytes (= 768 fp32). UI smoke-tested: `GET /clusters` returned 200 with all 63 clusters rendering correctly.
- Label quality (eyeball): ~50/63 clean editorial signals (e.g. "Wizards of the Coast misses union recognition deadline", "Greedfall developer Spiders closing", "Star Fox 64 remake for Switch 2"). ~10–13 vague or single-source long-tail clusters acceptable — they will be deprioritized by the cross-source × signal × recency ranking heuristic in Phase 3b.

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
