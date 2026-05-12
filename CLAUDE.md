# gaming-chatter — instructions for Claude

Personal gaming-news aggregator. Daily ingest from 15 news sites + 10 subreddits + 6 YouTube channels → Monday-morning weekly exec summary + live dashboard. Local-only, single user.

## Status
Phases 0–3c.0.5 shipped (2026-05-12). Corpus state: 988 items ingested · **887 Haiku-enriched** + 13 preserved-qwen (Haiku returned out-of-taxonomy category; safety net kept prior row) + 88 skipped (body < 200 chars) · 900 freshly re-embedded via `nomic-embed-text` (768-dim) · **189 games** tagged via Haiku (131 existing / 28 upcoming / 30 unknown; 55 live-service) · **55 new per-ISO-week clusters** (W17:4 / W18:13 / W19:38), plus 63 legacy `week_id='all'` Phase 3b clusters still in DB (cleanup deferred). **claude.ai/design `/reports` port (2026-05-11)** + **walkthrough lock (2026-05-12)** intact: 13 cards → 9 + Trends 5-tab. **Phase 3c.0 schema** (genres/platforms/event columns + `games` dim table) + **Phase 3c.0.5 Haiku migration** complete: `app/services/anthropic.py` ships `enrich_item()` + `tag_game()` via `messages.parse(output_format=...)` with system-block `cache_control` marker (SYSTEM_PROMPT ~855 tokens, under Haiku's 4096-token caching min → no-ops harmlessly). One-line swap in `app/services/enrich.py`; `_persist_failed` path unchanged. 10-item sample → side-by-side md diff for user sign-off; 988-item backfill 39.5 min @ ~2.4 s/item; re-embed 37 min; games-dim populate 3.6 min; per-week clustering 4.5 min. **Total Phase 3c.0.5 spend: ~$5** (inside $500/yr ceiling). Embeddings remain on Ollama; `label_cluster()` still on qwen2.5:7b pending Sonnet 4.6 migration in Phase 3c.4. `.env` (gitignored) holds the Anthropic key, loaded via `python-dotenv` in `app/config.py`. **Next session (Phase 3c.1):** revisit dropped/trimmed data with the new tag dimensions — restore platform + lifecycle chips on Hottest, structured release-date extraction on Releases, re-evaluate Card 1 overview. Then 3c.2 (Trends 5-tab build), 3c.3 (Source Drawer + Exec-summary modal port), 3c.4 (Opus 4.7 synthesis + critic + Sonnet 4.6 cluster labels), 3c.5 (wire `/reports` to real data). See `docs/SESSION_LOG.md` 2026-05-12 (Phase 3c.0.5 entry) + `docs/DECISIONS.md` 2026-05-12 (later) + `docs/TASKS.md`.

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
