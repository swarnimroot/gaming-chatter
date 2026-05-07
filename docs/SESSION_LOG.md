# Session log

Append-only. Newest entries on top. Each entry: date, what was done, where we left off, blocked-on / next.

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
