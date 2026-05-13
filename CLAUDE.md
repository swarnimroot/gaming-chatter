# gaming-chatter — instructions for Claude

Personal gaming-news aggregator. Daily ingest from 15 news sites + 10 subreddits + 6 YouTube channels → Monday-morning weekly exec summary + live dashboard. Local-only, single user.

## Status
Phases 0–3c.2 shipped (2026-05-13). Corpus state unchanged from Phase 3c.1: 988 items ingested · 887 Haiku-enriched + 13 preserved-qwen + 88 skipped · 900 embeddings (`nomic-embed-text`, 768-dim) · 184 games in dim (109 existing / 44 upcoming / 36 NULL-lifecycle · 49 live-service · 50 games with `release_date`) · 55 per-ISO-week clusters (W17:4 / W18:13 / W19:38) + 63 legacy `week_id='all'` (cleanup deferred). **Phase 3c.2 shipped 2026-05-13:** Card 5 "Trends" wired — 5-tab CSS-only radio structure (Games / Genres / Platforms / Live-service / Events). Games tab has stacked Current + Upcoming sub-sections. Math is **mention-rate delta in percentage points** — `(count_this / total_this - count_prev / total_prev) * 100`, sorted signed DESC, top-5 per tab. Falling-and-gone entries filtered. Service module gains `prev_week_id()`, `week_item_total()`, five `top_*_wow()` queries, and a single `trends_for_week()` aggregator. Legacy WoW/MoM toolbar dropped from card header. Phase 3c.2 spend: $0 (no API calls — pure SQL + template work). **Surfaced this session (not fixed):** out-of-taxonomy values in `enrichments.genres` (MMO / Indie/Roguelike / Survival-horror / Multi-platform) and `enrichments.platforms` (Multi-platform) despite the locked 12-genre and 6-platform taxonomies — Pydantic validators in `app/services/ollama.py` may not be running on the Haiku-enrichment path. **Next session (Phase 3c.3):** port Source Drawer (right-side slide-in for cluster synthesis) + Exec-summary modal (1-paragraph tldr via second Anthropic call) from `.tmp_design_bundle/`. Then 3c.4 (Opus 4.7 synthesis + critic + Sonnet 4.6 cluster labels), 3c.5 (wire remaining cards to real synthesized data). Optional hygiene: taxonomy-drift audit, numeral/partial-name dedupe (Diablo IV ↔ Diablo 4), series-as-game cleanup. See `docs/SESSION_LOG.md` 2026-05-13 (Phase 3c.2 entry) + `docs/DECISIONS.md` 2026-05-13 (Phase 3c.2 shipped) + `docs/TASKS.md`.

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
