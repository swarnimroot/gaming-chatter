# gaming-chatter — instructions for Claude

Personal gaming-news aggregator. Daily ingest from 15 news sites + 10 subreddits + 6 YouTube channels → Monday-morning weekly exec summary + live dashboard. Local-only, single user.

## Status
Phases 0–3c.5 shipped (2026-05-13). Corpus state unchanged from Phase 3c.1: 988 items / 887 Haiku-enriched / 900 embeddings (`nomic-embed-text`, 768-dim) / 184 games in dim / 55 per-ISO-week clusters (W17:4 / W18:13 / W19:38) + 63 legacy `week_id='all'` (cleanup deferred). All 55 per-week clusters have Sonnet-4.6 labels. `weekly_reports` has 1 row (W19) with `synthesis_json` (7395 chars) + Opus-overwritten exec-summary. **Phase 3c.5 shipped 2026-05-13:** `/reports` cut from 13 cards to 10 (Card 1 / Card 8 Studio watch / Card 9 Storefronts dropped per 2026-05-12 walkthrough lock; Trends stays as the re-instated 5-tab card). Card 2 Biggest rewritten to plural top-3 with rank badge + dek + source pills + cluster-drawer trigger (span-2 preserved); old single-hero pieces (sparkline / heat-conf-relevance signal cluster / threads-velocity / Read-in-detail button / freshness chip) dropped. Card 4 MM rewritten to row list with category chips (acquisitions / funds / platform-policy / structural / people-moves); absorbs the dropped Studio Watch + Storefronts. Card 6 CS rewritten to narrative + "Reddit is heated about" / "Reddit is celebrating" two-list. Card 7 Risks trend chip dropped ("stable" was a fabrication; "rising" needs multi-week corpus). Card 10 Esports rewritten to row list of corpus-anchored clusters (no fabricated Twitch metrics). Sidebar nav trimmed from 6 placeholders to 4 real routes (Weekly read-out → `/reports`, Dashboard → `/`, Clusters → `/clusters`, Sources → `/sources`); user-avatar block replaced with corpus-stats grid (items / clusters / sources) via new `corpus_stats(session)` helper; sidebar "Generate exec summary" CTA removed. Header chrome trimmed: Grid / Comfortable / Theme toggles removed (variants are locked). Standalone headline block + footer hint block dropped. New `source_pills_for_clusters(session, cluster_ids)` helper derives Biggest pills from cluster members (synthesis schema doesn't carry them). Honest empty-state pattern `synth_ran = week.cards.synthesis_meta` differentiates "Awaiting synthesis. Run `scripts/run_synthesis.py 2026-W18`" (W17/W18) from topic-specific "No esports stories in this week's corpus" (W19, synthesized but empty). Router: `_apply_synthesis(session, cards, synth)` writes community/MM/esports as first-class card keys (no more `*_synth` stash); `biggest` becomes a list; risks adapter drops the `trend` field. Deleted: `_PLACEHOLDER_OTHER` / `_MOMENTUM_KEYS` / `USER` constants, `_enrich_for_render` function (no more sparkline geometry), `sparkline_path` + `delta_tone` helpers. `_empty_cards()` helper now backs both per-week build and the empty-corpus fallback. CSS: 17 dead blocks dropped + 5 new blocks added (`gc-sb-corpus*`, `gc-biggest*`, `gc-mm-category*` with 5 color variants, `gc-cs-narrative` + `gc-cs-dot*`, `gc-row--mm` / `gc-row--cs` / `gc-row--esports`). Verified end-to-end on fresh uvicorn `:8002` for W17/W18/W19: W19 shows 10 cards with full synthesis (3 biggest rows / 5 MM rows / 1 heated + 2 celebrating CS / 2 risks / honest "No esports" / 1 drama / 5 watch / 15 Hottest / 30 Trends); W17 + W18 show 7 "Awaiting synthesis" prompts on synthesis-dependent cards (chrome + Hottest + Trends + Releases work without). One bug caught + fixed mid-verification: `corpus_stats.items` collided with Python `dict.items()` in Jinja attribute access; switched to `corpus_stats['items']` bracket access. No Anthropic spend this session (pure template/router/CSS work); cumulative project ~$7.56. **User's existing `:8001` uvicorn (`--reload`) is stuck on 500 from earlier in the session — needs manual restart to pick up 3c.5 code; my test instance on `:8002` (PID 40032, no reload) is serving the new layout correctly.** **Next session (Phase 3c.6):** markdown + standalone-HTML export from `synthesis_json` → `weekly_reports.markdown_content` + `html_content`, with inlined CSS for the export button. Then Phase 4 APScheduler Monday auto-run. Optional hygiene unlock: backfill synthesis for W17/W18 (~$1.80) — clears the 14 "Awaiting synthesis" prompts and unlocks flipping the sidebar week-list source from `available_weeks()` (clusters) to `weekly_reports desc by generated_at` per the original walkthrough spec. Plus: drop 63 legacy `week_id='all'` clusters; taxonomy-drift audit; numeral / partial-name dedupe; Summer Game Fest casing investigation. See `docs/SESSION_LOG.md` 2026-05-13 (Phase 3c.5 entry) + `docs/DECISIONS.md` 2026-05-13 (Phase 3c.5 shipped) + `docs/TASKS.md`.

## Read first
- `docs/PRD.md` — what we're building and why
- `docs/ARCHITECTURE.md` — how it works
- `docs/DECISIONS.md` — locked choices + rationale
- `docs/TASKS.md` — phased build plan + status
- `docs/OPEN_QUESTIONS.md` — unresolved items
- `docs/SESSION_LOG.md` — prior-session handoff notes

## Hard architectural constraints — do not violate without explicit approval

- **Single Python process.** FastAPI + APScheduler + scrapers-lib + Ollama HTTP + Anthropic SDK in one app. Do not introduce a worker queue, separate scheduler service, Docker container, or split process model.
- **SQLite single-file storage.** No Postgres, no DuckDB, no Redis, no dedicated vector DB. Embeddings stored as BLOBs; cosine similarity in numpy.
- **HTMX + Jinja frontend.** No React/Vue/Svelte. No JavaScript build step. The UI template handed over from claude.ai/design will be ported into Jinja partials.
- **LLM split (updated 2026-05-12 — see DECISIONS.md "2026-05-12 (later)"):** **embeddings on Ollama** (`nomic-embed-text`, 768-dim); **per-item enrichment on Anthropic Haiku 4.5**; **cluster labels on Anthropic Sonnet 4.6**; **synthesis + critic pass on Anthropic Opus 4.7**. Do not introduce OpenAI, llama.cpp direct, or other providers. The pre-2026-05-12 lock said "Ollama local for per-item work, Anthropic API for synthesis only" — that lock was overridden after the qwen2.5:7b structured-output sample exposed concrete quality issues (Reddit-handle leak in entities, movie tagged with game genres) and 4–5× runtime regression vs Haiku.
- **scrapers-lib is an external Python dependency** at `..\scrapers-lib`. Use `tier1` modules: `rss` (handles BOTH news-site feeds AND Reddit subreddit feeds — see DECISIONS.md 2026-05-07), `youtube`, `article`. The `tier1.reddit` (PRAW) module is currently NOT used because the Reddit API application was rejected; see `docs/OPEN_QUESTIONS.md`. Do not modify scrapers-lib from this project.
- **Personal-local only.** No auth, no TLS, no cloud, no multi-user. Listens on `localhost`.

## Session conventions

- Major decisions → append a dated entry in `docs/DECISIONS.md`.
- End of every working session → append to `docs/SESSION_LOG.md`: what was done, where we left off, what's blocked.
- Update `docs/TASKS.md` checkboxes as work moves.
- New unknowns / deferred items → `docs/OPEN_QUESTIONS.md`.

## Out of scope (deferred to "Later")

- Push delivery (email/Discord) — after core phases ship
- Multi-user, accounts, sharing
- Backfill of historical data — accept cold start
- Mobile-specific UI

## scrapers-lib at a glance

Located at `C:\Users\AW-testing\Downloads\Workspace\scrapers-lib`. Python lib. `tier1` provides RSS (used for both news sites AND Reddit subreddits via Reddit's public RSS endpoint), Reddit-PRAW (currently unused — API rejected, may flip back if reapproved), YouTube + transcripts, generic article extraction (justext). `core` provides rate limiting, caching, robots.txt, attribution, scheduler. `tier2/tier3` (laptop/retail) are unused for this project.
