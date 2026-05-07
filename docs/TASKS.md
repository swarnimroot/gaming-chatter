# Tasks

Phased build plan. Check off as work moves. **End of Phase 3 = working product.** Phases 4–5 are automation + polish. "Later" is deferred.

---

## Phase 0 — Skeleton

- [ ] `pyproject.toml` with dependencies (fastapi, uvicorn, jinja2, apscheduler, sqlmodel/sqlalchemy, httpx, anthropic, numpy, scrapers-lib via path)
- [ ] Folder structure (`app/`, `app/templates/`, `app/static/`, `app/db/`, `tests/`)
- [ ] FastAPI app skeleton with one placeholder route
- [ ] SQLite DB initialization + schema migration mechanism (alembic or hand-rolled)
- [ ] All 7 tables defined as SQLModel/SQLAlchemy models
- [ ] Source registry seeded from `sources.yaml` on first run
- [ ] Sources page (`/sources`) — read-only list view for now
- [ ] Dashboard placeholder (`/`)
- [ ] Basic Jinja layout + HTMX include from CDN
- [ ] Port UI template from claude.ai/design once delivered
- [ ] Create `CHANGELOG.md` with first entry

## Phase 1 — Manual ingest end-to-end

- [ ] Wrapper functions for each scrapers-lib tier1 module in use: `rss` (covers news sites + Reddit subreddits) and `youtube`. `tier1.article` available for direct-URL fallbacks if needed. `tier1.reddit` paused pending PRAW reapproval.
- [ ] "Ingest now" button on Sources page (per-source + run-all)
- [ ] Write to `raw_items` and `items`; honor exact-match dedup
- [ ] Update `sources.last_fetched_at` and error tracking
- [ ] Dashboard shows raw item list (latest 50)
- [ ] **Verify the 6 YouTube channels** via `tier1.youtube` (RSS feeds were pre-verified 2026-05-07; YouTube is unverified).
- [ ] **Re-verify all 24 RSS feeds** under real-ingest conditions before enabling scheduled runs (network/health changes over time).
- [ ] During first real-ingest run, sanity-check a handful of items per source type for shape correctness.

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
