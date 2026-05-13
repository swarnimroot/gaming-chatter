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
- [x] Port UI template from claude.ai/design once delivered — **delivered + ported 2026-05-11.** `/reports` renders all 13 cards from the design's `cards.jsx` with placeholder data and the four locked variants (grid + comfortable + light + orange `#D9682B`). Standalone template — does not affect existing pages. Section trim + real-data wiring is Phase 3c walkthrough work. See SESSION_LOG 2026-05-11 + DECISIONS 2026-05-11.
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

- [x] Cosine clustering of weekly enriched items (numpy) — `app/services/cluster.py`. Connected-components on a thresholded similarity graph at **0.85** (locked after exploration on the 908-item corpus; see DECISIONS.md 2026-05-07). 63 clusters / 157 clustered items on first run.
- [x] Per-cluster label generation (local Ollama) — `label_cluster()` in `app/services/ollama.py`, qwen2.5:7b, JSON-mode. ~3s per cluster. 63/63 labelled cleanly on first run.
- [x] Cluster ranking heuristic (cross-source × signal × recency) — `score = source_count * member_count / (1 + days_since_latest)` persisted on each `clusters` row alongside `source_count` and `latest_published_at`. `/clusters` now sorts by score DESC. Single-source long-tail clusters (YongYea / VG247 / Fallout walkthroughs) all score < 1.0 and sink to the bottom; cross-source stories (Mixtape 5×5, Griffin Fund 4×5, Take-Two 4×4, Star Fox 4×4) dominate the top. See DECISIONS 2026-05-08.
- [x] Define "industry risks" rubric — **locked 2026-05-11:** layoffs/closures + regulation/legal/policy. Excludes broader market structural shifts and consumer-side pressures. See DECISIONS 2026-05-11.
- [x] Define "community sentiment" rubric — **locked 2026-05-11:** Reddit-only hybrid. Numeric `mean(sentiment_score)` over Reddit-source cluster members + 2–3 `sentiment_summary` excerpts. See DECISIONS 2026-05-11.
- [x] Lock synthesis model — **Opus 4.7** (`claude-opus-4-7`), once weekly, prompt-cached system block. See DECISIONS 2026-05-11.
- [x] Port claude.ai/design UI template to `/reports` (placeholder data) — see SESSION_LOG + CHANGELOG 2026-05-11.
- [x] **Walk `/reports` section-by-section with user** to lock keep/drop/rework of the 13 cards + 6 sidebar nav items + header chrome + footer hint. Decide also: port the `exec-summary` modal and `SourceDrawer` side panel from the bundle, or drop them. — **Done 2026-05-12.** Walkthrough drove the re-scope below: Card 1 dropped, Studio Watch + Storefronts folded into MM, Trends restored as a 5-tab card, exec-summary modal + SourceDrawer kept. Drove Phase 3c.0 tagging foundation.

### Phase 3c.0 — Tagging foundation

- [x] Schema migration: add `genres TEXT`, `platforms TEXT`, `event TEXT` columns to `enrichments` (multi-valued stored as JSON arrays); add new `games` dim table with `name TEXT PK`, `lifecycle TEXT`, `live_service INTEGER` (boolean). — **DONE 2026-05-12.** Idempotent migration in `app/db/init.py` (extended `_migrate_enrichments_columns`); `Game` SQLModel added to `app/db/models.py`. Verified via PRAGMA + double-run `init_db()`.
- [x] Extend Ollama enrichment prompt with 3 new structured fields (`genres[]`, `platforms[]`, `event`); add worked examples for each taxonomy; cap genres at 3; drop out-of-taxonomy values rather than mapping. — **DONE for code 2026-05-12.** SYSTEM_PROMPT restructured in `app/services/ollama.py`; constrained-decoding via `EnrichmentData.model_json_schema()` passed as `format` (plain `format:"json"` was silently omitting the new fields). Pydantic field validators drop out-of-taxonomy values; genres capped at 3. **Note:** the prompt content itself is reusable but the *calling code* will be ported to Anthropic Haiku 4.5 in Phase 3c.0.5 — see DECISIONS 2026-05-12 (later).
- [x] Re-enrich the 908-item backlog with new fields. — **DONE 2026-05-12 via Haiku 4.5 in Phase 3c.0.5.** 988 attempted, 887 Haiku-rewrote, 88 skipped (body < 200 chars), 13 preserved-qwen (Haiku returned out-of-taxonomy category like `'guide'`; safety net kept the prior valid row), 0 hard failures. 39.5 min elapsed, ~$3-4 spend.
- [x] Populate `games` dim table: extract unique game names from `entities.games`, tag each with `lifecycle` + `live_service`. — **DONE 2026-05-12 in Phase 3c.0.5.** 189 unique games (min_mentions=2) tagged via Haiku in 3.6 min: 131 existing / 28 upcoming / 30 unknown; 55 live-service; 0 failed. Run against Haiku-enriched corpus (not qwen).
- [x] Re-bin items into ISO weeks by `published_at`; run per-ISO-week clustering. — **DONE 2026-05-12 in Phase 3c.0.5.** 55 new clusters created across 2026-W17 (4) / W18 (13) / W19 (38). 0 label failures. 4.5 min elapsed. 63 legacy `week_id='all'` rows from Phase 3b still in DB alongside — cleanup decision deferred.

### Phase 3c.0.5 — Anthropic Haiku migration for per-item enrichment

Inserted 2026-05-12 after the qwen2.5:7b quality ceiling forced an override of the "Ollama-only for per-item work" lock. See DECISIONS 2026-05-12 (later). Gates the staged Phase 3c.0 execution steps.

- [x] Design `app/services/anthropic.py` for Haiku-backed enrichment — signed off 2026-05-12 (trust-Haiku approach, swap-not-flag integration, side-by-side diff review).
- [x] Implement `anthropic.py` and swap `app/services/enrich.py` import. Uses `messages.parse(output_format=EnrichmentData)`, system-block `cache_control` marker (SYSTEM_PROMPT ~855 tokens, under Haiku's 4096-token min so caching no-ops harmlessly), wraps `anthropic.APIError` and `ValidationError` as `ValueError` so existing `_persist_failed` path is untouched.
- [x] Run a 10-item Haiku sample → docs/SAMPLE_HAIKU_2026-05-12.md. User signed off. Cost: ~$0.04.
- [x] Run the full 988-item backfill via Haiku. 39.5 min, 887 OK / 13 preserved / 0 failed. ~$3-4.
- [x] Execute the Phase 3c.0 staged steps now unblocked: ported `tag_game()` to anthropic.py + swapped import in `scripts/populate_games_dim.py`; ran populate_games_dim (189 games) + `run_cluster.py --per-week` (55 new clusters) + re-embed-all (900/900).
- [x] Document actual Haiku model version used, observed token costs in DECISIONS.md — see 2026-05-12 (later) addendum.

### Phase 3c.1 — Revisit dropped data with new tags  *(SHIPPED 2026-05-12)*

- [x] Hottest Games: restore platform + lifecycle chips (was trimmed pre-tagging). **Done — extended with 3-tab structure (All / Current / Upcoming) via CSS-only radio toggle. Rows show: rank · name · platform chips · `upcoming` chip (when applicable) · `live-service` chip (when applicable) · mention count. "existing" chip explicitly NOT rendered — default state. See DECISIONS 2026-05-12 (Phase 3c.1 shipped).**
- [x] Release Radar: structured release-date extraction from upcoming-tagged games. **Done — IGN scrape dead-end (React/Next.js rendered, only 1/5 sample games in static HTML); pivoted to corpus-context Haiku extraction. 10 of 28 upcoming-tagged games got initial dates; after broader retag, 50 of 184 games have dates. Card simplified to date + name only; future-date filter via `is_future_or_unknown()`. `Calendar →` link in card header points at IGN.**
- [x] Card 1 "This week in gaming" overview: re-evaluate (was dropped). **Done — restored. Card title shows `N stories · M sources`; body has top-5 genres + top-6 platforms mini-bars. Net-sentiment block dropped per user call (composite "+X · Mixed" not actionable).**
- [x] **Bonus / mid-session correction:** corpus-context retag of all 189 games via `scripts/retag_games_with_context.py`. Root cause: `tag_game()` passed only the game name; Haiku's Jan-2026 cutoff misclassified anything shipped after. Result: 129/189 updated, 50 games with dates (was 10). Crimson Desert + 8 others manually flipped on `live_service`. 5 case-fold duplicate pairs dedupedvia `scripts/dedupe_games_dim.py`; queries case-insensitive on `entities.games`. Dim now 184 rows.
- [ ] **Open hygiene (deferred):** numeral-variant duplicates (Diablo IV ↔ Diablo 4, Endfield ↔ Arknights: Endfield); series-as-game entries (Resident Evil / The Witcher / etc.) — currently lifecycle=null; could filter out of dim.

### Phase 3c.2 — Build Trends card (5 tabs)

- [ ] Games (existing + upcoming sub-blocks)
- [ ] Genres
- [ ] Platforms
- [ ] Live-service
- [ ] Events
- [ ] WoW only; top-N by mention-rate delta; click-to-drawer where applicable; clean empty-state for sparse tabs.

### Phase 3c.3 — Port Source Drawer + Exec-summary modal

- [ ] Source Drawer = right-side slide-in panel; opens on Biggest/MM/Risks/etc. row clicks; shows cluster synthesis paragraph + member items with outbound source links.
- [ ] Exec-summary modal = header CTA opens it; second Anthropic call produces 1-paragraph tldr of the synthesized report.

### Phase 3c.4 — Write Phase 3c synthesis prompt + service

- [ ] `app/services/synthesis.py` — Anthropic Opus 4.7 (`claude-opus-4-7`), prompt-cached system block.
- [ ] Schema covers 10 sections (Biggest, Hottest, MM, CS, Risks, Esports, Releases, Drama narrow, Watch, Trends) + exec-summary pass.
- [ ] First run on most-recent ISO week (no longer `week_id='all'`).
- [ ] Persist markdown + html to `weekly_reports`.

### Phase 3c.5 — Wire `/reports` template to real synthesized data

- [ ] Replace placeholder data in `app/routers/reports.py` with real `weekly_reports` rows.
- [ ] Apply all locked layout changes (drop Card 1, fold Studio Watch + Storefronts into MM, etc.).
- [ ] Smoke test end-to-end.

### Phase 3d — Archive + export

- [ ] Markdown → standalone HTML rendering with inlined CSS
- [ ] "Generate report" manual button
- [ ] Reports archive view — sibling of `/reports/{id}`
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
