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
| `enrichments` | item_id, tldr, entities (games/companies/people JSON), category, sentiment_score, sentiment_summary, embedding (BLOB), status (`ok`/`failed`/`skipped`), error |
| `clusters` | week_id, label, centroid (BLOB), member_item_ids, member_count, source_count, latest_published_at, score (Phase 3b) |
| `weekly_reports` | week_start, week_end, markdown_content, html_content, generated_at, status |
| `run_log` | job_type, source_id, started_at, completed_at, status, items_processed, error |

Two-stage dedup: **exact** (`external_id` or fingerprint hash) on ingest; **semantic** (embedding cosine) at clustering time.

## LLM pipeline

| Stage | Where | Cost | Trigger |
|---|---|---|---|
| Per-item enrichment (TL;DR, entities, category, sentiment, genres, platforms, event) | Anthropic Haiku 4.5 | ~$100–200/yr | After each daily ingest |
| Per-item embedding (768-dim) | Ollama `nomic-embed-text` local | $0 | After each daily ingest |
| Game tagging (lifecycle + live_service per unique game) | Anthropic Haiku 4.5 | ~$1 per backfill | After enrichment |
| Weekly clustering (cosine connected-components @ 0.85) | numpy in-process | $0 | Monday before report |
| Cluster labels | Anthropic Sonnet 4.6 (migrated 2026-05-13 from Ollama qwen2.5:7b) | ~$0.002/call (~$0.10 to relabel all 55 existing; ~$10/yr ongoing) | Same pass as clustering |
| Cluster ranking (Phase 3b) | numpy in-process: `source_count × member_count / (1 + days_since_latest)` | $0 | Same pass as clustering |
| Weekly synthesis (9 cards + exec_summary_paragraph) | Anthropic Opus 4.7, single structured `WeeklySynthesis` Pydantic call — **shipped 2026-05-13 Phase 3c.4** | ~$0.40/run | Monday 8am + on-demand (manual today; Phase 4 APScheduler) |
| Synthesis critic pass | Anthropic Opus 4.7 second call (drop-and-replace revision) — **shipped 2026-05-13 Phase 3c.4** | ~$0.50/run | Same run as synthesis |
| Exec-summary modal (1-paragraph TLDR) | Anthropic Haiku 4.5 on first open; **overwritten by Opus 4.7 once weekly synthesis has run** — shipped 2026-05-13 Phase 3c.3 / 3c.4 | ~$0.001/run on Haiku path | On modal open (lazy + cached to `weekly_reports.exec_summary_text`) |

**Measured volume — Phase 3c.0.5 Haiku backfill (988-item run, 2026-05-12):** 39.5 min wall-clock, ~2.4 s/item, 887 ok / 88 skipped / 13 preserved (Haiku returned an out-of-taxonomy category, prior valid row kept) / 0 hard failures. Estimated cost ~$3-4. Re-embed of all 900 ok rows via `nomic-embed-text` took 37 min (~2.5 s/item) — slower than Phase 2's 2.3 s/item, network/IO jitter. **Lock-override (2026-05-12 later):** per-item work moved off qwen2.5:7b after a 10-item sample exposed Reddit-handle leak into `entities.people` and a movie tagged with game genres; both are visibly fixed under Haiku. The `qwen2.5:7b` model remains resident in Ollama only because `label_cluster()` still calls it pending the Sonnet 4.6 migration in Phase 3c.4. See DECISIONS 2026-05-12 (later).

## Trend detection

- **WoW/MoM** = entity-mention counts week-over-week, month-over-month, by game/company/category
- **Hottest games** = entity-mention velocity (acceleration × signal score)
- **Biggest story** = top-scored cluster from Phase 3b ranking: `score = source_count × member_count / (1 + days_since_latest)`. Reddit upvote/comment weighting was rejected during 3b because Reddit RSS doesn't carry score data; reconsider only if PRAW reapproves
- **Watch-list** = entities with rising trajectory but low absolute volume late in the week
- The LLM **narrates the numbers**; it does not invent them

## UI

HTMX + Jinja, server-rendered. No JS build step.

| Route | Purpose |
|---|---|
| `/` | Dashboard (live) — latest exec summary on top + this-week-so-far cards + trend mini-charts + regenerate button |
| `/sources` | CRUD + per-source status (last fetched, error count, enabled toggle) |
| `/reports` | Per-ISO-week read-out (9-card grid as of Phase 3c.4 wiring; 3c.5 will restructure the template). Selects via `?week=2026-Wnn` |
| `/reports/drawer` | HTMX fragment endpoint — source drawer body, params: `kind={game\|genre\|platform\|event\|cluster}&value=&week=` (3c.3 + 3c.4) |
| `/reports/exec-summary` | HTMX fragment endpoint — exec-summary modal body, param: `week=` (3c.3) |
| `/runs` | Recent ingest / enrichment / report run log |

UI template is being built externally in **claude.ai/design** and will be ported to Jinja partials when delivered.

## External dependencies

- **scrapers-lib** at `..\scrapers-lib` (Python lib). Uses `tier1` modules: `rss` (news sites AND subreddits via Reddit's public RSS endpoint), `youtube` (incl. transcripts), `article` (justext). The `tier1.reddit` module (PRAW) is currently NOT used — see `DECISIONS.md` 2026-05-07 (PRAW API rejected). Tier2/Tier3 unused.
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
