# gaming-chatter — instructions for Claude

Personal gaming-news aggregator. Daily ingest from 15 news sites + 10 subreddits + 6 YouTube channels → Monday-morning weekly exec summary + live dashboard. Local-only, single user.

## Status

Latest work: **2026-06-10 (Phase 4 — automation wiring + per-run cost meter) — scheduler chained + retimed (still INERT), nightly full-corpus backfills killed, r/GamesIndustry removed, cost meter BUILT**. All verified live on `:8001`. The scheduler is now wired the way it should run but still INERT: daily cron moved **07:00 → 23:00 local (CST)** so the brief is ready in the morning, and the standalone `Mon 07:30` weekly cron was **removed** — the weekly now runs **chained inline at the end of each daily run** (`_previous_week_needs_synthesis()` → `run_weekly_extension(week_id=...)`, RLock re-entrant), so it always runs AFTER that night's ingest + self-heals a missed run (`app/main.py`, `app/services/jobs.py`). Decision: **no timezone migration** ("Option A") — kept UTC week definitions; 23:00 Central already briefs the just-closed UTC week. **Nightly full-corpus backfill warts fixed (cost-critical):** the daily's region backfill is scoped to items enriched *this run* (not the whole untagged corpus — was re-billing ~10,495 Haiku calls/night forever) and `enrich_after_fetch` re-enriches only items that just got bodies (`enrich_pending(item_ids=...)`, not the whole skipped backlog — was re-running Whisper over the entire YT backlog); full-corpus region pass is now manual-only (`scripts/backfill_region.py`), which also got a `""`-sentinel idempotency fix. Typical-night cost ≈ **$0.30 (~$120/yr)** WITH the fixes vs ~$1,500/yr WITHOUT. **r/GamesIndustry removed** (frozen `.rss`, 0 items since 2026-05-21; source id=24 + 13 items/raw/enrich + 5 run_log rows purged) — NOT `GamesIndustry.biz` (news, id=9, KEPT). Corpus: **12,710 items / 31 active sources** / 5 synthesized `weekly_reports` rows (W19–W23; W24 clusters-only). Earlier-today operator-console work (health band, earned `degraded` + floors, reconcile-on-boot, per-source recency grid, nav/styling, synthesis retry-cap) remains current. Reddit Jun 3–6 permanently lost (RSS rolloff); pre-3c.35 history (W17/W18) lost from the 3c.34 corpus wipe. The daily scheduler is still INERT (`SCHEDULER_ENABLED` off). **Per-run cost meter now BUILT** (`app/services/cost.py`): a thread-local, exclusive-semantics stack accumulator captures each Anthropic response's real `usage` (input/output + cache tokens), prices it per model (Haiku $1/$5, Sonnet $3/$15, Opus $4/$20 per MTok; cache read 0.1x, cache write 1.25x; unknown model → $0 + warning), and shows actual $ per `JobRun` on `/runs` (Cost column, tokens in tooltip; pre-meter rows render `—`). The inner-frame attribution keeps inline-nested weekly Opus tokens off the daily row (no double-count); `record()` is wired at all 9 Anthropic call sites; 3 nullable columns (`input_tokens`/`output_tokens`/`cost_usd`) added via the idempotent `_migrate_job_runs_columns` ALTER pattern in `app/db/init.py`. Verified: imports compile, migration idempotent, stack unit test passes. **One item remains: scheduler activation** (flip `SCHEDULER_ENABLED=1` + restart uvicorn) is the user's action — as is a one-off live `/runs` trigger to populate a real cost row (spends real API $). For phase-by-phase history and rationale, see `docs/SESSION_LOG.md`, `docs/DECISIONS.md`, and `CHANGELOG.md`.

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
