# Open questions & deferred items

Living doc. Resolved items move to `DECISIONS.md`. New unknowns are appended here as they surface.

---

## Pending external delivery

- **UI template** — being built in claude.ai/design. Will be ported to Jinja partials in Phase 0. Until delivered, Phase 0 placeholder templates are minimal.
- **Source list** — user has the 15 news sites + 10 subreddits + 6 YouTube channels. Needed at start of Phase 1 as `sources.yaml`.

## Deferred to relevant phase

- **"Industry risks" rubric** — precise definition (layoffs/regulation/platform vs. consumer-side?) decided in Phase 3 when synthesis prompts are written.
- **"Community sentiment" rubric** — Reddit-only? Include YouTube comments? Numeric vs. vibe summary? Decided in Phase 3.
- **Synthesis prompt structure** — section-by-section prompt design + evaluation harness. Phase 3.
- **Local 14B model selection** — pick the specific 14B (Qwen 2.5 14B Instruct is strong default). Decide in Phase 2 with a quick prompt-quality check on real items.
- **Embedding model** — `nomic-embed-text` is the default. Confirm at start of Phase 2.

## Risks to validate during build

- **scrapers-lib smoke test on real gaming sources.** Tier1 looks well-shaped on paper. Verification = first action of Phase 1.
- **Article extractor (justext) per-source overrides.** Some publishers (paywalls, JS-heavy) may need site-specific selectors. Plan for 2–3 sites needing custom logic.
- **Trend-detection signal-to-noise.** Same story phrased 5 ways across sources is the hard part. Embedding-cluster + LLM-label hybrid is the bet; quality unproven until Phase 3.
- **Synthesis "useful vs. slop" quality bar.** Failure mode: report reads like a generic aggregator. Mitigate with explicit rubrics + few-shot examples + eval pass.
- **Ollama keep-alive vs. cold-start latency.** Verify model load time vs. ingest cadence in Phase 2. Probably fine on dedicated laptop, confirm.

## Architectural choices to revisit only if scale changes

- SQLite single-file vs. dedicated vector DB — only if embedding count exceeds ~100k or similarity queries become slow.
- Single-process vs. split worker — only if ingest hangs cause real UI lag.
- HTMX vs. React — only if UI requirements grow into rich interactivity that's painful in Jinja+HTMX.
