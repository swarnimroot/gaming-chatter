# Changelog

## [Unreleased]

### Added — Phase 3c.7: UI consistency + live search (2026-05-13)
- **Routing swap.** `/` now serves the weekly read-out (was `/reports`). Old `/` (raw items table) moved to `/dashboard`. Internal HTMX sub-endpoints stay at `/reports/exec-summary`, `/reports/drawer`, `/reports/export`. `/reports` returns 404 (no redirect — personal local tool).
- **Shared shell for Dashboard / Clusters / Sources.** New `app/templates/shell_base.html` + `_sidebar.html` partial provides the dark sidebar (nav + corpus stats) + main column with header chrome — identical visual treatment to the home page. Each non-home page extends `shell_base.html`; reports.html keeps its own inline shell (per-week Read-out section is unique to it).
- **`app/services/chrome.py` (new).** `NAV_ITEMS_BASE` (Weekly / Dashboard / Clusters / Sources) + `nav_items_for(active_id)` helper. Single source of truth for the sidebar nav.
- **Dashboard re-skin.** Old `<table>`-in-`base.html` replaced with a `.gc-table` rendering: source pill / when / title-+-TLDR / category-chip / sentiment-score columns. New `app/templates/_dashboard_list.html` partial for HTMX fragment swap.
- **Clusters re-skin.** Cluster rows render as `.gc-cluster-card`s — label + meta (score · members · sources · latest) + bordered member list with source pills.
- **Sources re-skin.** `.gc-table` with name pill / type / URL (mono) / status chip / last-fetched / errors columns.
- **Live HTMX search on Dashboard / Clusters / Sources.** `<input class="gc-search-input" hx-trigger="keyup changed delay:300ms" hx-push-url="true">` in each header. Server detects `HX-Request` and returns just the list partial. Filters use case-insensitive `ILIKE`:
  - Dashboard: title / TLDR / source.name
  - Clusters: cluster.label
  - Sources: name / url_or_handle
- **CSS additions (~150 lines).** `.gc-search-input` (matches `.gc-cta` height with accent-soft focus ring), `.gc-table` family (sticky header, bordered cells, hover row, tabular-num timestamps, chip variants `--ok`/`--bad`/`--off`), `.gc-cluster-card` family (label + meta + bordered member list), `.gc-pill-dot--youtube` (missing variant added).

### Fixed — Drawer empty rectangles (2026-05-13)
- Each item in the cluster drawer was rendering with two empty bordered rectangles. Root cause: `_drawer.html` wrapped each item in `<a class="gc-drawer-item" href="...">` and the inner source pill (from the `source_pill` macro) was also an `<a class="gc-pill" href="#">`. HTML doesn't allow nested `<a>`; the browser parser auto-closes the outer link before opening the inner one, producing an empty `.gc-drawer-item` border + orphaned content. Fix: drawer template renders the source pill inline as `<span class="gc-pill">` instead of calling the macro. Other consumers of the macro (Biggest stories on the home page) are unaffected because they're not inside another `<a>`.

### Added — Phase 3c.6: Executive 1-pager + standalone HTML / PDF export (2026-05-13)
- **Exec-summary modal upgraded to a 1-pager.** Header strip (week label + range + corpus stats) → existing Haiku 4.5 paragraph as the lead → structured sections pulled from `synthesis_json`: Biggest top-3 (numbered, with source-pill subline), Market momentum top-3 (with `gc-onepager-mmcat--{category}` chip), two-col Industry risks top-2 (with severity dot) / Community (1 heated + 1 celebrating). Same modal trigger; only the response shape changes.
- **`[Export HTML]` + `[Export PDF]` buttons in modal footer.** Both `target="_blank"` anchors to a new `GET /reports/export?week=...&format=html|pdf` endpoint. HTML serves as `Content-Disposition: attachment`; PDF serves inline with a `window.print()` script injected so the OS print dialog fires on load (user picks "Save as PDF"). Zero new deps.
- **Standalone HTML doc with inlined CSS.** New `_report_standalone.html` template embeds the full `app.css` (~33KB) inside a `<style>` block in `<head>`, plus `.gc-standalone-*` wrapper chrome and a `@media print` block. Self-contained — no external asset request, works as an email attachment, prints clean.
- **DB cache on `weekly_reports.html_content`.** First export renders + persists; subsequent exports read from the column (mirrors the Phase 3c.3 `exec_summary` cache). `?force=1` refresh. PDF route injects auto-print *after* the cache read so one canonical doc serves both render modes.
- **Graceful degrade on weeks without synthesis.** Modal renders Haiku paragraph + a `<code>scripts/run_synthesis.py {week}</code>` hint inside a dashed box; export buttons hidden. Server-side guard returns 409 with plain-text on direct URL access.
- **New module `app/services/export.py`** (~180 lines). `inline_css(refresh=False)` (module-level cached read of `app.css`), `build_payload(session, week_id, exec_*) -> dict | None` (shared between modal endpoint and export endpoint — returns None when synthesis hasn't run), `load_cached_html` / `save_cached_html`, `inject_auto_print`.
- **Endpoint changes in `app/routers/reports.py`:** `reports_exec_summary` rewritten to load synthesis + stats and render the 1-pager body; new `reports_export` endpoint (~75 lines) handles format validation, cache lookup, fresh render, and the two response shapes.
- **CSS additions (~170 lines):** `.gc-onepager-headstrip` / `-statstrip` / `-section` / `-sectlabel` / `-numlist` / `-buls` / `-itemtitle` / `-itemdek` / `-srclist` / `-mmcat` (5 category variants) / `-rlvl` (3 severity variants) / `-cstag` (heated + celebrating variants) / `-twocol` / `-empty` / `-nosynth` / `-exports` / `-export` (anchor styling); `.gc-standalone-body` / `-doc` / `-head` / `-eyebrow` / `-title` / `-foot` (export-only chrome); `@media print` block (hides overlays/sidebars, forces light background, page-break-inside avoid on sections, A4 margins). `.gc-modal-footer` `justify-content` flipped from `flex-end` to `space-between` to fit the attribution-text + export-buttons split.
- **No new Python deps.** Browser print dialog handles the PDF path; WeasyPrint / pdfkit / Playwright explicitly rejected per the locked single-process minimal-deps stack.

### Revised — Phase 3c.6 visual pass (2026-05-13, same-day after user review)
- **Export action moved from modal footer to header** as a CSS-only `<details><summary>Export ▾</summary>` dropdown next to the `.gc-modal-close` × button. Panel: `Save as PDF` + `Download HTML`. Footer dropped entirely — attribution moved to a one-line `gc-onepager-attribution` caption inline at the bottom of the body.
- **4-tile stat row at the top of the body** (`items` / `sources` / `top game · N` / `top genre · N`). Pulls from existing `top_games_for_week(limit=1)` + `top_genres_for_week(limit=1)` — no new queries.
- **Biggest deks dropped** — numbered list now shows title + source pills only. Single largest vertical-space saving.
- **Two-col Risks/Community → three-col MM/Risks/Community.** Market momentum joined the column strip instead of getting its own section. Column ratio 1.5fr / 1fr / 1fr.
- **Type scale shrunk ~25%** (lead 15→12.5px, numlist 13→12.5px, bul list 13→11.5px, section labels 10→9px, chip 9→8px). Stat tile values 17px bold (numbers) / 14px bold (names) / 9px uppercase label.
- **Stale `weekly_reports.html_content` cache invalidated** so the next export re-renders against the new layout.
- **`.gc-modal-footer` `justify-content`** reverted to original `flex-end` (we no longer use the footer).
- **Verified on fresh `:8001 --reload`:** W19 modal 200/6971 bytes (down from 8747, 20% smaller); 4 stat tiles, 3-col present, twocol absent, export dropdown + summary + panel with 2 anchors, 7 clipped item titles, 0 dek references, footer absent, attribution caption present. W18 (no-synthesis) degrades correctly: stat tiles + Haiku paragraph + nosynth note + CLI hint, export dropdown hidden. W19 export HTML 200/42401 bytes; PDF 200/42507 with auto-print injected. Test HTML saved to `exec_summary_W19.html` in project root for visual review.

### Verified — Phase 3c.6 end-to-end (on fresh uvicorn `:8002`)
- W19 modal: 200, 8747 bytes, 4 section labels, 10 list items (3 biggest + 3 MM + 2 risks + 1 heated + 1 celebrating), 2 export anchors, 3 MM chips, 2 risk dots, 2 CS tags, two-col layout, no-synth note absent.
- W18 modal (no synthesis): 200, 1724 bytes, 0 section labels, 0 export anchors, Haiku paragraph present, nosynth note + `scripts/run_synthesis.py 2026-W18` hint visible.
- W19 export HTML (cold): 200, 41935 bytes, `Content-Disposition: attachment; filename="gaming-chatter-2026-W19.html"`.
- W19 export HTML (warm): 200, identical 41935 bytes — DB cache hit.
- W19 export PDF: 200, 42041 bytes (cold HTML + 106-byte auto-print script), no Content-Disposition (inline), `window.print()` script verified present before `</body>`.
- W18 export: 409 + plain-text "Synthesis hasn't run for 2026-W18 — Run: `scripts/run_synthesis.py 2026-W18`".
- Bad format: 400.
- DB: `weekly_reports.html_content` populated 41935 bytes (matches response length) after first W19 export.
- Anthropic spend this session: ~$0.001 (1 Haiku call for the W18 modal degrade test, which auto-generated a missing exec_summary).
- `:8001` reloader stuck on stale code again (export endpoint 404; modal endpoint 500 from partial Jinja-only reload). Verified on fresh `:8002`; user to restart `:8001` to validate in their main session.

### Changed — Phase 3c.5: 9-card layout restructure (2026-05-13)
- **Sidebar:** nav trimmed from 6 placeholders to 4 real routes (Weekly read-out / Dashboard / Clusters / Sources); user-avatar block replaced with corpus-stats grid (items / clusters / sources) backed by new `corpus_stats(session)` helper in `app/services/reports.py`; "Generate exec summary" CTA removed (deduped with header).
- **Header:** Grid / Comfortable / Theme toggles removed (variants are locked statically — buttons were decorative); Exec-summary CTA preserved.
- **Cards 13 → 10** (walkthrough header said 13→9 but Trends came back as a single re-instated card, leaving 10): Card 1 ("This week in gaming") / Card 8 ("Studio watch") / Card 9 ("Storefronts") dropped.
- **Card 2 "Biggest" — plural top-3** (was: single hero with sparkline + heat/conf/relevance signal cluster + threads/velocity + "Read in detail" button). Each row = rank badge + title + dek + source pills + cluster-drawer trigger. Span-2 preserved. New `source_pills_for_clusters(session, cluster_ids)` helper derives pills from cluster members (synthesis schema doesn't carry them).
- **Card 4 "Market momentum" — row list** (was: 4-platform-sparkline placeholder grid). Each row = category chip + title + note + cluster-drawer trigger. 5 category color variants: acquisitions / funds / platform-policy / structural / people-moves. Absorbs the dropped Studio Watch + Storefronts per walkthrough.
- **Card 6 "Community sentiment" — narrative + heated/celebrating two-list** (was: aggregate pos/neu/neg bar + Top-threads placeholder). Narrative paragraph on top; two per-cluster lists with section eyebrows.
- **Card 7 "Industry risks" — `gc-risk-trend` chip dropped** ("stable" hardcode was a fabrication; "rising" requires multi-week corpus).
- **Card 10 "Esports & streaming" — row list of corpus-anchored clusters** (was: top_stream / big_event / movers placeholder). Honest about what the corpus has — no Twitch / esports metrics fabricated.
- **Empty-state pattern** with `synth_ran = week.cards.synthesis_meta` gate: differentiates between "synthesis hasn't run for this week" (action prompt: `scripts/run_synthesis.py 2026-W17`) and "synthesis ran, list was honestly empty" (e.g. "No esports / streaming stories in this week's corpus"). Applied to MM / Risks / Esports / Drama / Watch.
- **Router refactor:** `_apply_synthesis(session, cards, synth)` writes community / market_momentum / esports as first-class card keys (no more `*_synth` stash from the 3c.4 transition); biggest becomes a list; risks adapter drops the `trend` field. `_PLACEHOLDER_OTHER` / `_MOMENTUM_KEYS` / `USER` constants deleted. `_enrich_for_render` deleted (no sparkline geometry to compute anymore). New `_empty_cards()` helper used by both per-week build and empty-corpus fallback.
- **Removed chrome:** standalone headline block above the grid + footer hint block (locked walkthrough: both redundant with Biggest title + exec-summary CTA).
- **CSS cleanup:** ~17 dead-style blocks dropped (`.gc-segmented` / `.gc-toolbar-btn` / `.gc-icon-btn` / `.gc-headline-block` / `.gc-sb-cta` / `.gc-sb-user` / `.gc-sb-avatar` / `.gc-stats-row` / `.gc-genres` / `.gc-genre-*` / `.gc-bars-spacer` / `.gc-fresh` / `.gc-sent-bar` / `.gc-sent-legend` / `.gc-row--studio` / `.gc-row--platform` / `.gc-row--mover` / `.gc-row--thread` / `.gc-row-sub` / `.gc-row-event` / `.gc-row-platform-name` / `.gc-row-impact*` / `.gc-add-btn` / `.gc-sub-pill` / `.gc-thread-*` / `.gc-big-*` / `.gc-momentum-*` / `.gc-es-*` / `.gc-risk-trend` / `.gc-footer-hint` / `.gc-ghost-btn` / `.gc-card-clickable`). New blocks: `.gc-sb-corpus*`, `.gc-biggest*`, `.gc-mm-category*`, `.gc-cs-narrative` / `.gc-cs-divider` / `.gc-cs-dot*`, `.gc-row--mm` / `.gc-row--cs` / `.gc-row--esports`.

### Verified — Phase 3c.5 end-to-end (on fresh uvicorn `:8002`)
- **W19** (synthesis ran 3c.4): 200, 10 `.gc-card`, 3 plural-Biggest rows with pills, 5 MM category-chip rows, CS narrative + 1 heated + 2 celebrating rows, 2 risks rows (no trend chip), 0 esports → "No esports / streaming stories in this week's corpus", 1 drama row, 5 watch rows, 4 nav items, corpus stats `988 · 55 · 30`.
- **W18 + W17** (no synthesis): 200, 10 `.gc-card`, 7 "Awaiting synthesis. Run `scripts/run_synthesis.py 2026-W18`" prompts (Biggest / MM / CS / Risks / Esports / Drama / Watch); Hottest / Trends / Releases still render real data.
- **Bug caught + fixed mid-verification:** `corpus_stats.items` collided with Python `dict.items()` in Jinja attribute access (rendered `<built-in method items of dict object>`); fixed by switching to `corpus_stats['items']` bracket access.
- **No Anthropic spend** this session (pure template/router/CSS work).

### Added — Phase 3c.4: Weekly synthesis (Opus 4.7 + critic), Sonnet 4.6 cluster labels, cluster drawer (2026-05-13)
- **Sonnet 4.6 `label_cluster()` migration.** `app/services/anthropic.py` gains `ClusterLabelData` Pydantic + `CLUSTER_LABEL_SYSTEM_PROMPT` + `label_cluster(titles, tldrs)` mirroring the `tag_game()` shape. `app/services/cluster.py` import swapped (`ollama` → `anthropic`). New `ANTHROPIC_CLUSTER_LABEL_MODEL` env (default `claude-sonnet-4-6`).
- **One-time relabel of 55 per-week clusters** via new `--relabel-existing` flag on `scripts/run_cluster.py` (in-place, no re-cluster; filters out the 63 legacy `week_id='all'` rows). 101s, 55/55, ~$0.10.
- **DB migration:** `weekly_reports` gains `synthesis_json TEXT`, `synthesis_model TEXT`, `synthesis_generated_at TIMESTAMP` via idempotent `_migrate_weekly_reports_columns()`. `WeeklyReport` SQLModel extended.
- **`app/services/synthesis.py` (new module ~590 lines).** Single-call `WeeklySynthesis` Pydantic schema covering all 9 synthesizable card sections (biggest plural, hottest_reasons, market_momentum, community_sentiment narrative+heated_about+celebrating, risks, esports, drama, release_notes, watch, exec_summary_paragraph). Two Opus 4.7 calls: synthesis pass + critic pass (drop-and-replace revision). System block carries `cache_control: ephemeral`. Per-field `max_length` is a runaway-output guardrail (~2x the editorial cap from the prompt); first W19 run made the case against capping at the design intent (158-char `reason` failed a 140-char cap, burned ~$0.40). Input builder fetches top-12 clusters with 5 sample members each + Reddit-cluster sentiment summaries + week_stats + top games/genres/platforms/events + Trends WoW risers + upcoming releases.
- **`scripts/run_synthesis.py` (new).** CLI: `python scripts/run_synthesis.py 2026-W19 [--force] [--dry-run]`. Calls `init_db()` at import so it works without FastAPI lifespan.
- **Synthesis path overwrites `exec_summary_text` / `_model` / `_generated_at`** with the Opus paragraph. The 3c.3 modal endpoint serves the deeper version once synthesis has run; footer reads `cached · claude-opus-4-7 · …`.
- **Drawer `kind=cluster`** (alongside game / genre / platform / event). Service resolves int cluster_id → `member_item_ids` → joins to items+sources+enrichments. Drawer header swaps the numeric id for the cluster's Sonnet-relabeled `label`.
- **Router wires synthesis JSON into existing 13-card template via `_load_synthesis` + `_apply_synthesis`.** Biggest hero shows `synthesis.biggest[0]` (full plural list stashed under `cards["biggest_list"]` for Phase 3c.5). Risks / drama / watch adapted to existing row shapes. Hottest_reasons + release_notes overlaid by case-insensitive game-name match. Mismatched-shape sections (community, MM, esports) stashed under `cards["*_synth"]` keys awaiting 3c.5 layout restructure.
- **`reports.html` row triggers** for Biggest hero (whole card clickable via inline radio-flip + `hx-get`; can't use `<label>` because the card contains other interactive elements), Risks rows (conditional `<label>` when `cluster_id` present), Drama rows (same), Watch rows (same; also dropped the "+" Add-reminder button per walkthrough lock). Hottest `hot_rows` macro got a `gc-row-reason` subline; Releases row got the same for `note`.
- **`app.css` additions:** `.gc-card-clickable` + `:hover`, `.gc-row-reason` (Hottest/Releases sublines), extended `.gc-row-trigger:hover` to also color risk/drama/watch titles.

### Verified — Phase 3c.4 end-to-end
- **Relabel:** 55/55 in 101s, ~$0.10. Sample improvements: "2K NFL and MLB game future" → "Take-Two exits NFL and MLB licensed sports games"; "Aliens: Fireteam Elite 2 announcement" → "Aliens Fireteam Elite 2 officially announced by Cold Iron Studios".
- **Synthesis dry-run:** input prompt ~40k chars / ~10k tokens — well within Opus's 200k window.
- **Synthesis live run W19:** 57.7s, synthesis returned biggest=3 MM=5 risks=3 esports=0 drama=1 watch=5; critic returned biggest=3 MM=5 risks=**2** (dropped 1 out-of-scope item) esports=0 drama=1 watch=5. Persisted as 7395-char JSON.
- **Spend forecast vs actual:** forecast ~$0.45; actual ~$1.30 (the burned synthesis call from the Pydantic-cap retry ~$0.40 + the second-attempt full run ~$0.90). Above forecast but inside PRD's $1-5/month target.
- **Sample W19 output:** Biggest "Nintendo announces Star Fox 64 remake for Switch 2, dated June 25"; Risks "UK age-verification laws draw coordinated opposition" / "Wizardry IP ownership disputed between Atari and Drecom"; Drama "Mortal Kombat 2 producer attacks critics over negative reviews"; Watch (5): specific releases + IP-dispute follow-up + Xbox lineup tracking. Exec summary names Star Fox 64 / Griffin Gaming Partners $100M fund / Pearl Abyss CCP Games $120M sale / Mixtape reviews / UK age-verification opposition — every specific number and entity grounded.
- **Router:** `/reports?week=2026-W19` 200 with 7 cluster-drawer triggers + 14 reason/note sublines on Hottest/Releases rows. Hero card title is the synthesized one.
- **Cluster drawer:** `/reports/drawer?kind=cluster&value=81&week=2026-W19` 200, header "Cluster · Star Fox 64 remake announced for Switch 2 · 7 items · Week of May 4, 2026"; lists 7 articles with source pills + tldrs + outbound links.
- **Modal:** `/reports/exec-summary?week=2026-W19` 200; footer reads `cached · claude-opus-4-7 · generated May 13, 18:42 UTC`.

### Decided — Phase 3c.4 locked choices
- **One big structured Opus call**, not per-section. PRD + 2026-05-11 lock both presume single-call ($1-5/month, ~$0.30/run).
- **Critic returns revised synthesis** (drop-and-replace), not critique-then-merge.
- **`max_length` is a runaway-output guardrail**, not a design cap. ~2x the editorial intent. Prompt encodes the cap as a soft target.
- **Synthesis persists to `weekly_reports.synthesis_json`**; `markdown_content` / `html_content` stay reserved for Phase 3d standalone-HTML export.
- **Synthesis overwrites `exec_summary_text`** so the 3c.3 modal serves the deeper Opus version once synthesis has run.
- **`kind=cluster` drawer**, not a per-cluster `synthesis_text` column. The drawer listing member articles is sufficient editorial context; per-cluster narrative deferred indefinitely.
- **Biggest hero card uses inline `onclick`** for the radio flip; `<label>` can't wrap interactive form controls.

### Surfaced (not fixed) — `r.trend` field still rendered
- Risks template still includes `<span class="gc-risk-trend">{{ r.trend }}</span>` reading the router-side adapter's hardcoded `"stable"`. Locked walkthrough decision was to drop the trend chip ("'rising' requires multi-week corpus we don't have yet"). Drop in the 3c.5 template cleanup.

### Added — Phase 3c.3: Source drawer + Exec-summary modal port (2026-05-13)
- **`app/db/models.py` + `app/db/init.py`** — three new optional columns on `weekly_reports` (`exec_summary_text TEXT`, `exec_summary_model TEXT`, `exec_summary_generated_at TIMESTAMP`); idempotent `_migrate_weekly_reports_columns()` in init.py mirrors `_migrate_games_columns()` pattern.
- **`app/services/reports.py`** — new public `items_for_entity_in_week(session, kind, value, week_id, limit=25) -> list[dict]` backs the drawer. `kind ∈ {game, genre, platform, event}`; rows are `{id, title, url, published_at, when_display, tldr, sentiment_score, sentiment_summary, category, source_name, source_kind}`. Reuses existing `json_each(e.entities, '$.games') / json_each(e.genres) / json_each(e.platforms)` patterns; nothing new at the SQL layer. Helpers: `_drawer_source_kind()` (outlet / youtube / subreddit mapping in one place), `_relative_when()` (`"3 d ago"` formatting).
- **`app/services/exec_summary.py` (new module)** — `get_or_generate(session, week_id, force=False) -> dict`. Lazy Haiku 4.5 call on cache miss + persistence to `weekly_reports`. Internal: `_build_input_text()` assembles a compact prompt body from existing `services.reports` queries (week stats + top genres / platforms / games + Trends risers + upcoming releases — no aggregation duplicated). `_call_haiku()` wraps `client.messages.create()` with the system block + `cache_control` marker (forward-compatible with prompt caching once the prompt grows past the cacheable minimum). System prompt forbids fabrication, requires 3-5 sentences naming the strongest concrete signal first, drops marketing voice and first/second person.
- **`app/config.py`** — `ANTHROPIC_EXEC_SUMMARY_MODEL` env-overridable, defaults to `claude-haiku-4-5`. Kept separate from `ANTHROPIC_ENRICH_MODEL` so a future model swap doesn't bleed across passes.
- **`app/routers/reports.py`** — two new endpoints: `GET /reports/drawer?kind=&value=&week=` renders `_drawer.html`; `GET /reports/exec-summary?week=` renders `_exec_summary.html`. Both gracefully degrade on bad inputs via an `error` flag in the fragment context. Main `/reports` context now carries `active_week_key` so trigger URLs interpolate cleanly across the three modal triggers and every row trigger.
- **`app/templates/_drawer.html` + `_exec_summary.html` (new)** — header / body / footer fragment templates. Drawer body uses the existing `source_pill` macro from `_components.html`; modal body shows a single `<p class="gc-exec-paragraph">` with attribution footer (`fresh|cached · model · generated-at`).
- **`app/templates/reports.html` rewired** — HTMX 2.0.3 `<script>` added to `<head>` (the page is standalone, doesn't extend `base.html`, so HTMX has to load here). Four hidden state radios as direct children of `<body>`: `drawer-closed` (checked), `drawer-open`, `modal-closed` (checked), `modal-open`. Drawer overlay + panel + close button + body wrap shell, and modal overlay + card + close button + body wrap shell, as direct children of `<body>` after `.gc-shell` so the `:checked ~ .panel` sibling selectors work. Three exec-summary triggers (sidebar `.gc-sb-cta`, header `.gc-cta`, footer `.gc-ghost-btn`) rewritten as `<label for="modal-open" hx-get="/reports/exec-summary?week={{ active_week_key }}" hx-target="#exec-summary-body" hx-swap="innerHTML">`. `hot_rows()`, `trend_rows(rows, kind)`, and the Releases row all rewritten as `<label class="gc-row ... gc-row-trigger" for="drawer-open" hx-get="/reports/drawer?kind=...&value={{ ...|urlencode }}&week={{ active_week_key }}" hx-target="#source-drawer-body">`. Trends macro's new `kind` parameter is called with `game / game / genre / platform / game / event` across the five tabs (live-service-tab still uses `kind=game`).
- **`app/static/app.css`** — new block at end: `.gc-overlay-state` (hidden radio), full `.gc-drawer-*` set (overlay, panel, close, header, title, meta, body-wrap, body, item, item-head, item-when, item-title, item-tldr, footer, foot-note), mirror `.gc-modal-*` set, shared `.gc-row-trigger` cursor + hover-tint, `.gc-exec-paragraph` typography. `:checked ~ ` selectors on `#drawer-open` / `#modal-open` slide each panel in (`transform: translateX(0)` / `opacity:1`). Overlays use `opacity` + `pointer-events` so backdrop clicks still close. `@media (prefers-reduced-motion: reduce)` disables transitions. HTMX `htmx-request` class on the panel drives a "loading…" / "Generating…" hint inside the panel body during the fetch.

### Verified — Phase 3c.3 end-to-end
- `/reports?week=2026-W19` 200, 55 drawer triggers + 3 modal triggers + both shells in rendered markup. All four state radios + both overlays + both panels present.
- `/reports/drawer?kind=game&value=Mixtape&week=2026-W19` 200, 15 items rendered (Kotaku, Reddit, etc. with source pills + tldrs + outbound links). `kind=genre&value=Action` 25 items. `kind=platform&value=PC` 25 items. `kind=event&value=Summer Game Fest` 1 item. `kind=game&value=BadGameThatDoesntExist` 0 items + empty-state row. `kind=bogus&value=x` returns the fragment with an `error` flag set.
- `/reports/exec-summary?week=2026-W19` first call 5.5s elapsed (Haiku cache miss, 1 API call), second call 2.1s (DB cache hit, footer reads `cached · claude-haiku-4-5`). DB row written: `week_start=2026-05-04`, `exec_summary_text` 635 chars, `exec_summary_model=claude-haiku-4-5`, `exec_summary_generated_at=2026-05-13 15:48 UTC`.
- Sample paragraph (W19): "Star Fox dominated gaming coverage this week with 20 mentions and a 3.1 percentage-point rise, driven by anticipation ahead of its June 25 release, while the remaster Star Fox 64 drew 12 mentions and a 2.2pp gain. Action and Adventure genres led discussion across 98 and 56 stories respectively, with PC platforms commanding 121 mentions and both Xbox and Nintendo platforms gaining ground week-over-week. Near-term attention is shifting toward May's release slate, including Thick As Thieves on May 20 and Batman & Robin on May 22, while MMO sentiment climbed 4.4pp with EVE Online picking up mentions alongside live-service tracking." — specific names, specific numbers, no fabrication, 3 sentences.
- Spend: ~$0.001 (one Haiku call). Cumulative project ~$6.16.

### Decided — Phase 3c.3 locked choices
- **Drawer orientation: entity-drill, not source-drill.** Bundle's source-keyed drawer flipped to entity-keyed; source pills inside drawer items still give back outbound-source affordance.
- **Drawer scope this phase: Trends + Releases + Hottest.** Biggest / Momentum / Risks deferred to 3c.4 (no real data yet).
- **Toggle: hidden radio + `<label for>` (CSS-only state).** `:target` URL fragments rejected after closer read of HTMX behavior (`hx-get` on `<a>` `preventDefault`s the click, suppressing native hash navigation).
- **Exec-summary model: Haiku 4.5.** Cost ~$0.001 per cache-miss; one call per week.
- **Exec-summary persistence: new columns on `weekly_reports`.** Separate `exec_summaries` table rejected — `weekly_reports` already owns the week-grain and Phase 3c.4 will fill `markdown_content`/`html_content` on the same row.

### Surfaced (not fixed) — `Summer Game Fest` event count
- The drawer for `kind=event&value=Summer Game Fest&week=2026-W19` returned 1 item. Worth checking whether the corpus actually has only 1 SGF mention this week or whether casing / phrasing variants split the count. Not blocking 3c.4.

### Added — Phase 3c.2: Trends card (5-tab WoW mention-rate delta) (2026-05-13)
- **`app/services/reports.py` extended.** Five new public queries (`top_genres_wow`, `top_platforms_wow`, `top_games_wow(lifecycle=…)`, `top_live_service_wow`, `top_events_wow`) plus a single `trends_for_week(session, week_id, limit=5)` aggregator that returns the full 5-tab payload. Math: per-entity `(count_this / total_this) - (count_prev / total_prev) * 100`, expressed as `+X.Xpp`, sorted signed DESC. Falling-and-gone entries (`count_this == 0`) filtered. Helpers: `prev_week_id()`, `week_item_total()`, three case-insensitive entity-count dicts (`_tag_counts_for_week`, `_game_counts_for_week(lifecycle=, live_service_only=)`, `_event_counts_for_week`), and a generic `_merge_wow()` that does the rate-delta computation + top-N selection.
- **`app/routers/reports.py` wired.** `_build_week_payload()` calls `trends_for_week()` and sets `cards["trends"]`. Old `{"wow": […], "mom": []}` placeholder removed from `_PLACEHOLDER_OTHER`. Empty-corpus fallback gets a defensive `{"has_prior": False}` shape.
- **`app/templates/reports.html` Card 5 rewritten.** 5-tab CSS-only radio structure (`trend-tab-games` checked by default, then `-genres`, `-platforms`, `-liveservice`, `-events`). Games tab has stacked Current + Upcoming sub-sections via `.gc-trend-subhead` mini-eyebrows. New `trend_rows(rows)` macro emits `gc-row--trend` rows with `gc-trend-name` (with `count this week · prev prior` tooltip) and the existing `delta()` macro for `+X.Xpp ▲` / `-X.Xpp ▼` / `±0pp •`. Per-tab `gc-row-empty` for sparse states; full-card "Need 2 weeks of data" notice when `has_prior=False`. Card-header WoW/MoM segmented toolbar dropped (WoW-only locked 2026-05-12).
- **`app/static/app.css` updated.** New `.gc-trend-tabs { position: relative; }` + five `:checked ~` rules each for active label styling and pane display (mirroring `.gc-hot-tabs`). New `.gc-trend-subhead` / `.gc-trend-subhead--second` / `.gc-trend-name`. Legacy `.gc-trend-tabs button` + `.is-active` rules deleted. Global `.gc-tab-input` / `.gc-tab-labels` / `.gc-tab-label` / `.gc-tab-pane` rules (from Phase 3c.1) reused unchanged.

### Verified — Phase 3c.2 end-to-end
- All three visible weeks (W17 / W18 / W19) render `/reports` 200 with the new Trends card. Sample W19 data spot-checked: Games-Current top-5 Mixtape +2.7pp / LEGO Batman +1.8pp / EVE Online +1.3pp / Civilization 7 +1.1pp; Genres MMO +4.4pp / Action +1.9pp; Platforms Xbox +2.9pp / Nintendo +2.5pp / PC -2.4pp (share fell despite raw count growth — exactly the signal rate-delta surfaces). W18 events tab shows 2 negative-delta events (Gamescom -0.6pp, Other-showcase -1.2pp) — coherent with the corpus lull between major events.
- W17 (earliest visible cluster week) has prior W16 with 20 items, so `has_prior=True` and the full-card empty-state path is only reachable via the empty-corpus fallback.

### Surfaced (not fixed) — taxonomy drift in enrichments tags
- `enrichments.genres` column has out-of-taxonomy values (`MMO`, `Indie/Roguelike`, `Survival-horror`, `Multi-platform`) despite the locked 12-genre taxonomy from Phase 3c.0. `platforms` column has `Multi-platform` despite the 6-platform lock. Likely cause: Pydantic field validators in `app/services/ollama.py` were the safety net, but the Phase 3c.0.5 Haiku migration may not have run them, or Haiku occasionally returns enums that slip past. Not blocking 3c.3/3c.4; logged as optional hygiene.

### Added — Phase 3c.0.5: Anthropic Haiku 4.5 per-item enrichment + tag_game + full backfill (2026-05-12)
- **`app/services/anthropic.py` (new).** Haiku-backed `enrich_item()` + `tag_game()`. Uses `client.messages.parse(output_format=...)` for structured Pydantic returns, system-block `cache_control` marker (forward-compatible — current SYSTEM_PROMPT is ~855 tokens, under Haiku 4.5's 4096-token caching min, so no-ops harmlessly). Reuses `EnrichmentData`, `GameTagData`, `SYSTEM_PROMPT`, `GAME_TAG_SYSTEM_PROMPT`, `_ALLOWED_CATEGORIES` from `app/services/ollama.py` — single source of truth for schema + prompt + validators. Wraps `anthropic.APIError` + `pydantic.ValidationError` as `ValueError` so the existing `_persist_failed()` path keeps working unchanged. Lazy-init module-level client; SDK reads `ANTHROPIC_API_KEY` from env.
- **One-line import swap in `app/services/enrich.py`** — `enrich_item` now from `anthropic`. Everything else (`embed_text`, `extract_video_id`, `fetch_youtube_transcript`, `_persist_*`, `RunLog`) untouched. One-line swap in `scripts/populate_games_dim.py` too.
- **`python-dotenv` added as a dep + `.env` loader wired in `app/config.py`.** `load_dotenv(ROOT / ".env")` at module import so API keys can live in a gitignored `.env` instead of the parent shell. Real env vars still take precedence. Config additions: `ANTHROPIC_ENRICH_MODEL` (default `claude-haiku-4-5`), `ANTHROPIC_TIMEOUT` (default 120s).
- **`scripts/sample_haiku_enrichment.py` (new).** Picks 10 items prioritized for known-bad cases (Minions movie miscategorization + Reddit-handle leak in `entities.people`), diversified by category, then fills with newest. Calls Haiku directly (no DB writes), writes a side-by-side markdown diff to `docs/SAMPLE_HAIKU_<date>.md` for user sign-off.

### Verified — Phase 3c.0.5 end-to-end
- **10-item Haiku sample** ran in ~30 sec, ~$0.04. Both known-bad cases visibly fixed: Minions now `games=[] / genres=[] / companies=['Universal Pictures']` (was `games=['Minions & Monsters'] / genres=['Indie/Roguelike']`); Reddit handle `Responsible_Box_2422` no longer in `entities.people`.
- **Full 988-item backfill via Haiku** — 39.5 min @ ~2.4 s/item. **988 attempted, 887 OK, 88 skipped (body < 200 chars), 13 preserved (Haiku returned out-of-taxonomy category; safety net kept prior valid qwen row), 0 hard failures.** Spend ~$3-4.
- **Re-embed of all 900 OK rows** required because Haiku rewrote the tldrs. SQL `UPDATE enrichments SET embedding=NULL WHERE status='ok'` then `embed_pending()`. 37 min, 900/900 OK, 0 failures. Free (Ollama local).
- **`populate_games_dim.py` executed** against the Haiku-enriched corpus. 189 unique games (min_mentions=2) tagged via Haiku `tag_game()`. 3.6 min, 0 failed. Distribution: 131 existing / 28 upcoming / 30 null-unknown; 55 live_service=true. ~$0.60.
- **`run_cluster.py --per-week` executed.** 55 new clusters across `2026-W17` (4) / `W18` (13) / `W19` (38). 4.5 min, 0 label failures. Cluster labels still on qwen2.5:7b — Sonnet 4.6 migration deferred to Phase 3c.4 bundled with synthesis. Legacy 63 `week_id='all'` clusters from Phase 3b remain in DB pending a cleanup decision.
- **Total Phase 3c.0.5 spend: ~$5** (inside the $500/yr ceiling locked 2026-05-12 later).

### Deferred / open
- 13 preserved-qwen items can be re-run by widening `_ALLOWED_CATEGORIES` to include observed-but-rejected values like `'guide'`, then targeted-rerun. Note: `_rerun_targeted_ids` in `scripts/rerun_enrichment.py:34` still imports `ollama_enrich_item` — needs swapping if used.
- Cleanup of the 63 legacy `week_id='all'` clusters (script intent was "replace") — deferred to next session for user decision.
- `label_cluster()` Sonnet 4.6 migration — deferred to Phase 3c.4 with synthesis.

### Added — Phase 3c.0 tagging foundation: schema + structured-output enrichment + per-week cluster scaffolding (2026-05-12)
- **Schema migration.** `app/db/init.py:_migrate_enrichments_columns` extended idempotently with `genres TEXT`, `platforms TEXT`, `event TEXT` columns on the `enrichments` table; new `games` dim table created (`name TEXT PRIMARY KEY`, `lifecycle TEXT`, `live_service INTEGER`). `Game` SQLModel class added to `app/db/models.py`. Verified via PRAGMA + a double-call `init_db()` for idempotency.
- **Ollama enrichment switched to structured-output (JSON schema) mode.** `app/services/ollama.py` SYSTEM_PROMPT restructured to demand `genres[]` / `platforms[]` / `event`; `EnrichmentData.model_json_schema()` passed directly as the Ollama `format` parameter (replacing `format:"json"` which silently omitted the new fields). `required` override on the schema forces the 3 new fields to appear despite their Pydantic defaults. Pydantic field validators drop out-of-taxonomy values; genres capped at 3. Locked taxonomies: 12 genres / 6 platforms / 12 events + Other-showcase.
- **`tag_game()` + `GameTagData` + `_game_tag_json_schema()`** added to `app/services/ollama.py` for the per-game `lifecycle` / `live_service` pass (separate from per-item enrichment so a game referenced by N clusters is tagged once consistently). Dedicated `GAME_TAG_SYSTEM_PROMPT` with the locked fuzzy rules.
- **`scripts/populate_games_dim.py` (new)** — extracts unique game names from `enrichments.entities` via `json_each`, filters to ≥2 mentions (configurable), idempotent INSERT into the `games` dim. Flags: `--limit`, `--sample`, `--min-mentions`.
- **`scripts/run_cluster.py` rewritten** with argparse + `--per-week` mode that iterates ISO weeks via `datetime.fromisocalendar()`, calling `cluster_window()` per week to replace the prior `week_id='all'` global clustering. Backward compat preserved (no args → legacy `"all"`).
- **`scripts/rerun_enrichment.py` (new)** — backfill driver for the re-enrichment pass.

### Aborted / blocked (later resolved in Phase 3c.0.5 above)
- **908-item re-enrichment run was aborted mid-run.** Killed after ~25 items: structured-output mode pushed qwen2.5:7b to ~26s/item (~7-hour ETA vs the ~45-min estimate); a 10-item sample exposed quality issues that the prompt restructure did not fix (Reddit username `Responsible_Box_2422` leaked into `entities.people`; the movie *Minions & Monsters* was tagged with `Indie/Roguelike`). User decision: pivot per-item enrichment to **Anthropic Haiku 4.5** before retrying the backfill — overrides the "Ollama-only for per-item work" architectural lock. See DECISIONS 2026-05-12 (later). DB state: ~25–30 items now hold partial qwen rewrites; next-session Haiku rerun will overwrite all 988 uniformly, no rollback needed.
- **`scripts/populate_games_dim.py` + `scripts/run_cluster.py --per-week`** both have code staged but execution is blocked on the Haiku backfill (they need to run against a uniformly-tagged corpus, not the qwen partial).

### Locked (2026-05-12, later)
- **Override of "Ollama-only for per-item work" lock.** Per-item enrichment now uses Anthropic Haiku 4.5. Cluster labels move to Anthropic Sonnet 4.6. Synthesis gains a critic / editor pass via a second Opus 4.7 call. Embeddings stay on local Ollama (`nomic-embed-text` 768-dim). Estimated total Anthropic spend ~$210–310/yr — inside the user's $500/yr ceiling. See DECISIONS 2026-05-12 (later) for the concrete-evidence rationale (qwen quality ceiling + structured-output runtime + budget headroom).

### Added — claude.ai/design weekly read-out ported to `/reports` (2026-05-11)
- `app/templates/reports.html` — standalone HTML doc (does NOT extend `base.html` — the design has its own full-bleed sidebar + main shell). Renders all 13 cards from the design's `cards.jsx` in default order with placeholder data verbatim from `data.jsx`. Locked variants: grid layout (3-col, biggest spans 2), comfortable spacing, light theme, orange accent `#D9682B` (editorial amber).
- `app/templates/_components.html` — Jinja macros mirroring `primitives.jsx`: `eyebrow`, `source_pill`, `source_row`, `freshness`, `meter`, `signal_cluster`, `mini_bar`, `delta`, `dot`, `sparkline`, `card_header`.
- `app/routers/reports.py` — `GET /reports?week=...` route (3 sample weeks selectable: `2026-W18` default, `2026-W17`, `2026-W16`); placeholder `WEEKS_RAW` mirroring `data.jsx` shape; `sparkline_path()` helper that reproduces the JSX sparkline geometry in Python; `SOURCES_META` / `NAV_ITEMS` / `USER` constants.
- `app/static/app.css` — rewritten. Legacy `body / table / .cluster*` rules preserved on top so Dashboard/Sources/Clusters keep working unchanged. Below: `:root` CSS variables (locked palette + spacing + motion tokens) and `.gc-*` namespace for sidebar, header, grid, card, signal cluster, source pills, sparkline, meters, delta, severity badges, risk/drama callouts, all row layouts.
- `app/static/img/alienware-head-light.svg` — sidebar logo, copied from the bundle.
- `app/main.py` — one-line additive: mount `reports.router`.
- `app/templates/base.html` — one-line additive: `Reports` nav link.

### Locked (2026-05-11)
- **Phase 3c industry-risks rubric:** layoffs/closures + regulation/legal/policy. Excludes broader market structural shifts and consumer-side pressures. See DECISIONS 2026-05-11.
- **Phase 3c community-sentiment rubric:** Reddit-only hybrid — numeric `mean(sentiment_score)` over Reddit-source cluster members + 2–3 `sentiment_summary` excerpts passed to Anthropic. See DECISIONS 2026-05-11.
- **Phase 3c synthesis model:** Opus 4.7 (`claude-opus-4-7`). ~$15/yr at weekly cadence. See DECISIONS 2026-05-11.
- **WoW-Trends section deferred** entirely from Phase 3c; when it lands later it will be WoW only (no MoM). Trends needs schema additions or a synthesis-time tagging pass for platform/genre/live-service/lifecycle dimensions. See DECISIONS 2026-05-11.

### Verified
- `GET /reports` smoke-tested: HTTP 200, ~40KB response. 54× `gc-card` class refs in markup, 5× `<polyline>` (biggest card + 4 momentum cells), 11× `data-lucide` icons, 4× `is-active` markers. Headline + week selector + all 13 card sections render. Other 2 weeks selectable via `?week=` query.

### Implementation simplifications vs the React/JSX prototype
- Dropped: drag-to-reorder cards, Tweaks panel, layout/density/theme runtime toggles (kept as static visual buttons in the header since variants are locked), exec-summary modal, SourceDrawer side panel.
- Sidebar nav items beyond "Weekly read-out" are `href="#"` visual placeholders pending the next-session walkthrough.
- Lucide icon CDN kept (`unpkg.com/lucide@latest`); React 18 + ReactDOM + Babel-standalone runtime stripped.

### Added — Phase 3b cluster ranking heuristic (2026-05-08)
- `clusters` table: three new columns (`source_count INTEGER`, `latest_published_at TIMESTAMP`, `score REAL`), added via idempotent SQLite ALTER in `app/db/init.py:_migrate_clusters_columns`. `Cluster` SQLModel updated.
- `app/services/cluster.py:cluster_window` now computes and persists per-cluster `source_count` (distinct member sources), `latest_published_at` (max member `published_at`), and `score = source_count * member_count / (1 + days_since_latest)` alongside the existing label/centroid/member fields. See DECISIONS 2026-05-08 for formula rationale.
- `app/routers/clusters.py:clusters_view` sorts by `score DESC NULLS LAST, member_count DESC` (was: `member_count DESC`).
- `app/templates/clusters.html` cluster card now shows `score N.N` and `latest YYYY-MM-DD` alongside member/source counts. Minor `.cluster-meta .score` weight bump in `app/static/app.css`.
- `scripts/inspect_cluster_ranking.py` — one-off script to dump top-N clusters by score for ranking review.

### Verified
- Re-ran `cluster_window(week_id='all')` on the 908-item corpus: 63 clusters / 157 items / 63 labelled / 0 failures. 186.0s wall clock.
- Top of ranked list: Mixtape coming-of-age review (5×5, today) 12.79; Griffin Gaming Partners $100M indie fund (4×5) 10.02; Take-Two/BioShock disappointment (4×4) 7.75; Star Fox 64 Switch 2 remake (4×4) 6.76; Valve restocks Steam Controller (4×4, 1d) 5.97. All 14 single-source long-tail clusters (YongYea / VG247 / Fallout walkthroughs / Game Informer weekly picks) scored <1.0 and sank to the bottom — the demotion the prior session called for.
- `GET /clusters?week_id=all` smoke-tested: HTTP 200, 88KB, score + latest date rendering on each card.

### Added — Phase 3a clustering + cluster labels (2026-05-08)
- `app/services/cluster.py` — `cluster_window(start, end, week_id)`: cosine connected-components clustering at `CLUSTER_THRESHOLD=0.85` (locked after corpus exploration; see DECISIONS 2026-05-07) over fp32 768-dim TL;DR embeddings. Persists per-cluster centroid (BLOB), member item IDs (JSON in TEXT), label, member_count to the `clusters` table keyed by `week_id`. Idempotent: re-runs delete prior rows for the same `week_id`. Writes a `RunLog` row with `job_type='cluster'`.
- `app/services/ollama.py` — `label_cluster(titles, tldrs)` helper: qwen2.5:7b in JSON-mode, returns a one-line cluster label. ~3s per call. System prompt with 5 worked examples.
- `app/routers/clusters.py` — `POST /clusters/run?week_id=&sync=` (manual trigger) and `GET /clusters?week_id=` (HTML view of clusters with per-member item links and source counts).
- `app/templates/clusters.html` + cluster card CSS in `app/static/app.css`. Nav link added to base layout.
- `scripts/run_cluster.py` — standalone runner (matches `run_enrich_batch.py` / `run_article_fetch.py` pattern). Optional `week_id` arg.
- `scripts/explore_clustering.py` — utility for re-tuning the threshold against the live corpus (kept around; not on the runtime path).
- Settings (`app/config.py`): `CLUSTER_THRESHOLD=0.85`, `CLUSTER_MIN_SIZE=2`, `CLUSTER_LABEL_SAMPLE=8`.

### Verified
- First production run on the 908-item corpus (`week_id='all'`): **63 clusters, 157 items grouped (17.3% of corpus), 63/63 labelled, 0 failures.** Wall clock 178.8s. Centroid blobs verified at 3072 bytes (= 768 fp32). UI smoke-tested: `GET /clusters` returned 200 with all 63 clusters rendering correctly.
- Label quality (eyeball): ~50/63 clean editorial signals (e.g. "Wizards of the Coast misses union recognition deadline", "Greedfall developer Spiders closing", "Star Fox 64 remake for Switch 2"). ~10–13 vague or single-source long-tail clusters acceptable — they will be deprioritized by the cross-source × signal × recency ranking heuristic in Phase 3b.

### Added — Phase 2.5 article body-fetch remediation (2026-05-07)
- `app/services/article_fetch.py` — `fetch_skipped_bodies()` re-fetches full article bodies for items whose enrichment status is `skipped`, via `scrapers_lib.tier1.article` (trafilatura). Updates `Item.body_text` only when the extracted body meets `ENRICH_BODY_CHAR_MIN`. Excludes YouTube items (transcript path handles those) and Reddit URLs (link-post pages return no extractable content — see DECISIONS 2026-05-07). 1s inter-request delay. Writes a `RunLog` row with `job_type='article_fetch'`.
- `scripts/run_article_fetch.py` — standalone runner that chains `fetch_skipped_bodies` → `enrich_pending(retry_failed=True)` → `embed_pending()` so the full Phase 2.5 pass runs unattended.

### Verified
- Full Phase 2.5 batch on the 173 skipped items: 95 attempted (after Reddit/YT exclusion), 94 fetched, 1 errored. Re-enrich produced 93 ok + 1 failed; embed top-up produced 93 new fp32 embeddings, 0 failed. Wall clock: 16m44s (fetch 2m12s, enrich 11m02s, embed 3m31s). **Final corpus: 988 items → 908 ok / 79 skipped / 1 failed. Coverage 82.5% → 91.9%.** 94/95 of the addressable subset recovered (98.9%).

### Added — Phase 2 local LLM enrichment + embeddings (2026-05-07)
- `app/services/ollama.py` — httpx client for `/api/generate` (JSON-mode) + `/api/embeddings`. Pydantic-validated `EnrichmentData` (tldr, entities, category, sentiment_score, sentiment_summary). Embeddings serialized as fp32 numpy bytes for SQLite BLOB storage. YouTube transcript fetch via `scrapers_lib.tier1.youtube` on-demand at enrichment time, with graceful fallback to ingest-time body when transcripts are unavailable / blocked.
- `app/services/enrich.py` — two-pass orchestration (`enrich_pending` then `embed_pending`) to avoid model swap thrash. Persists `status='ok' | 'failed' | 'skipped'`. Items below `ENRICH_BODY_CHAR_MIN` (default 200) are persisted as `skipped` rather than enriched from a useless title-only body.
- `app/routers/enrich.py` — `POST /enrich/pending` and `POST /embed/pending`, both with `?sync=true&limit=N` for sanity gates. Auto-chained after `POST /sources/ingest-all`.
- `enrichments` table: added `status` and `error` columns (idempotent SQLite ALTER in `app/db/init.py:_migrate_enrichments_columns`).
- Settings (`app/config.py`): `OLLAMA_HOST`, `OLLAMA_ENRICH_MODEL=qwen2.5:7b`, `OLLAMA_EMBED_MODEL=nomic-embed-text`, `OLLAMA_NUM_CTX=8192`, `OLLAMA_KEEP_ALIVE=24h`, `ENRICH_BODY_CHAR_CAP=24000`, `ENRICH_BODY_CHAR_MIN=200`.
- Dashboard renders TL;DR + category chip + sentiment per item, plus an "Enrich pending (N)" trigger.
- `scripts/run_enrich_batch.py` — standalone runner that chains `enrich_pending` → `embed_pending` for detached batch runs (used for the full-corpus backfill).

### Verified
- Full-corpus run on 988 items: **815 ok / 173 skipped / 0 failed** after fixes + retry pass. All 815 ok rows have 768-dim embeddings. Wall clock: ~1h55m (enrich 1h25m, embed 30m).

### Fixed
- `app/services/ollama.py`: added `'review'` to `_ALLOWED_CATEGORIES` and the SYSTEM_PROMPT — legitimate game/hardware review threads were being rejected. Added `@field_validator('games', 'companies', 'people', mode='before')` on `Entities` to normalize dict-shaped model output (`{name: {}}`) into the expected `list[str]`. Together these recovered all 13 batch failures.

### Deferred
- Phase 2.5 (article body-fetch via `scrapers_lib.tier1.article` for the 173 skipped items). Originally a "maybe" — promoted to **must-do before Phase 3** after observing skip composition included news-site RSS teasers, not just Reddit link-posts.

### Added — Phase 1 manual ingest end-to-end (2026-05-07)
- `app/services/scrapers.py` — thin wrappers around `scrapers_lib.tier1.rss` plus a YouTube `@handle` → channel-feed URL resolver (cached per-process).
- `app/services/ingest.py` — full ingest pipeline: dedup on `(source_id, mention_id)`, normalize RawMention → `items`, persist raw JSON to `raw_items`, fingerprint each item via `md5(normalized_title)`, update `sources.last_fetched_at` / `error_count` / `last_error`, log every run to `run_log`.
- `POST /sources/{id}/ingest` — synchronous per-source button.
- `POST /sources/ingest-all` — runs all enabled sources sequentially in a `BackgroundTasks` job.
- Dashboard now lists the latest 50 normalized items with source name, published date, title-link.
- Sources table now shows `last_fetched`, `error_count`, `last_error`, plus per-row Ingest button and an "Ingest all" button.

### Verified
- All 24 RSS feeds + 6 YouTube channels ingest cleanly under real network conditions on 2026-05-07. ~973 items in the first full run.
- Idempotency: re-running ingest on IGN twice keeps the items count at 20 (dedup confirmed).

### Fixed
- `sources.yaml`: corrected Gameranx YouTube handle from `@gameranx` (404) to `@GameranxTV`.

### Deferred
- YouTube transcript fetching via `tier1.youtube` — moves to Phase 2 enrichment. Phase 1 captures only video metadata (title, URL, channel, published).

### Added — Phase 0 skeleton (2026-05-07)
- `pyproject.toml` with FastAPI / SQLModel / APScheduler / HTMX-via-CDN / scrapers-lib (path dep) stack.
- `app/` package layout: `main.py`, `config.py`, `db/{models,session,init}.py`, `routers/{dashboard,sources}.py`, `utils/yaml_loader.py`, `templates/`, `static/`.
- All 7 SQLite tables defined as SQLModel: `sources`, `raw_items`, `items`, `enrichments`, `clusters`, `weekly_reports`, `run_log`.
- DB init via `SQLModel.metadata.create_all` + WAL + foreign-keys pragmas on connect.
- Idempotent seeder: loads `sources.yaml` into the `sources` table on startup.
- `GET /` placeholder dashboard and `GET /sources` read-only list view.
- Jinja base layout with HTMX 2.0.3 from unpkg.

### Pending
- UI template port from claude.ai/design (external delivery).
