# Tasks

Phased build plan. Check off as work moves. **End of Phase 3 = working product.** Phases 4–5 are automation + polish. "Later" is deferred.

---

## Phase 0 — Skeleton

- [x] `pyproject.toml` with dependencies (fastapi, uvicorn, jinja2, apscheduler, sqlmodel/sqlalchemy, httpx, anthropic, numpy, scrapers-lib via path)
- [x] Folder structure (`app/`, `app/templates/`, `app/static/`, `app/db/`, `tests/`)
- [x] FastAPI app skeleton with one placeholder route
- [x] SQLite DB initialization + schema migration mechanism (alembic or hand-rolled) — hand-rolled `SQLModel.metadata.create_all` + WAL pragma on connect
- [x] All 7 tables defined as SQLModel/SQLAlchemy models
- [x] Source registry seeded from `sources.yaml` on first run (idempotent upsert by `(type, url_or_handle)`)
- [x] Sources page (`/sources`) — read-only list view for now
- [x] Dashboard placeholder (`/`)
- [x] Basic Jinja layout + HTMX include from CDN (htmx 2.0.3 via unpkg)
- [ ] Port UI template from claude.ai/design once delivered — **blocked: awaiting external delivery**
- [x] Create `CHANGELOG.md` with first entry

## Phase 1 — Manual ingest end-to-end

- [x] Wrapper functions for each scrapers-lib tier1 module in use: `rss` (covers news sites + Reddit subreddits) and `youtube`. `tier1.article` available for direct-URL fallbacks if needed. `tier1.reddit` paused pending PRAW reapproval. — **Note:** YouTube sources go through `tier1.rss` against the channel-feed URL (resolved from `@handle`); transcript fetching deferred to Phase 2. See DECISIONS.md 2026-05-07.
- [x] "Ingest now" button on Sources page (per-source + run-all) — `POST /sources/{id}/ingest` (sync) + `POST /sources/ingest-all` (BackgroundTasks).
- [x] Write to `raw_items` and `items`; honor exact-match dedup — dedup on `(source_id, mention_id)`. Idempotency verified: re-ingesting IGN twice keeps count at 20.
- [x] Update `sources.last_fetched_at` and error tracking — last_fetched_at, last_error, error_count all updated; RunLog rows persisted per ingest.
- [x] Dashboard shows raw item list (latest 50) — shows latest 50 normalized `items` (chose normalized over raw_items for usability; raw JSON still in raw_items).
- [x] **Verify the 6 YouTube channels** via `tier1.youtube` (RSS feeds were pre-verified 2026-05-07; YouTube is unverified). — All 6 verified after correcting `@gameranx` → `@GameranxTV`. 15 videos each in one ingest cycle.
- [x] **Re-verify all 24 RSS feeds** under real-ingest conditions before enabling scheduled runs (network/health changes over time). — All 24 returned items on 2026-05-07 real ingest (range: 10–100 per source; 898 RSS items total).
- [x] During first real-ingest run, sanity-check a handful of items per source type for shape correctness. — RSS + YouTube samples both have non-empty title, real URL, populated published_at, body_text. 0 of 973 items had empty title/url/published.

## Phase 2 — Local LLM enrichment

- [ ] Ollama HTTP client + model selection (14B for enrichment + embedding model)
- [ ] Per-item enrichment prompt → structured JSON (tldr, entities, category, sentiment)
- [ ] Embedding generation per item
- [ ] "Enrich pending items" trigger
- [ ] Dashboard shows enriched feed (TL;DRs visible)
- [ ] Prompt-quality sanity check on real ingested items before locking the prompt

## Phase 3 — Clustering + synthesis report

- [ ] Cosine clustering of weekly enriched items (numpy)
- [ ] Per-cluster label generation (local Ollama)
- [ ] Cluster ranking heuristic (cross-source × signal × recency)
- [ ] Define "industry risks" rubric (deferred from design)
- [ ] Define "community sentiment" rubric (deferred from design)
- [ ] Anthropic synthesis prompt with all 7 report sections
- [ ] Markdown → standalone HTML rendering with inlined CSS
- [ ] "Generate report" manual button
- [ ] Reports archive view (`/reports`)
- [ ] Export-as-HTML button
- [ ] **End of Phase 3 = working product.**

## Phase 4 — Automation

- [ ] APScheduler jobs: daily ingest, Monday synthesis
- [ ] Catch-up logic on app startup for missed runs
- [ ] Run log table writes + UI (`/runs`)
- [ ] Source CRUD (add / edit / disable / remove) via web forms
- [ ] Per-source health/error display

## Phase 5 — Polish

- [ ] Trend mini-charts on dashboard (WoW/MoM)
- [ ] Watch-list section in synthesis
- [ ] Sentiment view (per-category aggregate)
- [ ] Source-failure alert (UI banner when error_count > N)
- [ ] Eval harness for synthesis quality (sample → manual rate → tune prompts)

## Later (deferred)

- [ ] Push delivery — email
- [ ] Push delivery — Discord webhook
- [ ] Recipient distribution-list management
- [ ] Mobile-friendly layout pass
