# gaming-chatter — instructions for Claude

Personal gaming-news aggregator. Daily ingest from 15 news sites + 10 subreddits + 6 YouTube channels → Monday-morning weekly exec summary + live dashboard. Local-only, single user.

## Status
Phases 0–3b shipped (2026-05-08). 988 items ingested · 908 ok-enriched + embedded (768-dim) · 63 clusters ranked by `source_count × member_count / (1 + days_since_latest)`. **claude.ai/design weekly read-out ported to `/reports` (2026-05-11)** with locked variants: grid + comfortable + light + orange `#D9682B`. **`/reports` redesign walkthrough complete (2026-05-12):** 13 cards → 9 (Card 1/8/9 dropped; Card 2 reworked to plural top-3; Card 6 Community Sentiment + Card 10 Esports honest-data reframes); sidebar/header/footer chrome simplified; **Trends RESTORED** via 5-tab plan (Games existing+upcoming / Genres / Platforms / Live-service / Events, WoW only). **Phase 3c.0 schema migration shipped (2026-05-12):** `games` dim table + `enrichments.{genres[], platforms[], event}` columns live in the DB. **Extended Ollama enrichment prompt working** in structured-output mode (JSON schema passed as `format`; plain `format:"json"` silently omitted the new fields). **Re-enrichment of 908 backlog ABORTED** mid-run: qwen2.5:7b quality ceiling exposed in a 10-item sample (Reddit-handle leak, movie tagged with game genres) + ~26s/item structured-output runtime ⇒ ~7-hour backfill ETA. **Code staged but BLOCKED on Haiku backfill:** `scripts/populate_games_dim.py` + `scripts/run_cluster.py --per-week` (replaces `week_id='all'`). **New architectural decision (2026-05-12, later):** per-item enrichment moves to **Anthropic Haiku 4.5**, cluster labels to **Anthropic Sonnet 4.6**, synthesis adds a critic-pass via a second **Opus 4.7** call — **overrides the "Ollama-only for per-item work" lock**. Embeddings stay on Ollama (`nomic-embed-text` 768-dim). Estimated total Anthropic spend ~$210–310/yr (inside $500/yr ceiling). Synthesis scope = 10 sections + exec-summary pass (up from PRD's 6). **Next session (Phase 3c.0.5):** design `app/services/anthropic.py` for Haiku-backed enrichment (sign-off required before the 988-item backfill), implement, 10-item sample, full backfill, then unblock the staged games-dim populate + per-week cluster runs. See `docs/SESSION_LOG.md` 2026-05-12 (both entries) + `docs/DECISIONS.md` 2026-05-12 (later) + `docs/TASKS.md` Phase 3c.0 / 3c.0.5 for the full lock list. Phase 3a + 3b + 3c-design-port + 3c-walkthrough + 3c.0-schema doc changes all intentionally uncommitted in the working tree.

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
