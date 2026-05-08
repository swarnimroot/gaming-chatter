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
            enrichments  (Ollama qwen2.5:7b → tldr, entities, category, sentiment; nomic-embed-text → 768-dim embedding)
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
| `enrichments` | item_id, tldr, entities (games/companies/people JSON), category, sentiment_score, sentiment_summary, embedding (BLOB), status (`ok`/`failed`/`skipped`), error |
| `clusters` | week_id, label, centroid (BLOB), member_item_ids, member_count, source_count, latest_published_at, score (Phase 3b) |
| `weekly_reports` | week_start, week_end, markdown_content, html_content, generated_at, status |
| `run_log` | job_type, source_id, started_at, completed_at, status, items_processed, error |

Two-stage dedup: **exact** (`external_id` or fingerprint hash) on ingest; **semantic** (embedding cosine) at clustering time.

## LLM pipeline

| Stage | Where | Cost | Trigger |
|---|---|---|---|
| Per-item enrichment (TL;DR, entities, category, sentiment) | Ollama `qwen2.5:7b` local | $0 | After each daily ingest |
| Per-item embedding (768-dim) | Ollama `nomic-embed-text` local | $0 | After each daily ingest |
| Weekly clustering (cosine connected-components @ 0.85) + cluster labels | numpy + Ollama `qwen2.5:7b` | $0 | Monday before report |
| Cluster ranking (Phase 3b) | numpy in-process: `source_count × member_count / (1 + days_since_latest)` | $0 | Same pass as clustering |
| Synthesis (exec summary sections) | Anthropic (Sonnet 4.6 or Opus 4.7 — TBD Phase 3c) | ~$0.05–0.30/run | Monday 8am + on-demand |

Measured volume from Phase 2 backfill (988-item run, 2026-05-07): enrichment ~7s/item on `qwen2.5:7b`, embedding ~2.3s/item on `nomic-embed-text`. Phase split (enrich-all then embed-all) avoids per-item model swap. **Why 7B not 14B:** VRAM math against the 12GB RTX 5070 — 14B Q4 sits at the edge with model-swap thrash risk; 7B is comfortable and genuinely sufficient for structured extraction. Promotion to 14B reserved if synthesis quality regresses. See DECISIONS 2026-05-07.

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
| `/reports` | Archive of past weekly reports, view + export each |
| `/runs` | Recent ingest / enrichment / report run log |

UI template is being built externally in **claude.ai/design** and will be ported to Jinja partials when delivered.

## External dependencies

- **scrapers-lib** at `..\scrapers-lib` (Python lib). Uses `tier1` modules: `rss` (news sites AND subreddits via Reddit's public RSS endpoint), `youtube` (incl. transcripts), `article` (justext). The `tier1.reddit` module (PRAW) is currently NOT used — see `DECISIONS.md` 2026-05-07 (PRAW API rejected). Tier2/Tier3 unused.
- **Ollama** at `http://localhost:11434`. Models locked: `qwen2.5:7b` for per-item enrichment + cluster labels (chose 7B over 14B for VRAM headroom on the 12GB RTX 5070 — see DECISIONS 2026-05-07), `nomic-embed-text` for 768-dim embeddings. Both kept resident via `OLLAMA_KEEP_ALIVE=24h`.
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
