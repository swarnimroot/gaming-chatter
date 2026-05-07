# Session log

Append-only. Newest entries on top. Each entry: date, what was done, where we left off, blocked-on / next.

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
