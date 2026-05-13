# gaming-chatter — instructions for Claude

Personal gaming-news aggregator. Daily ingest from 15 news sites + 10 subreddits + 6 YouTube channels → Monday-morning weekly exec summary + live dashboard. Local-only, single user.

## Status
Phases 0–3c.4 shipped (2026-05-13). Corpus state unchanged from Phase 3c.1: 988 items / 887 Haiku-enriched / 900 embeddings (`nomic-embed-text`, 768-dim) / 184 games in dim / 55 per-ISO-week clusters (W17:4 / W18:13 / W19:38) + 63 legacy `week_id='all'` (cleanup deferred). **All 55 per-week clusters now have Sonnet-4.6-generated labels** (qwen2.5:7b replaced via `--relabel-existing`). `weekly_reports` has 1 row (W19) with full Opus-synthesized `synthesis_json` (7395 chars) + Opus-overwritten exec-summary; the W19 Haiku exec-summary from 3c.3 was replaced by the deeper Opus paragraph. **Phase 3c.4 shipped 2026-05-13:** weekly synthesis pipeline. `app/services/synthesis.py` runs a single big Opus 4.7 structured call producing a `WeeklySynthesis` Pydantic covering all 9 synthesizable cards (biggest plural / hottest_reasons / market_momentum / community_sentiment / risks / esports / drama / release_notes / watch + exec_summary_paragraph), followed by a critic-pass Opus call that returns a drop-and-replace revised synthesis. Persists to new `weekly_reports.synthesis_json / _model / _generated_at` columns (idempotent migration `_migrate_weekly_reports_columns` extended); synthesis path also overwrites the 3c.3 exec-summary columns so the modal serves the corpus-aware Opus version. Sonnet 4.6 `label_cluster()` mirrors the `tag_game()` pattern (Pydantic `ClusterLabelData` + ephemeral cache_control); `cluster.py` import swapped; new `--relabel-existing` flag in `scripts/run_cluster.py`. Drawer extended with `kind=cluster` (resolves int cluster_id → member_item_ids → items+sources+enrichments); Biggest / Risks / Drama / Watch row triggers wired conditionally on `cluster_id`. Router `_load_synthesis` + `_apply_synthesis` merges synthesis into the existing 13-card template; mismatched-shape sections (community / market_momentum / esports) stashed under `cards["*_synth"]` keys for the Phase 3c.5 layout restructure. Phase 3c.4 spend: ~$1.30 (relabel ~$0.10 + Pydantic-cap retry burn ~$0.40 + successful synthesis+critic ~$0.90); cumulative project ~$7.56. Sample W19 output: hero "Nintendo announces Star Fox 64 remake for Switch 2, dated June 25"; risks "UK age-verification laws draw coordinated opposition" / "Wizardry IP ownership disputed between Atari and Drecom"; drama "Mortal Kombat 2 producer attacks critics over negative reviews"; exec summary names Griffin Gaming Partners $100M fund + Pearl Abyss CCP Games $120M sale + Mixtape reviews. Critic dropped 1 misplaced risks item (3→2). **Surfaced this session (not fixed):** the Risks template still renders `<span class="gc-risk-trend">` reading a hardcoded `"stable"` value — locked walkthrough was to drop it; will drop in 3c.5 template cleanup. **Next session (Phase 3c.5):** wire `/reports` to the full synthesized data + apply every locked layout change from the 2026-05-12 walkthrough — drop Card 1 / Studio Watch / Storefronts; re-render Biggest as plural top-3; rebuild Market momentum as a row list consuming `market_momentum_synth`; rebuild Community sentiment as narrative + heated/celebrating; rebuild Esports as a row list; sidebar nav trimmed to 4 routes; sidebar corpus-stats block replacing avatar; drop standalone headline + footer hint + header layout/density/theme toggles + Risks trend chip. Then Phase 3c.6 (markdown + standalone-HTML export from `synthesis_json` → `markdown_content` + `html_content`). Then Phase 4 APScheduler Monday auto-run. Optional hygiene: backfill synthesis for W17/W18 (~$1.80); drop 63 legacy `week_id='all'` clusters; taxonomy-drift audit; numeral / partial-name dedupe; Summer Game Fest casing investigation. See `docs/SESSION_LOG.md` 2026-05-13 (Phase 3c.4 entry) + `docs/DECISIONS.md` 2026-05-13 (Phase 3c.4 shipped) + `docs/TASKS.md`.

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
