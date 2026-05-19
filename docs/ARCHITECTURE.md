# Architecture

## Process model

**Single Python process.** One FastAPI app embeds:

- HTTP server (Uvicorn) for the web UI + API
- APScheduler for daily ingest + Monday synthesis jobs, with catch-up on startup for missed runs while the laptop was off
- scrapers-lib as a library import for ingest
- httpx client to Ollama at `localhost:11434` for local LLM
- Anthropic SDK for the weekly synthesis pass

No worker queue. No separate scheduler service. No container.

## Data flow

```
sources (DB, seeded from sources.yaml)
        │
        ▼
scrapers-lib tier1 (rss [news sites + reddit feeds] / youtube / article-justext)
        │
        ▼
raw_items  ──▶  items (normalized + exact-match dedup)
                    │
                    ▼
            enrichments  (Anthropic Haiku 4.5 → tldr, entities, category, sentiment, genres[], platforms[], event; Ollama nomic-embed-text → 768-dim embedding)
                    │
                    ▼
            games dim    (Anthropic Haiku 4.5 → lifecycle + live_service per unique game)
                    │
                    ▼
            clusters     (numpy cosine similarity + Anthropic Sonnet 4.6 cluster labels — migrated 2026-05-13 Phase 3c.4)
                    │
                    ▼
            weekly_reports  (Anthropic Opus 4.7 synthesis + Opus 4.7 critic — shipped 2026-05-13 Phase 3c.4; synthesis_json column; Markdown + standalone-HTML export pending Phase 3c.6)
                    │
                    ▼
            dashboard / export-button / (later) push delivery
```

## Data model

| Table | Holds |
|---|---|
| `sources` | id, name, type (rss/reddit/youtube), url_or_handle, enabled, last_fetched_at, last_error, error_count |
| `raw_items` | source_id, external_id (dedup key), raw_payload (JSON blob), fetched_at |
| `items` | normalized: title, url, body_text, author, published_at, score, comment_count, fingerprint |
| `enrichments` | item_id, tldr, entities (games/companies/people JSON), category, sentiment_score, sentiment_summary, embedding (BLOB), genres (JSON list — Phase 3c.0), platforms (JSON list — Phase 3c.0), event (string — Phase 3c.0), region_focus (comma-separated subset of `{americas, europe, asia}` or NULL — Phase 3c.15), status (`ok`/`failed`/`skipped`), error |
| `clusters` | week_id, label, centroid (BLOB), member_item_ids, member_count, source_count, latest_published_at, score (Phase 3b) |
| `weekly_reports` | week_start, week_end, markdown_content, html_content, generated_at, status |
| `run_log` | job_type, source_id, started_at, completed_at, status, items_processed, error |
| `game_releases` (Phase 3c.18) | game_name_lc, source (`'pcgamer' \| 'ign'`), release_date (`YYYY-MM-DD / YYYY-MM / Qn-YYYY / YYYY / TBA / NULL`), raw_label (debug-only, currently NULL — dropped from Pydantic schema to fit Haiku's 8192 max_tokens), updated_at. Composite PK `(game_name_lc, source)`. Source-of-truth for game release dates; `games.release_date` + `games.lifecycle` are a synced cache derived from this table via `sync_games_dim(...)` |

Two-stage dedup: **exact** (`external_id` or fingerprint hash) on ingest; **semantic** (embedding cosine) at clustering time.

### Release-date resolver (Phase 3c.18)

`game_releases` is the canonical source. Resolution lives in `app/services/release_dates.py`:

- `SOURCE_PRIORITY = ['pcgamer', 'ign']` — first-with-row wins on conflict.
- `release_date_for(session, name)` — case-insensitive lookup, source-priority resolved.
- `derive_lifecycle(release_date, today)` — pure function: None/TBA → None; future/current → 'upcoming'; past → 'existing'. Reuses existing `is_future_or_unknown` for boundary semantics.
- `sync_games_dim(session, game_name_lc)` — writes resolved release_date + derived lifecycle into matching `games` row(s); idempotent (only writes when values actually changed).

The `games.release_date` and `games.lifecycle` columns are now a **synced cache**, not source-of-truth — refreshed by `scripts/refresh_pcgamer_releases.py` (Haiku one-shot parse on `https://www.pcgamer.com/games/new-pc-games-2026/`, ~$0.04/run, diff-driven row writes). Existing consumers (Release Radar card, `top_games_for_week`, lifecycle chips on Hottest games) read the cached columns directly and didn't need a refactor. The cleanup pass to JOIN through the resolver is a future Phase 4 nicety. **Key insight driving the reframe:** lifecycle ('existing' vs. 'upcoming') is a function of `release_date < today`, NOT a Haiku name-only guess — fixes prior corpus noise where *BioShock* (2007) and *Aliens: Fireteam Elite* (2021) were tagged 'upcoming' from name alone.

## LLM pipeline

| Stage | Where | Cost | Trigger |
|---|---|---|---|
| Per-item enrichment (TL;DR, entities, category, sentiment, genres, platforms, event, region_focus) | Anthropic Haiku 4.5 | ~$100–200/yr | After each daily ingest |
| Per-item embedding (768-dim) | Ollama `nomic-embed-text` local | $0 | After each daily ingest |
| Game tagging (lifecycle + live_service per unique game — **superseded by `game_releases` resolver for release_date + lifecycle as of Phase 3c.18; still used for live_service**) | Anthropic Haiku 4.5 | ~$1 per backfill | After enrichment |
| Release-date ingestion (pcgamer list page → `game_releases` table) | Anthropic Haiku 4.5 on full article body, `tag_pcgamer_releases()` — **shipped 2026-05-19 Phase 3c.18** | ~$0.04/run (weekly cadence ≈ ~$2/yr) | `scripts/refresh_pcgamer_releases.py` (manual today; Phase 4 APScheduler) |
| Weekly clustering (cosine connected-components @ 0.85) | numpy in-process | $0 | Monday before report |
| Cluster labels | Anthropic Sonnet 4.6 (migrated 2026-05-13 from Ollama qwen2.5:7b) | ~$0.002/call (~$0.10 to relabel all 55 existing; ~$10/yr ongoing) | Same pass as clustering |
| Cluster ranking (Phase 3b) | numpy in-process: `source_count × member_count / (1 + days_since_latest)` | $0 | Same pass as clustering |
| Weekly synthesis (9 cards + exec_summary_paragraph) | Anthropic Opus 4.7, single structured `WeeklySynthesis` Pydantic call — **shipped 2026-05-13 Phase 3c.4; watch[] schema tightened in Phase 3c.22 2026-05-19** | ~$0.40/run | Monday 8am + on-demand (manual today; Phase 4 APScheduler) |
| Synthesis critic pass | Anthropic Opus 4.7 second call (drop-and-replace revision) — **shipped 2026-05-13 Phase 3c.4** | ~$0.50/run | Same run as synthesis |
| Exec-summary modal (1-paragraph TLDR) | Anthropic Haiku 4.5 on first open; **overwritten by Opus 4.7 once weekly synthesis has run** — shipped 2026-05-13 Phase 3c.3 / 3c.4 | ~$0.001/run on Haiku path | On modal open (lazy + cached to `weekly_reports.exec_summary_text`) |

**Measured volume — Phase 3c.0.5 Haiku backfill (988-item run, 2026-05-12):** 39.5 min wall-clock, ~2.4 s/item, 887 ok / 88 skipped / 13 preserved (Haiku returned an out-of-taxonomy category, prior valid row kept) / 0 hard failures. Estimated cost ~$3-4. Re-embed of all 900 ok rows via `nomic-embed-text` took 37 min (~2.5 s/item) — slower than Phase 2's 2.3 s/item, network/IO jitter. **Lock-override (2026-05-12 later):** per-item work moved off qwen2.5:7b after a 10-item sample exposed Reddit-handle leak into `entities.people` and a movie tagged with game genres; both are visibly fixed under Haiku. The `qwen2.5:7b` model remains resident in Ollama only because `label_cluster()` still calls it pending the Sonnet 4.6 migration in Phase 3c.4. See DECISIONS 2026-05-12 (later).

## Trend detection

- **WoW/MoM** = entity-mention counts week-over-week, month-over-month, by game/company/category
- **Hottest games** = entity-mention velocity (acceleration × signal score)
- **Biggest story** = top-scored cluster from Phase 3b ranking: `score = source_count × member_count / (1 + days_since_latest)`. Reddit upvote/comment weighting was rejected during 3b because Reddit RSS doesn't carry score data; reconsider only if PRAW reapproves
- **Watch-list** = entities with rising trajectory but low absolute volume late in the week. As of Phase 3c.22 (2026-05-19) each `WatchItem` in `synthesis_json.watch[]` carries a **`category`** field locked to one of 5 values — `release | drama | business | community | event` (default `event` via Pydantic validator if Opus emits anything else). The `day` field is a forgiving normalizer over `{Mon, Tue, Wed, Thu, Fri, Sat, Sun, TBA}` — variants like `Mid-week` / `Weekend` / `Saturday` coerced rather than rejected. `WeeklySynthesis.watch` `max_length` is 7 (was 5 pre-3c.22) to give the critic room to prune. Older synthesis_json rows (W17 / W18 / W19) lack the `category` field; templates render them without chips via a backward-compat guard
- The LLM **narrates the numbers**; it does not invent them
- **Region focus** is content-inferred by Haiku during enrichment (`region_focus` ∈ subset of `{americas, europe, asia}` or NULL — Phase 3c.15). Not source-attributed — IGN can publish a story anchored in Japan. Cluster-level region is computed on-the-fly as the union of member-item tags (no column on `clusters`), mirroring the Phase 3c.12 section-overlay pattern

## UI

HTMX + Jinja, server-rendered. No JS build step.

| Route | Purpose |
|---|---|
| `/` | Weekly read-out (Monday exec summary; 9-card layout; ISO-week selector). Phase 3c.7 swapped from `/reports`. |
| `/stories` | Live stories table — items in last 7 days by default; HTMX search + section / region tabs + date-range picker (`?from=YYYY-MM-DD&to=YYYY-MM-DD`; back-compat `?week_id=` shim) (Phase 3c.7 + 3c.9 + 3c.11 + 3c.15 + 3c.17) |
| `/clusters` | Cluster cards by date range (default last 30d; `?from=…&to=…` or back-compat `?week_id=`; any-member-in-range semantic) with editorial-section overlay chips, region tabs, view toggle (cluster cards / flat list) (Phase 3c.7 + 3c.10–3c.12 + 3c.15 + 3c.17) |
| `/sentiment` | Per-category average sentiment view — `AVG(sentiment_score) + COUNT(*) GROUP BY enrichments.category` over a date-range window; default last 30d; tone bucketed at ±0.05; date-range picker reuses the Phase 3c.17 `parse_date_range` + flatpickr UI (Phase 3c.21) |
| `/sources` | Source list — name / type / status / last fetch / errors; HTMX live search; force-pull buttons. (CRUD via web forms pending Phase 4.) |
| `/about` | 5-stage visual pipeline infographic + glossary + stack panel (Phase 3c.8) |
| `/reports/drawer` | HTMX fragment — source drawer body, params: `kind={game\|genre\|platform\|event\|cluster\|category}&value=&week=` (or `&from=YYYY-MM-DD&to=YYYY-MM-DD` as window-mode alternative; `kind=category` + `from`/`to` shipped Phase 3c.23 to back the `/sentiment` row → drawer flow) (3c.3 + 3c.4 + 3c.23) |
| `/reports/exec-summary` | HTMX fragment — exec-summary modal body, param: `week=` (3c.3) |
| `/pipeline/run-full` | POST trigger — full pipeline (ingest → enrich → embed → cluster_window_incremental → synthesize); module-level lock prevents double-fire (Phase 3c.9) |
| `/static/{path:path}` | Static file serve — FastAPI route, NOT `app.mount(StaticFiles(...))` (Phase 3c.13 — Mount + `root_path` interaction breaks proxy-stripped paths) |
| `/runs` | **Deferred — Phase 4.** Will surface recent ingest / enrich / cluster / synthesis runs from the `run_log` table. |

UI shell ported from claude.ai/design 2026-05-11 (one-time delivery), maintained in-repo via `shell_base.html` + `_sidebar.html` + `chrome.py`. **`app/templates/_alert_banner.html`** (Phase 3c.19) is included inside `.gc-main` above `.gc-header` in both `shell_base.html` and `reports.html` (which doesn't extend `shell_base`); emits nothing when no sources have `error_count > 3` (threshold + count from `app/services/chrome.py:FAILING_SOURCE_ERROR_THRESHOLD` / `failing_sources_count(session)`). **`trend_bar(delta_pp, tone)` Jinja macro** in `reports.html` (Phase 3c.20) renders an inline zero-line-centered CSS-only mini-bar next to each WoW delta on the Trends card; width is `abs(delta_pp)` clamped at 12pp = 100% of half-width.

**Trends card bidirectional (Phase 3c.23).** `_merge_wow()` in `app/services/reports.py` returns `dict[str, list[dict]]` = `{"rising": [...limit], "declining": [...limit]}` — rising = positive `delta_pp` DESC, declining = negative `delta_pp` ASC, neutrals dropped from both. All 5 callers (`top_genres_wow` / `top_platforms_wow` / `top_games_wow` / `top_live_service_wow` / `top_events_wow`) pass through the new shape; `trends_for_week()` payload exposes a single combined `games` (lifecycle=None — the Hottest card still carries the current/upcoming split, different card / different lens). Each Trends tab pane in `reports.html` renders two subsections (Rising + Declining) with the existing `.gc-trend-subhead` divider between them; the `trend_rows(rows, kind)` macro itself stayed flat-list. **`/sentiment` row → drawer (Phase 3c.23).** Each row on `/sentiment` is a `<label class="gc-row-trigger" for="drawer-open" hx-get=".../reports/drawer?kind=category&value=X&from=Y&to=Z">` triggering the shared drawer; drawer state radios + overlay + panel duplicated from `reports.html` into the bottom of `sentiment.html`'s `main_content` block (must be siblings of each other for the CSS `:checked ~ .gc-drawer-panel` slide-in selector to work; future cleanup pass extracts to a shared `_drawer_panel.html` partial when a third page wants in).

## External dependencies

- **scrapers-lib** at `..\scrapers-lib` (Python lib, v1.7.0+). Uses `tier1` modules: `rss` (news sites AND subreddits via Reddit's public RSS endpoint), `youtube` (caption-API path with **audio-fallback via yt-dlp + faster-whisper `small.en`** as of scrapers-lib v1.7.0 / gaming-chatter Phase 3c.14 — opt in via `audio_fallback=True` kwarg, requires the `[youtube-audio]` optional install extra), `article` (justext). The `tier1.reddit` module (PRAW) is currently NOT used — see `DECISIONS.md` 2026-05-07 (PRAW API rejected). Tier2/Tier3 unused.
- **Ollama** at `http://localhost:11434`. Models resident: `nomic-embed-text` for 768-dim embeddings (primary local model post-2026-05-12). `qwen2.5:7b` was retained for `label_cluster()` pre-Phase-3c.4; it can be unloaded now since label generation migrated to Sonnet 4.6 (2026-05-13). `OLLAMA_KEEP_ALIVE=24h` for the embed model.
- **Anthropic API** via SDK + env var (loaded from local `.env` via python-dotenv). Used for per-item enrichment (Haiku 4.5), game tagging (Haiku 4.5), cluster labels (Sonnet 4.6 — shipped 2026-05-13), exec-summary modal TLDR (Haiku 4.5; Opus 4.7 once synthesis has run for the week), and weekly synthesis + critic (Opus 4.7 — shipped 2026-05-13). API key never committed — `.env` is gitignored.

## Alternatives considered & rejected

(Detailed rationale in `DECISIONS.md`. Summary here.)

| Alternative | Why not |
|---|---|
| Split worker + API processes | Overkill at 31-source / personal-laptop scale |
| DuckDB + Streamlit | Better OLAP, but Streamlit is poor at the source-management CRUD UI |
| React SPA frontend | Two projects + JS toolchain not justified for personal local tool |
| Postgres / Redis / Celery | Personal-local scale doesn't need them |
| All-API LLM (no local) | Cost on 400 items/day |
| All-local LLM (no API) | Synthesis quality ceiling too low |
| Backfill historical data | Partial-data results would worsen trends, not improve them |
