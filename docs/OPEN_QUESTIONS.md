# Open questions & deferred items

Living doc. Resolved items move to `DECISIONS.md`. New unknowns are appended here as they surface.

---

## Pending external delivery

- **UI template** — being built in claude.ai/design. Will be ported to Jinja partials in Phase 0. Until delivered, Phase 0 placeholder templates are minimal.
- ~~Source list~~ — provided 2026-05-07; populated and verified in `sources.yaml`.

## Blocked by external party

- **PRAW (official Reddit API) — application rejected 2026-05-07.** Pivoted to Reddit's public RSS endpoint via `tier1.rss` (see `DECISIONS.md`). If/when API access is granted: switch the 11 subreddit entries in `sources.yaml` from `type: rss` back to `type: reddit` and we regain comment threads, upvote/comment counts, and comment-level sentiment. No code refactor needed — `scrapers-lib`'s `tier1.reddit` module still exists; this is a config-level switch.

## Deferred to relevant phase

- **"Industry risks" rubric** — precise definition (layoffs/regulation/platform vs. consumer-side?) decided in Phase 3 when synthesis prompts are written.
- **"Community sentiment" rubric** — Reddit-only? Include YouTube comments? Numeric vs. vibe summary? Decided in Phase 3.
- **Synthesis prompt structure** — section-by-section prompt design + evaluation harness. Phase 3.
- ~~**Local 14B model selection**~~ — **Resolved 2026-05-07.** Picked `qwen2.5:7b` (not 14B) for Phase 2 — VRAM headroom on the 12GB 5070; 14B reserved if Phase 3 reveals quality regression. See DECISIONS.md.
- ~~**Embedding model**~~ — **Resolved 2026-05-07.** `nomic-embed-text` (768-dim) confirmed; produces ~20-norm fp32 vectors that cluster reasonably in spot checks.
- **`tier1.article` in regular ingest vs. remediation pass** — currently kept as a Phase-2.5-style remediation pass after each daily ingest. Reconsider in Phase 3 once cluster quality across recovered-vs-original-body items is observed. Folding into ingest would slow daily runs and increase scrape-rate exposure; leaving as remediation keeps daily ingest fast.
- **Reddit-link-post resolver** — Phase 2.5 deliberately excludes Reddit URLs from article fetch (trafilatura returns nothing on link-post pages). A `URL.json` resolver could recover ~50–60 of the 72 Reddit-skipped items. Build only if Phase 3 cluster cross-referencing across Reddit ↔ news sites visibly weakens without it; otherwise Reddit link-posts remain accepted duplicates of news-feed coverage.

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
