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
scrapers-lib tier1 (rss / reddit-PRAW / youtube / article-justext)
        │
        ▼
raw_items  ──▶  items (normalized + exact-match dedup)
                    │
                    ▼
            enrichments  (Ollama 14B → tldr, entities, category, sentiment, embedding)
                    │
                    ▼
            clusters     (numpy cosine similarity + Ollama cluster labels)
                    │
                    ▼
            weekly_reports  (Anthropic synthesis → Markdown → standalone HTML w/ inlined CSS)
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
| `enrichments` | item_id, tldr, entities (games/companies/people JSON), category, sentiment_score, sentiment_summary, embedding (BLOB) |
| `clusters` | week_id, label, centroid (BLOB), member_item_ids, member_count |
| `weekly_reports` | week_start, week_end, markdown_content, html_content, generated_at, status |
| `run_log` | job_type, source_id, started_at, completed_at, status, items_processed, error |

Two-stage dedup: **exact** (`external_id` or fingerprint hash) on ingest; **semantic** (embedding cosine) at clustering time.

## LLM pipeline

| Stage | Where | Cost | Trigger |
|---|---|---|---|
| Per-item enrichment (TL;DR, entities, category, sentiment, embedding) | Ollama 14B local | $0 | After each daily ingest |
| Weekly clustering + cluster labels | numpy + Ollama | $0 | Monday before report |
| Synthesis (exec summary sections) | Anthropic Sonnet | ~$0.05/run | Monday 8am + on-demand |

Volume: ~400 items/day × ~5–10s on Ollama 14B ≈ 30–60 min daily enrichment. Synthesis runs on already-distilled inputs.

## Trend detection

- **WoW/MoM** = entity-mention counts week-over-week, month-over-month, by game/company/category
- **Hottest games** = entity-mention velocity (acceleration × signal score)
- **Biggest story** = cluster with highest cross-source presence × Reddit signal × recency
- **Watch-list** = entities with rising trajectory but low absolute volume late in the week
- The LLM **narrates the numbers**; it does not invent them

## UI

HTMX + Jinja, server-rendered. No JS build step.

| Route | Purpose |
|---|---|
| `/` | Dashboard (live) — latest exec summary on top + this-week-so-far cards + trend mini-charts + regenerate button |
| `/sources` | CRUD + per-source status (last fetched, error count, enabled toggle) |
| `/reports` | Archive of past weekly reports, view + export each |
| `/runs` | Recent ingest / enrichment / report run log |

UI template is being built externally in **claude.ai/design** and will be ported to Jinja partials when delivered.

## External dependencies

- **scrapers-lib** at `..\scrapers-lib` (Python lib). Uses `tier1` modules: `rss`, `reddit` (PRAW — official Reddit API), `youtube` (incl. transcripts), `article` (justext). Tier2/Tier3 unused.
- **Ollama** at `http://localhost:11434`. Models: a 14B for enrichment + a small embedding model (e.g. `nomic-embed-text`).
- **Anthropic API** via SDK + env var. Used only in the weekly synthesis pass.

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
