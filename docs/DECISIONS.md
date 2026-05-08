# Decisions log

Append-only. Newest entries on top. Each entry: date, decision, rationale, alternatives rejected.

---

## 2026-05-07 — Phase 2.5: exclude Reddit URLs from article fetch; quality bar reframed to ≥40% of 173
**Decision:** `app/services/article_fetch.py` skips any URL whose host ends in `reddit.com` (alongside existing exclusion of `source.type='youtube'` items). The Phase 2.5 closing quality bar was reframed from "≥80% of the 173 skipped items flip to ok" (set in SESSION_LOG before the skipped-set composition was known) to "≥40% of 173" — corresponding to ~74% of the addressable (non-Reddit, non-YouTube) subset.
**Why:** Smoke-testing `tier1.article` (trafilatura) against Reddit link-post URLs returned empty bodies — Reddit link-post pages have no extractable article body, they're redirect-pointers. 72 of the 173 skipped items (42%) were Reddit URLs. The 80% bar was structurally unmeetable; even perfect recovery on the 95 non-Reddit items only reaches 55% of 173. Keeping the bar at 80% would have forced a false "Phase 2.5 failed" conclusion despite the addressable subset recovering essentially completely. The original 2026-05-07 `ENRICH_BODY_CHAR_MIN=200` decision already noted that Reddit link-posts are duplicates of articles we scrape from news feeds, so skipping them in Phase 2.5 is consistent — not a new accepted loss.
**Outcome:** 94/95 addressable items recovered (98.9%); 94/173 of all skipped (54.3%). 1 fetch errored (transient HTTP), 1 re-enrichment failed (model returned non-conforming JSON on a thin-content list-article — Forza Horizon 6 car list). Corpus coverage 82.5% → 91.9%.
**Rejected:** (a) Build a Reddit-link-post resolver (fetch `URL.json`, follow `data.children[0].data.url` to the external article, then trafilatura that) — would recover ~50–60 of the 72 Reddit items; deferred as out-of-scope for the planned remediation pass. Reconsider in Phase 3 only if Reddit-link-post coverage gaps materially weaken cluster cross-referencing. (b) Lower `ENRICH_BODY_CHAR_MIN` and accept tiny-body enrichments — same dashboard-pollution argument as before.

## 2026-05-07 — Phase 2.5 (article body-fetch) escalated from deferred to must-do
**Decision:** Phase 2.5 — using `scrapers_lib.tier1.article` to fetch article bodies for items that skipped enrichment due to short body — is no longer deferred. It runs **before Phase 3** (clustering + synthesis).
**Why:** Phase 2's full-batch run skipped 173/988 items (17.5%) at the 200-char threshold. Spot-checking the skipped set showed it is *not* dominated by Reddit link-posts as originally assumed in the 2026-05-07 `ENRICH_BODY_CHAR_MIN` decision — news-site RSS feeds (PC Gamer, Kotaku, Game Developer, others) also produce 100–200-char teasers and skip. That is real corpus loss across both source types. Phase 3 clustering on a corpus missing 17.5% of items, including news-site coverage, would underweight stories that don't happen to land on a long-form feed.
**Rejected:** (a) Lower `ENRICH_BODY_CHAR_MIN` and accept noisy meta-TLDRs — pollutes the dashboard for the same downstream cluster quality; (b) Skip Phase 2.5 and rely on whatever full-text feeds we have — biases coverage toward feed-rich sources; (c) Add `tier1.article` to the *ingest* path now instead of a remediation pass — couples ingest to scraper rate limits and slows cold-start; defer that decision until Phase 2.5 evaluates real recovery rate.

## 2026-05-07 — ollama.py schema fixes: add 'review' category + dict→list validator on Entities
**Decision:** `_ALLOWED_CATEGORIES` extended with `'review'`. The `Entities` Pydantic model gained a `@field_validator('games', 'companies', 'people', mode='before')` that converts dict-shaped input (`{name: {}}`) to `list(keys)`. SYSTEM_PROMPT updated to include the new category in both the enum line and the rules block.
**Why:** The 988-item batch run produced exactly 13 failures across two patterns: 6× missing-category errors on legitimate game/hardware reviews ("Saros Review", "Will: Follow the Light review", Reddit "Mixtape - Review Thread"), 7× dict-shaped people fields. Both are model-side artifacts that show up regardless of prompt tuning. The category enum was provably incomplete; the validator absorbs a real model variance without loosening the public type. After re-run with `retry_failed=True`: 0 failed.
**Trade-off accepted:** The validator silently normalizes any dict-shaped list input — if the model ever returns `{"X": {"meta": ...}}` we lose the meta. Acceptable: the schema doesn't capture per-entity metadata anyway.
**Rejected:** (a) Tighter prompt rule against dict shape — was already implicit; model still does it; (b) Loosen `Entities.people: list[str]` to `list[str] | dict[str, Any]` — leaks model variance into downstream code; (c) Drop the failing rows entirely — losing 1.3% of corpus to fixable parse errors is wasteful when the fix is two lines.

## 2026-05-07 — Underscored-handle bleed in entities.people: 1.9% accepted, no further iteration
**Decision:** The prompt rule excluding underscored Reddit handles from `entities.people` reduced the bleed-through rate but not to zero — 15/798 ok rows (1.9%) still contain handles like `Batz_Gaming`, `biohazard_fanatic`, `/u/ChickenAI_Prod`. We accept this rate and stop iterating on the prompt for now.
**Why:** Diminishing returns on prompt-fix attempts vs. cost (one full re-run is ~2 hours of GPU time). 1.9% on the people field is unlikely to materially affect Phase 3 clustering, which clusters on TL;DR embeddings, not entities. If Phase 3 entity-aware features (per-person trend tracking, etc.) ever surface the issue, address it then with a deterministic post-process filter (regex for `_` or `/u/` prefix on entity strings) rather than another prompt iteration.
**Rejected:** (a) Another prompt iteration — sub-1% diminishing-returns expectation, full re-run cost prohibitive for the gain; (b) Post-process filter now — speculative; the data may not need it.

## 2026-05-07 — Phase 2 enrichment model = qwen2.5:7b (not 14B as originally planned)
**Decision:** Per-item enrichment + entity extraction + cluster labeling runs on **`qwen2.5:7b`** (Q4_K_M, ~4.5GB resident). Embeddings via **`nomic-embed-text`** (768-dim, ~270MB). Promotion to 14B is reserved for future quality regression observed in Phase 3 clustering or weekly synthesis.
**Why:** VRAM math on the 12GB RTX 5070 — 14B Q4 (~9GB) + KV cache at 8k ctx (~1.6GB) + embed model (~0.3GB) + OS/desktop headroom (~0.5GB) = 11.4GB, right at the edge with real model-swap thrashing risk if enrich+embed alternate per item. 7B sits at ~5GB total resident, gives room to keep both models hot, doubles tok/s (~50–70 vs ~25–40), and finishes the ~978-item backlog in ~2hr instead of ~3hr. For the structured-extraction task (TLDR + categorized entities + sentiment), 7B is genuinely sufficient — it's not creative writing.
**Rejected:** (a) 14B at default 4k ctx — silent transcript truncation; (b) 14B at 16k+ ctx — tips into CPU offload; (c) interleaved enrich+embed without phase split — model swap thrash. Phase split (enrich-all then embed-all) is part of this decision.

## 2026-05-07 — Skip enrichment for items with body < 200 chars (Reddit link-only posts)
**Decision:** Items whose effective body (post-YouTube-transcript-fetch) is shorter than `ENRICH_BODY_CHAR_MIN=200` chars are persisted as `status='skipped'` rather than enriched. They appear on the dashboard with title only, no TL;DR.
**Why:** The dominant case is Reddit link-posts that point at articles we already scrape directly from the 13 news-site RSS feeds. The article's full enrichment shows on the original news-feed row; the Reddit version becomes a "community noticed this" duplicate signal. Enriching from a 50-char title produces useless meta-TLDRs ("TheVerge publishes an article about Xbox") that pollute the dashboard.
**Trade-off accepted:** Reddit link-posts pointing at sites we don't monitor (~estimated <5% of items) lose their AI summary; user sees title + URL only. Reversible: setting `ENRICH_BODY_CHAR_MIN=0` re-enables; `tier1.article` body-fetch is queued as Phase 2.5 if the skip rate proves too high in practice.
**Rejected:** (a) Always enrich, accept noise; (b) Drop link-only items at ingest (loses the "community signal" that Reddit users surfaced something); (c) Implement `tier1.article` body-fetch now (half-day of work; defer until empirical need).

## 2026-05-07 — YouTube transcripts fetched at enrichment time, not ingest
**Decision:** `app/services/ollama.py:fetch_youtube_transcript` calls `scrapers_lib.tier1.youtube.fetch_youtube_transcript(video_id)` on-demand inside `enrich_pending` for items whose source is `type='youtube'`. Transcript chunks are concatenated to a single body before going to the LLM. All failure modes (no captions, blocked, age-gated, private) silently fall back to the YouTube RSS description captured at ingest.
**Why:** Confirms the architectural plan from Phase 1 — transcripts are large; fetching at ingest would inflate `raw_items` for videos we may never enrich. On-demand fetch keeps storage bounded and lets failures degrade gracefully (we still have the title to enrich from).
**Rejected:** (a) Eager transcript fetch at ingest — wasted bytes; (b) Title-only enrichment for YouTube — testable later if transcript fetch rate-limits become a problem.

## 2026-05-07 — YouTube ingest = channel-feed RSS, not transcripts (at ingest time)
**Decision:** YouTube sources are ingested via each channel's public Atom feed (`https://www.youtube.com/feeds/videos.xml?channel_id=UC...`) through `scrapers_lib.tier1.rss`, not through `tier1.youtube`. We get one item per video (title, URL, published date, channel author). **Transcript fetching is deferred to Phase 2 enrichment**, when Ollama actually needs the text to summarize.
**Why:** `tier1.youtube` doesn't accept `@handle` and returns transcript *chunks* (≈60s windows) per video — the wrong shape for an "items" feed. `tier1.rss` against the channel feed gives us the same per-video metadata we get from news sites, and it's free of YouTube bot-gate (`BlockedError`). Transcripts are large; pulling them at ingest would inflate the DB and burn requests on videos we may never enrich.
**Resolver:** `app/services/scrapers.py:resolve_youtube_feed` scrapes the channel page once for `channelId`, caches per-process. Verified across all 6 YouTube sources (after correcting `@gameranx` → `@GameranxTV` in `sources.yaml`).
**Rejected:** (a) Calling `tier1.youtube` per video at ingest time — wrong granularity, slow, expensive; (b) Storing channel_ids in `sources.yaml` — adds a manual maintenance step the resolver removes; (c) YouTube Data API — needs a key, exceeds personal-local scope.

## 2026-05-07 — Source list correction: `@gameranx` → `@GameranxTV`
**Decision:** Corrected the Gameranx YouTube handle in `sources.yaml`. The original `@gameranx` 404s on YouTube; the real channel is `@GameranxTV` (channel_id `UCpFHkjOa7ia6bH5_6cDsDXg`). Caught during Phase 1 real-ingest verification — Phase 0 source-list lock-in had only verified RSS feeds, leaving YouTube channels unverified.
**Why:** Empirical: 5 of 6 YouTube channels resolved fine; only Gameranx 404'd. Direct probe confirmed handle was wrong, not a UA / bot-gate issue.
**Consequence:** Reinforces that source-list verification must happen against the real ingest path, not just by visual inspection of `sources.yaml`. Future YouTube additions should be ingest-tested before being considered locked.

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
