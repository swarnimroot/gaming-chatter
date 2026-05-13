# Session log

Append-only. Newest entries on top. Each entry: date, what was done, where we left off, blocked-on / next.

---

## 2026-05-13 (Phase 3c.5) — 9-card layout restructure: drop Cards 1/8/9, plural Biggest, MM/CS/Esports synthesized

**Done:**
- **Sidebar restructure.** Nav trimmed from 6 placeholder routes to 4 real ones: `/reports` (Weekly read-out, active), `/` (Dashboard), `/clusters` (Clusters), `/sources` (Sources). `NAV_ITEMS` gained an `href` field; template `<a href="#">` → `<a href="{{ n.href }}">`. Sidebar "Generate exec summary" CTA removed (deduped with header CTA). User-avatar block replaced with a 3-cell corpus-stats block reading new `corpus_stats(session)` helper (items / clusters / sources). Sidebar week-list source unchanged — still `available_weeks()` (clusters table). Spec said `weekly_reports desc by generated_at` but with synthesis only run for W19 that would hide W17/W18 from the picker; flipping to `weekly_reports` becomes correct once the W17/W18 backfill runs (optional hygiene).
- **Header chrome trimmed.** Layout (Grid) / density (Comfortable) / theme (moon) toggles removed; only the Exec-summary CTA stays in `.gc-header-actions`. Header meta still reads `range · N stories · refreshed X ago` (one breadcrumb under the title), but the dependent template var changed from `week.summary.stats.stories` to `week.stats.stories` (intermediate `summary` dict removed in the router refactor).
- **Standalone headline block dropped** (locked walkthrough: redundant with Biggest title + exec-summary).
- **Footer hint block dropped** (locked walkthrough: instructions for Hottest/Trend/Release row triggers no longer needed once every card row is a trigger).
- **Card 1 "This week in gaming" — DROPPED.** Top-genres + top-platforms mini-bars removed. Locked walkthrough rationale: overlaps with sidebar corpus stats; per-week genre / platform signal already lives in Trends card with WoW deltas.
- **Card 2 "Biggest" — rewritten to plural top-3.** `<span-2>` preserved. Each row = `#1/#2/#3` rank badge + title + dek + source pills, with `<label for="drawer-open" hx-get="...kind=cluster">` opening the cluster drawer on click. New helper `source_pills_for_clusters(session, cluster_ids)` in `app/services/reports.py` derives the per-cluster source list from `clusters.member_item_ids` → `sources` (the synthesis schema doesn't carry pills — pulling them from cluster members keeps the template free of a second query). Old single-hero pieces dropped: sparkline meta + signal cluster (heat/conf/relevance) + threads/velocity + "Read in detail" button + first_seen freshness chip + `gc-card-clickable` whole-card click affordance.
- **Card 4 "Market momentum" — rewritten to row list.** Replaces the 4-platform sparkline placeholder grid (Steam CCU / Twitch hrs / Game Pass net / PSN net adds) with a row list consuming the synthesis `market_momentum` items (max 5). Each row = `gc-mm-category` chip (acquisitions / funds / platform-policy / structural / people-moves, color-coded per category) + title + note + drawer trigger on `cluster_id`. Absorbs the dropped Studio Watch (layoffs went to Risks, M&A to MM) + Storefronts (platform-policy is MM's scope) per walkthrough.
- **Card 6 "Community sentiment" — rewritten to narrative + heated/celebrating.** Aggregate pos/neu/neg stacked bar + Top-threads list dropped. New layout: `.gc-cs-narrative` paragraph on top + two per-cluster lists with section eyebrows "Reddit is heated about" (red dot) / "Reddit is celebrating" (green dot). Each row anchored to a cluster → drawer. Per CommunitySentimentSection schema: max 3 heated + max 3 celebrating.
- **Card 7 "Industry risks" — `gc-risk-trend` span dropped.** Per walkthrough: "stable" hardcode was a fabrication ("rising" requires multi-week corpus). Row collapsed to severity bar + title + low/med/high badge + note + drawer trigger. Defensive `{% if r.cluster_id %}` branch dropped — synthesis schema makes `cluster_id` required on `IndustryRisk`.
- **Card 8 "Studio watch" — DROPPED, folded into MM.** Card 9 "Storefronts" — DROPPED, folded into MM. Per walkthrough.
- **Card 10 "Esports & streaming" — rewritten to row list of corpus-anchored clusters.** Old top_stream / big_event / movers placeholder dropped (no Twitch / esports metrics in the corpus). Each row = title + note + drawer trigger on `cluster_id`.
- **Honest empty-state pattern: `synth_ran = week.cards.synthesis_meta`.** Applied to Biggest (still uses single-branch since synthesis schema requires min_length=1), MM, Risks, Esports, Drama, Watch. Three-branch logic: `if cards.X` → render; `elif synth_ran` → honest "No X stories in this week's corpus"; `else` → "Awaiting synthesis. Run `scripts/run_synthesis.py {{ active_week_key }}`". Drama + Watch + the new cards all share the pattern.
- **Router refactor:** `_apply_synthesis` now takes `(session, cards, synth)` and writes community / market_momentum / esports as first-class card keys (no more `*_synth` stash from Phase 3c.4 transition). `risks` mapping drops the `trend` field. `biggest` becomes a list, not a single dict — pulls source pills inline via the new helper. `_build_week_payload` builds on `_empty_cards()` helper instead of `copy.deepcopy(_PLACEHOLDER_OTHER)`; `_PLACEHOLDER_OTHER` constant deleted. `_enrich_for_render` deleted (no more biggest sparkline + momentum sparkline + esports.movers delta_tone enrichment to do). `_MOMENTUM_KEYS` deleted. `USER` constant deleted (template no longer references `user.initials` / `user.name`).
- **CSS cleanup:** added `gc-sb-corpus*` (corpus-stats grid), `gc-biggest*` (plural rows), `gc-mm-category*` (MM category chips with 5 color variants), `gc-cs-narrative` + `gc-cs-dot` + `gc-cs-divider` (CS layout), `gc-row--mm` / `gc-row--cs` / `gc-row--esports` (grid columns). Deleted: `gc-segmented` / `gc-toolbar-btn` / `gc-icon-btn` (header toggles); `gc-headline-block` / `gc-headline-eyebrow` / `gc-headline`; `gc-sb-cta` / `gc-sb-user` / `gc-sb-avatar` / `gc-sb-user-name` / `gc-sb-user-meta`; `gc-stats-row` / `gc-stat-value` / `gc-net-sent*` / `gc-genres` / `gc-genre-*` / `gc-bars-spacer` (Card 1); `gc-fresh` / `gc-fresh-dot` (old biggest hero); `gc-sent-bar` / `gc-sent-legend` / `seg-pos|neu|neg` (old CS); `gc-row--studio` / `gc-row--platform` / `gc-row--mover` / `gc-row--thread` + dependent `gc-row-sub` / `gc-row-event` / `gc-row-platform-name` / `gc-row-impact*` / `gc-add-btn` / `gc-sub-pill` / `gc-thread-*`; `gc-big-*` / `gc-momentum-*` / `gc-es-*`; `gc-risk-trend`; `gc-footer-hint` / `gc-ghost-btn`; `gc-card-clickable` block.
- **Verified end-to-end on `:8002`** (started fresh uvicorn for testing; user's existing `:8001` `--reload` instance is stuck on 500 from earlier in the session and needs a manual restart).
  - W19 (full synthesis): 200, 10 `.gc-card`, 0 "Awaiting synthesis", 3 plural-Biggest rows, 5 MM rows, 1 heated + 2 celebrating CS rows + narrative, 2 risks rows, 0 esports rows → "No esports / streaming stories in this week's corpus" honest empty-state, 1 drama row, 5 watch rows, 15 Hottest rows (3 tabs × 5), 30 Trends rows (5 tabs × ~5 + Games sub-split), 4 nav items (Weekly / Dashboard / Clusters / Sources), corpus stats `988 items · 55 clusters · 30 sources`. Drawer endpoint `/reports/drawer?kind=cluster&value=143&week=2026-W19` 200. Exec-summary endpoint 200.
  - W18 + W17 (no synthesis yet): 200, 10 `.gc-card`, 7 "Awaiting synthesis" empty rows (Biggest / MM / CS / Risks / Esports / Drama / Watch) — chrome + Hottest + Trends + Releases render fine.
- **Mid-verification fix: `corpus_stats.items` collided with Python `dict.items()` in Jinja attribute access.** First W19 fetch rendered `<built-in method items of dict object at 0x...>` in the corpus-stats block. Fix: switch to `corpus_stats['items']` bracket access (also for `clusters`/`sources` for consistency). Considered renaming the dict keys; chose bracket access as the smaller change.

**Decided / verified:**
- **Sidebar week-list source: keep `available_weeks()`** (clusters table) rather than the walkthrough-spec'd `weekly_reports desc by generated_at`. Reason: with synthesis only run for W19 today, switching would hide W17/W18 from the picker, which contradicts the user's mental model of "the corpus has these weeks." Reverts once the W17/W18 synthesis backfill (~$1.80) lands — already in the optional-hygiene backlog.
- **Empty-state messaging differentiates between "synthesis hasn't run" and "synthesis ran, no items":** uses `week.cards.synthesis_meta` as the gate. Reason: an honest "No esports stories in this week's corpus" is more useful than the same "Awaiting synthesis" string under both states.
- **Source pills for Biggest derived from cluster members, not synthesized.** Reason: synthesis schema doesn't carry pills, and the cluster member→source join is a single extra query per render (one for all top-3 cluster_ids). Adding pills to the synthesis schema would have meant a re-run of the W19 synthesis (~$0.90) without UI gain.

**State at end of session:**
- Modified files: `app/services/reports.py` (+`corpus_stats()` +`source_pills_for_clusters()`, +60 lines), `app/routers/reports.py` (heavy refactor — `_PLACEHOLDER_OTHER` / `_MOMENTUM_KEYS` / `USER` / `_enrich_for_render` / `sparkline_path` / `delta_tone` removed; `_apply_synthesis` signature changed to take session, writes first-class card keys; new `_empty_cards()` helper; NAV_ITEMS trimmed to 4 with `href`), `app/templates/reports.html` (Card 1 / Card 8 / Card 9 / standalone headline / footer hint / header toggles / sidebar CTA + avatar dropped; Cards 2 / 4 / 6 / 10 rewritten; Risks trend chip dropped; empty-state pattern added across 6 cards), `app/static/app.css` (~17 dead-style blocks deleted; new MM / CS / Biggest / Esports / corpus-stats blocks added).
- Docs updated: this entry; `docs/TASKS.md` Phase 3c.5 boxes ticked; `docs/DECISIONS.md` 2026-05-13 (Phase 3c.5 shipped) entry; `CHANGELOG.md` Unreleased / Phase 3c.5 entry; project `CLAUDE.md` Status line updated.
- Corpus state unchanged from 3c.4 (988 items · 887 Haiku-enriched · 900 embeddings · 184 games in dim · 55 per-ISO-week clusters + 63 legacy `week_id='all'`). `weekly_reports` still has the 1 W19 row from 3c.4 (synthesis_json + exec_summary_text).
- **Two uvicorn processes running:** user's `:8001 --reload` (PID 32724) is stale (500 from earlier in session — needs manual restart to pick up 3c.5 code); my test instance `:8002` (PID 40032, no reload) serving the new code correctly. User should `Ctrl+C` :8001 and re-launch to validate the new layout in their main session.
- **No Anthropic spend this session** (no synthesis re-runs, no enrichment, no relabel — pure router/template/CSS work).

**Next session should:**
1. **Phase 3c.6 — Markdown / standalone-HTML export.** Render `weekly_reports.markdown_content` from the synthesis JSON; render `weekly_reports.html_content` standalone with inlined CSS for the export button. The 9-card layout is the visual target.
2. **Phase 4 — APScheduler automation.** Daily ingest + Monday-morning synthesis cron; catch-up on startup; run-log UI.
3. **Optional hygiene (not blocking):**
   - Backfill synthesis for W17 + W18 (~$1.80). Side benefit: lets the sidebar week-list flip from `available_weeks()` to `weekly_reports desc by generated_at` per the original 3c.5 walkthrough spec.
   - Drop the 63 legacy `week_id='all'` cluster rows.
   - Numeral-variant dedupe (Diablo IV ↔ Diablo 4, Endfield ↔ Arknights: Endfield).
   - Series-as-game cleanup.
   - Taxonomy drift audit in `_filter_genres` / `_filter_platforms`.
   - `Summer Game Fest = 1` casing-variant investigation.

**Open / blocked:**
- Phase 3c.6 markdown + standalone-HTML export — next session.
- Phase 4 APScheduler — not blocking 3c.6.
- Sidebar week-list source flip (`available_weeks` → `weekly_reports`) — waiting on W17/W18 synthesis backfill.

---

## 2026-05-13 (Phase 3c.4) — Synthesis (Opus 4.7 + critic) + Sonnet 4.6 cluster labels + cluster drawer

**Done:**
- **Sonnet 4.6 `label_cluster()` migration shipped.** `app/services/anthropic.py` gained `ClusterLabelData` Pydantic + `CLUSTER_LABEL_SYSTEM_PROMPT` + `label_cluster(titles, tldrs)` mirroring the `tag_game()` pattern. Prompt refined for Sonnet's tighter instruction-following ("If the cluster spans multiple sub-topics, pick the dominant one"). `app/services/cluster.py` import swapped from `ollama` → `anthropic`. New `ANTHROPIC_CLUSTER_LABEL_MODEL` env var in `app/config.py`, default `claude-sonnet-4-6`.
- **One-time relabel of all 55 per-week clusters.** New `--relabel-existing` CLI flag + `_relabel_existing()` helper in `scripts/run_cluster.py` re-labels every cluster in place (no re-clustering — centroid, members, score, week_id all preserved). Filters out the 63 legacy `week_id='all'` rows (deferred cleanup). Ran in **101s, 55/55 success, ~$0.10 spend**. Sample improvements: "2K NFL and MLB game future" → "Take-Two exits NFL and MLB licensed sports games"; "Aliens: Fireteam Elite 2 announcement" → "Aliens Fireteam Elite 2 officially announced by Cold Iron Studios".
- **DB migration shipped.** `app/db/models.py` `WeeklyReport` extended with `synthesis_json TEXT`, `synthesis_model TEXT`, `synthesis_generated_at TIMESTAMP`. `app/db/init.py` `_migrate_weekly_reports_columns()` extended idempotently. Confirmed cols added on uvicorn restart.
- **`app/services/synthesis.py` (new module, ~590 lines).** Single big-call `WeeklySynthesis` Pydantic schema covering all 9 cards' synthesizable fields (biggest plural, hottest_reasons, market_momentum, community_sentiment, risks, esports, drama, release_notes, watch, exec_summary_paragraph). System prompts: `_SYNTHESIS_SYSTEM_PROMPT` (locked rubrics: industry-risks scope, CS Reddit-only, drama narrow; voice constraints; section-by-section instructions) and `_CRITIC_SYSTEM_PROMPT` (groundedness checks, section-placement enforcement, prose tightening, returns revised synthesis drop-and-replace). Input builder fetches top-12 clusters with 5 sample members each + Reddit-cluster sentiment summaries + week_stats + top games/genres/platforms/events + Trends WoW risers + upcoming releases. Single `synthesize_week(session, week_id, force=False) -> dict` public API. Both Opus calls use the same `_call_opus()` wrapper; system block carries `cache_control: ephemeral` marker (forward-compatible).
- **`scripts/run_synthesis.py` (new).** CLI: `python scripts/run_synthesis.py 2026-W19 [--force] [--dry-run]`. Calls `init_db()` at import so it doesn't depend on FastAPI lifespan. Pretty-prints exec_summary + biggest stories to stdout for visual QA.
- **First W19 synthesis run.** **57.7s wall-clock for synthesis + critic. ~$0.90 spend on the successful run + ~$0.40 burned on a Pydantic-cap retry (see below) = ~$1.30 total this session.** Synthesis pass returned biggest=3 MM=5 risks=3 esports=0 drama=1 watch=5; critic pass returned biggest=3 MM=5 risks=**2** (dropped 1 out-of-scope item) esports=0 drama=1 watch=5. Persisted as 7395-char JSON in `weekly_reports`.
- **Critic dropped 1 risks item correctly.** Synthesis pass had 3 risks; critic dropped one (presumably a market-shift story misplaced into risks). The remaining 2: "UK age-verification laws draw coordinated opposition" / "Wizardry IP ownership disputed between Atari and Drecom". Both are honest rubric matches.
- **Router wired synthesis into the existing 13-card template.** `_load_synthesis()` + `_apply_synthesis()` in `app/routers/reports.py`. Biggest hero card uses `synthesis.biggest[0]` (single); rest stashed under `cards["biggest_list"]` for Phase 3c.5. Risks/drama/watch adapted to the existing row shapes. Hottest reasons + release notes overlaid onto top_games / upcoming_releases by case-insensitive game-name match. Shape-mismatched sections (community_sentiment, market_momentum, esports) stashed under `cards["*_synth"]` keys awaiting the 3c.5 layout restructure.
- **`exec_summary_text` overwritten** by the synthesis path. Modal footer now reads `cached · claude-opus-4-7 · generated May 13, 18:42 UTC` instead of the 3c.3 Haiku entry. Modal serves the corpus-rich Opus paragraph on the next open.
- **Drawer extended with `kind=cluster`.** New branch in `items_for_entity_in_week()` resolves `value` as integer cluster_id, fetches `member_item_ids`, joins items+sources+enrichments. Drawer header swaps the numeric ID for the cluster's `label` (which is now the Sonnet-relabeled version). `_DRAWER_KIND_LABELS` extended; `_DRAWER_KINDS` extended.
- **`reports.html` row triggers wired** for Biggest (whole hero card, with inline `onclick="document.getElementById('drawer-open').checked=true"` because the hero contains the "Read in detail" button — can't wrap in `<label>`), Risks rows (conditional `<label>` when `r.cluster_id` present), Drama rows (same), Watch rows (same; also dropped the "+" Add-reminder button per walkthrough lock). Hottest macro got a `gc-row-reason` subline rendering synthesis-provided `reason`. Releases row got the same for `note`.
- **CSS additions:** `.gc-card-clickable` + hover, `.gc-row-reason` (sublime), `.gc-row-trigger:hover` extended to color risk/drama/watch titles.

**Decided / verified (full rationale in DECISIONS 2026-05-13 Phase 3c.4 entry):**
- **One big structured Opus call, not per-section.** PRD's $1-5/month cap + 2026-05-11's ~$0.30/run lock both presume single-call. Confirmed: full schema delivered in ~33s for $0.40.
- **Critic returns the revised synthesis (drop-and-replace).** Simpler than critique-then-merge. Working as intended — critic dropped 1 misplaced risks item.
- **`max_length` is a runaway-output guardrail, not a design cap.** First run failed Pydantic validation on 158-char `reason` (cap 140) and 360-char `narrative` (cap 320). Burned ~$0.40. Lesson: re-tuned every field's max_length to ~2x the editorial target; prompt still encodes the editorial intent ("≤140 chars; one sentence").
- **Synthesis persistence on `weekly_reports.synthesis_json`** as a JSON dump. `markdown_content` / `html_content` columns stay reserved for the Phase 3d standalone-HTML export.
- **Synthesis run overwrites `exec_summary_text` / `_model` / `_generated_at`** so the 3c.3 modal serves the deeper Opus version once synthesis has run.
- **Drawer `kind=cluster` is the cluster-drill mechanism**, not a new `synthesis_text` column on `clusters`. Per-cluster narrative deferred indefinitely; the drawer listing member articles is enough editorial context for now.
- **Biggest hero card uses inline `onclick`** for the radio flip (one-line) because `<label>` can't wrap interactive form controls inside the hero card. Acceptable single inline-JS use; all other row triggers stay on the 3c.3 radio+label pattern.

**State at end of session:**
- New files: `app/services/synthesis.py` (~590 lines), `scripts/run_synthesis.py`.
- Modified files: `app/db/models.py` (+3 fields on WeeklyReport), `app/db/init.py` (+3 cols in `_migrate_weekly_reports_columns`), `app/config.py` (+2 model env vars), `app/services/anthropic.py` (+ClusterLabelData/SYSTEM_PROMPT/label_cluster), `app/services/cluster.py` (1-line import swap), `app/services/reports.py` (+ cluster branch in items_for_entity_in_week + `_DRAWER_KINDS` extension, ~60 new lines), `app/routers/reports.py` (+ `_load_synthesis` + `_apply_synthesis` + cluster-drawer label resolution + `_DRAWER_KIND_LABELS` extension, ~120 new lines), `app/templates/reports.html` (Biggest/Risks/Drama/Watch row-trigger wiring + Hottest reason subline + Releases note subline, ~80 net new lines), `app/static/app.css` (~30 new lines), `scripts/run_cluster.py` (+ `--relabel-existing` + helper, ~75 new lines).
- Docs updated: `docs/DECISIONS.md` 2026-05-13 (Phase 3c.4 shipped) entry, `docs/TASKS.md` 3c.4 boxes ticked, `CHANGELOG.md` Unreleased / Phase 3c.4 entry, this entry, project `CLAUDE.md` Status line updated.
- Corpus state: 988 items / 887 Haiku-enriched / 900 embeddings / 184 games dim — unchanged. **Cluster labels: all 55 per-week clusters relabeled via Sonnet 4.6.** 63 legacy `week_id='all'` rows still have qwen labels (cleanup still deferred). `weekly_reports` now has 1 row with full synthesis JSON for W19 + the Opus-overwritten exec-summary.
- Test uvicorn :8001 restarted clean (had a stuck reloader from earlier in session). PID changed; verified live.
- **Anthropic spend this session: ~$1.40** (Sonnet relabel ~$0.10 + Opus-pass burned-by-pydantic-cap ~$0.40 + Opus synthesis+critic ~$0.90). Cumulative project: ~$7.56, still well under the $500/yr cap.

**Surfaced for next session — `r.trend` still rendered.**
- The Risks template still includes `<span class="gc-risk-trend">{{ r.trend }}</span>` reading the router-side adapter's hardcoded `"stable"`. Locked walkthrough decision was to drop the trend chip ("'rising' requires multi-week corpus we don't have yet"). Will drop in the 3c.5 template cleanup.

**Next session should:**
1. **Phase 3c.5 — wire `/reports` to the full synthesized data + apply every locked layout change from the 2026-05-12 walkthrough.** Concretely:
   - **Card 1 "This week in gaming" — DROP** (locked walkthrough; redundant with sidebar corpus stats).
   - **Card 2 Biggest — re-render plural top-3** (currently shows synthesis.biggest[0] only; full list is already in `cards["biggest_list"]`).
   - **Card 4 Market momentum — replace the 4-platform-sparkline placeholder layout with a row list** consuming `cards["market_momentum_synth"]` (acquisitions / funds / platform-policy / structural / people-moves chips).
   - **Card 6 Community sentiment — replace the aggregate pos/neu/neg bar + top-threads placeholder** with the synthesized narrative + "Reddit is heated about" / "Reddit is celebrating" two-list layout from `cards["community_synth"]`.
   - **Card 7 Risks — drop the `gc-risk-trend` span** (now always reads "stable").
   - **Card 8 Studio watch + Card 9 Storefronts — DROP** (locked: folded into MM).
   - **Card 10 Esports — replace the top_stream/big_event/movers placeholder with a row list** consuming `cards["esports_synth"]`.
   - **Sidebar nav: drop Watchlist / Trends-nav / All-stories / Archive** (locked: 4 routes only).
   - **Sidebar corpus-stats user block** instead of the user-avatar.
   - **Drop the standalone headline block above the grid** (locked: redundant with Biggest title + exec-summary).
   - **Drop the footer hint block** (locked).
   - **Drop the header layout/density/theme toggles** (locked: variants are static).
2. **Phase 3c.6 (formerly 3d) — Markdown / HTML export.** Render `weekly_reports.markdown_content` from the synthesis JSON + a standalone-HTML view with inlined CSS for the export button.
3. **Optional hygiene (not blocking):**
   - Drop the 63 legacy `week_id='all'` cluster rows (now that 55 per-week clusters cover the same content with Sonnet labels).
   - Run synthesis on W17 + W18 to backfill the historical archive (~$1.80 additional spend).
   - Taxonomy drift audit in `_filter_genres` / `_filter_platforms`.
   - Numeral-variant dedupe (Diablo IV ↔ Diablo 4).
   - Series-as-game cleanup.
   - `Summer Game Fest = 1` casing-variant investigation (Phase 3c.3 finding).

**Open / blocked:**
- Phase 3c.5 layout restructure to 9 cards — next session's main work.
- W17 / W18 synthesis backfill — cheap to add; the data is just placeholder for those weeks today.
- Phase 4 — APScheduler Monday-morning auto-run of synthesis. Not blocking 3c.5 since synthesis can be triggered manually via `scripts/run_synthesis.py`.

---

## 2026-05-13 (Phase 3c.3) — Source drawer + Exec-summary modal port

**Done:**
- **DB migration shipped.** `app/db/init.py` `_migrate_weekly_reports_columns()` (idempotent, mirrors `_migrate_games_columns()`) adds three columns to `weekly_reports`: `exec_summary_text TEXT`, `exec_summary_model TEXT`, `exec_summary_generated_at TIMESTAMP`. `WeeklyReport` SQLModel extended in `app/db/models.py`.
- **`app/services/reports.py` extended.** New public `items_for_entity_in_week(session, kind, value, week_id, limit=25) -> list[dict]` with `kind ∈ {game, genre, platform, event}` — backs the drawer. Each row carries id / title / url / published_at / when_display / tldr / sentiment_score / sentiment_summary / category / source_name / source_kind. Reuses existing `json_each` patterns; nothing new at the SQL layer. Helpers: `_drawer_source_kind()` (router-side mapping in one place) and `_relative_when()` ("3 d ago" formatting).
- **`app/services/exec_summary.py` (new module).** `get_or_generate(session, week_id, force=False) -> dict`. Lazy Haiku 4.5 call on cache miss + persistence to `weekly_reports`. `_build_input_text()` assembles a compact prompt body from existing `services.reports` queries (week_stats, top genres / platforms / games, Trends risers, upcoming releases — no new aggregation duplicated). `_call_haiku()` wraps `client.messages.create()` with prompt-cached system block. System prompt forbids fabrication, requires 3-5 sentences naming the strongest concrete signal first, drops marketing-voice and first/second person.
- **`app/config.py` addition.** `ANTHROPIC_EXEC_SUMMARY_MODEL` env-overridable, defaults to `claude-haiku-4-5`. Kept separate from `ANTHROPIC_ENRICH_MODEL` so 3c.4 can swap independently if we ever revisit.
- **`app/routers/reports.py` extended.** Two new endpoints: `GET /reports/drawer?kind=&value=&week=` rendering `_drawer.html`; `GET /reports/exec-summary?week=` rendering `_exec_summary.html`. Both gracefully degrade on bad inputs via an `error` flag in the fragment context. Main `/reports` context now carries `active_week_key` so trigger URLs interpolate cleanly.
- **`app/templates/_drawer.html` + `_exec_summary.html` (new).** Drawer fragment: header (kind eyebrow + entity name + items + week), body (article cards with `source_pill` macro + when + title + tldr + outbound link), footer placeholder note. Modal fragment: header (eyebrow + week label), body (single `<p class="gc-exec-paragraph">`), footer attribution (`fresh|cached · model · generated-at`).
- **`app/templates/reports.html` rewired.**
   - HTMX 2.0.3 `<script>` added to `<head>` (the page is standalone — doesn't extend `base.html` — so HTMX has to load here).
   - Four hidden state radios as direct children of `<body>` before `.gc-shell`: `drawer-closed` (checked), `drawer-open`, `modal-closed` (checked), `modal-open`. Drawer overlay + panel + close button + body wrap shell, and modal overlay + card + close button + body wrap shell, as direct children of `<body>` after `.gc-shell` — so `:checked ~ .panel` sibling selectors work.
   - Three exec-summary triggers (sidebar `.gc-sb-cta`, header `.gc-cta`, footer `.gc-ghost-btn`) rewritten as `<label for="modal-open" hx-get="/reports/exec-summary?week={{ active_week_key }}" hx-target="#exec-summary-body" hx-swap="innerHTML">`. Existing classes carry the styling; `<label>` just inherits the visual.
   - `hot_rows()` macro rewritten — outer row is now `<label class="gc-row gc-row--hottest gc-row-trigger" for="drawer-open" hx-get="/reports/drawer?kind=game&value={{ g.name|urlencode }}&week={{ active_week_key }}" hx-target="#source-drawer-body">`.
   - `trend_rows()` macro takes a new `kind` parameter (game / genre / platform / event); the Trends card calls it five times with the right kind per tab (games_current → game, games_upcoming → game, genres → genre, platforms → platform, live_service → game, events → event).
   - Releases row rewritten as a `<label>` trigger with `kind=game`.
- **`app/static/app.css` extended.** New block at end: `.gc-overlay-state` (hidden radio), `.gc-drawer-overlay` / `.gc-drawer-panel` / `.gc-drawer-close` / `.gc-drawer-header` / `.gc-drawer-title` / `.gc-drawer-meta` / `.gc-drawer-body-wrap` / `.gc-drawer-body` / `.gc-drawer-item` / `.gc-drawer-item-head` / `.gc-drawer-item-when` / `.gc-drawer-item-title` / `.gc-drawer-item-tldr` / `.gc-drawer-footer` / `.gc-drawer-foot-note`; mirror set for `.gc-modal-*`; `.gc-row-trigger` cursor + hover-tint shared between Hottest / Trends / Releases. `:checked ~ ` selectors on `#drawer-open` and `#modal-open` reveal each panel. Overlays use `opacity` + `pointer-events` so backdrop clicks still close. `@media (prefers-reduced-motion: reduce)` disables transitions. HTMX `htmx-request` class on the panel drives a "loading…" / "Generating…" hint inside the panel body during the fetch.
- **Verified end-to-end on `:8001`.** Restarted uvicorn with `--reload` (prior process didn't have reload set and the stale router code was serving stale 404s on the new endpoints).
   - `/reports?week=2026-W19` 200, 55 drawer triggers + 3 modal triggers + both shells present.
   - `/reports/drawer?kind=game&value=Mixtape&week=2026-W19` 200, 15 items.
   - `/reports/drawer?kind=genre&value=Action&week=2026-W19` 200, 25 items. `kind=platform&value=PC` 25 items. `kind=event&value=Summer%20Game%20Fest` 1 item. `kind=game&value=BadGameThatDoesntExist` 0 items + empty-state row. `kind=bogus&value=x` returns the fragment with the `error` flag.
   - `/reports/exec-summary?week=2026-W19` first call 5.5s (Haiku cache miss, 1 API call), second call 2.1s (DB cache hit, footer reads `cached · claude-haiku-4-5`). DB row: `week_start=2026-05-04`, `exec_summary_text` 635 chars, `model=claude-haiku-4-5`, `generated_at` populated.
   - Sample paragraph (W19): "Star Fox dominated gaming coverage this week with 20 mentions and a 3.1 percentage-point rise, driven by anticipation ahead of its June 25 release, while the remaster Star Fox 64 drew 12 mentions and a 2.2pp gain. Action and Adventure genres led discussion across 98 and 56 stories respectively, with PC platforms commanding 121 mentions and both Xbox and Nintendo platforms gaining ground week-over-week. Near-term attention is shifting toward May's release slate, including Thick As Thieves on May 20 and Batman & Robin on May 22, while MMO sentiment climbed 4.4pp with EVE Online picking up mentions alongside live-service tracking." Specific names, specific numbers, no fabrication, 3 sentences.

**Decided / verified (full rationale in DECISIONS 2026-05-13 Phase 3c.3 entry):**
- **Drawer orientation: entity-drill, not source-drill.** Bundle's source-keyed drawer flipped to entity-keyed (game / genre / platform / event); source pills inside the drawer items give back the outbound-source affordance.
- **Drawer scope this phase: Trends + Releases + Hottest.** Biggest / Momentum / Risks drawer wiring deferred to 3c.4 — their data is still placeholder.
- **Toggle: hidden radio + `<label for>` (CSS-only state).** Rejected `:target` URL fragments after realizing HTMX `hx-get` on `<a>` `preventDefault`s the click and suppresses native hash navigation. Radios + labels also avoid hash pollution and history-stack growth.
- **Exec-summary model: Haiku 4.5.** Cost ~$0.001 per cache miss; one call per week.
- **Exec-summary persistence: three new columns on `weekly_reports`** — separate `exec_summaries` table rejected (table already owns the week-grain; Phase 3c.4 will fill `markdown_content`/`html_content` on the same row).

**State at end of session:**
- Modified files: `app/db/models.py` (+3 fields on `WeeklyReport`), `app/db/init.py` (+ `_migrate_weekly_reports_columns()`, called from `init_db()`), `app/services/reports.py` (+ `items_for_entity_in_week` + helpers `_drawer_source_kind` / `_relative_when` + `_DRAWER_KINDS` const, ~135 new lines), `app/routers/reports.py` (+ 2 endpoints, + `active_week_key` in context, ~95 new lines), `app/templates/reports.html` (HTMX `<script>`, 4 state radios, drawer + modal shells, 4 macro/row rewrites for triggers — ~70 net new lines), `app/static/app.css` (+ drawer + modal + trigger block, ~210 new lines), `app/config.py` (+1 env-overridable model name).
- New files: `app/services/exec_summary.py` (~135 lines), `app/templates/_drawer.html`, `app/templates/_exec_summary.html`.
- Docs updated: `docs/DECISIONS.md` 2026-05-13 (Phase 3c.3 shipped) entry, `docs/TASKS.md` 3c.3 boxes ticked, `CHANGELOG.md` Unreleased / Phase 3c.3 entry, this entry.
- Corpus state unchanged from Phase 3c.2 (988 items · 887 Haiku-enriched + 13 preserved-qwen + 88 skipped · 900 embeddings · 184 games dim · 55 per-week clusters + 63 legacy `week_id='all'`).
- `weekly_reports` table now has 1 row from the smoke test: `week_start=2026-05-04` (W19), 635-char exec summary, `model=claude-haiku-4-5`, `generated_at=2026-05-13 15:48 UTC`.
- Test uvicorn server running on `:8001` (background process from this session; PID 17020 + reloader 38660). User's `:8000` instance still has stale router code from earlier phases — restart if they want the new endpoints there.
- Anthropic spend this session: 1 Haiku call (~$0.001). Cumulative project ~$6.16.

**Surfaced for next session — `Summer Game Fest` event count:**
- The drawer for `kind=event&value=Summer Game Fest` returned 1 item this week. Worth checking whether the corpus actually has only 1 SGF mention or whether casing / phrasing variants split the count (e.g. `Summer Game Fest` vs `SGF` vs `Summer Game Fest 2026`). Low priority; not blocking 3c.4.
- Same taxonomy-drift caveat noted in Phase 3c.2 still applies (`MMO` / `Indie/Roguelike` / `Multi-platform` in genres / platforms).

**Next session should:**
1. **Phase 3c.4 — synthesis.** `app/services/synthesis.py` calling Opus 4.7 with prompt-cached system block. Second Opus call for the critic pass. Migrate `label_cluster()` to Sonnet 4.6 (still deferred from 3c.0.5 / 3c.2 / 3c.3). With synthesis in place, the Biggest / Momentum / Risks placeholders become real; THEN wire their drawers (the radio + label trigger pattern from 3c.3 carries straight over).
2. **Phase 3c.5 — wire `/reports` to real synthesized data** and apply every remaining locked layout change (drop Card 1 if walkthrough still asks; fold Studio Watch + Storefronts into Market Momentum; etc.).
3. **Optional hygiene (not blocking):**
   - Audit `_filter_genres` / `_filter_platforms` validators in `app/services/ollama.py` against the Haiku enrichment path. Either fix or expand the locked taxonomies.
   - Investigate the `Summer Game Fest = 1` count above.
   - Numeral-variant dedupe (Diablo IV ↔ Diablo 4, Endfield ↔ Arknights: Endfield).
   - Series-as-game cleanup.
   - 63 legacy `week_id='all'` cluster cleanup.

**Open / blocked:**
- Per-cluster synthesis text (`clusters.synthesis_text` or similar) — Phase 3c.4. Drawer footer note already references this.
- Biggest / Momentum / Risks drawer wiring — Phase 3c.4 (waits on real data).
- Sonnet 4.6 `label_cluster()` migration — Phase 3c.4.
- Opus 4.7 synthesis prompt + critic pass — Phase 3c.4.

---

## 2026-05-13 (Phase 3c.2) — Trends card: 5-tab WoW mention-rate delta

**Done:**
- **`app/services/reports.py` extended** with `prev_week_id()`, `week_item_total()`, three count helpers (`_tag_counts_for_week`, `_game_counts_for_week(lifecycle=, live_service_only=)`, `_event_counts_for_week`), a generic `_merge_wow()` that computes signed percentage-point rate deltas and returns top-N rows, plus five public `top_*_wow()` queries and a single `trends_for_week()` aggregator. Rate-delta math: `(count_this / total_this - count_prev / total_prev) * 100`. Sort is signed DESC so risers dominate; falling-and-gone entries (`count_this == 0`) are filtered out.
- **`app/routers/reports.py` wired** to the new aggregator — `_build_week_payload()` adds `cards["trends"] = trends_for_week(session, week_id, limit=5)`; the empty-corpus fallback gets a defensive `{"has_prior": False}` so the empty-state path still renders. Old `"trends": {"wow": [...], "mom": []}` placeholder dropped from `_PLACEHOLDER_OTHER`.
- **`app/templates/reports.html` Card 5 rewritten** — replaced the single-list `gc-row--trend` block + WoW/MoM segmented toolbar with a 5-tab CSS-only radio structure. Inputs: `trend-tab-games` (checked), `-genres`, `-platforms`, `-liveservice`, `-events`. Games tab has stacked Current + Upcoming sub-sections via `.gc-trend-subhead` mini-eyebrows. Each row uses a `trend_rows(rows)` macro emitting `gc-row--trend` with `gc-trend-name` (with `count this week · prev prior` title tooltip) and the existing `delta()` macro for the `+X.Xpp ▲` widget. Per-tab `gc-row-empty` for sparse states; full-card empty state ("Need 2 weeks of data to compute WoW deltas.") if `has_prior` is False.
- **`app/static/app.css` updated** — added `.gc-trend-tabs { position: relative; }` plus five `#trend-tab-*:checked ~ .gc-tab-labels label[...]` rules (active styling) and five `:checked ~ .gc-tab-panes .gc-tab-pane--*` rules (pane display). New `.gc-trend-subhead` (+ `--second` variant) for the stacked Games sub-headers. New `.gc-trend-name` for the row name span. Deleted the legacy `.gc-trend-tabs button` / `.gc-trend-tabs button.is-active` rules. Global `.gc-tab-input` / `.gc-tab-labels` / `.gc-tab-label` / `.gc-tab-pane` rules (from Phase 3c.1) reused unchanged.
- **Verified end-to-end on `:8001`.** W19/W18/W17 all return 200. Real data sample (W19 Games-Current): Mixtape 15 mentions (+2.7pp), LEGO Batman 10 (+1.8pp), EVE Online 7 (+1.3pp), Civilization 7 (+1.1pp). W19 Genres top: MMO 30 mentions (+4.4pp), Action 98 (+1.9pp). W19 Platforms: Xbox 48 (+2.9pp), Nintendo 34 (+2.5pp), PC -2.4pp (down — share fell despite raw count growth, exactly what rate-delta surfaces). W17 has prior W16 (20 items) so `has_prior=True` even for the earliest visible cluster week — full-card empty state is reachable only via the empty-corpus fallback.

**Decided / verified:**
- **Mention-rate delta locked over raw count delta** per user choice — week-volume swings (W17:W18:W19 ≈ 89:189:551 items) would let a busy week win every "biggest mover" ranking under raw count. Rate-delta normalizes that out.
- **New entries (no prior-week mentions) included** — surface naturally with delta = full this-week rate. Rejected alternative was filtering to entities present in both weeks; loses the most useful Trends signal.
- **CSS-only radio tabs** — mirror Phase 3c.1's `.gc-hot-tabs` pattern exactly, no JS / no HTMX call. 5 tabs scoped via `#trend-tab-*` ids alongside the existing `#hot-tab-*` ids; global tab rules (input/labels/label/pane) work for both.
- **Click-to-drawer deferred to Phase 3c.3.** The original Phase 3c.2 task line mentioned "click-to-drawer where applicable" but the Source Drawer port is itself a separate phase — no drawer infra exists yet, so trend rows are plain rows for now. Will re-wire in 3c.3.

**State at end of session:**
- Modified files: `app/services/reports.py` (+~180 lines: helpers + queries + aggregator), `app/routers/reports.py` (1 placeholder dict trim, 1 trends_for_week wire-up, 1 empty-corpus fallback line), `app/templates/reports.html` (Card 5 replaced, ~45 lines), `app/static/app.css` (Trends tabs block replaced, +24 lines of new rules - 7 lines of deleted button rules).
- Docs updated: `docs/DECISIONS.md` 2026-05-13 entry, `docs/TASKS.md` Phase 3c.2 ticked, this entry.
- Corpus state unchanged (no ingest/enrich/cluster runs this session).
- Test uvicorn server still running on `:8001` (background process from this session). No Anthropic spend.

**Surfaced for next session — taxonomy drift in enrichments tags:**
- Genres column has out-of-taxonomy values (`MMO`, `Indie/Roguelike`, `Survival-horror`, `Multi-platform`) despite the locked 12-genre list. Platforms column has `Multi-platform` despite the locked 6-platform list. Visible right now in W19 Genres tab (MMO is #1) and W19 Platforms tab (Multi-platform shows).
- Likely cause: Pydantic field validators in `app/services/ollama.py` were the safety net, but the Phase 3c.0.5 Haiku migration may not have wired them through correctly, or Haiku's outputs slip past them. Either fix the validators + re-enrich, or expand the taxonomy lists. Both feasible; the second is faster, the first is more honest to the original design.
- Not blocking 3c.3 / 3c.4. Flag in the OPEN_QUESTIONS.md as an optional hygiene pass.

**Next session should:**
1. **Phase 3c.3 — port Source Drawer + Exec-summary modal** from `.tmp_design_bundle/`. Wire bullet/row clicks on Biggest / Momentum / Risks / Trends / Releases to the drawer; modal hosts a second Anthropic call producing a 1-paragraph tldr of the week.
2. **Phase 3c.4 — synthesis.** `app/services/synthesis.py` calling Opus 4.7 with prompt-cached system block. Second Opus call for the critic pass. Migrate `label_cluster()` to Sonnet 4.6 (deferred from 3c.0.5).
3. **Phase 3c.5 — wire `/reports` to real synthesized data** and apply every remaining locked layout change.
4. **Optional hygiene (not blocking):**
   - Audit `_filter_genres` / `_filter_platforms` validators in `app/services/ollama.py` against the Haiku enrichment path — confirm they actually drop out-of-taxonomy values, fix if not, then re-enrich. OR expand the locked taxonomies to cover `MMO` / `Indie/Roguelike` / `Survival-horror` / `Multi-platform`.
   - Numeral-variant dedupe (Diablo IV ↔ Diablo 4, Endfield ↔ Arknights: Endfield).
   - Series-as-game cleanup.
   - 63 legacy `week_id='all'` clusters.

**Open / blocked:**
- Source Drawer + Exec-summary modal port — Phase 3c.3.
- Opus 4.7 synthesis prompt + critic pass — Phase 3c.4.
- Sonnet 4.6 cluster labels — bundled into Phase 3c.4.
- Taxonomy drift in genres/platforms columns — surfaced today, not fixed.

---

## 2026-05-12 (Phase 3c.1) — Real-data wiring for Week / Hottest / Releases + corpus-context retag

**Done:**
- **Schema migration:** `games.release_date TEXT NULL` column added via new `_migrate_games_columns()` helper in `app/db/init.py`. `Game` SQLModel extended in `app/db/models.py`. Idempotent.
- **`app/services/reports.py` shipped** — per-ISO-week aggregation module with `iso_week_bounds()` (Python `datetime.fromisocalendar`, avoids SQLite strftime portability concerns), `week_label_and_range()`, `week_stats()`, `top_genres_for_week()` / `top_platforms_for_week()` (generic `_tagcount_for_week(col, ...)`), `top_games_for_week(lifecycle=None|'existing'|'upcoming')`, `upcoming_releases()`, `format_release_date()`, `is_future_or_unknown()`. All `entities.games` queries are case-insensitive on both join + group sides.
- **`app/routers/reports.py` rewritten** — replaces the hardcoded `WEEKS_RAW` placeholder with DB-driven per-week payloads via `_build_week_payload(session, week_id)`. Three real-data overlays on top of a shared `_PLACEHOLDER_OTHER` dict reused for every week (Phase 3c.4 will fill the other cards with synthesis). Header refreshed-at pulls from `run_log` MAX(`completed_at`). Source-pill kinds derived from `sources.type` + URL prefix instead of a hardcoded map. Empty-corpus fallback added.
- **Template `app/templates/reports.html` updated** — Card 1 (top genres + top platforms bar stacks, no sentiment, no threads stat), Card 3 (`gc-hot-tabs` 3-tab CSS-only structure with `{{ hot_rows(rows) }}` macro), Card 11 (date + name only, `Calendar →` action link).
- **CSS `app/static/app.css` updated** — `.gc-row--hottest` grid `20px 1fr auto auto` → `20px 1fr auto`; `.gc-row--release` grid `60px 1fr 80px` → `60px 1fr`; new `.gc-chip` + variants (`--platform`, `--lifecycle-existing`, `--lifecycle-upcoming`, `--service`); new `.gc-row-count`; new `.gc-row-empty`; new `.gc-hot-tabs` + radio-driven tab toggling via `:checked ~ .sibling` selectors; `.gc-bars-spacer` for Card 1.
- **IGN `/upcoming/games` extraction attempted, abandoned** — page is React/Next.js hydrated. Only 1 of 5 sample upcoming games (Subnautica 2) appeared in the static HTML, at byte position 388K. Truncating to 160K chars cut it off, and the full page (~2.9MB) exceeds Haiku's 200K context.
- **Pivoted to corpus-context date extraction.** `scripts/extract_release_dates.py` rewritten — per-game Haiku call with 8–10 recent article titles + tldrs from items mentioning the game. 28 upcoming-tagged games → 10 got dates. ~$0.10.
- **Mid-session: lifecycle errors surfaced** (Crimson Desert in upcoming, Civilization 7 / Subnautica 2 / Clair Obscur 33 / etc. all wrongly tagged upcoming). Root cause: original `populate_games_dim.py` + `tag_game()` passed only the game name; Haiku's Jan-2026 training cutoff couldn't see post-cutoff launches. → User approved corpus-context retag.
- **`scripts/retag_games_with_context.py` shipped + run.** Per-game Haiku call with 8–10 article snippets; system prompt explicitly forbids overriding article evidence with training knowledge. 189 games processed, 129 updated, 60 unchanged, 0 errors, 264s wall-clock, ~$1.00 spend. Lifecycle 131/28/30 (existing/upcoming/null) → 109/44/36. 50 games now have `release_date`.
- **8 manual `live_service=false` flips** post-retag: Civilization 7, Dead Cells, Phasmophobia, MindsEye, Magic: The Gathering, Dungeons & Dragons, Battlefield 4, The Sims 4 — none are battle-pass / season-pass games; Haiku's live-service definition over-counted "regular updates." Plus Crimson Desert ("MMO-style support model" ≠ live-service economy). 57 → 49 rows.
- **`scripts/dedupe_games_dim.py` shipped + run.** 5 case-fold duplicate pairs collapsed (EVE Online, GreedFall, Invincible VS, LEGO Batman, Thick As Thieves). Canonical chosen by most-mentioned casing in `entities.games`; metadata COALESCEd. Dim 189 → 184 rows. Queries now case-insensitive on the article side so future casing variants ("Mixtape"/"MIXTAPE", "BioShock"/"Bioshock") collapse without further dedupe.
- **Drop the "existing" chip from Card 3** per user call: "if nothing is mentioned that means it is current." Only `upcoming` lifecycle chip + `live-service` chip render now.

**State at end of session:**
- New files: `app/services/reports.py`, `scripts/extract_release_dates.py`, `scripts/retag_games_with_context.py`, `scripts/dedupe_games_dim.py`. Test HTML dumps in working dir (`reports_v*.html`).
- Modified files: `app/db/init.py` (+ `_migrate_games_columns`), `app/db/models.py` (+ `Game.release_date`), `app/routers/reports.py` (full rewrite), `app/templates/reports.html` (Cards 1/3/11), `app/static/app.css` (grid columns + chips + tabs + spacer).
- Logs: `logs/extract_release_dates_2026-05-12_v2.log`, `logs/retag_games_2026-05-12.log`.
- Corpus state: 988 items · 887 Haiku-enriched + 13 preserved-qwen + 88 skipped · 900 embeddings · **184 games in dim** (was 189; -5 case-dedupe) · **109 existing / 44 upcoming / 36 NULL-lifecycle** · **49 live-service** · **50 games with release_date**. Per-ISO-week clusters unchanged (W17:4 / W18:13 / W19:38 + 63 legacy `all`).
- Session spend: ~$1.15 Anthropic (cumulative project: ~$6.15, well under $500/yr ceiling).
- Test uvicorn server running on `:8001`. The user's existing `:8000` instance returns 500 on `/reports` because it has stale router code — needs restart to pick up Phase 3c.1.

**Decided / verified:**
- **Card 1 keep + extend** (overrode the walkthrough drop) — sidebar shows corpus stats, Card 1 shows per-week breakdown; different surfaces. Net-sentiment block dropped mid-session per user call.
- **Card 3 Hottest tabs** — 3 tabs (All / Current / Upcoming), CSS-only radio toggling. Each tab's top-5 is a separate query against `top_games_for_week(lifecycle=...)`. No JS, no HTMX call.
- **Existing chip explicitly dropped** — "existing" is the default state; only "upcoming" gets a visible chip. NULL-lifecycle treated as default-current.
- **Card 11 Release radar simplified** to date + name only; future-date filter; `Calendar →` link to IGN as canonical reference (since corpus dates are spotty and IGN curates the upcoming calendar).
- **Corpus context > training memory** for game tagging — the retag prompt explicitly instructs Haiku not to override article evidence with training knowledge. Confirmed effective: post-retag, only post-2026-05-12 launches stayed in `upcoming`.

**Next session should:**
1. **Phase 3c.2 — build the Trends card** (5-tab layout: Games existing+upcoming / Genres / Platforms / Live-service / Events; WoW only; top-N by mention-rate delta).
2. **Phase 3c.3 — port Source Drawer + Exec-summary modal** from `.tmp_design_bundle/`.
3. **Phase 3c.4 — synthesis.** `app/services/synthesis.py` calling Opus 4.7 with prompt-cached system block. Second Opus call for the critic pass. Migrate `label_cluster()` to Sonnet 4.6 (deferred from 3c.0.5).
4. **Phase 3c.5 — wire `/reports` to real synthesized data** and apply every remaining locked layout change.
5. **Optional data hygiene before 3c.4:**
   - Numeral-variant dedupe (Diablo IV ↔ Diablo 4, Endfield ↔ Arknights: Endfield).
   - Series-as-game cleanup (drop "Resident Evil" / "The Witcher" / "Sonic the Hedgehog" / etc. franchise rows from dim).
   - 13 preserved-qwen items (from Phase 3c.0.5) still pending — `_rerun_targeted_ids` in `rerun_enrichment.py` still imports from `app.services.ollama`; needs swap to anthropic.
   - 63 legacy `week_id='all'` clusters cleanup decision.

**Open / blocked:**
- Numeral / partial-name dedupe — needs a smarter normalizer. Not blocking 3c.2/3c.3.
- Cluster boundary spanning (stories across 2 ISO weeks → near-duplicate clusters) — still deferred from 2026-05-12 walkthrough.
- Trends "top N" cutoff, empty-state design for sparse Events tab — still open from prior session.
- Sonnet 4.6 cluster labels — bundled into Phase 3c.4.
- Opus 4.7 synthesis prompt + critic pass — Phase 3c.4.

---

## 2026-05-12 — Phase 3c.0.5 SHIPPED: Haiku 4.5 migration, full backfill, games dim, per-week clustering

**Done:**
- **`app/services/anthropic.py` shipped.** Module-level `Anthropic()` client lazy-init (reads `ANTHROPIC_API_KEY` from env). `enrich_item()` mirrors `ollama.enrich_item()` signature exactly — reuses `EnrichmentData` + `SYSTEM_PROMPT` + `_ALLOWED_CATEGORIES` from `app/services/ollama.py` so there's a single source of truth. Calls `client.messages.parse(model=ANTHROPIC_ENRICH_MODEL, max_tokens=2048, output_format=EnrichmentData, ...)` so the SDK returns a validated Pydantic instance directly; field validators (`_filter_genres`, `_filter_platforms`, `_filter_event`) run automatically. Catches `anthropic.APIError` and `ValidationError` and wraps as `ValueError` so the existing `_persist_failed()` path in `enrich.py` works unchanged. Includes `cache_control: {"type": "ephemeral"}` on the system block — SYSTEM_PROMPT is ~855 tokens which is **under** Haiku 4.5's 4096-token minimum cacheable prefix, so caching no-ops harmlessly today. Will activate automatically if the prompt grows past 4096 tokens.
- **`tag_game()` also ported to anthropic.py** mid-backfill. Same pattern: reuses `GameTagData` + `GAME_TAG_SYSTEM_PROMPT` from ollama.py, `max_tokens=128`.
- **One-line swap in `app/services/enrich.py`** — `enrich_item` now imported from `app.services.anthropic` instead of `app.services.ollama`. Everything else (`embed_text`, `extract_video_id`, `fetch_youtube_transcript`, `_body_for_enrichment`, `_persist_ok/_failed/_skipped`, `RunLog`) untouched. One-line swap in `scripts/populate_games_dim.py` too — `tag_game` now from anthropic.
- **`python-dotenv` added as a dep + `.env` loader wired in `app/config.py`.** `load_dotenv(ROOT / ".env")` at module import. `.env` (gitignored) holds `ANTHROPIC_API_KEY=...`; SDK reads it from env. Real env vars take precedence over `.env`.
- **Config additions in `app/config.py`:** `ANTHROPIC_ENRICH_MODEL` (default `claude-haiku-4-5`), `ANTHROPIC_TIMEOUT` (default 120s).
- **10-item Haiku sample (`scripts/sample_haiku_enrichment.py`)** — picks 10 items with priority on the two known-bad cases (Minions movie miscategorization + Reddit-handle leak), then diversifies by category, then fills with newest. Writes side-by-side markdown diff to `docs/SAMPLE_HAIKU_2026-05-12.md`. Does NOT touch the DB. User signed off on the diff before backfill. Both known-bad cases visibly fixed: Minions movie now has `games=[]` + `genres=[]` (was `['Minions & Monsters']` + `['Indie/Roguelike']`); Reddit-handle `Responsible_Box_2422` no longer appears in `entities.people`. Cost: ~$0.04.
- **Full 988-item Haiku backfill.** Default invocation of `scripts/rerun_enrichment.py` (which routes through `enrich_pending(force=True)` → `enrich_module.enrich_item` → now `anthropic.enrich_item`). 39.5 min wall-clock, ~2.4 s/item (faster than the ~5 s/item estimated; matches the sample). **Totals: 988 attempted, 887 OK, 88 skipped (body too short — structural, same as Phase 2), 13 preserved (Haiku returned out-of-taxonomy category like `'guide'` → safety net kept prior valid qwen row), 0 hard failures.** Preservation rate 1.4% — well under the 5% threshold. Estimated spend ~$3-4.
- **Cleared all 899 OK embeddings + re-ran `embed_pending()`.** Necessary because the Haiku-rewritten tldrs are different text from the qwen tldrs the embeddings were originally computed on. Took 37 min (~2.5 s/item), 900/900 OK, 0 failed.
- **`populate_games_dim.py` executed.** 189 unique games (min_mentions=2 default) tagged via Haiku `tag_game()`. 3.6 min, 0 failed. Distribution: 131 existing / 28 upcoming / 30 null-unknown; 55 live_service=true. Sample spot-check: Aliens: FE / FE 2 split correctly between existing+upcoming, Among Us flagged live-service, MMOs (Allods Online) correctly live-service. ~$0.60 spend.
- **`run_cluster.py --per-week` executed.** 55 new clusters across `2026-W17` (4 clusters), `W18` (13), `W19` (38). 4.5 min wall-clock. 0 label failures — every cluster got a qwen-generated label (label_cluster still on Ollama pending Phase 3c.4). Earlier weeks (W12-W16) had too few items to form clusters at threshold 0.85. **Top scorers still from the legacy `week_id='all'` set** because the per-week corpora are smaller so `source_count × member_count` is lower. Cleanup of the 63 legacy 'all' rows deferred — user will decide.

**Decided / verified:**
- **Trust-Haiku over force-required-fields** for the new genres/platforms/event tags. Trade-off accepted: simpler schema, faster iteration; safety net (Pydantic validators) handles any out-of-taxonomy values. The sample confirmed Haiku honors the taxonomies cleanly without strict-mode forcing.
- **Swap-not-flag integration.** No `ENRICH_PROVIDER` config flag; ollama.enrich_item left in place only as the source of truth for shared types (`EnrichmentData`, `SYSTEM_PROMPT`, validators).
- **Side-by-side markdown diff** for sample review preferred over terminal scroll or summary-only — matches the user's walkthrough preference.
- **Prompt caching on system block is correct in principle** even though the current prompt is under the cache threshold. The architecture is forward-compatible; if SYSTEM_PROMPT grows past 4096 tokens in a later phase, caching activates automatically with no code change.

**State at end of session:**
- New files: `app/services/anthropic.py`, `.env` (gitignored), `scripts/sample_haiku_enrichment.py`, `docs/SAMPLE_HAIKU_2026-05-12.md` (the sample diff).
- Modified files: `app/services/enrich.py` (one-line import swap), `app/config.py` (dotenv loader + Anthropic env vars), `scripts/populate_games_dim.py` (one-line import swap + docstring), `pyproject.toml` (+python-dotenv).
- Logs (gitignored): `logs/haiku_backfill_2026-05-12.log`, `logs/reembed_2026-05-12.log`, `logs/games_dim_2026-05-12.log`, `logs/cluster_per_week_2026-05-12.log`.
- DB state: 887 Haiku-enriched + 13 preserved-qwen + 88 skipped enrichments; 900 fresh embeddings; 189 rows in `games` dim; 55 new per-week clusters + 63 legacy `week_id='all'` clusters.
- Anthropic SDK 0.100.0 already installed; `anthropic>=0.40` in pyproject covers it. `python-dotenv` 1.2.2 confirmed installed.
- All Phase 3c.0.5 changes intentionally uncommitted in the working tree per prior-session convention.

**Next session should:**
1. **Phase 3c.1 — revisit dropped/trimmed data with the new tag dimensions.**
   - Restore platform + lifecycle chips on the Hottest card (was trimmed pre-tagging on 2026-05-12 walkthrough).
   - Add structured release-date extraction on the Releases card from the upcoming-tagged games in the `games` dim.
   - Re-evaluate the Card 1 "this week in gaming" overview (dropped in walkthrough) — top-genres + top-platforms is now real data, not fabrication.
2. **Decide the cleanup of the 63 legacy `week_id='all'` clusters.** They're still authoritative-looking at the top of `/clusters` because Phase 3b's cross-corpus run produced bigger groups. Either delete them (script intent was "replace") or keep both views and update the UI filter to default to per-week.
3. **Phase 3c.2 — build the Trends card** (5-tab layout: Games existing+upcoming / Genres / Platforms / Live-service / Events; WoW only; top-N by mention-rate delta).
4. **Phase 3c.3 — port Source Drawer + Exec-summary modal** from `.tmp_design_bundle/`.
5. **Phase 3c.4 — synthesis.** `app/services/synthesis.py` calling Opus 4.7 with prompt-cached system block. Second Opus call for the critic/editor pass. **Also in Phase 3c.4: migrate `label_cluster()` to Anthropic Sonnet 4.6** (deferred from this session). Both bundled because synthesis quality depends on label quality.
6. **Phase 3c.5 — wire `/reports` to real synthesized data** and apply every locked layout change from the 2026-05-12 walkthrough.
7. **Audit and tighten the 13 preserved-qwen items.** Either re-run them with a wider `_ALLOWED_CATEGORIES` set, or accept them as low-priority residue. Easier path: add `'guide'` (and any other observed-but-rejected categories) to the allowed set, then re-run those 13 via `python scripts/rerun_enrichment.py --ids ...`. But note: `_rerun_targeted_ids` in that script still calls `ollama_enrich_item` directly (line 132) — that path needs an import swap to anthropic before --ids can use Haiku.

**Open / blocked:**
- `_rerun_targeted_ids` in `scripts/rerun_enrichment.py` line 34 still imports `enrich_item as ollama_enrich_item` from `app.services.ollama`. If we ever want to re-do specific items via Haiku, that line needs swapping too. Default no-args path (which is what we used for the backfill) is correctly Haiku-routed via the swapped `enrich_module.enrich_item`.
- Cluster boundary spanning, per-week threshold tuning, empty-state design for sparse Trends tabs — all still open from the prior walkthrough.
- The 13 preserved-qwen items + the open question of whether to widen the category enum.
- Sonnet 4.6 cluster-labels migration — deferred to Phase 3c.4, not blocking anything before then.
- Synthesis prompt / Opus 4.7 / critic pass — deferred to Phase 3c.4.

---

## 2026-05-12 — Phase 3c.0 schema + prompt + code staging; backfill aborted pending Haiku migration

**Done:**
- **Phase 3c.0 schema migration shipped (DONE).** Added `genres TEXT`, `platforms TEXT`, `event TEXT` columns to the `enrichments` table; created a new `games` dim table (`name TEXT PRIMARY KEY`, `lifecycle TEXT`, `live_service INTEGER`). Idempotent migration done by extending the existing `_migrate_enrichments_columns` helper in `app/db/init.py` (mirrors the pattern used for status/error and the clusters migration). Verified via PRAGMA inspection on the DB; ran `init_db()` twice to confirm idempotency (no double-add errors, no spurious changes).
- **Extended Ollama enrichment prompt to cover the 3 new fields (DONE, but with a non-trivial fix mid-session).** First attempt at restructuring the SYSTEM_PROMPT to demand `genres[] / platforms[] / event` failed — qwen2.5:7b silently *omitted* the three new fields from JSON output despite explicit instructions and worked examples. Root cause: `format:"json"` in Ollama's API only constrains output to *valid JSON*, it does not enforce *schema conformance*. **Fix:** switched the call from `format:"json"` to constrained-decoding via passing `EnrichmentData.model_json_schema()` directly as the `format` parameter. Had to override `required` on the schema to include `genres`/`platforms`/`event` because they have Pydantic defaults (Ollama treats absence-with-default as "not required → may omit"). After the fix, all 3 fields appear in every sample. Worked-examples for the locked 12-genre / 6-platform / 12-event-plus-Other taxonomies are in the prompt. Pydantic field validators drop out-of-taxonomy values silently; genres capped at 3.
- **Code staged for steps 4-5 of the next-session plan (DONE, NOT YET EXECUTED):**
  - **`scripts/populate_games_dim.py` (new).** Extracts unique game names from `enrichments.entities` via `json_each` over the games array, filters to games with ≥2 mentions (config-tunable via `--min-mentions`), then idempotently INSERTs a row per game into the new `games` dim table. `tag_game()` will fill `lifecycle` + `live_service` columns. Flags: `--limit N` (cap rows for sanity runs), `--sample` (print first N games + exit without writing), `--min-mentions N` (default 2).
  - **`tag_game()` + `GameTagData` Pydantic model + `_game_tag_json_schema()` helper added to `app/services/ollama.py`.** Pattern mirrors `enrich_item()` — constrained-decoding via the Pydantic schema, dedicated `GAME_TAG_SYSTEM_PROMPT` with the locked lifecycle + live-service fuzzy rules and worked examples. Note: this code is now slated for replacement when per-item enrichment moves to Haiku (see Decided below), but the prompt content is reusable.
  - **`scripts/run_cluster.py` rewritten** with argparse + a new `--per-week` mode. `--per-week` iterates through every ISO week present in `items.published_at` via `datetime.fromisocalendar()` and calls `cluster_window()` per week, replacing the prior `week_id='all'` global clustering. Backward compat preserved: invocation with no args defaults to the legacy `"all"` behavior so prior callers don't break.
- **Files touched this session:** `app/db/models.py` (added `Game` SQLModel class + the 3 enrichment columns), `app/db/init.py` (extended `_migrate_enrichments_columns`, added the games table create), `app/services/ollama.py` (SYSTEM_PROMPT restructure for new fields + JSON-schema enforcement + `GameTagData` + `tag_game()` + `GAME_TAG_SYSTEM_PROMPT`), `scripts/rerun_enrichment.py` (new — backfill driver), `scripts/populate_games_dim.py` (new), `scripts/run_cluster.py` (rewrite with `--per-week`).

**Decided:**
Three Anthropic API expansions adopted, all priced inside the user's stated $500/yr ceiling:
- **Per-item enrichment → Anthropic Haiku 4.5.** Replaces the qwen2.5:7b Ollama path for the per-item enrichment pass. Estimated ~$5–10 one-time for the 988-item backfill + ~$100–200/yr ongoing for ~200 items/week. **This overrides the "Ollama-only for per-item work" architectural lock** from project CLAUDE.md / DECISIONS 2026-05-06 — see DECISIONS 2026-05-12 (later) for the formal entry and the lock-override rationale.
- **Cluster labels → Anthropic Sonnet 4.6.** Replaces `label_cluster()` Ollama path. Sharper editorial titles for the weekly report's cluster surfaces. ~$10/yr ongoing. Synthesis-adjacent — doesn't itself touch the per-item lock.
- **Critic/editor pass on synthesis → second Opus 4.7 call** after the main Opus 4.7 synthesis. Standard pattern for tightening long-form output. ~$100/yr ongoing.
- **Embeddings stay on local Ollama** (`nomic-embed-text` 768-dim). Total Anthropic spend estimate: ~$210–310/yr, comfortably under the $500/yr budget.

Lock-override rationale (concrete evidence, not vibes):
- **Quality:** today's 10-item structured-output sample exposed qwen2.5:7b quality issues that prompt restructure did NOT fix. Reddit username `Responsible_Box_2422` leaked into `entities.people` despite an explicit negative-example prompt rule against underscored handles. The movie *Minions & Monsters* was tagged with `Indie/Roguelike` — clearly not a game. The three new fields had to be forced into output via JSON-schema constrained decoding; "ask nicely in the prompt" wasn't enough.
- **Runtime:** structured-output mode pushed qwen2.5:7b to ~26s/item — extrapolated to ~7 hours for the 988-item backfill, vs the originally-estimated 45 min for the non-constrained call. Haiku at ~5s/item ⇒ ~1.5 hours for the same backfill. 4–5× speedup.
- **Cost:** fits well inside the user's $500/yr ceiling. Tradeoff explicitly acknowledged below.
- **Tradeoff:** core ingest pipeline now depends on a working Anthropic API key + network availability. Personal-local single-user project — acceptable; the Phase 4 weekly auto-run will need the API key in env, and if the key is rotated/expires the weekly ingest halts.

**Aborted / DB state:**
- **Re-enrichment of the 908 ok-enriched backlog was ABORTED mid-run.** Started a full re-enrichment using the new structured-output prompt to fill the 3 new fields. After ~25 items the run was killed because:
  - (a) tqdm ETA showed ~7 hours total, way over the original estimate (the structured-output enforcement halved throughput to ~26s/item);
  - (b) one item (#63) timed out with a ReadTimeout warning;
  - (c) the quality signals enumerated above (Reddit-handle leak, *Minions & Monsters* tag) were already visible in the 10-item sample taken before the full run.
- Background Python process killed cleanly during session wrap. **DB state:** ~25–30 items now have qwen-generated tags from the aborted partial run; the remaining ~860 ok-enriched items still hold their original Phase 2 enrichments unchanged. **No rollback needed** — the next-session Haiku rerun will overwrite all 988 items uniformly, so the partial qwen rewrites are throwaway.

**Next session should:**
1. **Read this entry first** — it supersedes the prior 2026-05-12 walkthrough entry's "Next session should" plan for Phase 3c.0.
2. **Design `app/services/anthropic.py` for Haiku-backed enrichment. Show the user the design BEFORE writing code.** Cover: Anthropic SDK client setup (API key from env, retry/backoff config); prompt caching on the system block (the `system` parameter caches well across calls when stable — see the `claude-api` skill); Pydantic schema use for structured output (Anthropic supports tool-use-style schema enforcement); error handling for transient API failures (rate limits, 5xx); retry policy. **The 988-item backfill is the irreversible spend — wait for sign-off before kicking it off.**
3. **After design sign-off:** implement `anthropic.py`, refactor `enrich_pending` in `app/services/enrich.py` to call Haiku instead of (or alongside, gated by a config flag) the existing Ollama `enrich_item` path. **Keep embeddings on Ollama** — `embed_text()` stays untouched.
4. **10-item Haiku sample first.** Pick 10 items spanning categories + sources, run them through Haiku, eyeball the output side-by-side against the current qwen-generated tags. Get explicit user sign-off before the full backfill.
5. **Run the full 988-item backfill via Haiku** (~1.5 hours estimated, backgrounded).
6. **After backfill completes:** run `scripts/populate_games_dim.py` (staged this session, ready to go — note that `tag_game()` will also want to move to Haiku at that point, but the games-dim population script's structure stays the same) and `scripts/run_cluster.py --per-week` (also staged this session) to land the per-ISO-week clustering that replaces `week_id='all'`.
7. **Decide between Sonnet 4.6 cluster labels and the critic-pass synthesis additions:** these are independent of the Haiku migration. Implement in Phase 3c.4 alongside the main synthesis prompt — not blocking on 3c.0.5.
8. **After everything lands:** update `docs/ARCHITECTURE.md` to reflect the new LLM split. Old split: "Ollama for per-item work, Anthropic for synthesis only." New split: "Ollama for embeddings only (`nomic-embed-text` 768-dim); Anthropic Haiku 4.5 for per-item enrichment; Anthropic Sonnet 4.6 for cluster labels; Anthropic Opus 4.7 for synthesis + critic pass."

**Open / blocked:**
- Anthropic Haiku 4.5 service module — design pending sign-off (next session step 2).
- 988-item Haiku backfill — blocked on the service module + 10-item sample sign-off.
- Games-dim populate run — code staged, blocked on the Haiku backfill completing first (otherwise the games-dim tag pass would run against qwen-tagged enrichments).
- `scripts/run_cluster.py --per-week` execution — also blocked on Haiku backfill (per-week clustering should run against uniform Haiku-enriched corpus).
- `docs/ARCHITECTURE.md` update — deferred until the new LLM split is implemented end-to-end.

---

## 2026-05-12 — /reports section walkthrough + Trends design + tagging foundation committed

**Done:**
- **No app code modified this session.** Pure design pass: walked `/reports` end to end with the user, locked keep/drop/rework for every chrome element + card, designed a real Trends layout, and committed to a tagging-foundation detour that gates the whole synthesis prompt. All decisions enumerated in DECISIONS.md 2026-05-12; this entry narrates the path.
- **Walkthrough order:** sidebar → header → headline strip → 13 cards top-to-bottom → Trends deep-dive → tagging schema implications → re-scope of Phase 3c. Each pass surfaced "this depends on data we don't have" friction that ultimately consolidated into one tagging-foundation milestone (`3c.0`) rather than per-card workarounds.
- **Chrome simplification — strip everything that's fake.** Sidebar nav cut from 6 placeholder `href="#"` items to **4 real routes that actually exist**: Weekly read-out / Dashboard / Clusters / Sources. Sidebar week-list capped at 5 entries scrollable. Sidebar user-block (avatar + name + role) replaced with **corpus stats** (item count / cluster count / last-ingest timestamp) — useful local-only telemetry, not fake-multi-user theatre. Sidebar "Generate exec summary" CTA dropped (duplicates the header CTA). Header layout/density/theme toggles all dropped — variants are locked, the buttons were visual noise. Headline block above the grid (big H1 + dek) dropped entirely — folds into the reworked Biggest card. Footer hint block dropped.
- **Exec-summary feature:** single CTA stays in header right; modal to be PORTED from `.tmp_design_bundle/.../exec-summary.jsx`. Second Anthropic pass for 1-paragraph tldr — adds one synthesis call per generation, acceptable cost.
- **Source Drawer to be PORTED** — right-side slide-in shown on bullet/row click; renders cluster synthesis paragraph + member source links. Layout details (width, animation, click-outside) deferred to implementation time.
- **Cards 13 → 9 (with Trends re-instated as #10):**
  - **Dropped:** Card 1 Overview (overlaps the new sidebar corpus stats), Card 8 Studio Watch (absorbed into Market Momentum), Card 9 Storefronts (absorbed into Market Momentum).
  - **Reworked:** Card 2 Biggest singular → **plural top-3 list**, absorbs the killed headline block, click opens drawer. Card 3 Hottest trimmed to **title + mention count + reason** (platform + lifecycle chips removed — restored later once tagging foundation lands). Card 4 Market Momentum reshaped from 4-platform-sparkline grid (fabricated data) to **row list of clusters**, absorbs Studio Watch + Storefronts content. Card 6 Community Sentiment — **honest reframe, aggregate pos/neu/neg bar removed**, per-cluster polarized lists + narrative on top (rationale: sentiment is tone of Reddit *posts* not community *reaction*; RSS exposes no upvotes so no reach weighting; "41% positive about what?" is topic-anchorless). Card 10 Esports honestly reframed — corpus has 15 news + 10 subreddits + 6 YouTube and **zero Twitch/streamcharts/esports-tracker sources**, so Twitch metrics are fabrication; reframed to **filtered news clusters with esports category**. Card 11 Releases trimmed. Card 12 Drama narrowed to **exec/PR drama only** (avoid community-flamewar bleed). Card 13 Watch — drop reminder button (no notifications plumbed).
  - **Kept ~as-is:** Card 7 Industry Risks (trend chip dropped — no multi-week data yet).
- **Trends card RE-INSTATED via 5-tab layout** (was dropped from Phase 3c on 2026-05-11). Tabs: **Games (sub-blocks: existing + upcoming) / Genres / Platforms / Live-service / Events**. WoW only (MoM dropped for now; revisit if WoW proves insufficient). Ranking is **top-N by *delta*** — explicitly distinct from Hottest's absolute-count ranking, so the two cards don't echo each other. Events tab will frequently be sparse (most weeks have no E3/Summer Game Fest/TGS); accepted, empty-state design deferred.
- **Tagging-foundation detour committed before any synthesis prompt is written.** Net-new schema: 4 tag dimensions across 2 tables — **new `games` dim table** keyed by `name PK` with `lifecycle` + `live_service` columns (per-game, not per-item, so cross-item consistency is structural); **3 new columns on `enrichments`** — `genres TEXT` (JSON list), `platforms TEXT` (JSON list), `event TEXT` (single value or NULL).
- **Three taxonomies locked** (exhaustive lists in DECISIONS.md 2026-05-12):
  - **Genres (12):** Action, Adventure, RPG, Shooter, Strategy, Simulation, Sports, Racing, Fighting, Puzzle, Platformer, Horror. **Multi-value cap = 3** per item.
  - **Platforms (6):** PC, PlayStation, Xbox, Nintendo, Mobile, VR.
  - **Events (12 + Other):** E3, Summer Game Fest, TGS, Gamescom, PAX, GDC, BlizzCon, The Game Awards, Nintendo Direct, State of Play, Xbox Showcase, PlayStation Showcase, Other.
- **Fuzzy rules locked** (necessary because the corpus is real-world messy):
  - **"existing"** = released on ≥1 platform. **Early access counts** as existing. **Remasters are existing** (the original shipped). **Cross-platform-delay still existing** (PS5-only games are "existing" while Xbox port is pending).
  - **"live-service"** = seasonal / battle-pass / league / warbond content model with regular content drops. Not just "has multiplayer."
  - **Out-of-taxonomy values DROPPED, not mapped.** No fuzzy-match to nearest neighbour; validation rejects and field goes empty for that item. Keeps taxonomies honest, avoids semantic drift.
- **WoW baseline strategy:** **re-bin existing 988 items by `published_at` into ISO weeks**, replacing the current `week_id='all'` global clustering. Yields ~4–8 weeks of synthetic history *immediately*, no waiting on Phase 4 APScheduler weekly cuts. Per-week cluster threshold may need re-tuning (smaller per-week corpus → potentially different connectivity profile).
- **Synthesis scope formally widened: PRD-locked 6 sections → 10 sections + exec-summary pass.** Net-new beyond PRD: **Esports** (honestly reframed), **Releases**, **Drama** (narrowed), **Trends** (returned via tagging foundation). Acknowledged as **explicit scope expansion, not oversight**.
- **Visual monotony flagged.** Stripping fabricated charts (Momentum sparklines, Sentiment aggregate bar, Trends bars) left 7–8 cards in the same "row list of clusters" shape. Charts were removed as fabrication risks, not because variety was undesirable. Either accept the monotony or reintroduce **real visual variation** (genre distribution, platform mix, sentiment per cluster) in a later CSS/component pass once the tagging foundation provides honest dimensions to chart against.

**State at end of session:**
- All design decisions LOCKED in `docs/DECISIONS.md` 2026-05-12 (parallel agent enumerating the full lock list — see there for taxonomies, fuzzy rules, and per-card before/after).
- `docs/TASKS.md` re-scoped Phase 3c into **3c.0 → 3c.5** sub-phases (parallel agent).
- **No app code modified this session.** The 2026-05-11-port `/reports` template still renders the 13 placeholder cards with the un-locked layout. None of today's keep/drop/rework changes are applied yet — that's Phase 3c.5.
- `.tmp_design_bundle/` still present in repo root, untracked. **Kept intentionally** — needed for Source Drawer + Exec-summary modal porting in Phase 3c.3.
- Phase 3a + 3b + 3c-design-port code remains uncommitted in the working tree per prior-session convention.

**Next session should:**
1. **Phase 3c.0 schema migration first.** Add `enrichments.genres TEXT`, `enrichments.platforms TEXT`, `enrichments.event TEXT`. Create new `games` dim table (`name TEXT PRIMARY KEY`, `lifecycle TEXT`, `live_service INTEGER`). Idempotent migration in `app/db/init.py` mirroring the existing `_migrate_enrichments_columns` / `_migrate_clusters_columns` pattern.
2. **Extend Ollama enrichment prompt** with the three new structured fields + worked examples drawn from the locked taxonomies. JSON-mode schema additions. **Validation drops out-of-taxonomy values** (don't fuzzy-map).
3. **Re-enrich the 908-item backlog** with new fields. ~30–45 min on RTX 5070 based on Phase 2 timings.
4. **Populate `games` dim table.** Extract unique names from `entities.games` across all enrichments; separate Ollama pass tags each game's `lifecycle` + `live_service` using the locked fuzzy rules. Per-game pass (not per-item) so a game referenced by 20 clusters gets tagged once consistently.
5. **Re-bin into ISO weeks + re-cluster per-week** to replace `week_id='all'`. Per-week threshold may need tuning — start at 0.85 and inspect.
6. **Phase 3c.1 revisits** with real tag data: restore platform + lifecycle chips on Hottest; structured release-date on Releases; **re-evaluate Card 1 "overview"** (was dropped today) now that top-genres is actual data, not fabrication.
7. **Phase 3c.2 build Trends card** (5-tab layout, top-N by WoW delta).
8. **Phase 3c.3 port Source Drawer + Exec-summary modal** from `.tmp_design_bundle/`.
9. **Phase 3c.4 write synthesis prompt + service.** Opus 4.7. Schema covers 10 sections + exec-summary pass. First run on most-recent ISO week.
10. **Phase 3c.5 wire `/reports` to real synthesized data** and apply every locked layout change from this session (sidebar trim, chrome strip, card rework, headline removal, footer removal).

**Open / blocked:**
- Source Drawer layout details — right-panel width, animation timing, click-outside behavior, content density. Decide at implementation time in 3c.3.
- Exec-summary modal layout — just the 1-paragraph summary, or the full report alongside the summary? Decide in 3c.3.
- Per-week clustering parameter tuning — threshold (currently 0.85) may need revisit for smaller per-week corpora; can't tell until re-binning runs.
- Cluster boundary-spanning de-duplication — stories that span 2 ISO weeks will produce two near-identical clusters; needs handling but deferred until first re-bin run shows scale of the problem.
- Trends "top N" cutoff per tab — likely 5 but depends on how cleanly deltas separate.
- Empty-state designs for sparse tabs (Events especially — most weeks have nothing).
- Phase 3c synthesis prompt + service — **gated on the entire 3c.0 tagging foundation completing first**. Cannot start 3c.4 until the schema, prompt extension, re-enrichment, games dim, and ISO-week re-bin are all done.

---

## 2026-05-11 — Phase 3c design locks + claude.ai/design ported to /reports

**Done:**
- **Three Phase 3c locks taken before any synthesis code was written** (per the prior session's gating checklist):
  1. **Industry-risks rubric — "standard" scope:** layoffs/closures + regulation/legal/policy. Excludes broader market structural shifts (acquisitions, funds, platform-side policy) — those live in Market Momentum to keep section boundaries clean. Mirrors the actual signal in the ranked 63-cluster corpus (Spiders studio closure, WotC union deadline, Sony PlayStation Store settlement, Stop Killing Games petition).
  2. **Community-sentiment rubric — Reddit-only, hybrid:** numeric `mean(enrichments.sentiment_score)` over the cluster's Reddit-source members + 2–3 `sentiment_summary` excerpts passed to Anthropic for the qualitative narrative. "Community" reads as community-surfaced reaction, not editorial framing; numeric anchor + vibe summary together give Anthropic both calibration and texture.
  3. **Synthesis model — Opus 4.7** (`claude-opus-4-7`). Once-weekly run at ~$0.30/run = ~$15/yr; cost is trivial at this volume and synthesis is the user-facing quality moment per PRD.
- **WoW-Trends section dropped entirely from Phase 3c.** User flagged that real trend tracking requires per-cluster tagging of dimensions the current enrichment doesn't capture — hottest games existing/upcoming, genre, platform, live-service flag. The current schema has `entities.{games, companies, people}` + the 7-value `category` enum + sentiment, but no platform/genre/lifecycle tags. Building the section as the user described requires either (a) extending the enrichment prompt + re-enriching the 908 corpus, or (b) a second LLM tagging pass at synthesis time; plus multi-week corpus to compute WoW deltas against. Decoupled from 3c synthesis; user will spec the full layout in a future session.
- **Pivot before any Phase 3c code was written:** user asked to see the claude.ai/design template first so the synthesis output format (loose markdown vs structured JSON) and the data contract could be reverse-engineered from the actual rendering target.
- **Inventory agent confirmed pre-port state:** `WeeklyReport` already has both `markdown_content` + `html_content` columns + status/week_start/week_end/generated_at — no schema change needed for either output format. CSS is a 15-line placeholder ("UI template will replace this in Phase 1" already in the header comment), so the design replaces it wholesale. Cluster→items join is via `Cluster.member_item_ids` (text-serialized JSON list), not a junction table — fine for synthesis input.
- **Fetched + decoded the claude.ai/design bundle.** URL: `https://api.anthropic.com/v1/design/h/I2HoKb9BrzKLYmp4VJXRwQ?open_file=Gaming+Chatter.html`. Bundle is a **React/JSX prototype** loaded via Babel-standalone, NOT plain HTML. Variants are not class- or attribute-based — they're React state mutated by a Tweaks panel: `tw.layout`, `tw.density`, `tw.mode`, `tw.accent`. Each variant is read by JS and applied as inline `style={{}}` props plus component selection (`FeedLayout | GridLayout | MagazineLayout`, `themes.light | themes.dark` dict swap, accent mixed via `hexMix()`). `tokens.css` exists but the JSX duplicates its values inline rather than reading them — meaning the port can rebuild from `tokens.css` only for the locked variant. Cards live in `cards.jsx` (13 React components: `week, biggest, hottest, momentum, trends, community, risks, studios, platforms, esports, releases, drama, watch`). Layout in `layouts.jsx` (Grid = 3-col CSS grid, `gap:16`, biggest spans 2). Sidebar lives in `shell.jsx` and its active-state colors are **hard-coded purple literals** (`rgba(95,0,248,0.22)`, `inset 2px 0 0 #5F00F8`), NOT theme refs — had to find/replace to the orange in the port.
- **Locked variant computed values (orange `#D9682B`):**
  - `accent = #D9682B`
  - `accentSoft = hexMix(#D9682B, #FFFFFF, 0.86) = #FAEAE1`
  - `accentHover = hexMix(#D9682B, #000000, 0.35) = #8D441C`
  - Sidebar active-state literals swapped to: `rgba(217,104,43,0.22)` background + `inset 2px 0 0 #D9682B` shadow.
  - Light-theme palette taken verbatim from `primitives.jsx:6–29`.
- **Port complete; faithful render at `/reports`:**
  - **New files:** `app/templates/reports.html` (standalone — does NOT extend `base.html`, since the design has its own full-bleed sidebar+main shell), `app/templates/_components.html` (Jinja macros mirroring `primitives.jsx`: eyebrow, source_pill/row, freshness, meter, signal_cluster, mini_bar, delta, dot, sparkline, card_header), `app/routers/reports.py` (`GET /reports?week=...` route + 3 weeks of placeholder data verbatim from `data.jsx` + sparkline_path geometry helper + delta_tone helper + SOURCES_META + NAV_ITEMS), `app/static/img/alienware-head-light.svg` (sidebar logo, copied from bundle).
  - **Modified files:** `app/static/app.css` (rewritten — legacy `body / table / .cluster*` rules preserved on top so Dashboard/Sources/Clusters keep working unchanged; new `.gc-*` namespace below with `:root` tokens, sidebar/header/grid/card/meter/pill/sparkline/etc. styles for the locked variant), `app/main.py` (one-line additive — mounted reports router), `app/templates/base.html` (one-line additive — added Reports nav link). Phase 3a/3b code and 3b-specific doc updates remain intentionally uncommitted per the prior-session instruction; this session's design-port changes are also uncommitted.
- **Implementation simplifications vs the React prototype:** dropped drag-to-reorder, Tweaks panel, layout/density/theme toggles (kept the chrome visually as static buttons since variants are locked), exec-summary modal, source-drawer side panel. Sidebar nav items (Weekly read-out / All stories / Watchlist / Trends / Sources / Archive) are `href="#"` visual placeholders pending walkthrough. Lucide CDN script kept for icons; React/Babel runtime stripped.
- **Sparkline math** reproduced verbatim from `primitives.jsx:186–235` in Python (`sparkline_path` in the router) — `min/max include 0/1`, `xStep = width/(len-1)`, `yScale = height - 2 - ((v-min)/range)*(height-4)`. Pre-computed points + filled-area polygon strings passed to the `sparkline` macro so Jinja doesn't do float math at render time.
- **Smoke test passed.** `GET /reports`: HTTP 200, 39913 bytes. Spot-checks: 54× `gc-card` class refs, 5× `<polyline>` (biggest sparkline + 4 momentum cells), 11× `data-lucide` icons, 4× `is-active` markers, headline "Elder Scrolls VI delayed" rendered. The other 2 week keys (`2026-W17`, `2026-W16`) selectable via `?week=` query.
- **Port hiccup, no code impact:** user couldn't reach `http://127.0.0.1:8765/` from their browser despite `Get-NetTCPConnection` confirming the listener was up — Windows networking quirk; switched to `:8000` and it worked. The earlier "exit code 1" background-task notification for the uvicorn process is a Windows-uvicorn signal-handling artifact, not a real crash (server was actually serving requests).

**State at end of session:**
- `/reports` renders all 13 cards from the design with placeholder data and the four locked variants (grid + comfortable + light + orange `#D9682B`).
- Phase 3c synthesis code NOT yet started — gated on the design walkthrough.
- Existing functional pages (`/`, `/sources`, `/clusters`) unaffected: separate templates, legacy CSS preserved, new design CSS namespaced under `.gc-*`.
- `.tmp_design_bundle/` extracted bundle (~70KB) still present in repo root, untracked. Contents: `gaming-chatter/project/{Gaming Chatter.html, app.jsx, cards.jsx, data.jsx, design-canvas.jsx, exec-summary.jsx, layouts.jsx, primitives.jsx, shell.jsx, tokens.css, tweaks-panel.jsx}` + assets + bundle tar/gz. Kept around since the walkthrough may need to reference exec-summary and source-drawer markup.

**Next session should:**
1. **Walk `/reports` section by section** with the user to lock keep/drop/rework decisions for the 13 cards, 6 sidebar nav items, header chrome (layout switcher, density toggle, theme toggle, exec-summary CTA), and the footer hint. Goal: a trimmed `/reports` that's the actual Phase 3c output target.
2. **Decide whether `exec-summary.jsx` modal and `SourceDrawer` side panel get ported** — both were left out of the initial port; both are real interactions in the design.
3. **Once sections are locked, write the synthesis prompt** structured to emit exactly the JSON/markdown shape the trimmed `/reports` template consumes. Synthesis goes in `app/services/synthesis.py`, prompt-cached system block, Opus 4.7. Top-N=25 clusters fed in (default unless user objects); first run on `week_id='all'`; per-week scoping waits for Phase 4 APScheduler weekly cuts.
4. **WoW-Trends design pass** (separate from 3c) — user will provide the layout spec covering which dimensions (genre / platform / live-service / lifecycle / etc.) get tracked. That informs schema changes vs synthesis-time tagging, plus the week-window bounding for deltas.
5. **Cleanup decision on `.tmp_design_bundle/`** — delete once the walkthrough doesn't need it as reference.
6. **Recency-penalty tuning** still deferred per prior session — only if the first synthesis run on a real weekly window visibly under-represents day-0/day-1 stories.
7. **`tier1.article` fold-in decision** still deferred — same condition as before.

**Open / blocked:**
- Design walkthrough — the entire shape of Phase 3c synthesis output (sections + per-section data contract) depends on it.
- Trends section design + WoW deltas — needs user spec on what dimensions to track + multi-week corpus or backfill strategy.
- Phase 3c synthesis code — gated on walkthrough.
- Phase 3d (archive view + HTML export) — gated on 3c.

---

## 2026-05-08 — Phase 3b: cluster ranking heuristic shipped; 63 clusters re-scored

**Done:**
- Phase 3b scoped tightly to ranking + persistence + sort + render. Phase 3c (synthesis) and 3d (UI) deferred to next session per agreement; locking 3b first lets us eyeball ranked output before committing to the synthesis prompt.
- **Schema migration** — added `source_count INTEGER`, `latest_published_at TIMESTAMP`, `score REAL` to `clusters` via `_migrate_clusters_columns` in `app/db/init.py` (idempotent ALTER, mirrors `_migrate_enrichments_columns`). `Cluster` SQLModel updated. Migration applied via direct `init_db()` call before re-running clustering; existing rows would have inherited NULLs but were wiped by the idempotent re-run anyway.
- **Score formula (locked):** `score = source_count * member_count / (1.0 + days_since_latest)` where `days_since_latest` is fractional days from `datetime.utcnow()` to the most recent member `published_at`. No tau, no exp, no log dampening, no upvote weighting — matches the session-log guidance to "start with simple multiplicative weights (1×1×1) and tune after seeing real data." Computed inside the existing per-cluster loop in `cluster_window`, no new code paths. See DECISIONS 2026-05-08 for the full rationale and rejected alternatives.
- **Router + template:** `GET /clusters` sorts by `Cluster.score.desc().nulls_last(), Cluster.member_count.desc()` (was: `member_count.desc()`). `clusters.html` now renders `score N.N · {n} items · {n} sources · latest YYYY-MM-DD`. Tiny `.cluster-meta .score { color:#222; font-weight:600 }` to make the score visually pop in the meta line.
- **Re-ran `cluster_window(week_id='all')`** — 186.0s wall clock, 63 clusters / 157 items / 63 labelled / 0 failures. Identical shape to the Phase 3a run (same threshold, same min size); labels rotated slightly because Ollama is non-deterministic. Acceptable.
- **Eyeball check passed.** Top-12 by score: 1) Mixtape coming-of-age review (5 sources × 5 members, today) 12.79; 2) Griffin Gaming Partners $100M indie fund (4×5) 10.02; 3) "game releases and announcements" (4×4) 8.34 [vague label, real cross-source signal]; 4) Take-Two CEO disappointed with BioShock (4×4) 7.75; 5) Star Fox 64 remake for Switch 2 (4×4) 6.76; 6) Valve restocks Steam Controller (4×4, 1d) 5.97; 7–12) tied tier of (3×3) clusters — Mortal Kombat 2 movie, LEGO Batman launch, Stop Killing Games petition, Mixtape no-streamer-mode, Star Fox preorder, etc. All 14 single-source clusters (YongYea Metal Gear playthrough, VG247 Diablo 4 Warlock series, Fallout 4 walkthrough, Game Informer weekly picks, RPGs popularity etc.) scored <1.0 — exactly the demotion the prior session called for.
- **One observation worth flagging:** the Spiders studio closure cluster (5 sources × 5 members, 7 days old) ranks #13 at 2.73 despite having maximal cross-source breadth. The `1 / (1 + days)` recency factor divides by 8 at day 7 — that's a steep penalty. For week_id='all' (all-time corpus) this is fine. For weekly windows in Phase 3c, today vs end-of-week will differ by 8×, which may under-represent stories that broke early in the week. Tuning deferred until first weekly synthesis run shows whether this is a real problem.
- **UI smoke test:** `GET /clusters?week_id=all` returned HTTP 200, 88KB. Score + latest date render on each card. Sort order matches the SQL query.
- **End-of-session doc-alignment pass.** Audited every doc end-to-end against current state and fixed the staleness: `CLAUDE.md` + `README.md` had Phase-0-era "Design phase / no code yet" status blocks; `README.md` had a never-filled "Run — TBD" section; `ARCHITECTURE.md` still called out Ollama 14B in 4 places (data flow, schema row, LLM pipeline table, external deps line) and the schema rows missed the Phase-2 `enrichments.{status,error}` and Phase-3b `clusters.{score,source_count,latest_published_at}` columns; `PRD.md` rubric language said "refined in Phase 3" rather than "Phase 3c"; `OPEN_QUESTIONS.md` was missing the 3b recency-penalty tuning question and the Phase-3c Sonnet-vs-Opus decision. All fixed. `CHANGELOG.md`, `DECISIONS.md`, `SESSION_LOG.md`, `TASKS.md` were already aligned.

**State at end of session:**
- Phase 3b done. 63 clusters under `week_id='all'` now have `score`, `source_count`, `latest_published_at` populated. TASKS.md "Cluster ranking heuristic" ticked.
- Modified: `app/db/init.py` (+migration helper), `app/db/models.py` (+3 fields on Cluster), `app/services/cluster.py` (score computation in cluster_window), `app/routers/clusters.py` (sort by score), `app/templates/clusters.html` (render score + latest date), `app/static/app.css` (.score weight).
- New file: `scripts/inspect_cluster_ranking.py` — one-off ranking dump utility.
- DECISIONS.md, CHANGELOG.md, TASKS.md, SESSION_LOG.md updated.
- Runtime log at `logs/cluster_2026-05-08_phase3b.log` (gitignored).

**Next session should:**
1. **Resolve the two deferred Phase-3 design questions before writing the synthesis prompt:**
   - "Industry risks" rubric — layoffs only? Include regulation (Stop Killing Games, age verification, EU/UK rulings)? Platform-side (console-maker policy changes) vs. consumer-side (price hikes, store changes)?
   - "Community sentiment" rubric — Reddit-only or include YouTube comments? Numeric sentiment aggregate (mean of `enrichments.sentiment_score` per cluster) or vibe-summary derived from TLDRs?
2. **Phase 3c — Anthropic synthesis.** Confirm model (**Sonnet 4.6 vs Opus 4.7** — once-weekly run, ~$0.05 vs ~$0.30, and synthesis is the "thoughtful colleague's brief" quality moment per PRD). Write `app/services/synthesis.py` calling Anthropic with the top-N ranked clusters + per-cluster member TLDRs. 7-section prompt locked from PRD: Biggest Story / Hottest Games / Industry Risks / Market Momentum / WoW-MoM Trends / Community Sentiment / Watch-List. Persist markdown + html to `weekly_reports`.
3. **Phase 3d — report rendering + UI.** Markdown → standalone HTML with inlined CSS for portability. `/reports` archive view, manual "Generate report" button, export-as-HTML button.
4. **Recency-penalty tuning (only if needed).** If synthesis on a real weekly window visibly under-represents day-0/day-1 stories vs day-6/day-7 stories, swap `1/(1+days)` for `exp(-days/3)` or similar. Don't pre-tune.
5. **Revisit the open architectural decision** on whether to fold `tier1.article` into regular ingest vs. keep as remediation pass — defer until first weekly synthesis run informs whether daily fresh-corpus quality matches the 91.9% backlog quality.

**Open / blocked:**
- The Spiders 7-day-old cluster ranking #13 — flagged but accepted; tuning deferred to post-3c.
- Two synthesis design questions (industry risks rubric, community sentiment rubric) — block 3c, not 3b.
- Synthesis model choice (Sonnet 4.6 vs Opus 4.7) — pending user decision at start of 3c.
- claude.ai/design UI template — still pending external delivery; not blocking 3c/3d.

---

## 2026-05-08 — Phase 3a: clustering + labels working; 63 clusters / 157 items grouped

**Done:**
- Phase 3 scoped to "3a — group + label only" for this session; ranking heuristic + Anthropic synthesis + reports archive deferred to next session.
- **Threshold exploration** (`scripts/explore_clustering.py`, throwaway): connected-components on a thresholded cosine-similarity graph of the 908 fp32 TL;DR embeddings. Tried {0.55, 0.60, 0.65, 0.70, 0.75} first — every threshold ≤0.75 produced one giant 500+ item blob via chain-merge through baseline "gaming-ness" similarity. Re-ran at {0.78, 0.80, 0.82, 0.85, 0.88}: at 0.85 the blob fully fragments and every top-10 group passes editorial inspection (Mixtape reviews × 5 sources, Spiders studio closure × 5 sources, Star Fox 64 remake × 4, Steam Controller restock × 4, etc.). 0.88 over-fragments real stories. **Locked: threshold 0.85, min cluster size 2.**
- **`app/services/cluster.py`** — `cluster_window(start, end, week_id)` loads ok-enrichments + items in window, normalizes vectors, builds N×N similarity matrix, runs union-find connected-components at `CLUSTER_THRESHOLD`, computes per-cluster centroid (mean of normalized vectors, re-normalized) as fp32 BLOB, calls `label_cluster()` for each, persists to `clusters` table keyed by `week_id`. Idempotent: re-runs delete prior rows for the same `week_id`. Writes a `RunLog` row with `job_type='cluster'`.
- **`label_cluster()` added to `app/services/ollama.py`** — qwen2.5:7b, JSON-mode `{"label": "..."}`, system prompt with 5 worked examples. Caps prompt to top `CLUSTER_LABEL_SAMPLE=8` member items. ~3s/call.
- **`app/routers/clusters.py`** — `POST /clusters/run` (trigger, sync or background) + `GET /clusters?week_id=` (HTML view). Mounted into `app/main.py`; nav link added to base layout; small CSS additions for the cluster card layout.
- **`scripts/run_cluster.py`** — standalone runner, optional `week_id` arg (defaults to `all`). Followed the same pattern as `run_enrich_batch.py` and `run_article_fetch.py`.
- **First production run** (`week_id='all'` against the full 908-item corpus): 178.8s wall clock, 63 clusters, 157 items grouped (17.3% of corpus), 63/63 labelled, 0 failures. Centroid blobs verified at 3072 bytes (= 768 fp32). Run log row #50 written `status='ok'`.
- **UI smoke test:** booted uvicorn on :8765, `GET /clusters` returned 200 / 80KB, top clusters render with label, member count, source count, and per-item links. Cluster #1 confirmed "Mixtape indie game review" with 5 items / 5 sources rendering correctly.
- **Quality assessment of the 63 labels (eyeball):** ~50/63 are clean editorial signals ("Wizards of the Coast misses union recognition deadline", "Sony PlayStation Store settlement", "Dying Light franchise director leaves Techland", "Atari acquires Implicit Conversions", etc.). ~10–13 are vague generic labels ("game releases and announcements", "Release dates announced", "RPGs popularity and appeal") or single-source long-tail series (YongYea Metal Gear playthrough, VG247 Diablo 4 Warlock series, Game Informer weekly recommendation column). The vague/long-tail clusters are real but low-priority — they'll get filtered by the cross-source × signal × recency ranking heuristic in 3b.

**State at end of session:**
- Phase 3a done. 63 clusters persisted under `week_id='all'`, all labelled. Phase 3 boxes 1+2 ticked in TASKS.md.
- New files: `app/services/cluster.py`, `app/routers/clusters.py`, `app/templates/clusters.html`, `scripts/run_cluster.py`, `scripts/explore_clustering.py` (kept as a utility for re-tuning later if needed).
- Modified: `app/services/ollama.py` (added `label_cluster()` + system prompt), `app/main.py` (router mount), `app/templates/base.html` (nav link), `app/static/app.css` (cluster card styles), `app/config.py` (3 new CLUSTER_* settings).
- TASKS.md, DECISIONS.md updated. Runtime log at `logs/cluster_2026-05-07.log` (gitignored).

**Next session should:**
1. **Phase 3b — cluster ranking heuristic.** For each cluster, compute a score from cross-source breadth (number of distinct sources) × volume signal (member count, optionally weighted by upvotes/comments where available) × recency decay (days since latest member's `published_at`). Start with simple multiplicative weights (1×1×1) and tune after seeing the ranking on real data. Persist scores to a new column on `clusters` (small migration) or compute on-the-fly in the router.
2. **Phase 3c — Anthropic synthesis.** Lock the 7-section weekly report prompt structure (exec summary / biggest stories / industry signals / launches & releases / community sentiment / hottest games / watch-list). Write `app/services/synthesis.py` calling Anthropic Sonnet 4.6 (or Opus 4.7 — to confirm with user; once-weekly + ~$0.05/run) with the cluster summaries + per-cluster member TL;DRs. Persist to `weekly_reports`.
3. **Phase 3d — report rendering + UI.** Markdown → HTML with inlined CSS for portability. `/reports` archive view. Manual "Generate report" button. Export-as-HTML button.
4. Resolve 2 deferred Phase-3 design questions before writing the synthesis prompt: "industry risks" rubric (layoffs / regulation / platform vs consumer-side) and "community sentiment" rubric (Reddit-only? numeric vs vibe summary?).
5. After the first synthesis run: revisit the open architectural question on whether to fold `tier1.article` into regular ingest vs. keep as remediation pass (Phase 2.5 carryover; will have data to decide once cluster quality on a fresh weekly window is observed).

**Open / blocked:**
- The single-source long-tail clusters (YongYea playthrough series, VG247 Diablo 4 series) are not noise but also not "weekly news stories" — confirmed deferred to Phase 3b ranking, no filter at clustering time.
- claude.ai/design UI template — still pending external delivery; not blocking Phase 3b/c/d. The Phase-3 cluster + report UIs are placeholder Jinja, ready to swap.

---

## 2026-05-07 — Phase 2.5 closed; 908/988 enriched (91.9%); ready for Phase 3

**Done:**
- Built `app/services/article_fetch.py` — `fetch_skipped_bodies()` calls `scrapers_lib.tier1.article` (sync, trafilatura under the hood) on each item whose enrichment is `status='skipped'`. Updates `item.body_text` only when the extracted body meets `ENRICH_BODY_CHAR_MIN`. Logs a `RunLog` row with `job_type='article_fetch'`. 1s inter-request delay (matches `app/services/scrapers.py` direct-tier1 pattern; no `core` integration).
- Built `scripts/run_article_fetch.py` — chains `fetch_skipped_bodies` → `enrich_pending(retry_failed=True)` → `embed_pending` so the whole Phase 2.5 pass runs unattended.
- **Pre-launch finding that reshaped scope.** A 5-item smoke test exposed that trafilatura returns *zero* extractable body for Reddit link-post URLs (the page is just a title + outbound-link redirect). Domain breakdown of the 167 skipped RSS items: **72 reddit.com / 95 non-Reddit news sites** (Game Developer 39, GamesIndustry.biz 24, PC Gamer 18, Kotaku 8, Eurogamer 5, GameSpot 1). The session-log "≥80% of 173" quality bar was therefore structurally unmeetable. Confirmed direction with user: skip Reddit URLs in the fetcher (consistent with the original `ENRICH_BODY_CHAR_MIN` decision that Reddit link-posts duplicate news-feed coverage), reframe bar to ≥40% of 173. Logged in DECISIONS.md.
- Ran the full chained batch detached. Wall clock **16m44s**: fetch 2m12s, enrich 11m02s, embed 3m31s.
  - Article fetch: **94 of 95 attempted succeeded**, 1 errored. 72 Reddit + 6 YouTube skipped by design.
  - Re-enrich (retry_failed=True): 93 ok, 1 failed (`ValueError: ollama JSON failed schema` on PC Gamer's Forza Horizon 6 car-list page — model returned a non-conforming `{title, cars: ...}` shape on a thin-content list article; acceptable 1% rate).
  - Embed top-up: 93 new fp32 vectors, 0 failed.
- Spot-checked 5 random new ok rows: TLDRs accurate and concise, categories correct (industry × 5 in the sample), sentiments reasonable, body lengths 1.6–2.9k chars (proper article bodies, not teasers). Quality clean.

**State at end of session:**
- Phase 2.5 done. **988 items → 908 ok / 79 skipped / 1 failed.** Coverage 82.5% → **91.9%**. All 908 ok rows have 768-dim embeddings.
- Skipped composition now: 72 Reddit link-posts + 6 YouTube (no transcript) + 1 fetch-errored news item = 79.
- New files: `app/services/article_fetch.py`, `scripts/run_article_fetch.py`. Runtime log at `logs/article_fetch_2026-05-07.log` (gitignored).
- TASKS.md / DECISIONS.md / CHANGELOG.md / SESSION_LOG.md all updated.

**Next session should:**
1. **Phase 3 — clustering + synthesis.** This is the "working product" milestone.
2. First move: cluster the 908 fp32 embeddings via numpy cosine similarity. Define cluster threshold (start ~0.55–0.65) and minimum cluster size (start at 2–3). Validate the cluster shape matches editorial intuition before locking parameters — pull a few clusters and inspect.
3. Per-cluster label generation via local Ollama (qwen2.5:7b) — prompt is similar to enrichment but takes N TLDRs + N titles and outputs a 1-line label.
4. Cluster ranking heuristic — cross-source × signal × recency. Define weights pragmatically (start equal, tune after first weekly synthesis).
5. Anthropic synthesis pass for the Monday weekly report — needs the 7-section prompt locked. End of Phase 3 = working product.
6. **Open architectural decision deferred to Phase 3 observations:** fold `tier1.article` into the regular ingest pipeline going forward, or keep it as a Phase-2.5-style remediation pass after each daily ingest. Currently leaning *remediation pass* — keeps daily ingest fast, bounded scrape rate.

**Open / blocked:**
- The 1 enrichment failure on PC Gamer's Forza Horizon 6 car list — accepted. List-article shape isn't the synthesis target anyway.
- Reddit-link-post resolver (resolve to external article URL via `URL.json`, fetch trafilatura against the target) — not built. Would recover ~50–60 of the 72 Reddit items. Reconsider in Phase 3 *only if* cluster cross-referencing across Reddit ↔ news-site weakens visibly without it. Otherwise the duplicate-news-coverage argument from the original 2026-05-07 skip decision still holds.
- claude.ai/design UI template — still pending external delivery; not blocking Phase 3.

---

## 2026-05-07 — Phase 2 closed; 815/988 enriched + embedded; Phase 2.5 escalated

**Done:**
- Full enrich+embed batch ran detached for 1h55m (enrich 1h25m, embed 30m). Initial result over 988 items: 798 ok / 177 skipped / 13 failed. `nomic-embed-text` is slower than projected (~2.3s/vec, not sub-second).
- Spot-check across the corpus surfaced two clean failure modes plus one borderline quality issue:
  - **6× `category 'review' not in allowed set`** — genuine product-review threads ("Saros Review", "Will: Follow the Light review", Reddit "Mixtape - Review Thread") rejected because the enum was incomplete.
  - **7× `entities.people` returned as `{name: {}}` dict** instead of `[name, ...]` list. The model occasionally emits the entities sub-fields as keyed maps.
  - **15/798 (1.9%) underscored Reddit handles** still appearing in `entities.people` (`Batz_Gaming`, `biohazard_fanatic`, `/u/ChickenAI_Prod`, etc.). Down from the prior baseline but not zero. Accepted for now — see DECISIONS.
- Two minimal fixes applied to `app/services/ollama.py` (no other files touched):
  - Added `'review'` to `_ALLOWED_CATEGORIES` and to the SYSTEM_PROMPT enum line + rules block.
  - Added `@field_validator('games', 'companies', 'people', mode='before')` on the `Entities` model that converts dict input to `list(keys)`. Applied defensively to all three list fields.
- Re-ran `enrich_pending(retry_failed=True)`: 190 attempted (13 prior failures + 177 prior skipped — `retry_failed=True` reprocesses every non-ok row), 17 new ok, 173 skipped, 0 failed. The +4 over the 13 failure recoveries are items that flipped skipped→ok on retry (likely transient YouTube transcript availability).
- Top-up `embed_pending()` on the 17 new ok rows. **Final state: 815 ok + 173 skipped + 0 failed; all 815 enrichments have embeddings.**
- **Skip composition is the real surprise.** Sampling 8 random skipped rows showed they're NOT just Reddit link-posts. News-site RSS feeds (PC Gamer, Kotaku, Game Developer) also skip because their feeds carry only 100–200-char teasers, not article bodies. So the 17.5% skip rate is real corpus loss across both Reddit *and* news sites — Phase 2.5 (article body-fetch) is escalated from "deferred unless quality demands it" to **must-do before Phase 3**.

**State at end of session:**
- Phase 2 done. 988 items, 82.5% enrichment + embedding coverage, zero failures.
- New files: `scripts/run_enrich_batch.py`. Runtime log at `logs/enrich_batch_2026-05-07.log` (gitignored).
- `app/services/ollama.py` modified (one import, one enum value, one validator, two prompt-text lines).
- TASKS.md and DECISIONS.md updated.

**Next session should:**
1. **Phase 2.5 — article body-fetch.** Build `app/services/article_fetch.py` wrapping `scrapers_lib.tier1.article` (rate-limit / robots / cache come from scrapers-lib `core`). For each of the 173 `status='skipped'` rows: fetch article body via `item.url`, update `item.body_text`, then re-run enrichment on those rows. Add a one-shot runner — pattern after `scripts/run_enrich_batch.py`.
2. After Phase 2.5 lands, `enrich_pending(retry_failed=True)` again on the 173. Then top-up `embed_pending()`.
3. Quality bar for closing Phase 2.5: ≥80% of the 173 flip to `ok`. <50% triggers investigation (paywalls, JS-rendered, robots blocks). 50–80% is judgement.
4. **Phase 3 — clustering + synthesis.** Cosine clustering on the fp32 vectors via numpy. Define cluster threshold + minimum size. Anthropic API for per-cluster labels and the Monday weekly report. End-of-Phase-3 = "working product."
5. Decide whether to fold `tier1.article` into the regular ingest pipeline going forward, or keep it as a remediation pass (depends on Phase 2.5 recovery rate + scraper-lib rate-limit behavior).
6. Update TASKS.md / DECISIONS.md / SESSION_LOG.md as work moves.

**Open / blocked:**
- Underscored-handle 1.9% rate — accepted; revisit only if Phase 3 entity-based features expose it.
- claude.ai/design UI template — still pending external delivery; not blocking Phase 2.5 or Phase 3.

---

## 2026-05-07 — Stale enrichments wiped; full enrich+embed batch launched detached

**Done:**
- Resumed from prior session's 6-step checklist. State at session start was unexpected: DB held **988 enrichments** (979 `ok`, 9 `failed`, 0 `skipped`), not the 10 mentioned in the prior log narrative. Root cause: the chained BackgroundTask wired into `POST /sources/ingest-all` (queues `ingest_all` then `enrich_pending`) auto-ran the full backlog under the **pre-fix prompt** at some point between the prior session's sanity gate and now. Confirmed staleness by sampling: random `ok` rows still contained underscored Reddit handles in `entities.people` (e.g. `Batz_Gaming`, `testus_maximus`), and zero `skipped` rows existed (the `ENRICH_BODY_CHAR_MIN=200` skip logic clearly wasn't in force when these were written).
- **Step 1 — wipe.** `DELETE FROM enrichments;` against `gaming_chatter.db`. Before=988, after=0. Items table untouched (988 rows still present).
- **Step 2 — kick off backlog.** Wrote `scripts/run_enrich_batch.py` — a standalone runner that calls `enrich_pending()` then `embed_pending()` back-to-back so step 3 auto-fires when step 2 finishes (avoids the manual handoff in the original checklist). Launched via `nohup python scripts/run_enrich_batch.py > logs/enrich_batch_2026-05-07.log 2>&1 &` so the batch survives session detach. Bypassed uvicorn entirely — no FastAPI process needed for batch jobs.
- Verified the batch is actually running:
  - Log file is being written to (two `POST /api/generate 200 OK` lines after launch).
  - DB shows progress within ~30s of launch: 2 ok + 1 skipped, `run_log` row #41 with `job_type='enrich'`, `status='running'`. Skip logic is firing as designed.
  - Per-item latency: ~7–8s on `qwen2.5:7b`, matching the prior projection.

**State at end of session:**
- `enrich_pending` running detached. Projected ~2h for ~988 items, then `embed_pending` chains automatically (~10–15 min).
- All other Phase 2 code unchanged from the prior session — only data was wiped.
- New file: `scripts/run_enrich_batch.py`. New artifact: `logs/enrich_batch_2026-05-07.log` (gitignored — runtime log).

**Next session should:**
1. Confirm the batch finished cleanly: `tail logs/enrich_batch_2026-05-07.log` should end with `=== batch complete; total ...s ===`. The two `RunLog` rows (`enrich`, `embed`) should both show `status='ok'`.
2. Sanity-check the full corpus:
   - Final counts by status (`ok` / `failed` / `skipped`). Skip rate = signal for whether Phase 2.5 (article body-fetch for Reddit link-posts) is needed — see prior session's checklist item 5.
   - Spot-check 10–15 enrichments across categories (mis-categorization, hallucinated entities, junk TLDRs).
   - Confirm zero underscored handles in `entities.people` (the prompt fix landed).
3. If quality holds: close Phase 2 (TASKS.md + DECISIONS.md), move to Phase 3 (clustering + weekly synthesis).
4. If skip rate is high or quality poor: trigger Phase 2.5 (`tier1.article` body-fetch for link-posts) as scoped in prior session.

**Open / blocked:**
- Phase 2.5 decision deferred pending batch completion + quality review.
- claude.ai/design UI template — still pending external delivery.

---

## 2026-05-07 — Phase 2 enrichment code complete and sanity-gated; full batch NOT yet run

**Done:**
- Built Phase 2 enrichment end-to-end:
  - `app/services/ollama.py` — httpx client for `/api/generate` (JSON-mode) + `/api/embeddings`. Single-prompt enrichment with Pydantic-validated schema (tldr, entities {games/companies/people}, category enum, sentiment_score, sentiment_summary). Embeddings serialized as fp32 numpy bytes for SQLite BLOB storage. YouTube transcript fetch via `scrapers_lib.tier1.youtube.fetch_youtube_transcript` on-demand at enrichment time.
  - `app/services/enrich.py` — orchestrates two phases (enrich-all then embed-all to avoid model swap thrash). Persists status='ok' | 'failed' | 'skipped' rows.
  - `app/routers/enrich.py` — `POST /enrich/pending` and `POST /embed/pending`, both supporting `?sync=true&limit=N` for the sanity gate.
  - Schema additions: `status` and `error` columns on `enrichments` (idempotent SQLite ALTER in `app/db/init.py:_migrate_enrichments_columns`).
  - Settings (`app/config.py`): `OLLAMA_HOST`, `OLLAMA_ENRICH_MODEL=qwen2.5:7b`, `OLLAMA_EMBED_MODEL=nomic-embed-text`, `OLLAMA_NUM_CTX=8192`, `OLLAMA_KEEP_ALIVE=24h`, `ENRICH_BODY_CHAR_CAP=24000`, `ENRICH_BODY_CHAR_MIN=200`.
  - Dashboard now renders TL;DR + category chip + sentiment per item, plus an "Enrich pending (N)" trigger.
  - Wired chained BackgroundTask: `POST /sources/ingest-all` queues `ingest_all` then `enrich_pending`.
- **Model size deliberation (logged in DECISIONS.md):** started with 14B per architecture; ran VRAM math against the 12GB 5070 (14B Q4 ≈ 9GB + 1.6GB KV at 8k ctx + 0.3GB embed model + 0.5GB headroom = right at the edge, with model-swap thrashing risk). Switched to **qwen2.5:7b** for Phase 2: ~4.5GB resident, comfortable 8–32k ctx, 50–70 tok/s, ~2hr batch projection vs ~3hr for 14B. Promotion to 14B reserved if Phase 3 clustering reveals quality regression.
- **Sanity gate (10 items, sync):** 10/10 enriched cleanly, 10/10 embedded (768-dim fp32 vectors, norms ~20). Output reviewed item-by-item: 8 strong, 2 acceptable. Findings drove two prompt iterations:
  1. Reddit usernames bleeding into `entities.people` (e.g. `Responsible_Box_2422`, `Eremenkism`) → added explicit prompt rule excluding underscored handles. **The 10 sanity items were enriched with the OLD prompt** — they retain the junk usernames until re-enriched.
  2. Reddit link-only posts (body too short to summarize) producing useless meta-TLDRs ("TheVerge publishes an article about Xbox") → added `ENRICH_BODY_CHAR_MIN=200` skip. Items below threshold get persisted as `status='skipped'` and render on dashboard with no TLDR. **Rationale (decision):** most link-posts duplicate articles we scrape directly from news feeds, so the content isn't lost — the proper enrichment shows on the original news source row. The Reddit version becomes a "community noticed this" duplicate signal. `tier1.article` body-fetch for link-posts is deferred to Phase 2.5 if real-world quality demands it.

**State at end of session:**
- Phase 2 code complete and proven end-to-end on 10 items. All schema migrations applied. Server tested and stopped cleanly.
- **Full ~978-item enrichment batch NOT yet run.** The 10 sanity items have status='ok' but were enriched with the pre-fix prompt — they need to be wiped and re-done so the entire corpus uses one consistent prompt version.
- TASKS.md Phase 2 capability boxes all checked; backlog-run is a remaining item.

**Next session should:**
1. Wipe the 10 stale enrichments: `DELETE FROM enrichments WHERE status='ok' AND created_at < '<today>'` (or simpler: delete all enrichment rows since none are committed long-term yet).
2. Kick off the full backlog: `POST /enrich/pending` (async BackgroundTask, ~2 hours for ~978 items at ~7s/item on qwen2.5:7b).
3. After enrichment finishes, kick off `POST /embed/pending` (~10–15 min for ~978 embeddings on nomic-embed-text).
4. Spot-check a sample of enrichments across category types — flag any systemic issues (mis-categorization, hallucinated entities, junk TLDRs from feeds we underestimated).
5. **Decision needed:** is the link-only skip behavior carrying enough articles? If a noticeable share of useful items are getting skipped, escalate Phase 2.5 = `tier1.article` body-fetch for Reddit link-posts. Otherwise close Phase 2 and move to Phase 3 (clustering + synthesis).
6. Update TASKS.md, DECISIONS.md, SESSION_LOG.md as work moves.

**Open / blocked:**
- Phase 2.5 (`tier1.article` body-fetch for Reddit link-posts) — deferred pending observation of skip rate on the full batch.
- claude.ai/design UI template — still pending external delivery; not blocking Phase 2/3.

---

## 2026-05-07 — Phase 1 manual ingest landed and verified end-to-end

**Done:**
- Inspected the scrapers-lib API surface to ground wrapper design (signatures + `RawMention` shape). Two findings drove the design:
  1. `tier1.youtube` doesn't accept `@handle` — only video IDs/URLs — and returns transcript chunks, not videos. Wrong shape for an "items" feed.
  2. `tier1.rss` against a YouTube channel's `feeds/videos.xml?channel_id=UC...` gives the same per-video metadata we get from news sites.
- Decision (logged in DECISIONS.md): **YouTube ingest goes through `tier1.rss`, transcript fetching is deferred to Phase 2 enrichment.** Built `resolve_youtube_feed()` that scrapes the channel page once for `channelId`, caches per-process.
- Wrote `app/services/scrapers.py` (wrapper + resolver) and `app/services/ingest.py` (dedup + persist + run logging). Dedup key is `(source_id, mention_id)`. Fingerprint = `md5(normalized_title)` — populated now, used for cross-source dedup later.
- Added routes: `POST /sources/{id}/ingest` (sync per-source) and `POST /sources/ingest-all` (BackgroundTasks). Sources table now shows `last_fetched`, `error_count`, `last_error`, per-row Ingest button + Ingest-all button. Dashboard shows latest 50 items.
- Real-network smoke test on all 30 sources: 29/30 worked first pass; Gameranx YouTube 404'd. Briefly went down a wrong path (changed UA suspecting bot detection); a probe agent identified the actual cause: the handle in `sources.yaml` was wrong. `@gameranx` doesn't exist; real handle is `@GameranxTV`. Reverted the UA change, fixed the YAML, patched the existing DB row in place, re-ingested → 15 videos, no error. **30/30 sources green.**
- Idempotency verified: re-ingest of IGN keeps items at 20, not 40.
- Item shape sanity (across 973 items): 0 empty titles, 0 empty URLs, 0 null `published_at`, 0 null body. 15 RSS items had null `author` (feeds vary — fine).
- Updated TASKS.md (all 8 Phase 1 boxes ticked), CHANGELOG.md (Phase 1 entry), DECISIONS.md (two new entries: YouTube path + Gameranx handle correction).

**State at end of session:**
- Phase 0 + Phase 1 complete. End-to-end manual ingest works against all 30 real sources. ~973 items in the local DB right now.
- "Working product" milestone is end of Phase 3, but the spine is in place: ingest → store → list. Phase 2 is enrichment (Ollama TL;DRs, embeddings).

**Next session should:**
1. Begin Phase 2 — Local LLM enrichment.
2. First move: Ollama HTTP client wrapper. Pick the 14B enrichment model + an embedding model (mxbai-embed-large or nomic-embed-text). Confirm both run on the user's RTX 5070 / 12GB VRAM (memory: prefer 14B for quality).
3. Per-item enrichment prompt → structured JSON: `tldr`, `entities` (games / companies / people), `category`, `sentiment_score`, `sentiment_summary`. Lock the prompt only after a sanity pass on real ingested items.
4. Embedding generation per item (BLOB into `enrichments.embedding`).
5. "Enrich pending items" trigger on the dashboard.
6. Dashboard renders TL;DR per item once enriched.
7. **Decision needed early in Phase 2:** how to handle YouTube transcript fetch. Options: (a) fetch + summarize at enrichment time using `tier1.youtube`; (b) summarize from title alone (cheap, low quality). Lean toward (a) — pull transcript on-demand, chunk-aggregate to a single body, then enrich.

**Open / blocked:**
- claude.ai/design UI template — still pending external delivery. Phase 2 enrichment work doesn't need it.

---

## 2026-05-07 — Phase 0 skeleton landed

**Done:**
- Decided SQLModel over raw SQLAlchemy (FastAPI-author lib, less boilerplate, no real downside at this scale).
- Decided hand-rolled `SQLModel.metadata.create_all` + WAL/foreign-keys pragmas on connect for schema bring-up — alembic deferred until the schema actually needs migrations.
- Wrote `pyproject.toml` with the locked stack (fastapi, uvicorn, jinja2, apscheduler, sqlmodel, httpx, anthropic, numpy, pyyaml). `scrapers-lib` referenced via `[tool.uv.sources]` editable path dep at `../scrapers-lib`; pip users will need to `pip install -e ../scrapers-lib` separately.
- Created the full `app/` package layout: `main.py`, `config.py`, `db/{models,session,init}.py`, `routers/{dashboard,sources}.py`, `utils/yaml_loader.py`, `templates/{base,dashboard,sources}.html`, `static/app.css`, plus `tests/`.
- Implemented all 7 SQLModel tables verbatim from ARCHITECTURE.md schema (sources, raw_items, items, enrichments, clusters, weekly_reports, run_log).
- Implemented idempotent `seed_sources()`: reads `sources.yaml`, upserts by `(type, url_or_handle)`. Runs in lifespan startup via `init_db()`.
- `GET /` placeholder dashboard + `GET /sources` read-only table view; base layout pulls htmx 2.0.3 from unpkg.
- Wrote `CHANGELOG.md` with the Phase 0 entry.
- All Python files compile cleanly under `python -m compileall`.

- Installed deps via pip: `pip install -e ../scrapers-lib` (editable) + `pip install -e .` (the project). `[tool.uv.sources]` is wired but currently inert because pip is in use; if we move to uv later, `uv sync` would replace both steps.
- Smoke-booted `uvicorn app.main:app` on port 8765. First boot revealed a bug: both routes 500'd with `TypeError: unhashable type: 'dict'` from Jinja's cache. Root cause: I'd written the old Starlette `TemplateResponse(name, {"request": request})` signature; modern Starlette (1.0+, shipped with FastAPI 0.115+) requires `TemplateResponse(request, name, context=None)`. Fixed both routers to the new signature. After fix, cold-start (DB deleted, re-seeded) returns 200 on `/` and `/sources`, with `/sources` rendering "Sources (30)" and all 7 tables present in `gaming_chatter.db`.
- Idempotency check passed earlier: a second boot left the `sources` count at 30, not 60.

**State at end of session:**
- 10 of 11 Phase 0 tasks done and verified end-to-end (skeleton boots, seeds, renders). Only deferred item: porting the claude.ai/design UI template (still awaiting external delivery — not blocking Phase 1).
- Deps installed in the system Python at `C:\Users\AW-testing\AppData\Local\Programs\Python\Python312` (no virtualenv). Fine for personal-local; revisit if it gets messy.

**Next session should:**
1. Begin Phase 1. First move: write thin scrapers-lib wrappers — `app/services/ingest.py` calling `tier1.rss` (covers both news sites and Reddit subreddits per 2026-05-07 decision) and `tier1.youtube`.
2. Add an "Ingest now" button (per-source + run-all) on `/sources`, wired to the wrappers; persist into `raw_items` and `items` with exact-match dedup; update `sources.last_fetched_at` and error counters.
3. **Verify the 6 YouTube channels** under `tier1.youtube` (still unverified from Phase 0 source-list lock-in).
4. Re-verify all 24 RSS feeds under real ingest conditions before scheduled runs come online in Phase 4.
5. Dashboard: list latest 50 raw items.

**Open / blocked:**
- claude.ai/design UI template — pending external delivery. Phase 1 ingest work can proceed against the placeholder layout.
- PRAW rejection — unchanged from prior session. See `OPEN_QUESTIONS.md`.

---

## 2026-05-07 — Reddit pivot to RSS (PRAW unavailable)

**Done:**
- User reported Reddit API application was rejected — PRAW unusable.
- Probed Reddit's per-subreddit RSS endpoint (`/r/<sub>/.rss`) via scrapers-lib's `tier1.rss`; confirmed it works without auth (25 entries per sub, hot view).
- Probed variants for r/VideoGameNews (returned 403); selected **r/GamingNews** as replacement (verified 25 entries, news-focused).
- Confirmed r/XboxSeriesX is mod-deprecated (top pinned post is "This sub has moved to r/Xbox") — switched to **r/Xbox**.
- Final 11-sub verification: all 11 working under scrapers-lib (~263 aggregate entries).
- Pivoted all 11 subreddit entries in `sources.yaml` from `type: reddit` → `type: rss` with Reddit RSS URLs.
- Logged the architectural pivot in `DECISIONS.md` (two new entries: pivot + source-list cleanup).
- Updated `ARCHITECTURE.md` data flow + external dependencies sections.
- Added PRAW-rejected note to `OPEN_QUESTIONS.md` under new "Blocked by external party" section.
- Softened "Community Sentiment" row in `PRD.md` (post-level, not comment-level).
- Pre-close audit: also updated `CLAUDE.md` (scrapers-lib usage block) and `TASKS.md` Phase 1 (wrapper modules + verification status) to remove staleness from the Reddit pivot. These are the docs the next session reads first.

**State at end of session:**
- 30 sources locked: 13 news RSS + 11 Reddit RSS + 6 YouTube. **24 RSS feeds verified live (~898 entries available right now)**; 6 YouTube channels still unverified.
- Reddit comment-thread + upvote/velocity signal lost until PRAW comes back. Reversible the moment it does — config-only switch.

**Next session should:**
1. (User to provide) UI template from claude.ai/design — when ready; not blocking Phase 0.
2. Begin Phase 0 from `TASKS.md` with placeholder layout.
3. **Phase 1: verify the 6 YouTube channels via scrapers-lib's `tier1.youtube` before locking source list.**
4. Phase 1: re-verify all 24 RSS feeds under real ingest conditions (network/health changes over time).
5. Append progress to this file at session end.

**Open / blocked:**
See `OPEN_QUESTIONS.md` (now includes PRAW rejection note).

---

## 2026-05-06 — Design session #1 (planning + docs scaffold)

**Done:**
- Surveyed `..\scrapers-lib`. Python lib. `tier1` covers RSS / Reddit (PRAW) / YouTube + transcripts / article extraction (justext); `core` provides rate limiting, caching, robots.txt, attribution, scheduler. Tier2/3 = retail/laptop scrapers, unused for this project.
- Walked through 6 clarifying questions: scope, LLM strategy, cadence, sources, output surfaces, cold-start.
- Brainstormed 3 architecture options (monolith / split-process / DuckDB+Streamlit) with tradeoffs.
- **Locked Option A** — single Python monolith + SQLite + HTMX + Ollama+Anthropic hybrid.
- Confirmed live-dashboard model and Monday-morning weekly report + on-demand regenerate.
- Committed to no historical backfill.
- Confirmed UI template will be built externally in claude.ai/design and handed over later.
- Initialized git repo (`git init`).
- Wrote all 8 design docs (this file + CLAUDE.md, README.md, PRD, ARCHITECTURE, DECISIONS, TASKS, OPEN_QUESTIONS).
- Created `.gitignore` for Python.
- Made initial commit: design-phase scaffold (no code yet).
- Created `sources.yaml` template; user then provided the actual list and it was populated: **13 RSS news sites + 11 subreddits + 6 YouTube channels = 30 sources**. RSS feed URLs are best-guess from standard CMS patterns; **Phase 1 smoke test must verify each** (1–3 likely need correction). Apparent duplicate of `r/Games` in the user's input was deduplicated. Counts differ slightly from PRD planning targets (15/10/6) — left PRD unchanged since the source list naturally evolves.
- Pre-flight verification of all 13 RSS feed URLs done in two passes:
  - **Pass 1 (WebFetch, generic UA):** 4 confirmed live, 1 redirect found (VentureBeat → GamesBeat), 8 inconclusive (403 / blocked by WAFs). WebFetch's UA was too restrictive to be authoritative.
  - **Pass 2 (scrapers-lib tier1.rss, in scrapers-lib's venv):** 11/13 worked on first try; 2 needed URL corrections found via alternates probe:
    - **Game Informer** `/feed` (404) → `/rss.xml` (✓ 50 entries).
    - **GamesBeat** `/feed` (403) → `/feed/` with trailing slash (✓ 10 entries).
  - **Final result: 13/13 RSS feeds confirmed working under scrapers-lib's actual fetcher** (~635 aggregate entries available). sources.yaml updated with the two URL fixes.
- Phase 1 smoke test should still re-verify before locking in (network conditions / source health change), but architectural type (`rss`) is confirmed correct for all 13 sites and the URL set is clean.
- Made follow-up commits. Session closed cleanly.

**Phase 0 start mode confirmed by user:** option (a) — begin skeleton next session with placeholder layout; port the claude.ai/design UI template in later as a swap-in.

**State at end of session:**
- Design phase complete. No code yet.
- All decisions captured in `DECISIONS.md`.
- Phase 0 ready to start. Can begin in parallel with UI template delivery using minimal placeholders.

**Next session should:**
1. (User to provide) UI template from claude.ai/design — when ready; not blocking Phase 0 skeleton.
2. Begin Phase 0 from `TASKS.md` with placeholder layout.
3. **Phase 1 first action: smoke-test every RSS feed URL in `sources.yaml`** before relying on them.
4. Append progress to this file at session end.

**Open / blocked:**
See `OPEN_QUESTIONS.md` for the running list.
