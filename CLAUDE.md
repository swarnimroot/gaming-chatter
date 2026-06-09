# gaming-chatter — instructions for Claude

Personal gaming-news aggregator. Daily ingest from 15 news sites + 10 subreddits + 6 YouTube channels → Monday-morning weekly exec summary + live dashboard. Local-only, single user.

## Status

Latest work: **2026-06-09 — W23 (week of Jun 1) full-pipeline run + Jun 3–6 backfill + read-out picker fix + mojibake repair**. W23 grew to 2,680 items / 208 clusters / synthesized (Opus 4.7 + critic); the home read-out (`/`) week picker now sources from SYNTHESIZED weeks only via new `readout_weeks()` in `app/services/reports.py` (in-progress W24 hidden until its synthesis runs — finally executes the long-deferred "flip picker `available_weeks` → `weekly_reports`" TODO); `app/templates/_report_grid.html` mojibake (`→ — · ●` + stray BOM) repaired at byte level. Corpus: **12,273 items / 11,843 Haiku-enriched ok (428 skipped, 1 failed) / 1,754 region-tagged / 184+187+189+166+208+18 W19/W20/W21/W22/W23/W24 clusters / 5 synthesized `weekly_reports` rows (W19–W23; W24 is clusters-only, not yet synthesized)**. Reddit Jun 3–6 permanently lost (RSS rolloff); pre-3c.35 history (W17/W18, pre-wipe) remains permanently lost from the 3c.34 corpus wipe. The daily scheduler is still INERT (`SCHEDULER_ENABLED` off) — activating Phase 4 is the next milestone. For phase-by-phase history and rationale, see `docs/SESSION_LOG.md`, `docs/DECISIONS.md`, and `CHANGELOG.md`.

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
