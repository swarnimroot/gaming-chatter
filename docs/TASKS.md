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

### Phase 3c.2 — Build Trends card (5 tabs)  *(SHIPPED 2026-05-13)*

- [x] Games (existing + upcoming sub-blocks) — stacked Current/Upcoming sub-sections in the Games tab, each top-5 by mention-rate delta filtered via games-dim `lifecycle`.
- [x] Genres — top-5 by mention-rate delta over `enrichments.genres`.
- [x] Platforms — top-5 by mention-rate delta over `enrichments.platforms`.
- [x] Live-service — top-5 by mention-rate delta over games-dim where `live_service=1`.
- [x] Events — top-5 by mention-rate delta over `enrichments.event`. Empty-state row (commonly sparse).
- [x] WoW only; top-N by mention-rate delta; clean empty-state for sparse tabs. **Click-to-drawer deferred to Phase 3c.3** (Source Drawer port).

### Phase 3c.3 — Port Source Drawer + Exec-summary modal  *(SHIPPED 2026-05-13)*

- [x] Source Drawer = right-side slide-in panel; opens on row clicks. **Done — reframed to entity-drill (game / genre / platform / event) instead of the bundle's source-drill orientation. Trends + Releases + Hottest rows wired in 3c.3; Biggest / Momentum / Risks deferred to 3c.4 because their backing data is still placeholder. Drawer shows article cards (source pill + when + title + tldr + outbound link). Toggle is CSS-only via hidden radio + `<label for>` triggers (mirrors the existing `.gc-hot-tabs` / `.gc-trend-tabs` pattern); HTMX 2.0.3 fetches the `_drawer.html` fragment per row click. Backed by new `items_for_entity_in_week()` in `app/services/reports.py`.**
- [x] Exec-summary modal = header CTA opens it; second Anthropic call produces 1-paragraph tldr. **Done — three triggers wired (sidebar `gc-sb-cta`, header `gc-cta`, footer `gc-ghost-btn`) all open the same modal. Haiku 4.5 produces a 3-5 sentence factual paragraph on first open; result persists to new `weekly_reports.exec_summary_text / exec_summary_model / exec_summary_generated_at` columns so subsequent opens serve from cache. Service: `app/services/exec_summary.py:get_or_generate()`. Endpoint: `GET /reports/exec-summary?week=...`. Verified end-to-end on `:8001` with one cache-miss + one cache-hit round-trip; ~$0.001 spend.**

### Phase 3c.4 — Write Phase 3c synthesis prompt + service  *(SHIPPED 2026-05-13)*

- [x] `app/services/synthesis.py` — Anthropic Opus 4.7 (`claude-opus-4-7`), prompt-cached system block. **Done — single-call `WeeklySynthesis` Pydantic schema covering all 9 cards' synthesizable fields. System block carries `cache_control: ephemeral` marker (forward-compatible). Public `synthesize_week(session, week_id, force=False)` API.**
- [x] Schema covers ~10 sections (Biggest plural, Hottest reasons, MM, CS, Risks, Esports, Drama narrow, Release notes, Watch) + exec-summary pass. **Done — WeeklySynthesis has 10 fields including `exec_summary_paragraph`. Per-field `max_length` tuned as runaway-output guardrails (~2x the editorial intent); the editorial caps live in the prompt.**
- [x] Critic pass — second Opus 4.7 call. **Done — drop-and-replace critic returning the revised WeeklySynthesis. W19 first run: critic dropped 1 misplaced risks item (3 → 2), preserved every other section count.**
- [x] First run on most-recent ISO week (no longer `week_id='all'`). **Done — `python scripts/run_synthesis.py 2026-W19`, 57.7s, persisted as 7395-char JSON. ~$0.90 + ~$0.40 burned on a Pydantic-cap retry = ~$1.30 total this session.**
- [x] Persist to `weekly_reports.synthesis_json` (+ synthesis_model + synthesis_generated_at). **Done — three new columns via idempotent `_migrate_weekly_reports_columns`. Synthesis path also overwrites the 3c.3 `exec_summary_text` / `_model` / `_generated_at` with the Opus paragraph so the modal serves the corpus-aware version.**
- [x] Sonnet 4.6 `label_cluster()` migration (deferred from 3c.0.5 / 3c.2 / 3c.3). **Done — port mirrors `tag_game()` pattern. `cluster.py` import swapped. All 55 per-week clusters relabeled in 101s, ~$0.10. Labels visibly sharper.**
- [x] Drawer `kind=cluster` + Biggest / Risks / Drama / Watch row triggers. **Done — `items_for_entity_in_week()` extended with cluster branch (resolves cluster_id, fetches member_item_ids, joins to items+sources+enrichments). Drawer header swaps numeric id for the cluster label. Row triggers conditionally rendered as `<label>`s when `cluster_id` present; Biggest hero card uses one-line inline `onclick` since `<label>` can't wrap interactive form controls.**
- [x] Router wires synthesis output into existing template fields. **Done — `_load_synthesis` + `_apply_synthesis` overlay; mismatched-shape sections (community, MM, esports) stashed under `cards["*_synth"]` keys for Phase 3c.5.**

### Phase 3c.5 — Wire `/reports` template to real synthesized data

- [x] Replace placeholder data in `app/routers/reports.py` with real `weekly_reports` rows. — **Done 2026-05-13.** `_apply_synthesis` now writes community / market_momentum / esports as first-class card keys (no more `*_synth` stash). Placeholder dicts dropped: `momentum_raw`, `studios`, `platforms`, old esports/community shapes. Empty-corpus fallback rewired to `_empty_cards()` helper.
- [x] Apply all locked layout changes (drop Card 1, fold Studio Watch + Storefronts into MM, etc.). — **Done 2026-05-13.** Dropped: Card 1 / Card 8 / Card 9 / standalone headline / footer hint / header Grid+Comfortable+Theme toggles / sidebar "Generate exec summary" CTA / sidebar user-avatar / Risks `gc-risk-trend` chip. Reworked: Card 2 plural top-3 with rank badge + source pills (span-2 preserved); Card 4 MM row list with category chip; Card 6 CS narrative + heated/celebrating; Card 10 Esports row list. Sidebar nav trimmed to 4 real routes (`/reports` / `/` / `/clusters` / `/sources`). Sidebar bottom now corpus stats (items / clusters / sources).
- [x] Smoke test end-to-end. — **Done 2026-05-13.** Verified on `:8002`: W19 (200, full synthesis: 3 biggest / 5 MM / 1 heated + 2 celebrating / 2 risks / 0 esports → "No esports stories" honest empty / 1 drama / 5 watch); W18 + W17 200 with "Awaiting synthesis" empty-states on the 7 synthesis-dependent cards. Drawer + exec-summary fragment endpoints unchanged.

### Phase 3c.6 — Executive 1-pager + HTML / PDF export

- [x] Upgrade exec-summary modal body to a structured 1-pager (Haiku paragraph lead + Biggest top-3 + Market Momentum top-3 + two-col Risks top-2 / Community 1 heated + 1 celebrating). — **Done 2026-05-13.** Pulls from `synthesis_json` already in `weekly_reports`; no new LLM call. Modal degrades to Haiku-only + run-synthesis hint on weeks without synthesis; export buttons hidden in that state.
- [x] Standalone HTML rendering with inlined CSS. — **Done 2026-05-13.** New `app/services/export.py` + `_report_standalone.html` template. Full `<style>` block embeds the live `app.css` (~33KB) so the exported doc is self-contained. Includes `@media print` rules so direct Ctrl+P from the live `/reports` view also prints clean.
- [x] PDF export via browser print dialog (no new deps). — **Done 2026-05-13.** `format=pdf` serves the same standalone HTML inline with a `window.print()` script injected after `</body>`. Cached HTML stays canonical (one stored doc, two render modes).
- [x] `[Export HTML]` + `[Export PDF]` buttons inside the exec-summary modal footer. — **Done 2026-05-13.** Anchors open in new tab; modal stays accessible. Buttons hidden when synthesis hasn't run.
- [x] DB cache on `weekly_reports.html_content`. — **Done 2026-05-13.** Mirrors `exec_summary` cache pattern; `?force=1` refresh.

### Phase 3c.7 — UI consistency + live search

- [x] Routing swap: `/` is the weekly read-out (was `/reports`); raw items table moved to `/dashboard`. — **Done 2026-05-13.** Internal HTMX sub-endpoints (`/reports/exec-summary` / `/reports/drawer` / `/reports/export`) kept under their existing `/reports/*` namespace. `/reports` correctly 404s.
- [x] Re-skin Dashboard / Clusters / Sources to share the home page's design system. — **Done 2026-05-13.** New `app/templates/shell_base.html` + `_sidebar.html` shared shell. New `app/services/chrome.py` (`NAV_ITEMS_BASE` + `nav_items_for(active_id)`). Light re-skin: tables/lists kept (better for inspection than card grids), gc design tokens applied (Arial Nova, orange accent, gc-canvas/gc-border colors, source pills).
- [x] Live HTMX search on Dashboard / Clusters / Sources. — **Done 2026-05-13.** `<input class="gc-search-input" hx-get hx-trigger="keyup changed delay:300ms" hx-push-url="true">` in each header. Servers branch on `HX-Request` header → return list-only partial. URL stays in sync with the search term. Filters: dashboard = title/TLDR/source name (ILIKE), clusters = label, sources = name/URL.
- [x] Drawer `<a>`-nesting bug fix. — **Done 2026-05-13.** Each drawer item was rendering with two empty bordered rectangles per card because `source_pill` macro emits `<a href="#">` and we wrapped each item in `<a href="article-url">` — invalid HTML, browser auto-closes the outer `<a>` early. Fix: drawer renders the source pill inline as `<span class="gc-pill">` instead of calling the macro.

### Phase 3d — Archive (optional, deferred)

- [ ] Markdown rendering from synthesis_json → `weekly_reports.markdown_content`
- [ ] "Generate report" manual button (UI trigger for `scripts/run_synthesis.py`)
- [ ] Reports archive view — sibling of `/reports/{id}`

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
