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

### Phase 3c.13 — Path-prefix support (Tailscale Funnel) + url_for refactor — **Done 2026-05-15**

- [x] `FastAPI(root_path=os.getenv("GC_ROOT_PATH", ""))` with `.env` setting `/gaming-chatter` for deploy; empty default for local dev. — **Done 2026-05-15.**
- [x] 15-file refactor: hardcoded URL strings → `request.url_for(...)` across templates, nav (`chrome.py`), HTMX endpoints, and internal `RedirectResponse` calls. — **Done 2026-05-15.**
- [x] Static files: `app.mount("/static", StaticFiles)` → `@app.get("/static/{path:path}", name="static")` route. Reason: Starlette Mount + `root_path` interaction breaks proxy-stripped paths. Forward rule documented in `DECISIONS.md` 2026-05-15. — **Done 2026-05-15.**
- [x] Orphan `app/templates/base.html` deleted. — **Done 2026-05-15.**
- [x] Boot-time nav fail-fast validator in lifespan hook. — **Done 2026-05-15.**

### Phase 3d — Archive (optional, deferred)

- [ ] Markdown rendering from synthesis_json → `weekly_reports.markdown_content`
- [ ] "Generate report" manual button (UI trigger for `scripts/run_synthesis.py`)
- [ ] Reports archive view — sibling of `/reports/{id}`

- [ ] **End of Phase 3 = working product.**

## Phase 3c.14 (shipped 2026-05-15) — YouTube audio-transcribe integration

scrapers-lib v1.7.0 shipped the yt-dlp + faster-whisper audio fallback; gaming-chatter wired it in. 3-line app change + 35-item backfill of 2026-05-14's YT enrichments + W20 force-resynth. Per-item enrichment quality improved (0 taxonomy slippage on the backfill set); cross-source cluster effect ~zero (vocab gap unchanged at 0.85 cosine). See DECISIONS.md 2026-05-15 (later) + SESSION_LOG.md 2026-05-15 (Phase 3c.14).

- [x] Bump `scrapers-lib` version in `pyproject.toml` — `"scrapers-lib>=1.7.0"`; `[youtube-audio]` extra installed imperatively (see DECISIONS rationale). — **Done 2026-05-15.**
- [x] Swap transcript call in `app/services/ollama.py:185` — added `audio_fallback=True` kwarg; wrapper return shape unchanged. — **Done 2026-05-15.**
- [x] Sanity-test on 3 yesterday's `IpBlocked` video IDs via `scripts/_spike_yt_audio.py` — 1 audio rescue + 2 caption successes; ~88 s first call (cold start + model download), ~1.3 s warm. — **Done 2026-05-15.**
- [x] Re-enrich title-only YT items from 2026-05-14 — 34/35 ok, 1 skipped (audio also empty); 6 audio-fallback firings; ~71 min wall-clock dominated by cold-start. — **Done 2026-05-15.**
- [x] Run full pipeline + force re-synth W20 — `cluster_window_incremental` returned 0 appended / 0 new / 330 orphaned (vocab gap holds); synth regenerated fresh, 6246 chars JSON. — **Done 2026-05-15.**
- [x] Document outcome in `docs/DECISIONS.md` (model = `small.en`, runtime profile, quality delta, honest caveats on attribution). — **Done 2026-05-15.**
- [x] Close out the `docs/OPEN_QUESTIONS.md` transcript-deferred entry — resolved; 3 new flag-only entries added (audio-fallback length cap, transcript quality floor, rerun_enrichment cp1252 print bug). — **Done 2026-05-15.**

## Phase 3c.15 (shipped 2026-05-19) — Region tagging

Content-inferred `region_focus` added to per-item enrichment + 4-tab filter (Global / Americas / Europe / Asia) on `/stories` and `/clusters`. Cluster region computed on-the-fly as union of member tags. 1405-item Haiku backfill completed (~$0.30). Distribution: 89 Americas / 66 Europe / 59 Asia / 1220 untagged across 1412 ok enrichments; 18 multi-region items. See DECISIONS.md 2026-05-19 + SESSION_LOG.md 2026-05-19.

- [x] SQLite ALTER `enrichments` — added `region_focus TEXT NULL` via `_migrate_enrichments_columns` in `app/db/init.py`. — **Done 2026-05-19.**
- [x] Updated `Enrichment` SQLModel in `app/db/models.py` to expose the new field. — **Done 2026-05-19.**
- [x] Extended Haiku enrichment prompt + JSON schema in `app/services/ollama.py` — `region_focus` added to `EnrichmentData` with `_filter_region_focus` validator; taxonomy locked to subset of `{americas, europe, asia}` or NULL; added to `_enrichment_json_schema` required list. — **Done 2026-05-19.**
- [x] `scripts/backfill_region.py` — idempotent Haiku one-shot via new `tag_region()` in `app/services/anthropic.py`. Ran on 1405 rows / 0 failures / 29:43 wall / ~$0.30 actual. — **Done 2026-05-19.**
- [x] `/stories` region filter in `app/routers/dashboard.py` — `?region=americas|europe|asia` query param, strict tag match via JOIN on `Enrichment.region_focus.ilike('%region%')`. Unknown values normalize to Global. — **Done 2026-05-19.**
- [x] `/clusters` region filter in `app/routers/clusters.py` + new `cluster_regions(session, cluster_ids) -> dict[int, set[str]]` helper in `app/services/sections.py`. — **Done 2026-05-19.**
- [x] New `_region_tabs.html` partial; included in `dashboard.html` + `clusters.html`; HTMX-driven, `hx-include="[name='q'],[name='section'],[name='week_id']"` chains with existing filters; `hx-push-url="true"` for shareable state. — **Done 2026-05-19.**
- [x] CSS `.gc-region-tabs` + `.gc-region-tab` appended to `app/static/app.css` (visually inherits `.gc-view-labels` pill row; accent on active). — **Done 2026-05-19.**
- [x] Empty-state copy `"No region-tagged items yet — coverage depends on your source mix"` wired into `_dashboard_list.html` and `_clusters_list.html`; shows only when `region` is set and list is empty (not on Global). — **Done 2026-05-19.**
- [x] Smoke-tested end-to-end on `:8001`: all 4 tabs return 200 on both `/stories` and `/clusters`; invalid `?region=` normalizes to Global; HTMX fragment swap returns correct partial; active-class set on correct tab; bare + `/gaming-chatter`-prefixed paths both work. Stories counts: 383 Global / 18 Americas / 6 Europe / 14 Asia (last-7-day window). Clusters: 247 Global / 33 Americas / 15 Europe / 10 Asia. — **Done 2026-05-19.**

## Phase 3c.16 (shipped 2026-05-19, later) — Region tabs on weekly read-out

Same 4-tab strip (Global / Americas / Europe / Asia) on `/`. Cluster-keyed cards (Biggest / Risks / Drama / Market Momentum / Community / Esports / Watch) filter via `cluster_regions()`. Non-cluster cards (Hottest games / Trends / Release Radar) carry a "Not region-tagged" chip — they aggregate by game/entity name, not cluster_id. Exec-summary CTA hidden on regional tabs (the prose is whole-corpus). No per-region Opus pass — filter-existing-`synthesis_json` only. See DECISIONS.md 2026-05-19 (later) + SESSION_LOG.md 2026-05-19 (3c.16).

- [x] `_REGION_ALLOWED` constant + `_filter_cards_by_region()` helper in `app/routers/reports.py`. Collects all cluster_ids referenced by `synthesis_json` in one pass, calls `cluster_regions()` once, walks each card list in place. — **Done 2026-05-19.**
- [x] `_build_week_payload(region="")` signature extended; `/` handler accepts `?region=`, normalizes garbage to Global, passes `region` / `region_active` / `exec_summary_hidden_for_region` to template. — **Done 2026-05-19.**
- [x] Inlined region-tabs `<nav>` strip in `reports.html` (NOT shared `_region_tabs.html` partial — readout has different hx-include needs + needs `hx-select="body"`). `#readout-body` wrapper around grid. — **Done 2026-05-19.**
- [x] "Not region-tagged" chips on Hottest games / Trends / Release Radar card headers when `region_active`. — **Done 2026-05-19.**
- [x] Exec-summary CTA → inline note on regional tabs: "Exec summary covers the whole-corpus week. Switch to Global to read it." — **Done 2026-05-19.**
- [x] CSS for `.gc-card-note`, `.gc-chip--muted`, `.gc-meta-tag--note` in `app/static/app.css`. — **Done 2026-05-19.**
- [x] Smoke-tested all 4 tabs return 200 on `/`; active-class set correctly; exec-summary CTA toggles (Global=1 file-text icon, regional=0); 3 "Not region-tagged" chips on each regional tab; card empty-state counts increase on regional tabs (Global: 5, Americas: 6, Asia: 7, Europe: 9). — **Done 2026-05-19.**

### Phase 3c.16 follow-ups (same session)

Real-world tab-clicking surfaced three bugs in the 3c.15/3c.16 ship + one UX gap. All fixed same session. See SESSION_LOG.md 2026-05-19 (Phase 3c.16 fixes) + commit `cb74157`.

- [x] **Cluster cards / List view toggle moved to right** via new `.gc-clusters-toolbar` flex row (`justify-content: space-between`) inside `#clusters-list`. Radios stay outside `#clusters-list` so HTMX swap preserves user's view choice; view-labels move inside the toolbar so HTMX swap re-renders their active-class. — **Done 2026-05-19.**
- [x] **Region tab active-class now updates after HTMX swap on `/stories` + `/clusters`.** Tabs were OUTSIDE the swap target; moved `_region_tabs.html` include INTO the swap target (top of `_dashboard_list.html` for stories; inside `.gc-clusters-toolbar` in `_clusters_list.html` for clusters). HTMX responses now re-render the tab strip with the correct active class. — **Done 2026-05-19.**
- [x] **Blank-screen fix on `/?region=…`** — `hx-target="body" hx-select="body" hx-swap="innerHTML"` was rendering empty in practice. Replaced with element-scoped swap: added `id="readout-main"` to `<div class="gc-main">` in `reports.html`; tab buttons changed to `hx-target="#readout-main" hx-select="#readout-main" hx-swap="outerHTML"`. Still re-renders header + grid, properly scoped. — **Done 2026-05-19.**
- [x] **Spinner indicator on readout region tabs** — small 14px rotating border-spinner (`.gc-region-spinner` + `.htmx-indicator`) appended to `<nav class="gc-region-tabs">`; each tab declares `hx-indicator=".gc-region-spinner"`. Standard HTMX indicator CSS rules + `@keyframes gc-spin` added to `app/static/app.css`. Rationale: 2–3 s server-side delay on the readout swap (`synthesis_json` parse + `cluster_regions()` + `sources_meta`) was making tab clicks feel unresponsive; `/stories` + `/clusters` swaps are fast and don't need it. Commit `cb74157`. — **Done 2026-05-19.**

### Phase 3c.17 — date-range picker (shipped 2026-05-19)

Airline-style date-range picker driven by **flatpickr 4.6.13 vendored** into `app/static/vendor/flatpickr/`. Replaces the `<select name="week_id">` ISO-week dropdown on `/stories` and `/clusters`. Back-compat `?week_id=` shim retained so `/reports` footer "see all" links keep working. Defaults: `/stories` = last 7d (matches prior 3c.9 behavior); `/clusters` = last 30d (approximates prior multi-week list density). Cluster filter semantic = "any member in range." See DECISIONS.md 2026-05-19 (Phase 3c.17) + SESSION_LOG.md 2026-05-19 (Phase 3c.17).

- [x] Vendor flatpickr 4.6.13 min files (~50KB JS + ~16KB CSS, MIT) into `app/static/vendor/flatpickr/`; load via `<link>` + `<script>` in `app/templates/shell_base.html` (lines 22 + 25). Zero npm / zero build step. — **Done 2026-05-19.**
- [x] `parse_date_range(from_str, to_str, week_id, default_days, now)` helper in `app/services/reports.py` — returns `{start, end, from_display, to_display}`; precedence `week_id` > `from`+`to` > default last-N-days; `end` exclusive (picked day + 1) so SQL `< end` covers picked day inclusively. — **Done 2026-05-19.**
- [x] `clusters_with_items_in_range(session, start, end) -> set[int]` in `app/services/sections.py` — SQLite `json_each` over `member_item_ids`; any-member-in-range semantic. — **Done 2026-05-19.**
- [x] `app/routers/dashboard.py` rewritten — `?from`/`?to` via `Query(alias="from")` + back-compat `?week_id=` shim; `_DEFAULT_WINDOW_DAYS = 7`. — **Done 2026-05-19.**
- [x] `app/routers/clusters.py` rewritten — same shape; `_DEFAULT_WINDOW_DAYS = 30`; cluster set = `clusters_with_items_in_range()` ∩ q/section/region filters. — **Done 2026-05-19.**
- [x] `_preset_links()` returning 4 server-rendered presets (Last 7d / Last 30d / This week / All time = 2020-01-01 → today). Avoids tz/DST drift between server + client. — **Done 2026-05-19.**
- [x] `dashboard.html` + `clusters.html` — dropped `<select name="week_id">`; added `.gc-date-range-group` block with `#date-range-display` visible input + hidden `name="from"` / `name="to"` inputs + 4 `<button class="gc-preset" data-from data-to>` presets. — **Done 2026-05-19.**
- [x] `_region_tabs.html` — `hx-include` flipped from `[name='week_id']` → `[name='from'],[name='to']`. — **Done 2026-05-19.**
- [x] `_clusters_list.html` — empty-state copy references the date range; "latest" / week_id chips always shown. — **Done 2026-05-19.**
- [x] Eyebrow on `/stories` + `/clusters` shows `{{ date_range.from_display }} → {{ date_range.to_display }}`. — **Done 2026-05-19.**
- [x] Inline init JS in `shell_base.html`'s `end_scripts` block (~30 lines) — flatpickr range mode on `#date-range-display` with `defaultDate=[fromInput.value, toInput.value]`; `onClose` writes hidden inputs + fires `gc:daterange-picked` event; hidden `#date-from` input listens via `hx-trigger="gc:daterange-picked from:#date-range-display"`. Page-safe (bails if `#date-range-display` or `flatpickr` missing). — **Done 2026-05-19.**
- [x] `app/static/app.css` appended ~50 lines: `.gc-date-range-group`, `.gc-date-range-input`, `.gc-preset` + flatpickr accent-color overrides matching `--gc-accent` and `--gc-accent-soft`. — **Done 2026-05-19.**
- [x] Smoke-tested live on `:8002`: `/stories` (default), `/stories?from=…&to=…`, `/clusters` (default 30d), `/clusters?from=…&to=…`, `/clusters?week_id=2026-W19` (back-compat shim → eyebrow "2026-05-04 → 2026-05-10", 122 clusters), `/clusters?region=americas&from=…&to=…` (region chain works); HTMX fragment branch returns correct partial; vendored static files serve 200; `/`, `/about`, `/sources` still 200. — **Done 2026-05-19.**

### Phase 3c.18 — authoritative release-date table (shipped 2026-05-19)

Reframe of the morning's pcgamer carry-over into a multi-source source-of-truth table. New `game_releases` SQL table + `app/services/release_dates.py` resolver + `scripts/refresh_pcgamer_releases.py` driver + `tag_pcgamer_releases()` Haiku helper. **Key insight:** lifecycle ('existing' vs. 'upcoming') is derived from `release_date < today`, not a Haiku name-only guess — fixes prior corpus noise (*BioShock*, *Aliens: Fireteam Elite* mistagged 'upcoming'). `games.release_date` + `games.lifecycle` demoted to synced cache. See DECISIONS.md 2026-05-19 (Phase 3c.18) + SESSION_LOG.md 2026-05-19 (Phase 3c.18).

- [x] New SQL table `game_releases` in `app/db/models.py:71-88` — composite PK `(game_name_lc, source)`, columns `release_date` / `raw_label` / `updated_at`. Multi-source schema from day one (`source` ∈ `'pcgamer' | 'ign'`). Auto-created via existing `SQLModel.metadata.create_all(engine)`; no migration script. — **Done 2026-05-19.**
- [x] New `tag_pcgamer_releases(body_text)` in `app/services/anthropic.py` — Haiku 4.5 + cached system prompt + `PCGamerReleaseList` Pydantic schema. `max_tokens=8192` (initial 4096 truncated mid-JSON for the 286-entry article). `raw_label` dropped from the Pydantic schema to fit; column kept in DB for future use. Stop-reason logging warns on truncation. — **Done 2026-05-19.**
- [x] New service `app/services/release_dates.py` (~160 lines): `SOURCE_PRIORITY = ['pcgamer', 'ign']`, `is_valid_release_date(s)`, `release_date_for(session, name)` (case-insensitive lookup, source-priority resolved), `derive_lifecycle(release_date, today)` pure function, `sync_games_dim(session, game_name_lc)` (idempotent — only writes when values actually changed). — **Done 2026-05-19.**
- [x] New `scripts/refresh_pcgamer_releases.py` (~170 lines), diff-driven. Fetches via `scrapers_lib.tier1.article.fetch_article` (trafilatura + Chrome TLS impersonation — WebFetch couldn't get past pcgamer's nav chrome). One Haiku call → INSERT new / UPDATE on release_date change / no-op otherwise. Calls `sync_games_dim` for every changed row. Args: `--dry-run`, `--url`, `--limit`; default URL `https://www.pcgamer.com/games/new-pc-games-2026/`. — **Done 2026-05-19.**
- [x] Smoke-run verification — Body 28,701 chars; Haiku 286 valid entries / 0 invalid / ~44 s wall (distribution 197 YYYY-MM-DD / 88 YYYY / 1 TBA). Run #1: 286 inserts on empty table. Run #2 immediately after: 0 new / 1 updated / 285 unchanged (Haiku run-to-run drift, not a bug). games dim sync: 23 of 184 games matched pcgamer (case-insensitive name); 18 needed updates. Sample correct lifecycle flips: *Mixtape* (2026-05-07) → existing; *Subnautica 2* (2026-05-14) → existing; *Forza Horizon 6* (2026-05-19, today) → upcoming; *007 First Light* (2026-05-27, future) → upcoming. — **Done 2026-05-19.**

### Phase 3c.19 — source-failure UI banner (shipped 2026-05-19)

Small warning banner inside `.gc-main`, above `.gc-header`, on every full-page route. Appears when ≥1 `sources.error_count > 3` (strict greater-than); quiet when all healthy. Built in a parallel-worktree agent run + cherry-picked onto master as `52218eb`. See DECISIONS.md 2026-05-19 (Phase 3c.19 / 3c.20 / 3c.21) + SESSION_LOG.md 2026-05-19 (Phase 3c.19 / 3c.20 / 3c.21).

- [x] NEW `app/templates/_alert_banner.html` — singular/plural grammar handled in-partial; emits nothing when count is 0. — **Done 2026-05-19.**
- [x] `app/services/chrome.py` — new `FAILING_SOURCE_ERROR_THRESHOLD = 3` constant + `failing_sources_count(session) -> int` helper. — **Done 2026-05-19.**
- [x] All 5 full-page routers (`reports.py` / `dashboard.py` / `clusters.py` / `sources.py` / `about.py`) pass the count into context; `about.py` newly gained a `Session` dependency. — **Done 2026-05-19.**
- [x] `app/templates/shell_base.html` + `app/templates/reports.html` include the banner partial (same include in both because `reports.html` doesn't extend `shell_base`). — **Done 2026-05-19.**
- [x] `app/static/app.css` appended `.gc-alert-banner*` block reusing existing `--gc-warning` / `--gc-warning-soft` / `--gc-border` tokens (no new design tokens). — **Done 2026-05-19.**
- [x] Smoke-tested live — banner hidden when all sources healthy; appears with correct count + link when `error_count` forced to 99 + 7 via SQL on two rows; disappears after restore; all routes (`/`, `/stories`, `/clusters`, `/sources`, `/about`) 200. — **Done 2026-05-19.**

### Phase 3c.20 — Trends mini-bar visualization (shipped 2026-05-19)

Inline CSS-only mini-bar next to each WoW delta number on the Trends card (`/`). Zero-line-centered; positive grows right (green), negative grows left (red), neutral (gray). Width clamped at 12pp = 100% of half-width. No JS, no chart lib. Built in a parallel-worktree agent run + cherry-picked onto master as `8974be9`. See DECISIONS.md 2026-05-19 (Phase 3c.19 / 3c.20 / 3c.21) + SESSION_LOG.md 2026-05-19 (Phase 3c.19 / 3c.20 / 3c.21).

- [x] `app/templates/reports.html` — new `trend_bar(delta_pp, tone)` macro invoked inside the existing `trend_rows` loop between name and delta. — **Done 2026-05-19.**
- [x] `app/static/app.css` — appended `.gc-trend-bar*` block at EOF using existing `--gc-success` / `--gc-danger` / `--gc-fg3` / `--gc-border-strong` tokens (no new design tokens). — **Done 2026-05-19.**
- [x] Smoke-tested live — 54 `.gc-trend-bar` class refs on `/` (Trends card 5 tabs × ~10–12 rows each); no Python errors. — **Done 2026-05-19.**

### Phase 3c.21 — sentiment view (shipped 2026-05-19)

New `/sentiment` page surfacing per-category average `sentiment_score` across enriched items in a chosen window. SQL: `AVG(sentiment_score) + COUNT(*) GROUP BY enrichments.category` joined to `items` for the date filter, sorted by avg DESC; tone bucketed at ±0.05. Default window = last 30 days. Date-range picker reuses the Phase 3c.17 pattern (`parse_date_range` + flatpickr UI inherited via `shell_base.html`). Built in a parallel-worktree agent run + cherry-picked onto master as `ad0541f`. See DECISIONS.md 2026-05-19 (Phase 3c.19 / 3c.20 / 3c.21) + SESSION_LOG.md 2026-05-19 (Phase 3c.19 / 3c.20 / 3c.21).

- [x] NEW `app/routers/sentiment.py` (138 LOC) — single `GET /sentiment` route, name `sentiment_view`. — **Done 2026-05-19.**
- [x] NEW `app/templates/sentiment.html` — extends `shell_base.html`; uses `<form>` + `gc:daterange-picked` listener for full-page nav (single-card page, no list to swap). — **Done 2026-05-19.**
- [x] `app/main.py` — registered router. — **Done 2026-05-19.**
- [x] `app/services/chrome.py` — added nav entry between Clusters and Sources; icon `activity`, route name `sentiment_view`. — **Done 2026-05-19.**
- [x] `app/static/app.css` — appended `.gc-sentiment-*` block at EOF. — **Done 2026-05-19.**
- [x] Smoke-tested live — `/sentiment` 200 on default + explicit `?from`/`?to` + back-compat `?week_id=` + garbage params (graceful fallback to default 30d); 67 `.gc-sentiment` class refs on the page; sentiment nav link present on `/stories` shell (2 refs — icon + label); `/sentiment` appears in `/openapi.json`. — **Done 2026-05-19.**

### Phase 3c.22 — watch-list polish (shipped 2026-05-19)

Category chips + day-specificity push on the Watch card on `/`. Adds a `category` field to `WatchItem` (Pydantic) coerced to one of `{release, drama, business, community, event}` (default `event`); tightens `day` to a forgiving normalizer over `{Mon, Tue, Wed, Thu, Fri, Sat, Sun, TBA}` with variants coerced. `WeeklySynthesis.watch` `max_length` 5 → 7. Section 9 of `_SYNTHESIS_SYSTEM_PROMPT` rewritten + critic rule 7 added. W20 re-synthed for verification (~$0.30); W17 / W18 / W19 left untouched for backward-compat. See DECISIONS.md 2026-05-19 (Phase 3c.22) + SESSION_LOG.md 2026-05-19 (Phase 3c.22).

- [x] `app/services/synthesis.py` — `category` field added to `WatchItem` with `field_validator` coercing to one of `{release, drama, business, community, event}`; default `event`. — **Done 2026-05-19.**
- [x] `app/services/synthesis.py` — `day` field tightened to a forgiving normalizer over `{Mon, Tue, Wed, Thu, Fri, Sat, Sun, TBA}`; variants (`Mid-week` / `Weekend` / `Saturday`) coerced rather than rejected. — **Done 2026-05-19.**
- [x] `app/services/synthesis.py` — `WeeklySynthesis.watch` `max_length` bumped 5 → 7 to give the critic room to prune. — **Done 2026-05-19.**
- [x] `app/services/synthesis.py` — section 9 of `_SYNTHESIS_SYSTEM_PROMPT` replaced with the 5 category definitions + day-specificity preference + mix-grounded-with-corpus-wide guidance. — **Done 2026-05-19.**
- [x] `app/services/synthesis.py` — critic rule 7 added to `_CRITIC_SYSTEM_PROMPT` validating watch[] groundedness, category enum, and day-specificity preference. — **Done 2026-05-19.**
- [x] `app/routers/reports.py` — `cards["watch"]` dict comprehension (~line 244) passes `category` through from synthesis_json into the card context. — **Done 2026-05-19.**
- [x] `app/templates/reports.html` — Watch-card loop renders a chip inline at the head of `.gc-row-item` when `w.category` is present; backward-compat preserved via `{% if w.category %}`. Both the cluster-linked `<label>` variant and the static `<div>` variant updated. — **Done 2026-05-19.**
- [x] `app/static/app.css` — `.gc-watch-chip` + 5 per-category modifiers appended at EOF; reuses existing tokens (`--gc-success` / `--gc-danger` / `--gc-accent` / `--gc-warning` / muted fallback). — **Done 2026-05-19.**
- [x] Re-synth W20 — `python scripts/run_synthesis.py 2026-W20 --force` succeeded in ~112 s; synthesis emitted 7 watch items, critic pruned to 6. Days: 2 Tue / 1 Fri / 3 TBA; Categories: 3 release / 2 business / 1 community; all items cluster-grounded. — **Done 2026-05-19.**
- [x] Smoke-tested live (`:8011`) — 6 `.gc-watch-chip` refs on `/`, distributed 3/0/2/1/0 across release/drama/business/community/event. Backward-compat verified: W17 / W18 / W19 still 200 with no chips rendered. — **Done 2026-05-19.**

### Phase 3c.23 — Trends bidirectional + sentiment-row drawer (shipped 2026-05-19)

Two user-requested polish items on top of the late-session 3c.21 / 3c.22 pass. (1) Trends card on `/` flipped from top-N-by-`delta_pp`-DESC to bidirectional (top-5 rising + top-5 declining per tab); Games tab collapsed to a single combined view (Hottest card still carries the current/upcoming split). (2) `/sentiment` rows became clickable, opening the same right-drawer pattern as `/`. No new CSS, no new LLM calls, no schema change. See DECISIONS.md 2026-05-19 (Phase 3c.23) + SESSION_LOG.md 2026-05-19 (Phase 3c.23).

- [x] `app/services/reports.py` — `_merge_wow()` return shape flipped from `list[dict]` (top-N by `delta_pp` DESC) to `dict[str, list[dict]]` = `{"rising": [...limit], "declining": [...limit]}`; rising = positive `delta_pp` DESC, declining = negative `delta_pp` ASC, neutrals dropped. All 5 callers (`top_genres_wow` / `top_platforms_wow` / `top_games_wow` / `top_live_service_wow` / `top_events_wow`) pass through the new shape. — **Done 2026-05-19.**
- [x] `app/services/reports.py` — `trends_for_week()` payload dropped `games_current` + `games_upcoming` keys, replaced with a single combined `games` (lifecycle=None). Hottest card retains the current/upcoming split (different card, different lens). — **Done 2026-05-19.**
- [x] `app/templates/reports.html` — Trends panes restructured: each tab renders two subsections (`<div class="gc-trend-subhead">Rising</div>` + list, then `<div class="gc-trend-subhead gc-trend-subhead--second">Declining</div>` + list). `trend_rows(rows, kind)` macro unchanged. Games tab dropped `tr.games_current` + `tr.games_upcoming` refs; uses single `tr.games`. — **Done 2026-05-19.**
- [x] `app/services/reports.py` — `_DRAWER_KINDS` set gains `category`. `items_for_entity_in_week()` signature gains optional `start: datetime | None` + `end: datetime | None` kwargs as an alternative window mode to `week_id`; both modes route to the same SQL filter on `items.published_at`. New `category` branch in the if-chain filters on `LOWER(TRIM(e.category)) = LOWER(:v)`. — **Done 2026-05-19.**
- [x] `app/routers/reports.py` — `_DRAWER_KIND_LABELS` gains `"category": "Category"`. `/reports/drawer` endpoint signature gains `?from=YYYY-MM-DD&to=YYYY-MM-DD` query params (with `from` aliased via `Query(alias="from")`); when both provided, parses to datetimes and treats `to` as inclusive (adds +1 day for exclusive end), passes `start`/`end` kwargs into `items_for_entity_in_week`. Error paths added for bad date strings and "neither week nor from/to". — **Done 2026-05-19.**
- [x] `app/templates/sentiment.html` — each row converted from `<div class="gc-sentiment-row">` to `<label class="gc-sentiment-row ... gc-row-trigger" for="drawer-open" hx-get=".../reports/drawer?kind=category&value=X&from=Y&to=Z" hx-target="#source-drawer-body">`. Drawer infrastructure (state radios + overlay + panel) duplicated from `reports.html` into the bottom of the `main_content` block (must be siblings for the `:checked ~ .gc-drawer-panel` slide-in selector to work). Modal radios NOT included (no exec-summary on `/sentiment`). — **Done 2026-05-19.**
- [x] No CSS additions — existing `.gc-trend-subhead` carries over from the old Current/Upcoming pattern; `.gc-row-trigger` handles hover/cursor; `.gc-sentiment-row`'s grid layout works on `<label>` elements identically. — **Done 2026-05-19.**
- [x] Smoke-tested live on `:8012` — routes 200 on `/`, `/sentiment`, `/reports/drawer?kind=category&value=industry&from=2026-05-12&to=2026-05-19`, `/reports/drawer?kind=cluster&value=262&week=2026-W20` (back-compat). 10 `.gc-trend-subhead` refs on `/` (5 tabs × 2 subsections). Trends games sample: 5 rising + 5 declining with `prior_count > current_count` on every declining row. Drawer `kind=category value=industry` returns 25 items (cap), 125 class refs total. — **Done 2026-05-19.**

### Phase 3c.24 — Region-tab spinner alignment + IGN as 2nd `game_releases` source + Release Radar dual-link (shipped 2026-05-20)

Three items in one session — one UI polish bug on `/`, one carry-over from 3c.18, one small UI ride-along on the second. Region-tab spinner on `/` was visually extruding past the pill; fixed by lifting the spinner out of the `<nav>` into a sibling wrapper. IGN release-date ingestion shipped as the second source in `game_releases`; pcgamer remains primary via the already-locked `SOURCE_PRIORITY`. Release Radar card on `/` exposes both calendar URLs as stacked ghost links. Spend ~$0.08 (IGN Haiku passes only). See DECISIONS.md 2026-05-20 (Phase 3c.24) + SESSION_LOG.md 2026-05-20 (Phase 3c.24).

- [x] `app/templates/reports.html` — wrapped region-tabs `<nav>` + spinner `<span>` in new `<div class="gc-region-tabs-row">`; spinner is now a sibling of the nav, not a child. — **Done 2026-05-20.**
- [x] `app/static/app.css` — added `.gc-region-tabs-row` rule (inline-flex, gap 10px, align-items center, carries the bottom margin); stripped `margin-bottom` from `.gc-region-tabs`; stripped `margin-left` + `vertical-align` + `align-self` from `.gc-region-spinner`. — **Done 2026-05-20.**
- [x] `app/services/anthropic.py` — new `IGN_RELEASES_SYSTEM_PROMPT` + `tag_ign_releases(body_text)` after `tag_pcgamer_releases`. Reuses existing `PCGamerReleaseList` schema unchanged. `max_tokens=8192`; cached system prompt. — **Done 2026-05-20.**
- [x] `scripts/refresh_ign_releases.py` (~220 lines) — mirrors `refresh_pcgamer_releases.py` structurally. `SOURCE="ign"`, `DEFAULT_URL="https://www.ign.com/upcoming/games"`. CLI args: `--url` / `--limit` / `--dry-run` / new `--keep-tba` (disables preprocessor). — **Done 2026-05-20.**
- [x] `_strip_tba_year_lines(body)` preprocessor in the new script — regex `^\s*TBA\s*[/ ]\s*\d{4}\s*$` matches IGN's `TBA/<year>` date lines + pops the preceding name line (consecutive-line layout). Smoke run: 953 stripped → 9,370-char body remaining → 299 parsed entries / 0 format errors. — **Done 2026-05-20.**
- [x] `app/db/models.py:74` `GameRelease` docstring updated `"current sources: 'pcgamer'. IGN deferred."` → `"current sources: 'pcgamer' (3c.18) + 'ign' (3c.24)."` — **Done 2026-05-20.**
- [x] `app/templates/reports.html:493` — Release Radar `card_header` action arg replaced with two stacked ghost-links wrapped in an inline `<div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">` — "PCGamer →" + "IGN →". No new CSS class. — **Done 2026-05-20.**
- [x] Dry-run + real-run verified — body 34,616 chars; 953 TBA stripped → 9,370 chars; Haiku parsed 299 valid entries / 0 invalid / ~46 s wall. 299 inserted into `game_releases`; **2 games dim rows synced** (sample: *Yoshi and the Mysterious Book* → 2026-05-21 → `lifecycle='upcoming'`). 29-game overlap with pcgamer; all dates agree on the May overlap. — **Done 2026-05-20.**
- [x] Release Radar dual-link verified live — server boot on `:8021` → GET `/` 200 → regex-extracted ghost-link labels returned `PCGamer →` + `IGN →` in order. — **Done 2026-05-20.**

### Phase 3c.33 (shipped 2026-05-21) — YT resolver bypass + synth Trends-shape fix + 2 new RSS sources

Investigation session triggered by an empty W21 dashboard. The empty dashboard was caused by a silent synthesis crash (Phase 3c.23 Trends reshape regression); investigating that surfaced a separate silent YT mislabeling bug — for 5/6 YT sources, the `@handle → channel_id` HTML resolver had been picking wrong-but-real channel IDs for weeks. Both fixed. 2 new RSS sources added (GamingBible at non-standard `/index.rss`, Game Rant at standard `/feed/`). Sets up a staged YT-verification test + corpus wipe planned for next session. Spend ~$0.35 (W21 Opus re-synth + ~6 free httpx probes). See SESSION_LOG.md 2026-05-21 + DECISIONS.md 2026-05-21 + CHANGELOG.md.

- [x] **YT resolver bypass** — verified the 6 canonical channel IDs via each Atom feed's `<title>` matching the publisher name; hardcoded full feed URLs in `sources.yaml` + DB (UPDATE rows 25-30 + clear error state). `resolve_youtube_feed`'s pass-through at `scrapers.py:32` short-circuits the regex path. No code change to scrapers.py. — **Done 2026-05-21.**
- [x] **Synth Trends-shape fix** in `app/services/synthesis.py:516-533` — adapt `_format_input_for_prompt` to the Phase 3c.23 `{rising:[...], declining:[...]}` per-tab shape + dropped `games_current`/`games_upcoming` split. Inline comment explains the 3c.23 reshape. — **Done 2026-05-21.**
- [x] **W21 synthesis re-run** via `scripts/run_synthesis.py 2026-W21 --force` after both fixes — row id=5 / model=claude-opus-4-7 / synthesis_json=8418 chars / exec_summary=964 chars. Real editorial output across Biggest / Market momentum / Risks / Community / Watch. — **Done 2026-05-21.**
- [x] **GamingBible + Game Rant RSS sources** added after TheGamer in `sources.yaml`; seeded into DB via `seed_sources()`. Total enabled: 26 RSS + 6 YT = 32. Header comment + counts updated. — **Done 2026-05-21.**

### Phase 3c.34 (shipped 2026-05-21) — Staged YT verification + Haiku pre-screen + corpus wipe/rebuild

4-step staged plan executed. **Step 2 rescoped mid-session:** the original description-only enrich-pass-rate test was discarded as uninformative once it surfaced that `_body_for_enrichment` has fetched YT transcripts at enrich-time since Phase 3c.14 (`fetch_youtube_transcript(audio_fallback=True)`) — the SESSION_LOG 3c.33 note "No YT transcript-fetching yet" was stale. A captions-only probe confirmed YouTube captions are 100% POT-gated; whisper-CPU audio fallback (local, free, ~60–90s/item) is the only working transcript path. A new Haiku pre-screen gate was added to skip non-gaming YT videos before paying whisper cost. Corpus wiped + rebuilt fresh. Spend ~$5–6. See DECISIONS.md 2026-05-21 (two entries) + SESSION_LOG.md 2026-05-21 (Phase 3c.34) + CHANGELOG.md.

- [x] **Step 1 — YT-only smoke ingest.** All 6 YT channels 200 / 0 errors (3c.33 fix holds); 90 post-fix YT items; ~96% above the 200-char body floor. — **Done 2026-05-21.**
- [x] **Step 2 (rescoped) — transcript path verified.** Captions-only probe 0/12 (POT-gated); audio-fallback whisper produces transcript-rich TLDRs. Original pass-rate gate discarded as uninformative. — **Done 2026-05-21.**
- [x] **NEW — Haiku YT pre-screen.** `prescreen_yt_relevance()` + `YTPrescreenData` in `app/services/anthropic.py`; `_body_for_enrichment` returns 3-tuple `(body, label, prescreen_skip_reason)`; `enrich_pending` persists `status='skipped'` reason `yt prescreen: not gaming-related (...)`. Production callers `rerun_enrichment.py` + `sample_haiku_enrichment.py` updated. Smoke-tested 7 items (6 pass / 1 reject). — **Done 2026-05-21.**
- [x] **Step 3 — full pipeline + synthesis cite-check.** Re-cluster W21 (151 clusters, 11 carry YT members); re-synth W21 → 9 referenced clusters, 2 with YT members. GREEN. — **Done 2026-05-21.**
- [x] **Step 4 — corpus wipe + rebuild.** Wiped 7,446 rows across 8 tables; kept `sources`/`games`/`game_releases`; reset per-source counters. Full rebuild ~3h19m. Fresh corpus: 1,023 items / 866 ok / 152 skipped / 5 failed / 50 W21 clusters / 1 W21 synthesis. Final verify: 10 referenced clusters, 4 with YT members (7 YT items reach Opus). GREEN. W17–W20 history permanently lost (accepted). — **Done 2026-05-21.**

### Phase 3c.34 follow-ups (resolved 2026-05-27 in Phase 3c.35)

- [x] **`category` enum too narrow.** Resolved 2026-05-27 — added `EnrichmentData._coerce_category` pre-validator in `app/services/ollama.py` mapping `preview`/`guide`/`gameplay` → `news` and `interview` → `industry`. Removed dead post-parse `_ALLOWED_CATEGORIES` checks in `ollama.py` + `anthropic.py`. 5 previously-failed items (IDs 15, 626, 630, 921, 979) re-enriched and flipped to `status='ok'`. See DECISIONS 2026-05-27 "Coerce out-of-taxonomy `category` values".
- [x] **No length cap on whisper audio transcription.** Resolved 2026-05-27 — **user explicitly rejected the gate** ("don't want to put any whisper duration gate, that would mean less data ingestion and possibility of missing some data"). Pre-screen remains the only filter in front of whisper. See DECISIONS 2026-05-27 "No whisper-duration cap on YT audio transcription".
- [x] **Phase 3c.35 backfill — scoped to W19–W21 (3 weeks).** Resolved 2026-05-27 — shipped via parallel `scripts/backfill_youtube.py` (Path A, ~430 LOC, 220 new YT items across both windows) + `scripts/backfill_news.py` (Path B, ~1,063 LOC, ~4,550 items combined). Final corpus 6,958 items / 6,695 ok / 1 failed. Reddit 25-item RSS cap remains an accepted gap. See DECISIONS 2026-05-27 "Path A + Path B shipped in parallel".

### Phase 3c.35 (shipped 2026-05-27) — W19–W21 backfill + dashboard precompute + Phase 4 inert scaffolding

Long cross-midnight session. Three threads landed together: W19–W21 backfill (corpus 1,023 → 6,958), two performance fixes (query-plan hints + cached dashboard payloads), and Phase 4 automation infrastructure shipped INERT (env-gated). Total spend ~$8–10. Final corpus: **6,958 items / 6,695 ok / 262 skipped / 1 failed / 1,044 region-tagged / 184+187+189 W19/W20/W21 clusters / 3 synthesized weekly_reports rows**. See CHANGELOG 2026-05-27 + SESSION_LOG 2026-05-26/27 + DECISIONS 2026-05-27 (6 entries).

- [x] **Category coercion validator.** `EnrichmentData._coerce_category` in `app/services/ollama.py` maps YT-flavor categories (`preview`/`guide`/`gameplay` → `news`, `interview` → `industry`); dead `_ALLOWED_CATEGORIES` post-parse checks removed in `ollama.py` + `anthropic.py`. — **Done 2026-05-27.**
- [x] **5 failed YT items re-enriched** (IDs 15, 626, 630, 921, 979) — all `status='ok'` post-fix. — **Done 2026-05-27.**
- [x] **Path A — `scripts/backfill_youtube.py`** (~430 LOC, yt-dlp channel enumeration → existing transcript+enrich pipeline). 6 YT channels × 2 windows. 86 (W19/W20) + 134 (W21) = 220 new YT items. — **Done 2026-05-27.**
- [x] **Path B — `scripts/backfill_news.py`** (~1,063 LOC, 8 sitemap-recipe strategies: `ign_year` / `gamespot_numbered` / `monthly_archive` / `monthly_parts` / `yearly_archive` / etc.). 15 news sites × 2 windows. 1,851 (W21) + ~2,700 (W19/W20) items; +854 Game Rant after mid-run network switch. — **Done 2026-05-27.**
- [x] **Re-cluster W19 + W20.** 184 / 187 clusters; Sonnet labels; 0 failures. — **Done 2026-05-27.**
- [x] **Synthesize W19 + W20** via Opus 4.7 + critic. — **Done 2026-05-27.**
- [x] **Re-synthesize W21** (now backed by ~4× more items than the post-wipe corpus). 189 clusters. — **Done 2026-05-27.**
- [x] **`scripts/backfill_region.py` on full corpus.** 1,044 items now carry non-null `region_focus`. — **Done 2026-05-27.**
- [x] **Template hygiene.** `app/templates/_report_grid.html` Biggest/Community/Watch cards now use `{% elif synth_ran %}` to differentiate "no data in this region" from "synthesis missing" — matches the existing pattern on the other 4 cards. — **Done 2026-05-27.**
- [x] **`scripts/run_cluster.py::_run_single` bug fix.** Was calling `cluster_window(week_id=...)` without start/end → silently clustered ENTIRE corpus under the passed week_id. Patched to derive bounds via `iso_week_bounds(week_id)`. — **Done 2026-05-27.**
- [x] **`scripts/run_synthesis.py` cp1252 stdout crash fix.** Added `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at script entry. Same pattern as `rerun_enrichment.py` got in Phase 3c.14. — **Done 2026-05-27.**
- [x] **Perf regression fix in `app/services/reports.py`.** Added `INDEXED BY ix_items_published_at` hints to force items-first joins (planner was choosing games-first at 7× corpus scale). Added stable `(delta_pp, name)` tiebreaker in `_merge_wow` to deterministic-ize hash-seed-dependent set unions. `_build_week_payload`: 25–33s → 2.5–3.4s (~10×). HTML byte-identical W19/W21; W20 has one tied-pair swap now deterministic. — **Done 2026-05-27.**
- [x] **Dashboard precompute.** New `app/services/dashboard.py` (extracted `_empty_cards` / `_load_synthesis` / `_apply_synthesis` / `_filter_cards_by_region` / `_build_week_payload` + new `load_cached_payload` / `save_cached_payload` / `compute_and_cache_payload`). `routers/reports.py` re-exports the underscore-prefixed names so `eval.py` keeps working. New column `weekly_reports.dashboard_payload_json TEXT` (additive ALTER + idempotent init_db migration). Synthesis hook calls `compute_and_cache_payload()` post-persist (non-fatal). Read path: cached payload (~6ms) → region filter → render. — **Done 2026-05-27.**
- [x] **`scripts/rebuild_dashboard_payloads.py`** (idempotent; `--force` overwrite). Ran once → 16,853 / 18,924 / 19,630 bytes cached for W19/W20/W21. — **Done 2026-05-27.**
- [x] **Result: /reports per-click 5–15s → 210–240ms (~20–25× speedup).** HTML byte-identical across all 12 page variants (3 weeks × 4 regions). — **Done 2026-05-27.**

### Phase 3c.35 follow-ups (open)

- [ ] **Style `/runs` page** — cosmetic; new `gc-run-*` classes are currently unstyled. (Task #9.)
- [ ] **Path B silent-fail sources.** Polygon recovered on its W21 run; **Game Informer / GamesBeat / GamesIndustry / Game Developer** still appear to need recipe patches in `scripts/backfill_news.py`'s `SOURCE_RECIPES`. Estimated 200–400 items of leakage. (Task #10.)
- [ ] **1 failed enrichment item (ID 2504)** — Kotaku "Player Pirates Subnautica 2 And Then Asks For Tech Support". Triage deferred.
- [ ] **`run_cluster.py` regression test.** Single-week bug fixed; consider a regression test someday.
- [ ] **Current-week (W22) /reports falls through to live compute.** Intentional, not blocking — no synthesis yet means no cached payload. Revisit only if the live path becomes visibly slow on the current week.

### Phase 3d — YT transcript-fetching *(resolved 2026-05-21 — already shipped in 3c.14)*

Phase 3c.34's verification found YT transcript-fetching has been live since Phase 3c.14: `_body_for_enrichment` calls `fetch_youtube_transcript(vid, audio_fallback=True)` at enrich-time and uses the transcript as the body passed to Haiku. No separate Phase 3d work was needed. The one remaining design-intent item (persist transcript to `items.body_text` at ingest-time so re-enriches are idempotent / don't re-pay whisper cost) is deferred — see DECISIONS.md 2026-05-21 "YT transcripts already wired".

- [x] Transcript fetch at enrich-time — already wired (3c.14).
- [ ] *(deferred)* Persist transcript to `body_text` at ingest-time for idempotency — see DECISIONS.md 2026-05-21.

## Phase 4 — Automation

**Phase 3c.35 (2026-05-27)** shipped the scheduler + orchestrator + `/runs` page INERT under `SCHEDULER_ENABLED` env gate. Activation is the user's call.

- [x] **APScheduler jobs: daily ingest, Monday synthesis.** Shipped 2026-05-27 (inert). `app/main.py` lifespan creates a `BackgroundScheduler` only when `SCHEDULER_ENABLED=1`. `CronTrigger(hour=7, minute=0)` daily + `CronTrigger(day_of_week='mon', hour=7, minute=30)` weekly chained after daily. `max_instances=1`, `coalesce=True`. Single `threading.RLock` in `app/services/jobs.py` serializes all paths. See DECISIONS 2026-05-27 "Phase 4 automation locked to single-process APScheduler".
- [x] **Catch-up logic on app startup.** Shipped 2026-05-27 (inert). Daily overdue if >24h since last `started_at` (or crashed mid-flight); weekly overdue if today is Mon/Tue/Wed AND >8 days since last weekly. Lock-miss persists `status='skipped'`.
- [x] **Run log table writes + UI (`/runs`).** Shipped 2026-05-27. New `JobRun` SQLModel → `job_runs` table (orchestrator-level; distinct from existing per-step `run_log`). New `app/routers/runs.py` + `app/templates/runs.html` — job history + "Run now" panel + HTMX expand-row for `details_json`. **Not added to sidebar nav** (direct URL only — deliberate scope cut to avoid `chrome.py` edit). Page is currently unstyled (Task #9 follow-up).
- [ ] **Activate scheduler.** Set `SCHEDULER_ENABLED=1` in `.env` + restart uvicorn. Inert today.
- [ ] **Source CRUD (add / edit / disable / remove) via web forms.** Not started.
- [ ] **Per-source health/error display.** Already partially covered by the Phase 3c.19 source-failure banner; full per-source health page deferred.

## Phase 5 — Polish

- [x] Trend mini-charts on dashboard (WoW/MoM) — **shipped 2026-05-19 (Phase 3c.20).** Inline CSS-only zero-line-centered mini-bars on Trends card; 12pp clamp.
- [x] Watch-list section in synthesis — **shipped 2026-05-19 (Phase 3c.22).** Category chips (`release | drama | business | community | event`) + day-specificity push in the Opus prompt; critic rule 7 validates groundedness + category enum + day specificity. W20 re-synthed; W17–W19 backward-compatible (no chips).
- [x] Sentiment view (per-category aggregate) — **shipped 2026-05-19 (Phase 3c.21).** `/sentiment` page with date-range filter; per-category `AVG(sentiment_score) + COUNT(*)`.
- [x] Source-failure alert (UI banner when error_count > N) — **shipped 2026-05-19 (Phase 3c.19).** Banner inside `.gc-main` when ≥1 `sources.error_count > 3`.
- [x] IGN as a second `game_releases` source — **shipped 2026-05-20 (Phase 3c.24).** `tag_ign_releases()` + `scripts/refresh_ign_releases.py` + TBA-line preprocessor. 299 IGN rows / 2 games dim syncs / 29-game pcgamer overlap (dates agree); priority unchanged (`SOURCE_PRIORITY = ["pcgamer", "ign"]`). Release Radar card now exposes both calendar URLs as stacked ghost links.
- [x] Eval harness for synthesis quality (sample → manual rate → tune prompts) — **shipped 2026-05-20 (Phase 3c.25).** In-app `/eval` page replaces the markdown skeletons (now under `evals/.archive/`). Per-card F/S/B radios + note input + Missing textarea + live aggregate footer, persisting to new `eval_card_scores` + `eval_meta` tables. Reuses `_report_grid.html` (extracted from `reports.html` in the same phase). See DECISIONS 2026-05-20 "in-app `/eval` form". Outstanding: actual scoring across W17–W20; analyze repeat failures after 2–3 weeks scored.

## Later (deferred)

- [ ] Push delivery — email
- [ ] Push delivery — Discord webhook
- [ ] Recipient distribution-list management
- [ ] Mobile-friendly layout pass
