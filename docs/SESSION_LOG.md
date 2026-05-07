# Session log

Append-only. Newest entries on top. Each entry: date, what was done, where we left off, blocked-on / next.

---

## 2026-05-07 — Phase 1 manual ingest landed and verified end-to-end

**Done:**
- Inspected the scrapers-lib API surface to ground wrapper design (signatures + `RawMention` shape). Two findings drove the design:
  1. `tier1.youtube` doesn't accept `@handle` — only video IDs/URLs — and returns transcript chunks, not videos. Wrong shape for an "items" feed.
  2. `tier1.rss` against a YouTube channel's `feeds/videos.xml?channel_id=UC...` gives the same per-video metadata we get from news sites.
- Decision (logged in DECISIONS.md): **YouTube ingest goes through `tier1.rss`, transcript fetching is deferred to Phase 2 enrichment.** Built `resolve_youtube_feed()` that scrapes the channel page once for `channelId`, caches per-process.
- Wrote `app/services/scrapers.py` (wrapper + resolver) and `app/services/ingest.py` (dedup + persist + run logging). Dedup key is `(source_id, mention_id)`. Fingerprint = `md5(normalized_title)` — populated now, used for cross-source dedup later.
- Added routes: `POST /sources/{id}/ingest` (sync per-source) and `POST /sources/ingest-all` (BackgroundTasks). Sources table now shows `last_fetched`, `error_count`, `last_error`, per-row Ingest button + Ingest-all button. Dashboard shows latest 50 items.
- Real-network smoke test on all 30 sources: 29/30 worked first pass; Gameranx YouTube 404'd. Briefly went down a wrong path (changed UA suspecting bot detection); a probe agent identified the actual cause: the handle in `sources.yaml` was wrong. `@gameranx` doesn't exist; real handle is `@GameranxTV`. Reverted the UA change, fixed the YAML, patched the existing DB row in place, re-ingested → 15 videos, no error. **30/30 sources green.**
- Idempotency verified: re-ingest of IGN keeps items at 20, not 40.
- Item shape sanity (across 973 items): 0 empty titles, 0 empty URLs, 0 null `published_at`, 0 null body. 15 RSS items had null `author` (feeds vary — fine).
- Updated TASKS.md (all 8 Phase 1 boxes ticked), CHANGELOG.md (Phase 1 entry), DECISIONS.md (two new entries: YouTube path + Gameranx handle correction).

**State at end of session:**
- Phase 0 + Phase 1 complete. End-to-end manual ingest works against all 30 real sources. ~973 items in the local DB right now.
- "Working product" milestone is end of Phase 3, but the spine is in place: ingest → store → list. Phase 2 is enrichment (Ollama TL;DRs, embeddings).

**Next session should:**
1. Begin Phase 2 — Local LLM enrichment.
2. First move: Ollama HTTP client wrapper. Pick the 14B enrichment model + an embedding model (mxbai-embed-large or nomic-embed-text). Confirm both run on the user's RTX 5070 / 12GB VRAM (memory: prefer 14B for quality).
3. Per-item enrichment prompt → structured JSON: `tldr`, `entities` (games / companies / people), `category`, `sentiment_score`, `sentiment_summary`. Lock the prompt only after a sanity pass on real ingested items.
4. Embedding generation per item (BLOB into `enrichments.embedding`).
5. "Enrich pending items" trigger on the dashboard.
6. Dashboard renders TL;DR per item once enriched.
7. **Decision needed early in Phase 2:** how to handle YouTube transcript fetch. Options: (a) fetch + summarize at enrichment time using `tier1.youtube`; (b) summarize from title alone (cheap, low quality). Lean toward (a) — pull transcript on-demand, chunk-aggregate to a single body, then enrich.

**Open / blocked:**
- claude.ai/design UI template — still pending external delivery. Phase 2 enrichment work doesn't need it.

---

## 2026-05-07 — Phase 0 skeleton landed

**Done:**
- Decided SQLModel over raw SQLAlchemy (FastAPI-author lib, less boilerplate, no real downside at this scale).
- Decided hand-rolled `SQLModel.metadata.create_all` + WAL/foreign-keys pragmas on connect for schema bring-up — alembic deferred until the schema actually needs migrations.
- Wrote `pyproject.toml` with the locked stack (fastapi, uvicorn, jinja2, apscheduler, sqlmodel, httpx, anthropic, numpy, pyyaml). `scrapers-lib` referenced via `[tool.uv.sources]` editable path dep at `../scrapers-lib`; pip users will need to `pip install -e ../scrapers-lib` separately.
- Created the full `app/` package layout: `main.py`, `config.py`, `db/{models,session,init}.py`, `routers/{dashboard,sources}.py`, `utils/yaml_loader.py`, `templates/{base,dashboard,sources}.html`, `static/app.css`, plus `tests/`.
- Implemented all 7 SQLModel tables verbatim from ARCHITECTURE.md schema (sources, raw_items, items, enrichments, clusters, weekly_reports, run_log).
- Implemented idempotent `seed_sources()`: reads `sources.yaml`, upserts by `(type, url_or_handle)`. Runs in lifespan startup via `init_db()`.
- `GET /` placeholder dashboard + `GET /sources` read-only table view; base layout pulls htmx 2.0.3 from unpkg.
- Wrote `CHANGELOG.md` with the Phase 0 entry.
- All Python files compile cleanly under `python -m compileall`.

- Installed deps via pip: `pip install -e ../scrapers-lib` (editable) + `pip install -e .` (the project). `[tool.uv.sources]` is wired but currently inert because pip is in use; if we move to uv later, `uv sync` would replace both steps.
- Smoke-booted `uvicorn app.main:app` on port 8765. First boot revealed a bug: both routes 500'd with `TypeError: unhashable type: 'dict'` from Jinja's cache. Root cause: I'd written the old Starlette `TemplateResponse(name, {"request": request})` signature; modern Starlette (1.0+, shipped with FastAPI 0.115+) requires `TemplateResponse(request, name, context=None)`. Fixed both routers to the new signature. After fix, cold-start (DB deleted, re-seeded) returns 200 on `/` and `/sources`, with `/sources` rendering "Sources (30)" and all 7 tables present in `gaming_chatter.db`.
- Idempotency check passed earlier: a second boot left the `sources` count at 30, not 60.

**State at end of session:**
- 10 of 11 Phase 0 tasks done and verified end-to-end (skeleton boots, seeds, renders). Only deferred item: porting the claude.ai/design UI template (still awaiting external delivery — not blocking Phase 1).
- Deps installed in the system Python at `C:\Users\AW-testing\AppData\Local\Programs\Python\Python312` (no virtualenv). Fine for personal-local; revisit if it gets messy.

**Next session should:**
1. Begin Phase 1. First move: write thin scrapers-lib wrappers — `app/services/ingest.py` calling `tier1.rss` (covers both news sites and Reddit subreddits per 2026-05-07 decision) and `tier1.youtube`.
2. Add an "Ingest now" button (per-source + run-all) on `/sources`, wired to the wrappers; persist into `raw_items` and `items` with exact-match dedup; update `sources.last_fetched_at` and error counters.
3. **Verify the 6 YouTube channels** under `tier1.youtube` (still unverified from Phase 0 source-list lock-in).
4. Re-verify all 24 RSS feeds under real ingest conditions before scheduled runs come online in Phase 4.
5. Dashboard: list latest 50 raw items.

**Open / blocked:**
- claude.ai/design UI template — pending external delivery. Phase 1 ingest work can proceed against the placeholder layout.
- PRAW rejection — unchanged from prior session. See `OPEN_QUESTIONS.md`.

---

## 2026-05-07 — Reddit pivot to RSS (PRAW unavailable)

**Done:**
- User reported Reddit API application was rejected — PRAW unusable.
- Probed Reddit's per-subreddit RSS endpoint (`/r/<sub>/.rss`) via scrapers-lib's `tier1.rss`; confirmed it works without auth (25 entries per sub, hot view).
- Probed variants for r/VideoGameNews (returned 403); selected **r/GamingNews** as replacement (verified 25 entries, news-focused).
- Confirmed r/XboxSeriesX is mod-deprecated (top pinned post is "This sub has moved to r/Xbox") — switched to **r/Xbox**.
- Final 11-sub verification: all 11 working under scrapers-lib (~263 aggregate entries).
- Pivoted all 11 subreddit entries in `sources.yaml` from `type: reddit` → `type: rss` with Reddit RSS URLs.
- Logged the architectural pivot in `DECISIONS.md` (two new entries: pivot + source-list cleanup).
- Updated `ARCHITECTURE.md` data flow + external dependencies sections.
- Added PRAW-rejected note to `OPEN_QUESTIONS.md` under new "Blocked by external party" section.
- Softened "Community Sentiment" row in `PRD.md` (post-level, not comment-level).
- Pre-close audit: also updated `CLAUDE.md` (scrapers-lib usage block) and `TASKS.md` Phase 1 (wrapper modules + verification status) to remove staleness from the Reddit pivot. These are the docs the next session reads first.

**State at end of session:**
- 30 sources locked: 13 news RSS + 11 Reddit RSS + 6 YouTube. **24 RSS feeds verified live (~898 entries available right now)**; 6 YouTube channels still unverified.
- Reddit comment-thread + upvote/velocity signal lost until PRAW comes back. Reversible the moment it does — config-only switch.

**Next session should:**
1. (User to provide) UI template from claude.ai/design — when ready; not blocking Phase 0.
2. Begin Phase 0 from `TASKS.md` with placeholder layout.
3. **Phase 1: verify the 6 YouTube channels via scrapers-lib's `tier1.youtube` before locking source list.**
4. Phase 1: re-verify all 24 RSS feeds under real ingest conditions (network/health changes over time).
5. Append progress to this file at session end.

**Open / blocked:**
See `OPEN_QUESTIONS.md` (now includes PRAW rejection note).

---

## 2026-05-06 — Design session #1 (planning + docs scaffold)

**Done:**
- Surveyed `..\scrapers-lib`. Python lib. `tier1` covers RSS / Reddit (PRAW) / YouTube + transcripts / article extraction (justext); `core` provides rate limiting, caching, robots.txt, attribution, scheduler. Tier2/3 = retail/laptop scrapers, unused for this project.
- Walked through 6 clarifying questions: scope, LLM strategy, cadence, sources, output surfaces, cold-start.
- Brainstormed 3 architecture options (monolith / split-process / DuckDB+Streamlit) with tradeoffs.
- **Locked Option A** — single Python monolith + SQLite + HTMX + Ollama+Anthropic hybrid.
- Confirmed live-dashboard model and Monday-morning weekly report + on-demand regenerate.
- Committed to no historical backfill.
- Confirmed UI template will be built externally in claude.ai/design and handed over later.
- Initialized git repo (`git init`).
- Wrote all 8 design docs (this file + CLAUDE.md, README.md, PRD, ARCHITECTURE, DECISIONS, TASKS, OPEN_QUESTIONS).
- Created `.gitignore` for Python.
- Made initial commit: design-phase scaffold (no code yet).
- Created `sources.yaml` template; user then provided the actual list and it was populated: **13 RSS news sites + 11 subreddits + 6 YouTube channels = 30 sources**. RSS feed URLs are best-guess from standard CMS patterns; **Phase 1 smoke test must verify each** (1–3 likely need correction). Apparent duplicate of `r/Games` in the user's input was deduplicated. Counts differ slightly from PRD planning targets (15/10/6) — left PRD unchanged since the source list naturally evolves.
- Pre-flight verification of all 13 RSS feed URLs done in two passes:
  - **Pass 1 (WebFetch, generic UA):** 4 confirmed live, 1 redirect found (VentureBeat → GamesBeat), 8 inconclusive (403 / blocked by WAFs). WebFetch's UA was too restrictive to be authoritative.
  - **Pass 2 (scrapers-lib tier1.rss, in scrapers-lib's venv):** 11/13 worked on first try; 2 needed URL corrections found via alternates probe:
    - **Game Informer** `/feed` (404) → `/rss.xml` (✓ 50 entries).
    - **GamesBeat** `/feed` (403) → `/feed/` with trailing slash (✓ 10 entries).
  - **Final result: 13/13 RSS feeds confirmed working under scrapers-lib's actual fetcher** (~635 aggregate entries available). sources.yaml updated with the two URL fixes.
- Phase 1 smoke test should still re-verify before locking in (network conditions / source health change), but architectural type (`rss`) is confirmed correct for all 13 sites and the URL set is clean.
- Made follow-up commits. Session closed cleanly.

**Phase 0 start mode confirmed by user:** option (a) — begin skeleton next session with placeholder layout; port the claude.ai/design UI template in later as a swap-in.

**State at end of session:**
- Design phase complete. No code yet.
- All decisions captured in `DECISIONS.md`.
- Phase 0 ready to start. Can begin in parallel with UI template delivery using minimal placeholders.

**Next session should:**
1. (User to provide) UI template from claude.ai/design — when ready; not blocking Phase 0 skeleton.
2. Begin Phase 0 from `TASKS.md` with placeholder layout.
3. **Phase 1 first action: smoke-test every RSS feed URL in `sources.yaml`** before relying on them.
4. Append progress to this file at session end.

**Open / blocked:**
See `OPEN_QUESTIONS.md` for the running list.
