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

- [x] Ollama HTTP client + model selection — `app/services/ollama.py` (httpx, JSON-mode). **Chose `qwen2.5:7b` over 14B** for VRAM headroom on the 12GB 5070; embed model = `nomic-embed-text` (768-dim). See DECISIONS.md 2026-05-07.
- [x] Per-item enrichment prompt → structured JSON (tldr, entities, category, sentiment) — Pydantic-validated, category enum locked to news/leak/launch/industry/community/opinion/patch.
- [x] Embedding generation per item — `embed_text()` returns fp32 numpy bytes; stored as BLOB.
- [x] "Enrich pending items" trigger — `POST /enrich/pending` + `POST /embed/pending`, both with `?sync=true&limit=N` for sanity gates. Auto-chained after `/sources/ingest-all` via BackgroundTasks.
- [x] Dashboard shows enriched feed (TL;DRs visible) — TL;DR under title, category chip, sentiment score per item; "Enrich pending (N)" button at top.
- [x] Prompt-quality sanity check on real ingested items before locking the prompt — 10/10 enriched cleanly, 2 prompt fixes applied (Reddit username exclusion, skip empty bodies).
- [x] **Run full backlog enrichment + embedding.** 815/988 ok, 173 skipped, 0 failed (after retry pass). All 815 have embeddings. Embed pass took ~30 min, slower than projected. See SESSION_LOG 2026-05-07.
- [x] Spot-check enrichments across category types after batch run; flag systemic issues if any. — Two failure modes found and fixed in `ollama.py` (added `'review'` category; dict→list `field_validator` on `Entities`). 1.9% underscored-handle bleed accepted. Skip composition includes news-site RSS teasers, not just Reddit link-posts → escalates Phase 2.5.

## Phase 2.5 — Article body-fetch for skipped items

Phase 2's 200-char skip threshold dropped 17.5% of corpus (173/988). Sampling showed many are news-site RSS teasers, not just Reddit link-posts. Recovering them before Phase 3 keeps clustering accurate. Promoted from "deferred maybe" to **must-do before Phase 3** (DECISIONS 2026-05-07).

- [x] `app/services/article_fetch.py` wrapping `scrapers_lib.tier1.article`. Calls tier1 directly with a 1s inter-request delay (matches existing `app/services/scrapers.py` convention; scrapers-lib `core` not used here). Reddit URLs and YouTube items are explicitly excluded — see DECISIONS 2026-05-07.
- [x] One-shot runner `scripts/run_article_fetch.py` (pattern after `run_enrich_batch.py`) that iterates `enrichments.status='skipped'`, fetches body via `item.url`, updates `items.body_text`, then chains `enrich_pending(retry_failed=True)` + `embed_pending()`.
- [x] Recovery quality bar: ≥40% of skipped items flip to `ok` (revised down from 80% once the 72 Reddit link-posts among the 173 were identified as structurally unrecoverable via trafilatura — see DECISIONS 2026-05-07). **Achieved: 94/173 = 54.3%, or 94/95 = 98.9% of the addressable subset.** 1 fetch errored, 1 enrichment failed on a thin-content list-article. Final corpus: 908 ok / 79 skipped / 1 failed; coverage 82.5% → 91.9%.
- [ ] Decide whether to fold `tier1.article` into the regular ingest pipeline going forward, or keep it as a remediation pass — depends on Phase 3 cluster-quality observations + scheduled-ingest rate-limit behavior. **Currently leaning: keep as remediation pass** (skipped rate is bounded, daily ingest stays fast, no scrape-rate exposure during normal operation).

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
