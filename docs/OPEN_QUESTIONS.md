# Open questions & deferred items

Living doc. Resolved items move to `DECISIONS.md`. New unknowns are appended here as they surface.

---

## Pending external delivery

- ~~**UI template**~~ — **delivered + ported 2026-05-11.** claude.ai/design bundle for the weekly read-out ported to `/reports` with the locked variants (grid + comfortable + light + orange `#D9682B`). All 13 cards render with placeholder data. Section trim + production-data wiring is the next session's walkthrough work. See SESSION_LOG 2026-05-11.
- ~~Source list~~ — provided 2026-05-07; populated and verified in `sources.yaml`.

## Blocked by external party

- **PRAW (official Reddit API) — application rejected 2026-05-07.** Pivoted to Reddit's public RSS endpoint via `tier1.rss` (see `DECISIONS.md`). If/when API access is granted: switch the 11 subreddit entries in `sources.yaml` from `type: rss` back to `type: reddit` and we regain comment threads, upvote/comment counts, and comment-level sentiment. No code refactor needed — `scrapers-lib`'s `tier1.reddit` module still exists; this is a config-level switch.

## Deferred to relevant phase

- ~~**"Industry risks" rubric**~~ — **Resolved 2026-05-11.** Layoffs/closures + regulation/legal/policy. See DECISIONS.md.
- ~~**"Community sentiment" rubric**~~ — **Resolved 2026-05-11.** Reddit-only hybrid: numeric mean over Reddit-source members + 2–3 sentiment_summary excerpts. See DECISIONS.md.
- **Synthesis prompt structure** — section-by-section prompt design + evaluation harness. **Section list expanded 2026-05-12 to 10** (Biggest / Hottest / MM / Community Sentiment / Industry Risks / Esports / Releases / Drama / Watch / Trends) + an exec-summary pass that produces a 1-paragraph tldr from the synthesized report. Per-section data contract drives Phase 3c.4 work.
- ~~**Design walkthrough (Phase 3c gating)**~~ — **Resolved 2026-05-12.** Walkthrough drove 13 → 9 cards (Card 1 "This week in gaming" dropped, Card 8 Studio Watch + Card 9 Storefronts folded into MM); chrome stripped (4-route sidebar nav, no header toggles, no footer hint); Card 2 reworked to plural top-3 "Biggest stories"; Card 6 Community Sentiment + Card 10 Esports reframed honestly (no aggregate %, no Twitch metrics); Trends restored as 5-tab card; exec-summary modal + Source Drawer both kept and slated for Phase 3c.3 port. See DECISIONS.md 2026-05-12 + SESSION_LOG.md 2026-05-12 for full lock list.
- ~~**WoW-Trends section**~~ — **Restored to Phase 3c 2026-05-12.** 5-tab layout locked: Games (sub: existing + upcoming) / Genres / Platforms / Live-service / Events. WoW only (MoM dropped for now). Tagging foundation locked: new `games` dim table (`name PK`, `lifecycle`, `live_service`) + 3 new `enrichments` columns (`genres[]`, `platforms[]`, `event`) + locked taxonomies (Genres ×12, Platforms ×6, Events ×12+Other) + fuzzy rules (existing = released anywhere; live-service = seasonal/battle-pass content model) + multi-value cap 3 genres + drop-don't-map for out-of-taxonomy values. Multi-week corpus from re-binning existing items by `published_at` into ISO weeks. Implementation lives in Phase 3c.0 → 3c.2. See DECISIONS.md 2026-05-12.
- ~~**Local 14B model selection**~~ — **Resolved 2026-05-07.** Picked `qwen2.5:7b` (not 14B) for Phase 2 — VRAM headroom on the 12GB 5070; 14B reserved if Phase 3 reveals quality regression. See DECISIONS.md.
- ~~**Embedding model**~~ — **Resolved 2026-05-07.** `nomic-embed-text` (768-dim) confirmed; produces ~20-norm fp32 vectors that cluster reasonably in spot checks.
- **`tier1.article` in regular ingest vs. remediation pass** — currently kept as a Phase-2.5-style remediation pass after each daily ingest. Reconsider in Phase 3 once cluster quality across recovered-vs-original-body items is observed. Folding into ingest would slow daily runs and increase scrape-rate exposure; leaving as remediation keeps daily ingest fast.
- **Reddit-link-post resolver** — Phase 2.5 deliberately excludes Reddit URLs from article fetch (trafilatura returns nothing on link-post pages). A `URL.json` resolver could recover ~50–60 of the 72 Reddit-skipped items. Build only if Phase 3 cluster cross-referencing across Reddit ↔ news sites visibly weakens without it; otherwise Reddit link-posts remain accepted duplicates of news-feed coverage.
- **Phase 3b recency-penalty steepness** — current `score = source_count × member_count / (1 + days_since_latest)` divides by 8 at 7 days, which may under-represent early-week stories in weekly windows. The Spiders studio-closure cluster (5 sources × 5 members, 7 days old) lands at score 2.73 / rank #13 in the 2026-05-08 rerun despite maximal cross-source breadth. Tune to `exp(-days/tau)` or similar **only** if Phase 3c synthesis on a real weekly window shows visible under-representation of mid- and early-week stories. See SESSION_LOG 2026-05-08 + DECISIONS 2026-05-08.
- ~~**Phase 3c synthesis model: Sonnet 4.6 vs Opus 4.7**~~ — **Resolved 2026-05-11.** Opus 4.7 (`claude-opus-4-7`). Once weekly = ~$15/yr; synthesis is the user-facing quality moment per PRD. See DECISIONS.md.

## Open from 2026-05-12 Phase 3c.0.5 Haiku migration

- **Cleanup of 63 legacy `week_id='all'` clusters from Phase 3b.** `scripts/run_cluster.py --per-week` (2026-05-12) added 55 new per-ISO-week rows but did NOT delete the prior global rows. Script-intent docs say "replace". Top of `/clusters` is still dominated by the legacy 'all' rows because their cross-corpus `source_count × member_count` is larger. Decide: (a) `DELETE FROM clusters WHERE week_id='all'` and live with per-week only, (b) keep both and update the UI default to a per-week filter, or (c) keep both and treat 'all' as an explicit alternate view.
- **13 preserved-qwen items from the Haiku backfill.** Haiku occasionally returned an out-of-taxonomy category (e.g. `'guide'`) which failed `_ALLOWED_CATEGORIES`; the safety net preserved the prior valid qwen row. To migrate these too: either widen `_ALLOWED_CATEGORIES` to include observed-but-rejected categories (which broadens the taxonomy lock) or do a targeted re-run with a tweaked prompt. Note: `scripts/rerun_enrichment.py:34` still imports `enrich_item as ollama_enrich_item` from `app.services.ollama`, so the `--ids` path bypasses Haiku — that line needs swapping if we use `--ids` for the fix-up.
- **Anthropic API failure surface during weekly auto-run.** Phase 4 APScheduler weekly run will now halt on Anthropic API outage / expired key / rate limit, because per-item enrichment is no longer offline-capable. DECISIONS 2026-05-12 (later) accepted this. Decide a fallback policy: hard-stop the weekly run, queue items for retry, or accept-and-alert the user. Defer until Phase 4.

## Open from 2026-05-12 walkthrough (lock during Phase 3c implementation)

- **Source Drawer layout** — right-side slide-in panel to be ported in Phase 3c.3 from the design bundle's shell. Open: panel width, slide animation timing, click-outside dismissal behavior, content density (full member list vs paginated; full synthesis paragraph vs just member items + sources).
- **Exec-summary modal layout** — second Anthropic pass produces a 1-paragraph tldr of the synthesized report. Open: modal renders just the summary, or full report + summary together as a "save/print" view? Both are plausible; locks at 3c.3 implementation.
- **Per-week clustering threshold** — current `CLUSTER_THRESHOLD=0.85` was tuned against the 908-item `week_id='all'` corpus. Per-ISO-week corpora will be much smaller (~150-200 items each). Threshold may need re-tuning since the noise-floor changes with corpus size. Validate during Phase 3c.0 re-bin; re-run `scripts/explore_clustering.py` on a single week before committing the change.
- **Cluster boundary-spanning de-duplication** — stories that span 2 ISO weeks become 2 clusters in different windows. Small-in-practice based on the 63-cluster eyeball (most concentrate in 1-3 days), but worth checking once per-week clustering runs. Mitigation if needed: a centroid-similarity link pass across adjacent weeks.
- **Trends "top N" cutoff per tab** — Top 5? Top 10? Or all entries with WoW delta above some threshold? Locks at Phase 3c.2 once real WoW deltas are observable on the re-binned corpus.
- **Empty-state designs for sparse Trends tabs** — Events tab will frequently be empty (most weeks have no E3 / Summer Game Fest / Gamescom / TGS). Open: render an explicit "No events this week" placeholder, hide the tab entirely when empty, or show it with the "Other-showcase" overflow only. Locks at 3c.2.
- **Visual monotony in the redesigned grid** — the strip-out left 7-8 cards in a similar "row list of clusters" shape; the original charts/sparklines were stripped as fabrication risks. Either accept the uniform appearance as the price of honesty, or reintroduce *real* visual variation (sentiment bar chips on CS, severity bars on Risks, date strips on Releases) once data exists. Revisit after the 3c.0 tagging foundation lands and we can see how dense each card actually is with real data.

## Risks to validate during build

- ~~**scrapers-lib smoke test on real gaming sources.**~~ **Validated 2026-05-07** — Phase 1 real ingest hit 30/30 sources successfully (~973 items). `tier1.rss` works for both news feeds and YouTube channel feeds; `RawMention` shape maps cleanly to our `items` model. See SESSION_LOG.md and DECISIONS.md.
- ~~**Article extractor (justext) per-source overrides.**~~ **De-risked 2026-05-07** by Phase 2.5 batch. `tier1.article` (trafilatura) recovered 94/95 attempted across PC Gamer, Kotaku, Game Developer, GamesIndustry.biz, Eurogamer, GameSpot — no per-site overrides needed. The 1 errored case was a transient HTTP issue, not an extractor problem. Revisit only if new sources are added that fail.
- **Trend-detection signal-to-noise.** Same story phrased 5 ways across sources is the hard part. Embedding-cluster + LLM-label hybrid is the bet; quality unproven until Phase 3.
- **Synthesis "useful vs. slop" quality bar.** Failure mode: report reads like a generic aggregator. Mitigate with explicit rubrics + few-shot examples + eval pass.
- ~~**Ollama keep-alive vs. cold-start latency.**~~ **Validated 2026-05-07** across two batch runs. `OLLAMA_KEEP_ALIVE=24h` keeps both `qwen2.5:7b` and `nomic-embed-text` resident; observed ~7s/item enrich, ~2.3s/embed at steady state. Phase split (enrich-all then embed-all) avoids per-item model swap.

## Architectural choices to revisit only if scale changes

- SQLite single-file vs. dedicated vector DB — only if embedding count exceeds ~100k or similarity queries become slow.
- Single-process vs. split worker — only if ingest hangs cause real UI lag.
- HTMX vs. React — only if UI requirements grow into rich interactivity that's painful in Jinja+HTMX.
