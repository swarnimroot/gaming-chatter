# Decisions log

Append-only. Newest entries on top. Each entry: date, decision, rationale, alternatives rejected.

---

## 2026-05-07 — Reddit ingest = RSS via tier1.rss, not PRAW
**Decision:** Drop PRAW dependency for Reddit. Each subreddit's official RSS feed (`https://www.reddit.com/r/<sub>/.rss`) is consumed via scrapers-lib's existing `tier1.rss` module. All 11 subreddits use `type: rss` in `sources.yaml`.
**Why:** User's Reddit API application was rejected on 2026-05-07; PRAW unusable. Reddit's RSS endpoint is public, no auth, and reuses the same fetcher path as news sites. Architectural change is config-only.
**Consequences:**
- **Lose:** comment threads, upvote/comment counts, comment-level sentiment.
- **Keep:** post titles, post bodies (self-posts), URLs, authors, timestamps.
- **Cap:** Reddit serves max 25 items per subreddit RSS; daily ingest mitigates by sampling daily.
- "Community sentiment" report section becomes shallower (post-level, not comment-level).
- Reversible: flip `type: rss` back to `type: reddit` per subreddit if PRAW becomes available; scrapers-lib's `tier1.reddit` module still exists.
**Rejected:** Drop Reddit from v1 entirely (loses too much signal); HTML scraping (fragile + ToS gray area); anonymous JSON endpoint (rate-limited + may break without notice).

## 2026-05-07 — Source list cleanup: r/VideoGameNews → r/GamingNews; r/XboxSeriesX → r/Xbox
**Decision:** During Reddit RSS verification, two subreddits needed replacement.
- **r/VideoGameNews** returned HTTP 403 (private / quarantined / non-existent). Replaced with **r/GamingNews** — verified working, news-focused (latest post sample: "62% of hardcore players no longer buy full-price games").
- **r/XboxSeriesX** ingested fine but its top mod-pinned post is "This sub has moved to r/Xbox." Replaced with **r/Xbox** to track the active community.
**Why:** Empirically verified via scrapers-lib; user approved both swaps.

## 2026-05-06 — Build all 8 design docs as part of the design phase
**Decision:** Author CLAUDE.md, README, PRD, ARCHITECTURE, DECISIONS, TASKS, SESSION_LOG, OPEN_QUESTIONS now, before any code is written.
**Why:** Lock decisions in writing before they drift. Set up handoff for new Claude sessions so design choices aren't relitigated each time.
**Rejected:** Defer docs until first code lands.

## 2026-05-06 — Decision log = single `DECISIONS.md`
**Decision:** Single dated-entry file. Not per-decision ADR files in `decisions/`.
**Why:** Lower friction at personal scale. Easier to scan chronologically.
**Rejected:** Numbered ADR-style files — more ceremony than this scale needs.

## 2026-05-06 — Task tracking = `TASKS.md` checkboxes
**Decision:** Markdown file with phase headings and checkboxes.
**Rejected:** GitHub Issues / Linear / Trello — overkill for a personal local project.

## 2026-05-06 — UI template built externally in claude.ai/design
**Decision:** UI design handled in claude.ai/design and handed over later. Phase 0 uses minimal placeholder templates until then.
**Why:** User prefers to design the UI in a dedicated tool before porting to Jinja.

## 2026-05-06 — Cold start accepted; no historical backfill
**Decision:** Week 1 has no trend lines. Week 2 = first WoW. Week 5 = first MoM. Live with it.
**Why:** Backfilled data is partial (RSS feeds shallow, Pushshift effectively gone). Comparing "this week's full firehose" against "last month's incomplete sample" makes trends *worse*, not better.
**Rejected:** Light backfill (PRAW historical + RSS archive) and heavy backfill (paid history APIs).

## 2026-05-06 — Live dashboard model
**Decision:** UI always reflects current DB state. Tue–Sun shows accumulating data + last Monday's exec summary; Monday morning the new summary appears on top.
**Rejected:** Frozen dashboard (UI only updates Monday) — wastes the daily-ingest data mid-week.

## 2026-05-06 — Frontend = HTMX + Jinja (server-rendered)
**Decision:** No React, no SPA, no JS build toolchain.
**Why:** One language, one project, lower maintenance burden for personal scale.
**Rejected:** React SPA — polish not justified by a local-only audience of one.
**Note:** UI template being designed externally in claude.ai/design — will be ported to Jinja partials.

## 2026-05-06 — Storage = SQLite single file (WAL mode)
**Decision:** SQLite WAL mode. Embeddings stored as BLOBs; cosine similarity in numpy at query time.
**Why:** Personal-scale volume. One file = trivial backup. No vec extension needed (revisit only if ~100k+ embeddings).
**Rejected:** DuckDB (better OLAP but worse fit for source CRUD UI), Postgres (overkill), dedicated vector DB (overkill).

## 2026-05-06 — Process model = single Python monolith (Option A)
**Decision:** One FastAPI process embeds web server, scheduler (APScheduler), ingest, LLM clients, report rendering.
**Rejected:** Split worker + API (Option B; overkill); DuckDB + Streamlit (Option C; poor fit for admin UI).
**Consequence:** Long ingest tasks share the event loop — must run via thread pool to avoid UI lag.

## 2026-05-06 — LLM strategy = hybrid Ollama (local) + Anthropic API
**Decision:** Local 14B for per-item enrichment + embeddings + cluster labels; Anthropic API for weekly synthesis only.
**Why:** Cost-efficient ($1–5/mo target) while preserving synthesis quality where it matters most.
**Rejected:** All-local (synthesis quality too low); all-API (cost on 400 items/day).

## 2026-05-06 — Cadence = daily ingest, Monday weekly report + on-demand
**Decision:** Daily best-effort ingest with catch-up on missed runs at startup; weekly synthesis Monday morning; on-demand "regenerate" button always available.
**Why:** RSS feeds expose ~10 recent items — anything less than daily loses data permanently. Weekly report cadence matches the deliverable.
**Rejected:** Once-a-week ingest (data loss); hourly (no benefit at personal scale, more API and scrape load).

## 2026-05-06 — Sources = 15 news sites + 10 subreddits + 6 YouTube channels
**Decision:** ~31 curated sources at v1. User maintains list; light admin UI for add / remove / disable; status visible (last fetched, error count).
**Rejected:** Static config-only (no UI); 100+ firehose.

## 2026-05-06 — Local-only deployment, no auth
**Decision:** Runs on user's laptop, listens on `localhost`, no accounts. Laptop will be on 24×7 once operational.
**Rejected:** Cloud hosting; multi-user; shareable deployment.
