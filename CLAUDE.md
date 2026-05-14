# gaming-chatter — instructions for Claude

Personal gaming-news aggregator. Daily ingest from 15 news sites + 10 subreddits + 6 YouTube channels → Monday-morning weekly exec summary + live dashboard. Local-only, single user.

## Status
Phases 0–3c.12 shipped (2026-05-14). **Corpus state (post-first-pipeline-run):** 1556 items / 1377 Haiku-enriched + embedded (`nomic-embed-text`, 768-dim) / 184 games in dim / 247 per-ISO-week clusters (W17:4 / W18:13 / W19:115 / W20:115) — legacy `week_id='all'` partition (63 rows) **deleted** in 3c.9 (backup at `data/legacy_clusters_backup_20260514_023447.json`). All clusters have Sonnet-4.6 labels. `weekly_reports` has 4 rows, **all synthesized**: W17, W18, W19, W20 (W20 = current ISO week; synthesis_json freshest, 6705 chars; W19 was force-re-synthed at 7897 chars after the pipeline rotated W19 cluster IDs).

**Prior phases (1-3c.7) are summarized in SESSION_LOG / DECISIONS** — short version: claude.ai/design port → Phase 3c.5 9-card layout → Phase 3c.6 exec-summary 1-pager modal + HTML/PDF export → Phase 3c.7 routing swap (`/` = weekly read-out, Dashboard/Clusters/Sources reskinned via `shell_base.html` + shared `_sidebar.html` + `chrome.py`, live HTMX search on each).

**Phase 3c.8 shipped 2026-05-13:** card reorder (risks → drama → esports → release → watch), mention-count badge on Biggest top-3 (derived from cluster member_item_ids), scrollable Release Radar (`gc-row-list--scrollable`), new `/about` route with 5-stage visual pipeline infographic + glossary + stack panel, sidebar bottom-truncation fix (padding + overflow-y), W17 + W18 synthesis backfill ($0.70 — populated weekly_reports rows 1 and 2).

**Phase 3c.9 → 3c.12 shipped 2026-05-14 (this session):**
- **Corpus-sidebar block dropped** from `_sidebar.html` + `reports.html`; `corpus_stats(session)` calls cleaned from all 5 routers (helper retained in `services/reports.py`).
- **Dashboard renamed to Stories** (nav label, page H1, eyebrow, page title). URL `/dashboard` → `/stories`. File `app/routers/dashboard.py` kept its name for blast-radius. Stories scoped to last 7 days (`Item.published_at >= now - timedelta(days=7)`), no row cap — replaces the misleading "988 items header / 50 in list" mismatch with "267 items · last 7 days".
- **`/clusters` default flipped** from legacy `week_id='all'` (deleted in this phase) to per-ISO-week multi-week list (54+ → 247 cards after pipeline added W19/W20). Explicit `?week_id=…` still works.
- **Home-page header chrome:** dropped "refreshed X ago" suffix. Two new chips: **Last pull** (`MAX(run_log.completed_at) WHERE job_type='ingest'`) and **Last workflow** (`MAX(weekly_reports.synthesis_generated_at)`). New `_format_ago` / `_parse_dt` / `_latest_ingest_dt` / `_latest_workflow_dt` helpers in `reports.py`. **Run pipeline** button (gc-cta--ghost) — enabled only when `now - last_pull > 6 days`; disabled state shows tooltip.
- **`POST /pipeline/run-full`** endpoint (new `app/routers/pipeline.py`, ~80 lines). Module-level `threading.Lock` guards against double-clicks (returns 409 + "busy" chip). 5-step BackgroundTasks worker: `ingest_all → enrich_pending → embed_pending → cluster_window_incremental(prev) → cluster_window_incremental(curr) → synthesize_week(curr, force=True)`. **Skip-synth** when curr week has no cluster changes (`items_appended_existing == 0 AND clusters_new_created == 0`).
- **`/clusters` CSS-only Cluster cards / List view toggle** (radio inputs, sibling-combinator visibility swap).
- **Editorial-section overlay on `/clusters`** — chips show every editorial card a cluster landed in on the weekly read-out (Biggest / Risks / Drama / MM / Community / Esports / Watch / Not surfaced). **Multi-chip per cluster** (Phase 3c.12 — Phase 3c.10/3c.11 used first-wins primary, was masking community memberships). Sorted by priority. Section filter on `/clusters?section=X` is inclusive — matches any cluster whose section list contains X.
- **Section + Week dropdowns on `/clusters` AND `/stories`** (HTMX-driven, `hx-include` to chain with the search input). Stories' section filter uses new `items_in_section(session, week_ids, section) -> Optional[set[int]]` helper in **new shared service `app/services/sections.py`** (extracted from clusters.py so both routers can use it).
- **"See all stories this week →"** footer link on 7 editorial home-page cards (Biggest / MM / Community / Risks / Drama / Esports / Watch). Links to `/clusters?week_id={active_week_key}` — no section pre-filter, so the user lands on the full per-week list with chips visible.
- **Incremental clustering** — new `cluster_window_incremental(start, end, week_id)` in `app/services/cluster.py` (~165 lines). Appends new items to existing cluster centroids when cosine ≥ 0.85; creates new clusters only for items that don't fit; labels only new clusters via Sonnet 4.6. **Preserves existing cluster IDs and labels** so synthesis_json references stay valid across pipeline runs. The destructive `cluster_window()` stays available for explicit-rebuild use cases (`scripts/run_cluster.py`, `POST /clusters/run`).
- **Favicon link** added to `reports.html` + `shell_base.html` (`<link rel="icon" type="image/svg+xml" href="/static/img/alienware-head-light.svg">`); the `/favicon.ico` 404 in the dev log is now gone.
- **First end-to-end pipeline run** completed at 22:37 (44.5 min total — embed step was unexpectedly slow at ~2.3 s/item via Ollama). 568 new items / 477 enriched / 477 embedded / W19 re-clustered 38 → 115 / W20 fresh 115 / W20 synthesized. Cost: **~$1.29**. W19 needed one-shot `--force` re-synth after pipeline because the destructive cluster_window invalidated W19's synthesis_json IDs (added cost: $0.35). Total session spend: ~$2.34; cumulative project: ~$9.90.

**Verified end-to-end on `:8001 --reload`** (clean restart, no stale-worker gotcha this time): all routes 200, multi-chip rendering visible on W20 (5 clusters with 2-3 chips each, including 4 newly-visible community chips), section/week dropdowns work in combination on both `/clusters` and `/stories`.

**Known issue (deferred — see OPEN_QUESTIONS 2026-05-14):** YouTube public RSS endpoint broken broadly — 404/500 across all 6 of our channels AND verified across unrelated control channels (Computerphile, Veritasium, Vsauce). Last successful YouTube ingest: 2026-05-07 16:20. Probable cause: YouTube infrastructure change / deprecation of public RSS. User chose to wait + revisit next week before deciding between RSS retry vs. YouTube Data API v3 migration. 6 channels remain `enabled=1` and will continue to fail every pipeline run (`errors=6`) until fixed.

**Next session (Phase 4 — actual finish line):** APScheduler for daily ingest + Monday-morning synthesis cron; catch-up on startup; `/runs` UI for the run_log table; Source CRUD via web forms. Also: YouTube fix (retry RSS, or migrate to Data API). Optional hygiene: taxonomy-drift audit; numeral / partial-name dedupe; the W17/W18 weeks had no Reddit-source clusters so community sentiment is intentionally narrative-only — revisit if Reddit ingest improves there.

See `docs/SESSION_LOG.md` 2026-05-14 (Phase 3c.9 → 3c.12 entry, primary handoff) + `docs/DECISIONS.md` 2026-05-14 (locked decisions) + `docs/OPEN_QUESTIONS.md` 2026-05-14 (YouTube RSS).

## Read first
- `docs/PRD.md` — what we're building and why
- `docs/ARCHITECTURE.md` — how it works
- `docs/DECISIONS.md` — locked choices + rationale
- `docs/TASKS.md` — phased build plan + status
- `docs/OPEN_QUESTIONS.md` — unresolved items
- `docs/SESSION_LOG.md` — prior-session handoff notes

## Hard architectural constraints — do not violate without explicit approval

- **Single Python process.** FastAPI + APScheduler + scrapers-lib + Ollama HTTP + Anthropic SDK in one app. Do not introduce a worker queue, separate scheduler service, Docker container, or split process model.
- **SQLite single-file storage.** No Postgres, no DuckDB, no Redis, no dedicated vector DB. Embeddings stored as BLOBs; cosine similarity in numpy.
- **HTMX + Jinja frontend.** No React/Vue/Svelte. No JavaScript build step. The UI template handed over from claude.ai/design will be ported into Jinja partials.
- **LLM split (updated 2026-05-12 — see DECISIONS.md "2026-05-12 (later)"):** **embeddings on Ollama** (`nomic-embed-text`, 768-dim); **per-item enrichment on Anthropic Haiku 4.5**; **cluster labels on Anthropic Sonnet 4.6**; **synthesis + critic pass on Anthropic Opus 4.7**. Do not introduce OpenAI, llama.cpp direct, or other providers. The pre-2026-05-12 lock said "Ollama local for per-item work, Anthropic API for synthesis only" — that lock was overridden after the qwen2.5:7b structured-output sample exposed concrete quality issues (Reddit-handle leak in entities, movie tagged with game genres) and 4–5× runtime regression vs Haiku.
- **scrapers-lib is an external Python dependency** at `..\scrapers-lib`. Use `tier1` modules: `rss` (handles BOTH news-site feeds AND Reddit subreddit feeds — see DECISIONS.md 2026-05-07), `youtube`, `article`. The `tier1.reddit` (PRAW) module is currently NOT used because the Reddit API application was rejected; see `docs/OPEN_QUESTIONS.md`. Do not modify scrapers-lib from this project.
- **Personal-local only.** No auth, no TLS, no cloud, no multi-user. Listens on `localhost`.

## Session conventions

- Major decisions → append a dated entry in `docs/DECISIONS.md`.
- End of every working session → append to `docs/SESSION_LOG.md`: what was done, where we left off, what's blocked.
- Update `docs/TASKS.md` checkboxes as work moves.
- New unknowns / deferred items → `docs/OPEN_QUESTIONS.md`.

## Out of scope (deferred to "Later")

- Push delivery (email/Discord) — after core phases ship
- Multi-user, accounts, sharing
- Backfill of historical data — accept cold start
- Mobile-specific UI

## scrapers-lib at a glance

Located at `C:\Users\AW-testing\Downloads\Workspace\scrapers-lib`. Python lib. `tier1` provides RSS (used for both news sites AND Reddit subreddits via Reddit's public RSS endpoint), Reddit-PRAW (currently unused — API rejected, may flip back if reapproved), YouTube + transcripts, generic article extraction (justext). `core` provides rate limiting, caching, robots.txt, attribution, scheduler. `tier2/tier3` (laptop/retail) are unused for this project.
