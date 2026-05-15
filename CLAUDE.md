# gaming-chatter — instructions for Claude

Personal gaming-news aggregator. Daily ingest from 15 news sites + 10 subreddits + 6 YouTube channels → Monday-morning weekly exec summary + live dashboard. Local-only, single user.

## Status
Phases 0–3c.13 shipped (2026-05-15). **Corpus state (post-2026-05-15 YT-only ingest):** 1597 items / 1412 Haiku-enriched + embedded (`nomic-embed-text`, 768-dim) / 184 games in dim / 247 per-ISO-week clusters (W17:4 / W18:13 / W19:115 / W20:115; 4 new YT items appended to existing clusters via `cluster_window_incremental`, no new clusters formed). All clusters have Sonnet-4.6 labels. `weekly_reports` has 4 rows, **all synthesized**: W17, W18, W19, W20 (W20 = current ISO week, force-re-synthesized 2026-05-14 14:23 UTC at 6090 chars after the YT-only ingest).

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

**Phase 3c.13 shipped 2026-05-15 (this session):**
- **Path-prefix support for Tailscale Funnel deploy.** Public URL is `https://laptop-aknevrti.taile7462c.ts.net/gaming-chatter`. Tailscale strips `/gaming-chatter` before forwarding to localhost; app uses `FastAPI(root_path=os.getenv("GC_ROOT_PATH", ""))` so generated URLs carry the prefix while routes still match against bare paths. `.env` adds `GC_ROOT_PATH=/gaming-chatter`; unset for local dev.
- **15-file URL refactor → `request.url_for(...)`.** Every hardcoded `/static/...`, nav link, HTMX `hx-get/post`, and internal `RedirectResponse(url=...)` replaced with `url_for(...)`. `chrome.py` `NAV_ITEMS_BASE` now stores route names; `nav_items_for(request, active_id)` resolves at request time. 5 routers gained `request: Request` param. Query strings preserved as Jinja suffix pattern.
- **Static files: Mount → Route.** `app.mount("/static", StaticFiles(...))` replaced with `@app.get("/static/{path:path}", name="static")` using `FileResponse` + path-traversal guard. Reason: Starlette's Mount + `root_path` interaction silently breaks for proxy-stripped paths — `Mount.matches()` sets `child_scope.root_path = outer + matched_path`, then `StaticFiles.get_path()` resolves the wrong directory for bare `/static/...` requests. **Forward rule (now in DECISIONS 2026-05-15 + a `DO NOT` comment in `main.py`): do not add `app.mount(...)` while `root_path` is set — use FastAPI routes instead.**
- **Orphan `app/templates/base.html` deleted** (legacy pre-3c.7 shell; not extended by anything).
- **Boot-time nav validator** in the lifespan hook: every `NAV_ITEMS_BASE.route` name must resolve via `app.url_path_for(...)` or app refuses to start with `RuntimeError`. Converts silent runtime 500s on rename-without-update into loud boot crashes.
- **One-off YouTube triage** (morning): RSS endpoint healed from yesterday's transient YouTube-side outage (all 6 channels return 200 now; not a deprecation). Ran a YouTube-only ingest (41 new items / 0 errors / per-source error counts cleared) + chain through enrich/embed/cluster_incremental/force-resynth W20. Spend: ~$0.38; cumulative project ~$10.28. **Per-video YT transcript-API path remains bot-gated** (~19 of 35 attempted transcripts hit `BlockedError(IpBlocked)`; enrich correctly falls back to title/body, contributing to ~10% Haiku taxonomy slippage on YT items: `'guide' / 'preview' / 'interview'`).

**Verified end-to-end on `:8001 --reload`:** local (no env var) and prefixed (`GC_ROOT_PATH=/gaming-chatter`) both 200 across all routes; static files serve at both bare and prefixed paths; path-traversal probe blocked; nav validator passes at boot and fails loudly on injected bad route name; public Tailscale Funnel URL renders fully styled.

**Next session (locked priority — YouTube audio-transcribe integration):**
scrapers-lib has shipped the yt-dlp + faster-whisper audio path (user confirmed end of 2026-05-15 session). Integration tasks: bump scrapers-lib version → swap transcript call in `app/services/ollama.py` from bot-gated transcript-API to new audio path (prefer `audio_fallback` mode if exposed, else explicit fallback to title/body) → spike-test on 2-3 of yesterday's IpBlocked video IDs → run full pipeline + force re-synth W20 → compare cluster outcomes + taxonomy slippage vs. today's title-only baseline → log decision in DECISIONS.md (model used, runtime hit, quality delta) → close OPEN_QUESTIONS transcript-deferred entry. Expected: ~$1-2 LLM + ~90-180 min wall-clock depending on whisper model. After that: Phase 4 (APScheduler daily ingest + Monday-morning synthesis cron + catch-up-on-startup + `/runs` UI + Source CRUD via web forms).

See `docs/SESSION_LOG.md` 2026-05-15 (Phase 3c.13 entry, primary handoff) + `docs/DECISIONS.md` 2026-05-15 (Mount-vs-root_path rationale + forward rule) + `docs/OPEN_QUESTIONS.md` 2026-05-14 (YouTube RSS resolved + transcript ready-to-implement).

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
