# Session log

Append-only. Newest entries on top. Each entry: date, what was done, where we left off, blocked-on / next.

---

## 2026-05-19 (Phase 3c.16 fixes, end of session) — Three bug fixes from real-world tab-clicking

User-reported issues after the 3c.15 + 3c.16 ship; all three fixed in this same session.

**(1) Cluster cards / List view toggle moved to the right.** Was rendering left-aligned below the region tabs. Restructured `clusters.html` + `_clusters_list.html` to wrap region tabs + view-toggle labels in a new `.gc-clusters-toolbar` flex row (`justify-content: space-between`). Radios stay outside `#clusters-list` (so HTMX swap doesn't reset the user's view-toggle choice); view-labels move *inside* `#clusters-list` (so HTMX swap re-renders the active-class on them).

**(2) Active highlight on region tab stuck at "Global" on `/stories` + `/clusters`.** Tabs were rendered *outside* the swap target (`#dashboard-list` / `#clusters-list`), so HTMX swaps re-rendered only the list, leaving the server-rendered active-class on the original (Global) tab. Fix: moved `_region_tabs.html` include from the parent templates (`dashboard.html`, `clusters.html`) *into* the swap target — added as the first thing inside `_dashboard_list.html` and inside the new toolbar in `_clusters_list.html`. Now HTMX responses re-render the tab strip with the correct active class.

**(3) Blank white screen on `/?region=…`** (the readout). The previous Phase 3c.16 implementation used `hx-target="body" hx-select="body"` for a full-body swap to keep the header exec-summary CTA in sync. `hx-select="body"` produced an unrendered/empty swap in practice. Replaced with a tighter scope: added `id="readout-main"` to the `<div class="gc-main">`, and changed the tab buttons to `hx-target="#readout-main" hx-select="#readout-main" hx-swap="outerHTML"`. Still re-renders both the header (exec CTA toggles correctly) and the grid body (cards filter correctly), but as a properly-scoped element swap instead of a full-body innerHTML replacement.

**CSS** — updated `app/static/app.css`:
- `#view-cluster:checked ~ .gc-view-labels label[for=…]` → `#view-…:checked ~ #clusters-list .gc-view-labels label[for=…]` (descendant traversal through `#clusters-list` since view-labels moved inside it).
- New `.gc-clusters-toolbar` rules — `display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; gap: 16px;` + zero-out the inner-element margins.

**Smoke-tested live on `:8001`.** All three issues resolved:
- `/stories?region=americas` (HX-Request) returns fragment with active-class on Americas (not Global). Same for asia.
- `/clusters?region=europe` (HX-Request) returns fragment with `gc-clusters-toolbar` + `gc-view-labels` present and active-class on Europe tab.
- `/?region=americas` returns 50517 bytes, `/?region=asia` returns 49994 bytes (vs. 61993 for Global), `#readout-main` wraps the content, 1 active tab, exec-summary note present on regional tabs. Full readout not blank.

**(4) Spinner indicator on readout region tabs** (commit `cb74157`). Server-side filter on `/?region=…` is 2–3 s (synthesis_json parse + `cluster_regions()` + `sources_meta`); tab clicks felt unresponsive even after the swap-target fix. Added a small 14px rotating border-spinner at the end of `<nav class="gc-region-tabs">` in `reports.html` with `gc-region-spinner` + `htmx-indicator` classes; each tab button declares `hx-indicator=".gc-region-spinner"`. Standard HTMX indicator CSS rules added to `app/static/app.css` (`.htmx-indicator { opacity: 0; }` + `.htmx-request .htmx-indicator { opacity: 1; }` + `.htmx-request.htmx-indicator { opacity: 1; }`) plus `@keyframes gc-spin` rotation + `.gc-region-spinner` border/animation block. Scoped to the readout only — `/stories` and `/clusters` swaps are fast (small fragment endpoints) and don't need it.

---

## 2026-05-19 (Phase 3c.16, later) — Region tabs on weekly read-out (filter-existing synthesis, no per-region Opus pass)

**What shipped.** Same 4-tab strip (Global / Americas / Europe / Asia) now appears on `/` (the weekly read-out). Cluster-keyed cards (Biggest / Risks / Drama / Market Momentum / Community / Esports / Watch) are filtered on the fly via `cluster_regions()` — same helper shipped in 3c.15. Non-cluster cards (Hottest games / Trends / Release Radar) carry a small **"Not region-tagged"** chip on regional tabs because they aggregate by game-name or entity-name, not cluster_id. Exec-summary CTA is hidden on regional tabs and replaced with an inline note ("Exec summary covers the whole-corpus week. Switch to Global to read it.") — the synthesis prose was generated globally; showing it as if it were region-specific would mislead.

**Locked design choice — Option (D), not (B).** Filter the existing `synthesis_json` by region. Did NOT run a per-region Opus synthesis. Rationale: corpus is still too thin per-region for 3× weekly Opus calls to produce 3 strong reports; would just produce 3 weaker ones. When source mix diversifies (≥30–40 items/week per regional tab), revisit. Same rationale as the locked Phase 3c.15 "Per-region synthesis deferred" decision. Honest about being a filter, not a separate read-out.

**Implementation.**
- `app/routers/reports.py` — added `_REGION_ALLOWED` constant + `_filter_cards_by_region()` helper (collects every cluster_id referenced by synthesis_json in one pass, calls `cluster_regions()` once, walks each card list in place). `_build_week_payload(region="")` signature extended. Route handler gains `?region=` param, normalizes garbage to Global, passes `region` / `region_active` / `exec_summary_hidden_for_region` to template.
- `app/templates/reports.html` — inlined the region-tabs `<nav>` strip (NOT the shared `_region_tabs.html` partial — the readout has different hx-include needs + needs `hx-select="body"` to extract the rendered body from a full-page response, since `/` has no fragment branch); wrapped grid in `#readout-body`; added "Not region-tagged" chips to Hottest / Trends / Release Radar card headers; replaced exec-summary CTA with conditional note on regional tabs.
- `app/static/app.css` — `.gc-card-note`, `.gc-chip--muted`, `.gc-meta-tag--note` styles added for the new affordances (~15 lines).
- Watch[] entries without `cluster_id` (corpus-wide editorial) dropped on regional tabs. Community narrative (whole-corpus prose) cleared on regional tabs.

**Smoke-tested live on `:8001`.** All 5 routes return 200 (`/`, 3 regional tabs, garbage param normalizes to Global). Tab strip renders on all; active-class lands on correct tab. Exec-summary CTA hidden on regional tabs (1 file-text icon on Global, 0 on Asia). Card empty-state count increases on regional tabs (Global: 5, Americas: 6, Asia: 7, Europe: 9 — Europe is thinnest because only 15 clusters carry the europe tag). 3 "Not region-tagged" chips render on each regional tab as designed.

**HTMX behavior.** Tabs do a `hx-target="body" hx-select="body"` full-body swap because the header exec-summary CTA needs to update with region state. Heavier than the per-list swap on /stories + /clusters but `/` is a single-template render anyway — no perceptible cost. `hx-push-url="true"` for shareable URLs.

**Honest caveats.** Watch-card empty-state copy on regional tabs is the same generic "Awaiting synthesis…" string, which misleads slightly (synthesis ran, just nothing in the region). Header stats ("383 stories this week") still report whole-corpus counts on regional tabs — intentional; the data window is the whole week, the tab just filters which clusters are eligible for display.

**Spend.** $0 — no LLM calls. **Cumulative project:** ~$10.96 (unchanged from 3c.15).

---

## 2026-05-19 (Phase 3c.15) — Region tagging shipped · 4-tab filter on /stories + /clusters · 1405-item Haiku backfill ($0.30) · 89/66/59/1220 distribution

**What shipped.** Content-inferred `region_focus` per item (Haiku) → 4-tab filter (Global / Americas / Europe / Asia) on `/stories` and `/clusters`. Cluster region computed on-the-fly as union of member tags, mirroring the Phase 3c.12 section-overlay pattern (no `clusters` schema change). Strict tag matching — Global is the unfiltered default, regional tabs use `LIKE '%region%'`; `?region=garbage` normalizes to Global. Empty-state copy on sparse regional tabs: "No region-tagged items yet — coverage depends on your source mix."

**Data layer.**
- SQLite `enrichments.region_focus TEXT NULL` via `_migrate_enrichments_columns` in `app/db/init.py`. Column accepts comma-separated subset of `{americas, europe, asia}` or NULL. NULL = no regional anchor (item appears under Global only).
- `EnrichmentData` Pydantic schema (`app/services/ollama.py`) gained `region_focus: list[str]` + `_filter_region_focus` validator (lowercase, dedup, taxonomy-locked). `SYSTEM_PROMPT` extended with strict-tagging rule + 7 worked examples (anchor → tag mapping: "Capcom delays game in Japan only" → `["asia"]`; "GTA 6 trailer drops Nov 5" → `[]`; "Tencent acquires Norwegian studio Funcom" → `["asia","europe"]`). Added to `_enrichment_json_schema` required list so Haiku can't silently omit. Zero marginal cost on the going-forward enrich path — rides on the existing per-item call.
- `_persist_ok` in `app/services/enrich.py` now serializes `data.region_focus` as `",".join(...)` or NULL.

**Backfill** — new `scripts/backfill_region.py` + `tag_region(tldr)` + `RegionTagData` in `app/services/anthropic.py`. Lightweight prompt (uses existing `tldr` text, not full body) — much cheaper than a full re-enrich.
- Ran on `enrichments WHERE region_focus IS NULL AND status='ok'`. Idempotent (skip-on-non-NULL).
- **Result:** 1405 attempted / 1405 ok / 0 failed / 29:43 wall-clock / ~$0.30 actual spend.
- **Final distribution across 1412 ok enrichments:** 89 Americas (6.3%) / 66 Europe (4.7%) / 59 Asia (4.2%) / 1220 untagged (86.4%). **18 multi-region items** (4 carry all 3 tags — e.g., Switch 2 cross-region pricing, IGN consumer research report; 14 carry 2-region — e.g., Tencent-Funcom cross-border deal).
- Hand-picked candidate quality check (10 items): 9/10 correct (FTC/Activision → Americas; CA Stop Killing Games bill → Americas; Mozilla/UK gov → Europe; NetEase studio shutdown → Asia; Steins;Gate JP release → Asia; HK animated film → Asia; Trump+Huang+China → Americas+Asia; CA AB 1921 → Americas; activision CoD platform-skip → untagged; MS Game Pass speculation → untagged). One borderline: Korean toilet-paper Pokemon product (model picked untagged; arguably Asia).

**UI layer.**
- `/stories` (`app/routers/dashboard.py`): new `?region=` query param, JOIN to `Enrichment` with `ilike('%region%')`. Unknown values normalize to Global. `_REGION_ALLOWED = {"americas","europe","asia"}` constant gates the predicate.
- `/clusters` (`app/routers/clusters.py`): same param shape; uses new helper.
- New `cluster_regions(session, cluster_ids) -> dict[int, set[str]]` in `app/services/sections.py`. Walks each cluster's `member_item_ids` JSON, joins to `enrichments.region_focus`, returns union per cluster. Bulk-fetched in two queries (one for clusters, one for items) — O(n) on member count, not O(n²).
- New `_region_tabs.html` partial. Parent templates set `route_name` + `target_id` Jinja vars before include. HTMX `hx-get` + `hx-target` + `hx-include="[name='q'],[name='section'],[name='week_id']"` to chain with the existing filter dropdowns. `hx-push-url="true"` for shareable URLs.
- `dashboard.html` + `clusters.html` updated to include the partial above their respective swap-target divs.
- `_dashboard_list.html` + `_clusters_list.html` empty-state branches: `{% elif region %}` shows the source-mix copy.
- `app/static/app.css` — ~20-line `.gc-region-tabs` + `.gc-region-tab` block. Visually inherits `.gc-view-labels` pill-row look; accent on active.

**Smoke-test (live on `:8001`).**
- All 4 tabs return 200 on both `/stories` and `/clusters`. Both bare paths and `/gaming-chatter`-prefixed paths work.
- HTMX fragment swap returns correct partial (verified `HX-Request: true` header path).
- Active-class set on correct tab per server-rendered partial.
- Invalid `?region=garbage` → falls back to Global.
- Stories counts (default last-7-day window): 383 Global / 18 Americas / 6 Europe / 14 Asia.
- Cluster counts (across all weeks): 247 Global / 33 Americas / 15 Europe / 10 Asia.
- Empty-state copy renders for sparse regional tab combinations (e.g. `?week_id=2025-W01&region=asia`).

**Pre-flight doc updates** — all 5 main docs updated BEFORE implementation (delegated read+draft to a subagent to save context; reviewed and applied edits manually):
- PRD.md — new goal #7 (regional filtering); new non-goal (per-region synthesis deferred).
- ARCHITECTURE.md — `region_focus` added to enrichments-row, LLM-pipeline row, and a new Trend-detection bullet.
- DECISIONS.md — full 2026-05-19 (Phase 3c.15) dated entry with 10 locked decisions: content-inferred (not source-attributed) / strict tag match / no `global` tag value / Global tab is unfiltered (not "untagged" bucket) / cluster region computed on-the-fly / backfill via Haiku one-shot on existing tldr / cluster simple-union accepted for v1 / per-region synthesis deferred / honest scope note re: thin Asia tab.
- TASKS.md — Phase 3c.15 block inserted between 3c.14 and Phase 4. All 10 checkboxes flipped on ship.
- OPEN_QUESTIONS.md — 4 new entries under 2026-05-19: source-level region deferred, regional synthesis deferred, cluster-region union noise watch-item, Asia-tab thin-by-design (action: weight new sources Asian when CRUD lands).

**Carry-over staleness flagged but NOT auto-fixed during pre-flight** (per scope rules), THEN swept in close-out:
- ARCHITECTURE UI route table was pre-3c.7 stale (said `/` = Dashboard). Replaced with current 11-route table including `/stories`, `/clusters`, `/about`, `/pipeline/run-full`, `/static/{path}`, plus marking `/runs` as deferred-to-Phase-4.
- ARCHITECTURE `enrichments` row was missing `genres`/`platforms`/`event` from Phase 3c.0 (added 2026-05-12). Backfilled inline alongside `region_focus`.

**Spend this session.** ~$0.30 (Haiku backfill: 1405 × ~$0.0002 with prompt caching). **Cumulative project:** ~$10.96.

**Where we left off.** Phase 3c.15 fully shipped + smoke-tested + docs current + committed. No blockers.

**Open / next session — TBD.** Phase 4 (Automation) deferred at user request — revisit when daily/manual cadence becomes painful. Three carry-over candidates on the table from this session's planning conversation:
1. **pcgamer.com release-date integration** — one-shot Haiku parse on the static list page (`https://www.pcgamer.com/games/new-pc-games-2026/`) → upsert `games.release_date`. Replaces the abandoned IGN release-date-page scrape with a simpler LLM-on-static-URL approach.
2. **Date-range picker** replacing the ISO-week dropdown on `/stories` + `/clusters`. Open Q on cluster semantics (filter cluster members within range vs. show all members of clusters whose week overlaps range) + library choice (native `<input type="date">` × 2 vs. vendored flatpickr — new dep, needs user OK per CLAUDE.md global rule).
3. **Add IGN.cn as a regional source** — the only GREEN of 8 candidates probed 2026-05-18. Five REDs dropped (3dmgame, gamersky, vgn.cn TLS-expired, a9vg RSS-disabled, xiaoheihe SPA — see SESSION_LOG entry, this one's earlier text). Two YELLOWs (sector.sk, gamestar.de) need one more RSS-path probe. New source would auto-populate `region_focus="asia"` via the going-forward enrich path.

Plus Phase 5 (Polish) is pending — trend mini-charts, watch-list synthesis, sentiment view, source-failure UI banner, eval harness.

---

## 2026-05-15 (Phase 3c.14) — YouTube audio-transcribe path wired up · 35-item backfill · W20 force-resynth · cluster effect = ~0, per-item enrichment quality ↑

**What was done:**

1. **scrapers-lib v1.7.0 installed with `[youtube-audio]` extra** (yt-dlp 2026.3.17 + faster-whisper 1.2.1 + PyAV 17.0.1 + ctranslate2 4.7.1 + onnxruntime 1.26.0). One imperative `pip install -e "..\scrapers-lib[youtube-audio]"` against system Python 3.12.9 — project has no `.venv` and no `uv` on this machine, so `[tool.uv.sources]` in pyproject.toml is inert here. PyAV bundles its own audio decoding libs; **no system ffmpeg needed**.

2. **3-line app change:**
   - `pyproject.toml`: `"scrapers-lib"` → `"scrapers-lib>=1.7.0"` (extra deliberately NOT in pyproject — see DECISIONS).
   - `app/services/ollama.py:185`: `_yt(url_or_id)` → `_yt(url_or_id, audio_fallback=True)`. Wrapper still returns `str` (joined `raw_text` from chunks); `enrich.py:_body_for_enrichment` behavior preserved end-to-end.

3. **Spike-test on 3 yesterday-IpBlocked video IDs** via one-off `scripts/_spike_yt_audio.py`: first call 88.9 s (40 s model download/load + 49 s `small.en` on a 59.5 s horror-trailer clip; transcript = vocal-sting noise but Haiku-tagable). Other two videos hit working captions today, ~1.3 s each.

4. **35-item backfill** of yesterday's YT enrichment set via `scripts/rerun_enrichment.py --ids "..."`. Totals `ok=34 / skipped=1` (1567 — `1-yCgaoQ3BI` audio path empty too; existing `ok` preserved). 6 audio-fallback firings out of 35; 28 used captions. ~71 min wall-clock dominated by the cold-start first audio rescue. **Hit a Windows cp1252 crash on the post-run diff print** — `👀` emoji in a video title couldn't encode to console. DB writes are commit-per-item, all changes durable; crash purely cosmetic. Logged in OPEN_QUESTIONS as a small follow-up.

5. **Post-processing driver** (`scripts/_backfill_yt_audio_postprocess.py`, one-off): null embeddings on backfill set → `embed_pending()` re-embedded 35 via Ollama `nomic-embed-text` → `cluster_window_incremental('2026-W20')` → `synthesize_week('2026-W20', force=True)`. 3.5 min total. Result: `items_appended_existing=0 / clusters_new_created=0 / items_orphaned=330` — confirms the YT-vs-news vocab-gap framing from yesterday's OPEN_QUESTIONS; audio transcripts improve per-item enrichment but don't shift cluster membership at the current 0.85 cosine threshold. W20 synth regenerated fresh (Opus 4.7 + critic, 6246 chars JSON).

**Where we left off:**

- Phase 3c.14 fully shipped. Audio fallback engaged on every YT enrichment from this point forward.
- 2 one-off scripts (`_spike_yt_audio.py`, `_backfill_yt_audio_postprocess.py`) deleted at session close per their docstrings; behavior captured in this entry + DECISIONS.
- OPEN_QUESTIONS transcript-deferred entry resolved. 2 flag-only entries remain (audio-fallback length cap for future long-form sources, transcript quality floor for future hardening). A 3rd entry — rerun_enrichment.py cp1252 emoji-print crash — was flagged AND fixed same-session via `if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at `scripts/rerun_enrichment.py:21-22`.
- 35 backfilled items currently all sit in the 8-category locked taxonomy — 0 `'guide'/'preview'/'interview'` slippage on the set. Direction is correct; honest caveat that we can't fully separate audio-path effect from today's stabler caption endpoint (overwrote yesterday's enrichments in place).

**Spend this session:** ~$0.38 LLM (~$0.03 Haiku × 35 re-enrich + ~$0.35 Opus synth + critic). $0 audio path (local CPU). Cumulative project: ~$10.66.

**Next session — Phase 4 (Automation):** APScheduler daily ingest + Monday-morning synthesis cron + catch-up-on-startup + `/runs` UI + Source CRUD via web forms. See TASKS.md Phase 4.

---

## 2026-05-15 (Phase 3c.13 + one-off YouTube ingest) — YouTube RSS recovered · ad-hoc YT-only ingest + W20 force re-synth · Tailscale Funnel deploy revealed root_path coupling · 15-file URL refactor → request.url_for(...) · static Mount→Route fix · base.html killed · nav fail-fast validator · DECISIONS 2026-05-15

**Two threads this session:**

1. **YouTube triage + ad-hoc ingest** (morning): User asked to recheck the May 14 YouTube outage. Live curl against all 6 channel feeds returned 200 OK with fresh XML (~17–42 KB each) — the outage was transient and self-healed; not a deprecation. The URL pattern `feeds/videos.xml?channel_id=UC…` is unchanged. Ran a scoped YouTube-only ingest (`ingest_source` × 6 enabled YT sources) → 90 fetched / 41 new / 49 dedup-skipped / **0 errors**; `error_count` and `last_error` cleared on every source. Chained the rest: `python scripts/run_enrich_batch.py` (4 min — 41 attempted / 35 ok / 4 failed on Haiku taxonomy slippage `'guide' / 'preview' / 'interview'` / 2 skipped; 35/35 embedded), inline `cluster_window_incremental(W19, W20)` (4 items appended to existing clusters across both weeks, 0 new clusters, 0 Sonnet labels), then `python scripts/run_synthesis.py 2026-W20 --force` (62 s, 6090 chars JSON, Opus + critic). Cost: **~$0.38** (~$0.02 enrich + ~$0.36 synth). Cumulative: **~$10.28**.

   Per-video YT transcript-API path remained bot-gated through this run: ~19 of 35 attempted transcripts raised `BlockedError("bot-gate on <id> (IpBlocked)")`; `enrich.py` correctly fell back to title/body. That's likely what feeds the 10% taxonomy-failure rate on YT items (short titles → Haiku picks a category outside the 12-category lock). Wrote a scrapers-lib handoff brief for the deferred audio-transcribe path; user took that to scrapers-lib, returned later with confirmation that the fix is implemented there.

2. **Tailscale Funnel deploy → root_path refactor** (afternoon): User exposed `:8001` at `https://laptop-aknevrti.taile7462c.ts.net/gaming-chatter`. First load was completely unstyled (serif text, blue underlined links, no grid). Diagnosis from the rendered HTML: templates emit hardcoded root-absolute URLs (`/static/app.css`, `/clusters`, `hx-get="/clusters"`, …) but the browser resolves those against the public root, not the prefix subtree. Tailscale Funnel only forwards `/gaming-chatter/*` paths and strips that prefix before reaching the app. Two options: (1) drop `--set-path` in Tailscale, serve at device root; (2) make the app prefix-aware via FastAPI's `root_path` + Starlette's `request.url_for(...)`. User chose (2) for deployment portability (future cloud / custom domain / multi-app hosting should "just work").

**Phase 3c.13 — root_path + url_for refactor (15 files modified + 1 deleted):**

- **`app/main.py`** — `FastAPI(root_path=os.getenv("GC_ROOT_PATH", ""))`. Default empty = local dev at `localhost:8001/`. `.env` adds `GC_ROOT_PATH=/gaming-chatter` for Tailscale Funnel. Same `.env` loading via `app.config:load_dotenv` already imports before `os.getenv` runs (line 8 imports `app.config` which triggers dotenv → line 21 reads the populated env). No code-flow regression for the no-env case.
- **`app/services/chrome.py`** — `NAV_ITEMS_BASE` refactored from static `href` strings to **route names** (`reports_view` / `dashboard` / `clusters_view` / `list_sources` / `about`). `nav_items_for(request, active_id)` resolves via `request.url_for(...)` at request time. 5 call sites updated to pass `request`.
- **6 router files** (`about`, `clusters`, `dashboard`, `enrich`, `reports`, `sources`) — gained `request: Request` param in 7 routes; 5 internal `RedirectResponse(url="/...")` calls now use `request.url_for(...)` so redirect chains also respect the prefix.
- **7 template files** (`reports`, `shell_base`, `_sidebar`, `_exec_summary`, `clusters`, `dashboard`, `sources`) — every hardcoded `/static/...`, `/clusters`, `/stories`, `/sources`, `/about`, `/pipeline/run-full`, `hx-get="/..."`, `hx-post="/..."` replaced with `{{ request.url_for(...) }}`. Query strings preserved as Jinja suffix pattern (`{{ url_for('x') }}?week_id={{ key }}`) — Starlette's `url_for` doesn't take query params; the suffix approach is the documented workaround.
- **Static files: `app.mount("/static", StaticFiles(...))` → `@app.get("/static/{path:path}", name="static")` route** that uses `FileResponse` + a hand-rolled path-traversal guard. Reason: Starlette's Mount + `root_path` interaction silently breaks for proxy-stripped requests. Traced via debug ASGI middleware + monkey-patched `Mount.matches()` → confirmed `child_scope["root_path"] = outer_root_path + mount_path = "/gaming-chatter/static"`. Then `StaticFiles.get_path()` tries to strip that from request path, but bare `/static/app.css` (Tailscale-stripped) doesn't start with `/gaming-chatter/static`, so the strip is a no-op and StaticFiles resolves `STATIC_DIR/static/app.css` (404, wrong directory) instead of `STATIC_DIR/app.css`. A FastAPI route doesn't have this interaction — Route matching is `root_path`-aware in the standard way, and `name="static"` keeps `request.url_for('static', path=…)` working from templates unchanged. Cost: marginally slower than StaticFiles' optimized Mount + hand-rolled traversal guard, but invisible for a single-user local app.
- **`app/templates/base.html` deleted** — legacy pre-3c.7 nav shell, not extended by any live template (only `shell_base.html` is extended now). Still had hardcoded paths; would have re-introduced the prefix bug if anyone resurrected it.
- **Nav fail-fast validator** added to the lifespan hook: `app.url_path_for(name)` resolves every `NAV_ITEMS_BASE.route`; missing names raise `RuntimeError` at boot rather than 500-ing at first nav render. Verified the failure path by injecting a bogus route name into `NAV_ITEMS_BASE` — `RuntimeError: Nav routes not registered: ['this_route_does_not_exist']`.

**Process notes:**

- The refactor was delegated to a general-purpose subagent with an explicit phased brief (discovery → main.py edit → template edits → smoke test → report). It expanded scope cleanly into `chrome.py` (required for correctness — nav was the most coupled URL source) and the 5 internal `RedirectResponse` paths (also required). Verified by independent `git diff --stat` + my own smoke test before declaring done.
- The static 404 took a second diagnostic pass after the initial refactor — when I first tested with `GC_ROOT_PATH` set, the bare `/static/app.css` still 404'd. Routes returned 200 either way (bare or prefixed) but static only worked with prefix. Traced the asymmetry to `Mount.matches()` setting `child_scope.root_path = outer + matched` — the load-bearing line behind the bug.
- Honest forward-blocker evaluation at the end: 12 candidate concerns identified, filtered to 3 worth fixing now (Mount-trap signpost via DECISIONS + comment, `base.html` delete, nav validator). The other 9 are quick-fix-when-they-bite at the same cost as fix-now, so deferred. Real residual concerns: (a) the Mount-trap is signposted but not eliminated — future `app.mount(...)` calls re-trigger it; (b) URL generation outside request context (cron / email) needs a `gc_url()` helper when push delivery lands; (c) nav validator catches `NAV_ITEMS_BASE` route-rename breakage but not template-level `url_for('foo')` typos for non-nav routes. All bounded, none silent-data-loss.

**Verified end-to-end on the user's `:8001 --reload`:**

- Local (no env var): all 5 routes 200; generated URLs bare.
- With `GC_ROOT_PATH=/gaming-chatter`: all routes 200 at both bare and prefixed paths; generated URLs carry the prefix; path-traversal probe blocked.
- Public URL via Tailscale Funnel `https://laptop-aknevrti.taile7462c.ts.net/gaming-chatter`: CSS + favicon + nav + HTMX search-as-you-type all working.
- Nav validator: clean boot with 5 NAV_ITEMS_BASE entries; raises on injected missing route name.

**Spend this session:** ~$0.38 LLM (one-off YT ingest + W20 force re-synth). Cumulative project: ~$10.28.

**Where we left off:**

- Tailscale Funnel deploy live and fully styled. Local dev still works at `localhost:8001/` with the env var unset.
- 17 files modified + 1 deleted, **committed** as Phase 3c.13.
- YouTube RSS healed; per-source error counters cleared.
- W20 force-resynth fresh (Opus 4.7, 6090 chars JSON, regenerated 2026-05-14 14:23 UTC).

**Next session (locked priority — YouTube audio-transcribe integration):**

scrapers-lib has shipped the new yt-dlp + faster-whisper audio path (per user, end of this session). gaming-chatter integration tasks:

1. Bump `scrapers-lib` version in `pyproject.toml` (check scrapers-lib CHANGELOG for the new version + the exact API — sibling fn `fetch_youtube_audio_transcript` vs. mode arg on the existing `fetch_youtube_transcript`).
2. Swap the transcript call in `app/services/ollama.py` (legacy filename kept post-Haiku migration) from the bot-gated transcript-API path to the new audio path. Prefer `audio_fallback` mode if exposed — try caption-API first, fall back to audio on `BlockedError`. Fall back to title/body only when both paths fail.
3. Sanity check: `python -c` test against 2-3 of yesterday's IpBlocked video IDs to confirm audio path works on a fresh IP. Then run `python scripts/run_enrich_batch.py` to re-enrich the title-only items from this session (they'll now have full transcripts).
4. Run full pipeline (button or manual chain) + force re-synth W20. Compare cluster outcomes vs. today's title-only baseline (do any YT items now cluster with news? does taxonomy slippage drop below 10%?).
5. Document outcome in DECISIONS.md 2026-05-XX: model used (`small.en` recommended for the speed/quality balance per the handoff brief), per-week pipeline runtime hit, taxonomy-slippage delta.
6. Close out the OPEN_QUESTIONS.md transcript-deferred entry.

Expected: ~$1-2 LLM + ~90-180 min wall-clock for the whisper pass depending on model. After that: Phase 4 (APScheduler + `/runs` UI + Source CRUD via web forms).

**Files touched / new this session:**

- New: (none)
- Edited: `app/main.py`, `app/services/chrome.py`, `app/routers/{about,clusters,dashboard,enrich,reports,sources}.py`, `app/templates/{_exec_summary,_sidebar,clusters,dashboard,reports,shell_base,sources}.html`, `docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md`, `docs/SESSION_LOG.md`, `docs/TASKS.md`, `CLAUDE.md`, `.env` (added `GC_ROOT_PATH`).
- Deleted: `app/templates/base.html`.
- DB: 41 new YouTube items (W19/W20 windows), 35 enriched + embedded, 4 cluster appends (W19:1 + W20:3), W20 force-re-synthesized.

---

## 2026-05-14 (Phase 3c.9 → 3c.12) — Corpus sidebar drop · Dashboard→Stories · /stories URL · header pull/workflow tags · Run-pipeline button · cluster toggle view · section overlay · multi-chip per cluster · dropdowns on /clusters + /stories · See-all card footers · 63 legacy clusters dropped · first end-to-end pipeline run (~$1.29) · W19 re-synth · incremental clustering · skip-synth · favicon · YouTube RSS broken (deferred)

This session compounded across four loose phases. Grouped here for readability — every change is on disk; the cumulative ChangeSet covers ~12 files + 1 new module + 2 new templates + ~280 lines of CSS.

**Phase 3c.9 — Corpus-stats sidebar removed; Dashboard renamed to Stories; clusters default flipped to per-week:**
- `_sidebar.html` + `reports.html` lost their `.gc-sb-bottom` corpus-stats block. `corpus_stats(session)` call removed from all 5 routers that were passing it in context (reports / about / sources / clusters / dashboard); the helper stays in `services/reports.py` for future use.
- Nav label "Dashboard" → "Stories" in `chrome.py` (`id` flipped from `dashboard` → `stories`, icon `gauge` → `list`). The `Dashboard` H1 was killed from the template; eyebrow now reads "Last 7 days" (or "Week 2026-W17" when filtered).
- Stories filter: dropped the `_ITEM_LIMIT = 50` cap. Items now scoped by `published_at >= now - 7 days` (267 items on the active corpus, was visually misleading 50 of 988 before). Header reads `267 items` instead of the misleading `988 items` from the old all-items count.
- `/clusters` default URL now serves the per-week partitions (W17 + W18 + W19 = 55 clusters) instead of the 63 legacy `week_id='all'` rows. Explicit `?week_id=all` still works for opting in to the legacy bucket. Then the legacy bucket was **deleted** (see below).
- **Dropped the 63 legacy `week_id='all'` cluster rows** at user request. Backup written to `data/legacy_clusters_backup_20260514_023447.json` (full row payload, in case anything ever needs to be inspected). Remaining clusters total: 55 per-week (later 247 after pipeline run added W19+W20).

**Phase 3c.10 — URL rename · header tags + Run-pipeline button · cluster toggle · favicon:**
- `/dashboard` → `/stories` URL rename. `chrome.py` href, `dashboard.py` route path, `dashboard.html` `hx-get` URL all updated. File path stayed `app/routers/dashboard.py` to keep blast-radius small (the file name is internal; rename can come later if naming-vs-file mismatch bugs anyone).
- `reports.html` header: dropped the "refreshed X ago" suffix from `gc-header-meta`. Two new tag-chips in `gc-header-actions`:
  - **Last pull** — `MAX(completed_at)` from `run_log WHERE job_type='ingest' AND status='ok'`, formatted as `N min/h/d ago` via new `_format_ago` helper.
  - **Last workflow** — `MAX(synthesis_generated_at)` from `weekly_reports`; "workflow completion" = last synthesis since that's the user-visible weekly deliverable.
- **Run pipeline** button next to Exec summary. `gc-cta--ghost` style (secondary, outline + muted bg). Enabled iff `now - last_pull > 6 days` (or last_pull is null). When disabled, `disabled` attribute + hover tooltip explaining the 6-day gate. When enabled: HTMX `POST /pipeline/run-full` with a confirm dialog ("~5 min, ~$0.50 cost"), `hx-swap=outerHTML` to replace the button with a "Running… refresh in ~5 min" status chip.
- New `app/routers/pipeline.py` (~80 lines): module-level `threading.Lock` prevents double-click; `BackgroundTasks` runs the worker after the response. 5-step pipeline: ingest_all → enrich_pending → embed_pending → cluster(prev+curr) → synthesize_week(curr, force=True). Returns a `.gc-pipeline-status` HTML fragment.
- `/clusters` CSS-only **Cluster cards / List** view toggle. Radio-input pattern (matches the existing trend/hot tabs) — both views render in HTML, sibling `:checked` selectors show one and hide the other. List view = compact `gc-cluster-flatlist` with rank + label + meta (score + items + sources + latest date) per cluster.
- Favicon: `<link rel="icon" type="image/svg+xml" href="/static/img/alienware-head-light.svg">` added to `reports.html` + `shell_base.html`. Browsers now use the Alienware-head SVG as the tab icon; the `/favicon.ico` 404 in the dev log is gone.

**Phase 3c.11 — Section overlay on /clusters · "See all" footers · dropdowns on both inspection pages · first end-to-end pipeline run · W19 re-synth · `app/services/sections.py` extracted:**
- New module `app/services/sections.py` — moved the section-overlay helpers out of `clusters.py` so the Stories page can share them. Exposes `SECTION_OPTIONS` (9 keys: All / Biggest / Market momentum / Risks / Community sentiment / Esports / Drama / Watch / Not surfaced), `load_synthesis_section_map(session, week_ids)`, `section_label_for(section)`, and the new `items_in_section(session, week_ids, section) -> Optional[set[int]]`.
- `/clusters` cluster cards + list rows now show **section chips** — the editorial card the cluster landed in on the weekly read-out. Special chip for clusters not in any synthesis section ("Not surfaced"). Each section has a distinct color (Biggest=accent, MM=purple, Risks=danger, Community=warning, Esports=blue, Drama=danger-darker, Watch=neutral, Not surfaced=outlined-muted).
- **Section dropdown** on `/clusters` (next to search): "All sections" + 8 editorial sections + "Not surfaced". HTMX `change` trigger swaps `#clusters-list` while keeping search + week_id in sync via `hx-include`.
- **Week dropdown** on `/clusters` (next to section): "All weeks" + each per-ISO-week id from `available_weeks(session)`. Same HTMX swap pattern.
- "See all stories this week →" footer link on **7 editorial cards** on the home page (Biggest, Market momentum, Community, Risks, Drama, Esports, Watch) — Hottest/Trends/Release are per-entity not per-cluster, so they were skipped. Link → `/clusters?week_id={active_week_key}` (no section filter — landing on the full list lets the user see what got surfaced vs. left out, with chips telling them which).
- Stories page got **both dropdowns** (section + week). Same shape as /clusters. The section filter on Stories uses `items_in_section(session, available_weeks(session), section)` to compute the set of item IDs that belong to clusters in the requested section, then `Item.id IN (…)` against the items query. The week dropdown swaps the time window from "last 7 days" (default) to a specific ISO-week's `[start, end)` bounds.
- **First end-to-end pipeline run** triggered via the new button (accidentally — verification curl hit POST /pipeline/run-full instead of GET; the BG task started before I could pause). Ran to completion in 44.5 min:
  - Ingest: 898 fetched, 568 new, 330 dedup-skipped, 6 errors (all YouTube — see Open Questions)
  - Enrich: 568 attempted, 477 ok (Haiku 4.5), 4 failed, 87 skipped (body < 200 chars)
  - Embed: 477/477 ok via Ollama `nomic-embed-text` (much slower than expected — ~2.3 s/call locally instead of the ~10 ms I'd ballparked; total embed step took ~19 min instead of seconds)
  - Cluster prev (W19): re-clustered destructively → 115 groups, all relabeled via Sonnet 4.6 (~$0.23)
  - Cluster curr (W20): fresh clustering → 115 groups, all labeled (~$0.23)
  - Synth W20: Opus 4.7 synthesis + critic — 3 biggest / 5 MM / 1 risk / 0 esports / 0 drama / 4 watch (critic dropped one each from risks and watch). 6705 chars JSON. ~$0.35.
  - Pipeline cost: **~$1.29**
- **W19 invalidation fix** ($0.35 extra): the cluster_window for W19 was destructive — it deleted all 38 W19 cluster rows and rebuilt 115 new ones with new IDs. W19's existing synthesis_json (from the previous Phase 3c.8 backfill) still referenced the **old** IDs. So W19's home page was rendering titles/decks correctly but every drawer click, mention count, and source-pill lookup would have failed (dead IDs). Fix: `python scripts/run_synthesis.py 2026-W19 --force` to regenerate W19's synthesis JSON against the new cluster IDs. Took 73.6 sec, produced 7897 chars JSON (3 biggest / 5 MM / 2 risks / 0 esports / 2 drama / 5 watch).

**Phase 3c.12 — Incremental clustering · skip-synth-if-unchanged · multi-chip rendering per cluster:**
- The cluster-invalidation bug from 3c.11 motivated a real fix: new `cluster_window_incremental(start, end, week_id)` in `app/services/cluster.py` (~165 lines). Algorithm:
  - Load existing clusters' L2-normalized centroids (already normalized from prior runs).
  - Filter candidate items to those NOT in any existing cluster's `member_item_ids`.
  - For each new item: cosine to each existing centroid. If max ≥ 0.85 (`CLUSTER_THRESHOLD`) → append to that cluster (update `member_item_ids`, `member_count`, `source_count`, `latest_published_at`, weighted-mean centroid, recomputed score). **Don't re-label** — existing cluster identity preserved.
  - Items that didn't match: run connected-components among themselves (same threshold + min_size). New groups become new cluster rows, each gets one fresh Sonnet 4.6 label.
- Pipeline router (`app/routers/pipeline.py`) rewritten to call `cluster_window_incremental` for both prev + curr weeks (with explicit `iso_week_bounds(week_id)` for `start`/`end`). Synthesis now **skipped** when curr week has zero changes (`items_appended_existing == 0 AND clusters_new_created == 0`) — saves the ~$0.35 Opus cost on no-op pipeline runs.
- Verified the incremental fn by calling it directly (after pipeline already ran): it found **13 items** previously missed by the destructive connected-components pass (6 in W19 + 7 in W20 — singletons that didn't have a peer ≥ 0.85 in their own week's set, but DO have ≥ 0.85 similarity to an existing centroid; the broader "match against all existing centroids" search rescues them). Zero new Sonnet calls (no new clusters formed). Cluster IDs untouched. Cost: **$0.00**.
- Section map → **list-of-sections per cluster** (Phase 3c.10/3c.11 stored only the highest-priority section; 3c.12 keeps every section the cluster appears in). Rendered as multiple chips per cluster, sorted by priority (Biggest first, Watch last). Example: a W20 cluster that's Biggest #3 + Community heated + Watch · TBA now renders all 3 chips visibly.
- Why the change: the priority-first-wins approach was *technically* correct but **silently masked** that community sentiment was happening across many clusters that ALSO had a primary chip elsewhere. W20 community chip count went from 0 → 4 once multi-chip landed; W19 went from 1 → 3. Filter logic also flipped: `?section=community` now matches **any** cluster whose section list contains `community`, not just clusters whose primary section is community. Stories item filter (`items_in_section`) automatically inherits the inclusive matching since it iterates the same section_map.

**Verified end-to-end on `:8001 --reload` (clean restart, no stale-worker gotcha):**
- `/` → 200, 57k bytes (W20 default — pipeline-fresh data). Header shows `Last pull: 0 min ago` (right after pipeline) + `Last workflow: 0 min ago`, Run-pipeline button disabled (correctly, since pull was just now).
- `/?week=2026-W17/18/19/20` all render correctly with W19 having repaired cluster refs.
- `/stories` → 877k bytes, 827 items in the last 7 days. Dropdowns work: `?section=biggest` → 20 items / `?section=not_surfaced` → 143 items / `?week_id=2026-W17` → 90 items / combinations work.
- `/clusters` → 247 cluster cards (W17:4 + W18:13 + W19:115 + W20:115). Multi-chip rendering verified: 5 clusters in W20 carry 2-3 chips each. Section filter inclusive; week filter works.
- `/about` → 200, infographic intact.
- Favicon present in `<head>` of both reports.html + shell_base.html.

**Session cost:** ~**$2.34** Anthropic spend (W17/W18 backfill in 3c.8: $0.70 · pipeline ingest+enrich+labels+W20 synth: $1.29 · W19 re-synth: $0.35 · misc Haiku in modal degrade: ~$0.001). Cumulative project: ~**$9.90**.

**Where we left off:**
- All Phase 3c.9-3c.12 work shipped and verified on the user's `:8001 --reload`. Corpus is fresh (988 → ~1465 items, 4 weeks synthesized: W17 / W18 / W19 / W20). No mid-flight work.
- YouTube ingest is broken **on YouTube's side**, not ours — see Open Questions. User opted to wait rather than disable or migrate to API.

**Blocked / flagged:**
- YouTube public RSS endpoint returning 404/500 broadly (verified across our 6 channels + 3 unrelated control channels: Computerphile, Veritasium, Vsauce). Worked May 7 16:20 (last successful pull, 5×15 items); broken by May 14. Diagnosis: probably a YouTube infrastructure change or deprecation. User chose to wait and revisit next week. See `docs/OPEN_QUESTIONS.md`.

**Next session (Phase 4 still the actual finish line):**
APScheduler daily ingest + Monday-morning synthesis cron, catch-up on startup, `/runs` UI for `run_log`, Source CRUD via web forms. Plus the deferred YouTube fix (retry RSS or migrate to YouTube Data API v3 with a free-tier API key). The incremental clustering work in 3c.12 was the right groundwork — APScheduler-driven daily pulls will hit incremental_cluster cheaply, and skip-synth will avoid burning Opus on no-op days.

**Files touched / new:**
- New: `app/services/sections.py`, `app/routers/pipeline.py`, `data/legacy_clusters_backup_20260514_023447.json`.
- Edited: `app/services/chrome.py`, `app/services/cluster.py` (added incremental fn), `app/services/reports.py` (added `_format_ago`, `_parse_dt`, `_latest_ingest_dt`, `_latest_workflow_dt`), `app/routers/reports.py`, `app/routers/clusters.py`, `app/routers/dashboard.py`, `app/routers/sources.py`, `app/routers/about.py`, `app/main.py`, `app/templates/reports.html`, `app/templates/_sidebar.html`, `app/templates/dashboard.html`, `app/templates/clusters.html`, `app/templates/_clusters_list.html`, `app/templates/shell_base.html`, `app/static/app.css` (~280 new lines across phases).
- DB: 63 legacy `week_id='all'` cluster rows deleted; `weekly_reports.synthesis_json` for W20 newly created (6705 chars), for W19 rewritten with new cluster IDs (7897 chars).

---

## 2026-05-13 (Phase 3c.8) — Card reorder, mention badges, scrollable releases, About page, W17/W18 synthesis backfill

**Done:**
- **Card reorder on `/`** — bottom-right group resequenced from `risks → esports → release → drama → watch` to `risks → controversy tracker → esports → release radar → watch next week`. Single template-block swap in `app/templates/reports.html` (no router or schema change — `_apply_synthesis` writes to flat dict keys; template iteration order is the only ordering constraint). Verified on W17/W18/W19: card-header substring indexes ascend in target order.
- **Mention count badge on Biggest top-3.** `_apply_synthesis` now derives `mention_count` per biggest row from `clusters.member_item_ids` (inline `SELECT id, member_item_ids FROM clusters WHERE id IN (…)` with int-coerced IDs, JSON-parsed length). No synthesis schema change — count is rendered alongside the existing source pills inside the `gc-biggest-sources` flex row. New CSS class `gc-mention-badge` (small rounded chip, fg3 on surface-alt, 10px font). The `gc-biggest-sources` rule went from a plain block to a flex row so source pills + count badge coexist on one line.
- **Release radar scrollable.** Per "show 6 at a time, scrollable within card." Added `gc-row-list--scrollable` class (`max-height: 320px; overflow-y: auto`) to the release radar's `.gc-row-list`. The release query still returns up to 10 per `upcoming_releases(..., limit=10)`; the height cap shows ~6 rows visible and scrolls for the rest. No slice in the template — height-constrained container does the work.
- **About page (new `/about` route).** Per user direction "very simple, infographic, not scroll-death." New `app/routers/about.py`, new `app/templates/about.html` extending `shell_base.html`. Layout: 5-step horizontal pipeline (Ingest → Enrich → Cluster → Synthesize → Render) with a colored top-border per stage (blue/purple/green/accent/gray), 44×44 circular icon (Lucide: `download-cloud`, `sparkles`, `shapes`, `scroll-text`, `layout-dashboard`), step number, plain-language description (one sentence, beginner-friendly), and a dashed-border tech detail line. CSS `::after` chevron between cards (a rotated border square in `var(--gc-fg3)`). Below the pipeline: two side-by-side panels — "If you're new to the jargon" (6-term glossary in 2-col grid: RSS / LLM / Embedding / Clustering / Sentiment / Critic pass — each defined in non-technical language) and "Stack & numbers" (Python/FastAPI, SQLite, HTMX, Ollama, Anthropic, $0.35/week, single-process). Media query at 1080px stacks the pipeline 2-col + hides the chevrons; at 640px stacks everything single-column. The whole page fits on one screen at ≥1080px — no scroll-death.
- **`chrome.py` nav extended.** Added 5th nav item `{"id": "about", "label": "About", "icon": "info", "href": "/about"}` to `NAV_ITEMS_BASE`. The `_sidebar.html` partial picks it up automatically since it iterates `nav_items`. `reports.html`'s hardcoded sidebar uses the same `nav_items` context, so it also gets the About item without further changes.
- **Sidebar corpus-stats truncation fix.** Per user: bottom block was getting hidden on shorter viewports. Tightened sidebar padding (`16px 8px` → `12px 8px 8px`) and `.gc-sb-bottom` padding-top (12 → 8) and `.gc-sb-corpus` padding (`10px 12px` → `8px 12px 4px`) — net ~20px vertical savings. Added `overflow-y: auto` to `.gc-sidebar` and `flex-shrink: 0` to `.gc-sb-bottom` as belt-and-suspenders: if the viewport is genuinely too short, the sidebar scrolls internally rather than clipping the corpus stats, and the corpus block never shrinks below its natural height. Adding the 5th nav item (About) costs ~33px of vertical real estate, so the savings more than offset the new entry.
- **`main.py`** — registered the new `about.router`.
- **W17 + W18 synthesis backfill.** `python scripts/run_synthesis.py 2026-W17` (39.9s, 4592 chars JSON, 3 biggest / 2 MM / 2 risks / 0 esports / 0 drama / 5 watch / 813-char exec). `python scripts/run_synthesis.py 2026-W18` (53.0s, 6210 chars JSON, 3 biggest / 5 MM / 3 risks / 0 esports / 1 drama / 5 watch / 772-char exec). Both Opus 4.7 + critic. W17's `weekly_reports` row was auto-created on first call; W18's pre-existing empty row was populated. Historical raw-item backfill ruled out — `scrapers-lib` tier1 has no date-range parameters and RSS feeds only return recent items, so W17's 4 clusters and W18's 13 clusters are the corpus we have. Anthropic spend this session: ~$0.70 (lower than CLAUDE.md's $1.80 budget — that figure included cluster-relabel, which had already run in Phase 3c.4). Cumulative project spend ~$8.26.
- **Verified end-to-end** on uvicorn `:8001` (which picked up the reload cleanly this session — no orphan WatchFiles gotcha): W17/W18/W19 all show the new card order with ascending header indexes, 3 mention badges per Biggest card, `gc-row-list--scrollable` class on the release radar list, About in sidebar nav, `/about` page 200 / 8003 bytes with the full pipeline + 6 glossary terms + stack panel.

**Decided / verified:**
- **Mention count derived at render-time, not stored in synthesis JSON.** Reason: deriving from cluster member-count is free (one extra SELECT per page render, three rows per result), and avoiding a synthesis schema change means W17/W18/W19 all get the badge without re-running Opus. The schema stays focused on editorial fields (title/dek/cluster_id); the count is a presentation concern computed from the underlying corpus.
- **Release radar approach: height-cap + overflow, not Jinja slice.** Two interpretations of "show top 6 at a time" — (a) hard-cap at 6 via `[:6]`, or (b) constrain height so 6 are visible and scroll reveals the rest. Picked (b): if the query returns 10, the user can still reach all of them by scrolling within the card. Hard-capping would have hidden 4 future-release items entirely with no affordance.
- **Sidebar truncation fix: padding-tighten + overflow-y fallback, not structural reflow.** Rejected: restructuring the sidebar into "scrollable middle + fixed bottom" (would require a new wrapping flex container around logo+weeks+nav and a separate bottom anchor). Reason: simpler fix is enough. Net ~20px of vertical reclaim from tightened padding more than offsets the new 5th nav item, and `overflow-y: auto` covers the long tail of very-short viewports.
- **About page: visual flow + glossary, not narrative prose.** Per user "infographic and visual, not scrolling/text death." Five equal-width cards with iconography and a clear arrow chain gives the reader the whole pipeline in one glance; the glossary panel handles the jargon definitions that an outsider would need. Tech-stack detail is kept in a separate "Stack & numbers" panel so the main flow stays free of acronym-density.
- **Card reorder rationale (user spec).** Industry risks → Controversy tracker → Esports & streaming → Release radar → Watch next week. Logical pairing: risk-themed cards (industry risks + controversy) cluster together, then the forward-looking content (release radar + watch next week) cluster together with esports as the bridge. Implemented as a template-block reorder only — no Python or schema change.

**Where we left off:**
All Phase 3c.8 work shipped and verified. Page renders correctly for W17/W18/W19 with the new layout. /about renders. Mention badges show 3 per Biggest card. Sidebar bottom no longer truncated. The actual product surface is now closer to "feels finished" — automation (Phase 4) is the remaining big gap.

**Blocked / flagged:**
Nothing blocking. Phase 4 still ready to start.

**Next session (Phase 4 — same recommendation as 3c.7):**
APScheduler daily ingest + Monday-morning synthesis cron, catch-up on startup, `/runs` UI for the run_log table, Source CRUD via web forms. This is the PRD's "Monday-morning briefing" finish line — without it, every Monday's synthesis is still a manual `python scripts/run_synthesis.py …` invocation.

**Files touched:**
- `app/services/chrome.py` — added About to `NAV_ITEMS_BASE`.
- `app/routers/about.py` (new) — `/about` route renders `about.html` with corpus_stats + nav_items_for("about").
- `app/routers/reports.py` — `_apply_synthesis` derives `mention_count` per biggest entry from cluster member_item_ids.
- `app/templates/reports.html` — card reorder (drama block moved up), `gc-mention-badge` rendered in `gc-biggest-sources` flex row, `gc-row-list--scrollable` class on release radar's list.
- `app/templates/about.html` (new) — visual pipeline + glossary + stack panel.
- `app/static/app.css` — `.gc-sidebar` padding tightened + `overflow-y: auto`; `.gc-sb-bottom` padding + `flex-shrink: 0`; `.gc-sb-corpus` padding tightened; `.gc-biggest-sources` → flex row; new `.gc-mention-badge`; new `.gc-row-list--scrollable`; new `.gc-about-*` family (~110 lines, with two responsive media queries).
- `app/main.py` — registered `about.router`.
- `weekly_reports` DB rows for 2026-W17 (created) and 2026-W18 (filled).

---

## 2026-05-13 (Phase 3c.7) — UI consistency: routing swap, shared shell, live search

**Done:**
- **Routing swap.** `/reports` → `/` (the weekly read-out is now the home page). Old `/` (raw items table) moved to `/dashboard`. `/reports` now 404s. The internal HTMX sub-endpoints stay at their existing paths: `/reports/exec-summary`, `/reports/drawer`, `/reports/export`. Rationale: keeps the namespace for the modal/drawer/export fragments while still letting the user land on the read-out at the root URL.
- **`app/services/chrome.py` (new).** `NAV_ITEMS_BASE` list of 4 nav items (Weekly read-out → `/`, Dashboard → `/dashboard`, Clusters → `/clusters`, Sources → `/sources`) + `nav_items_for(active_id: str)` helper. One source of truth for the sidebar nav; every route calls `nav_items_for("dashboard")` etc. to flip the `is_active` bit. `reports.py` `NAV_ITEMS` constant deleted.
- **`app/templates/_sidebar.html` (new).** Extracted from `reports.html` so the four `.gc-shell`-based pages share the same dark sidebar. Conditionally renders the per-week Read-out section only when `weeks_index` is in context — the non-reports pages don't get that block. Logo + tagline + nav + corpus-stats block all live in one place now.
- **`app/templates/shell_base.html` (new).** The shared shell for Dashboard / Clusters / Sources. Provides `<body class="gc-shell-body">` + `.gc-shell` wrapper + `_sidebar.html` include + main column with header. Exposes Jinja blocks for `title`, `eyebrow`, `heading`, `header_meta`, `header_actions`, `main_content`. `reports.html` does NOT extend this — its sidebar has a Read-out section and its header has a different actions/breadcrumb shape, so the duplication cost was lower than the abstraction cost.
- **Dashboard re-skinned.** `app/templates/dashboard.html` now extends `shell_base.html`. Old `base.html`-extending table replaced with a `.gc-table`-styled rendering: source-pill column + when column + title/TLDR column + category-chip + sentiment-score columns. New `_dashboard_list.html` partial holds just the table; the full page wraps it in the shell. `app/routers/dashboard.py` rewritten: route moved `/` → `/dashboard`, added `?q=` filter (case-insensitive ILIKE against title / TLDR / source.name), added HX-Request branch that returns just the list partial without the chrome. Total/pending counts now passed to the header meta.
- **Clusters re-skinned.** Template extends `shell_base.html`; cluster rows render as `.gc-cluster-card`s with label + meta + member list. Source pills on each member item. `?q=` filters by cluster label. Re-run button dropped from this phase (was a POST form that's mostly a dev tool — covered in Phase 4 if needed).
- **Sources re-skinned.** Same shell pattern, `.gc-table` for the sources table. Status / errors rendered as color-coded `.gc-table-chip` (ok / off / bad variants). Per-source ingest button dropped (also belongs in Phase 4's source CRUD work). `?q=` filters name OR url_or_handle.
- **HTMX live search.** Each page has a `<input type="search" class="gc-search-input">` in the header (`gc-header-actions`). `hx-get="..." hx-trigger="keyup changed delay:300ms, search" hx-target="#<list-id>" hx-swap="innerHTML" hx-push-url="true"` — 300ms debounce, URL stays in sync via push-state so search results are bookmarkable. Server detects `HX-Request` header and returns the list partial directly (without shell chrome) to keep the response small. List wrappers (`#dashboard-list`, `#clusters-list`, `#sources-list`) are stable swap targets.
- **CSS additions (~150 lines):**
  - `.gc-search-input` — header search input style (matches `.gc-cta` height, accent-soft focus ring).
  - `.gc-table` family — bordered table with sticky header, hover row, monospace numerics. Sub-classes `.gc-table-when`, `.gc-table-source`, `.gc-table-cat`, `.gc-table-sent`, `.gc-table-title` (link → accent on hover), `.gc-table-tldr` (secondary gray subline), `.gc-table-mono` (url in code chip), `.gc-table-chip` + `--ok`/`--bad`/`--off` variants for source statuses.
  - `.gc-cluster-card` family — `.gc-cluster-label`, `.gc-cluster-meta` (with `.gc-cluster-sep` `·` dividers), `.gc-cluster-members` (border-separated row list), `.gc-cluster-member-title` (link → accent on hover), `.gc-cluster-member-when` (tabular-num timestamp).
  - `.gc-pill-dot--youtube` — YouTube-red pill dot variant (was missing — outlets/subreddits/forums had variants, youtube didn't).
- **Drawer pill-link bug fixed.** Each item in the cluster drawer was rendering with two empty bordered rectangles per card. Root cause: `_drawer.html` wrapped every item in `<a class="gc-drawer-item" href="...">` AND the inner source pill came from the `source_pill` macro which emits `<a class="gc-pill" href="#">`. HTML doesn't allow `<a>` inside `<a>`; the browser parser auto-closes the outer link before the nested one, producing an empty `.gc-drawer-item` border + orphaned content. Fix: drawer template renders the source pill inline as `<span class="gc-pill">` instead of calling the macro. Other consumers of the macro (Biggest stories pills) keep the `<a>` variant since they're not inside another `<a>`.

**Decided / verified (full rationale in DECISIONS 2026-05-13 Phase 3c.7 entry):**
- **`/` = weekly read-out** as the canonical home URL. Internal HTMX endpoints keep the `/reports/*` namespace so the routing stays semantically clean (read-out fragments at /reports/*, top-level URL is the actual product surface).
- **Light re-skin chosen over full gc-row card style.** Dashboard / Clusters / Sources are engineer-inspection surfaces; tables are denser per-row and easier to scan than cards. The visual consistency comes from sharing the shell + design tokens (Arial Nova, orange accent, gc-canvas/gc-border colors).
- **One HTMX endpoint per page, branching on `HX-Request` header.** Rejected: separate `/api/dashboard` or `/dashboard/fragment` routes. Reason: server-side branching is one `if request.headers.get("HX-Request"):` check; no schema duplication, the same context dict feeds both the partial and the full-page render.
- **300ms keyup debounce** as the live-search delay. Standard HTMX pattern; type "nin" → 300ms idle → fetch.

**State at end of session:**
- New files: `app/services/chrome.py` (~25 lines), `app/templates/shell_base.html` (~45 lines), `app/templates/_sidebar.html` (~50 lines), `app/templates/_dashboard_list.html`, `app/templates/_clusters_list.html`, `app/templates/_sources_list.html` (~30-50 lines each).
- Modified: `app/routers/dashboard.py` (rewritten, route + filter + HX branch, ~95 lines), `app/routers/clusters.py` (similar, ~125 lines), `app/routers/sources.py` (+filter + HX branch + corpus chrome, ~80 lines), `app/routers/reports.py` (`@router.get("/reports")` → `@router.get("/")`, `NAV_ITEMS` constant removed in favor of `nav_items_for("weekly")`), `app/templates/dashboard.html` / `clusters.html` / `sources.html` (rewritten to extend `shell_base.html`), `app/static/app.css` (+~150 lines: `.gc-search-input`, `.gc-table*`, `.gc-cluster-card*`, `.gc-pill-dot--youtube`), `app/templates/_drawer.html` (source pill as `<span>` not via macro to fix `<a>` nesting).
- All routes verified 200 on `:8001 --reload`: `/`, `/dashboard`, `/clusters?week_id=2026-W19` (38 cluster cards), `/sources`; `?q=` filters work on all three; HX-Request fragment branch returns shell-less HTML; `/reports` correctly 404s.
- **Corpus state unchanged.** No model spend this phase (pure routing / re-skin / search work). Cumulative project ~$7.56.

**Next session should:**
1. **Phase 4 — Automation.** APScheduler daily ingest + Monday-morning synthesis cron; catch-up on startup (resume missed Monday synthesis); `/runs` UI surfacing the existing `run_log` table; **Source CRUD via web forms** (add / edit / disable / remove — currently SQL-only). **This is the actual finish line** — the difference between "manual dashboard" and "Monday-morning self-running briefing" per the PRD.
2. **Optional Phase 3d — archive + markdown export.** Markdown render from `synthesis_json` → `weekly_reports.markdown_content` + "Generate report" button + `/reports/archive` list view.
3. **Optional hygiene:** W17/W18 synthesis backfill (~$1.80) unlocks the sidebar week-list flip to `weekly_reports desc by generated_at`; drop 63 legacy `week_id='all'` clusters; numeral-variant dedupe; taxonomy-drift audit.

**Open / blocked:** Nothing blocking. Phase 4 is the recommended next session focus.

---

## 2026-05-13 (Phase 3c.6) — Executive 1-pager + standalone HTML / PDF export

**Done:**
- **Re-scope of Phase 3c.6 mid-planning.** The next-session list inherited from 3c.5 said "markdown + standalone-HTML export of the full /reports view". User redirected scope: instead of exporting the full 10-card layout as markdown + HTML, build a 1-pager executive briefing inside the existing Exec-summary modal, with Export HTML + Export PDF buttons inside the modal footer. Markdown export deferred to Phase 3d. PDF strategy: browser print dialog (zero new deps), not WeasyPrint. 1-pager content: condense existing `synthesis_json` (no new LLM call), using the already-generated Haiku paragraph as the lead.
- **Modal upgraded to 1-pager.** `app/templates/_exec_summary.html` rewritten (~135 lines). Same modal shell; only the body content changes. Composition: header strip (week label + week_range + `stats.stories items · stats.sources sources`) → existing `gc-exec-paragraph` Haiku paragraph → Biggest section (numbered list, max 3, with title + dek + per-row source-pill subline) → Market momentum section (bulleted with `gc-onepager-mmcat--{category}` chip + title + note, max 3) → two-col layout: Risks (max 2, with severity dot + title + note) | Community (max 1 heated + max 1 celebrating, each with eyebrow tag + title + note). Modal footer gets `gc-onepager-exports` wrapper with two `<a class="gc-onepager-export" target="_blank">` anchors to `/reports/export?...&format=html|pdf`. Footer `justify-content` flipped from `flex-end` to `space-between` so the attribution text and export buttons split cleanly.
- **`reports_exec_summary` endpoint extended.** Previously passed only the Haiku paragraph + model + timestamp. Now also loads `synthesis_json` (via existing `_load_synthesis()`), week stats, source pills for the top-3 biggest cluster_ids. Refactored: the context-building work moved into a new `app/services/export.py` shared with the export endpoint; the router's `_one_pager_context()` thin-wraps the service call and falls back to a Haiku-only context when synthesis hasn't run.
- **`app/services/export.py` (new module, ~180 lines).** `inline_css(refresh=False)` reads `app.css` at module level and caches the string. `build_payload(session, week_id, exec_text, exec_model, exec_generated_at, exec_from_cache) -> dict | None` is the shared payload builder for both the modal and the export endpoint; returns None when `synthesis_json` is missing. `load_cached_html` / `save_cached_html` (DB cache pattern mirroring `exec_summary`). `inject_auto_print(html_text)` appends a `window.print()` script before `</body>` for the PDF path (so the cache stays canonical and one stored doc serves both render modes).
- **`_report_standalone.html` template (new).** Full HTML doc: `<!doctype>`, `<head>` with `<title>{{ week_label }} — Executive summary</title>` + `<meta viewport>` + `<style>{{ inline_css|safe }}</style>` (the full `app.css`, ~33KB). `<body class="gc-standalone-body">` wraps the same 1-pager content as the modal but inside a `.gc-standalone-doc` container with its own header (`gc-standalone-eyebrow` + `gc-standalone-title`) + footer (generated-at + synthesis_model + exec_model attribution). Optional auto-print `<script>` at the bottom gated by `{% if auto_print %}` (only the inject path uses it — the cached HTML has `auto_print=False` baked in).
- **`GET /reports/export?week=&format=html|pdf[&force=1]` (new endpoint, ~75 lines).** Format validation (only `html` / `pdf`, else 400) → week-id validation (else 400) → cache lookup unless `force=1` → if cache miss: re-trigger Haiku (cache hit on the exec_summary side too) + build synthesis payload + render `_report_standalone.html` + persist to `weekly_reports.html_content`. If synthesis is null, returns 409 plain-text with the CLI hint. HTML path: `Response` with `Content-Disposition: attachment; filename="gaming-chatter-{week}.html"`. PDF path: `Response` with `inject_auto_print(cached_html)` body, inline (no Content-Disposition) so the new tab actually renders + fires `window.print()`.
- **CSS additions (~170 new lines, no deletes).** `.gc-onepager-*` family for the modal 1-pager (head strip / section / numlist / buls / mmcat chips with 5 color variants / rlvl severity dots / cstag heated+celebrating tags / twocol grid / empty / nosynth dashed box / exports + export anchor button). `.gc-standalone-*` family for the export-only chrome (body / doc / head / eyebrow / title / foot). `@media print` block at the end: hides overlays + drawer + modal + sidebar + header + export buttons, forces `body { background: #fff; color: #000 }`, single-column at small print sizes (but keeps the two-col Risks/Community when print width permits), `@page { margin: 16mm 14mm }`, `page-break-inside: avoid` on sections. One existing-rule edit: `.gc-modal-footer` `justify-content: flex-end` → `space-between` + flex-wrap.
- **Verified on `:8002` (fresh uvicorn, no reload — `:8001`'s WatchFiles reloader hit the same orphan-worker pattern as last session and refused to pick up the new code).**
  - W19 modal (synthesis ran): 200, 8747 bytes, 4 section labels (Biggest / Market momentum / Industry risks / Community), 10 `<li>` items (3+3+2+1+1), 2 export anchors visible, 3 MM category chips, 2 risk severity dots, 2 CS sentiment tags, twocol layout present, nosynth note absent.
  - W18 modal (no synthesis): 200, 1724 bytes, 0 section labels, 0 export anchors (hidden by `{% if synthesis_ran %}`), Haiku paragraph present, nosynth dashed-box note present with `scripts/run_synthesis.py 2026-W18` CLI hint.
  - W19 export HTML (cold render): 200, 41935 bytes, `Content-Disposition: attachment; filename="gaming-chatter-2026-W19.html"`, `<!doctype html>` start verified.
  - W19 export HTML (warm cache hit): 200, identical 41935 bytes — DB-served, no re-render.
  - W19 export PDF: 200, 42041 bytes (cold HTML + 106-byte auto-print script), no Content-Disposition (inline), `window.print()` script verified present after `</body>` cut.
  - W18 export: 409 with plain-text "Synthesis hasn't run for 2026-W18 — Run: `scripts/run_synthesis.py 2026-W18`".
  - Bad format query: 400.
  - DB after first W19 export: `weekly_reports.week_start=2026-05-04` row has `html_content=41935 bytes`, `exec_summary_text=970 bytes`, `synthesis_model=claude-opus-4-7`. W18 row gained `exec_summary_text=749 bytes` from the modal-degrade test (1 Haiku call, ~$0.001).
  - Inlined CSS in the standalone doc: 33,417 bytes (the full `app.css` content unchanged). Title tag reads `Week of May 4, 2026 — Executive summary`. Body opens with `<body class="gc-standalone-body">` → `<div class="gc-standalone-doc">` → `<header class="gc-standalone-head">` → real W19 content (Nintendo Star Fox 64 announcement etc.).

**Decided / verified (full rationale in DECISIONS 2026-05-13 Phase 3c.6 entry):**
- **1-pager content from `synthesis_json` only — no new LLM call.** Rejected adding a second Opus pass that re-voices the existing synthesis into an exec briefing (~$0.30/wk). The existing Haiku paragraph + structured bullets already fits on a printed page.
- **PDF via browser print dialog, not WeasyPrint.** Zero new deps; one extra click for the user. Locked single-process minimal-deps stack reaffirmed.
- **One canonical cached HTML doc; PDF path injects auto-print *after* cache read.** Avoids storing two variants.
- **Modal-resident export buttons, not header buttons.** User previews 1-pager before exporting; header chrome stays minimal.
- **W17 / W18 graceful degrade.** Modal shows Haiku paragraph + CLI hint; export buttons hidden in the UI + 409 on direct URL hit. Rejected partial export (just Hottest / Trends / Releases for un-synthesized weeks) — would have produced a misleading half-document.
- **Inline the full `app.css` (~33KB) un-stripped.** A PurgeCSS / hand-curated subset would have introduced drift risk; 33KB is trivial for personal-local use.
- **`weekly_reports.markdown_content` stays unused this phase.** No use case surfaced for a markdown artifact, and a third modal-footer button would have crowded the chrome.

**State at end of session:**
- New files: `app/services/export.py` (~180 lines), `app/templates/_report_standalone.html` (~115 lines).
- Modified files: `app/templates/_exec_summary.html` (full rewrite, ~135 lines), `app/routers/reports.py` (+~95 lines: `_one_pager_context` thin-wrapper, `_exec_error_ctx` updated for new field shape, `reports_exec_summary` endpoint upgraded, new `reports_export` endpoint, +`from fastapi.responses import Response` + `export as export_svc` imports), `app/static/app.css` (+~170 new lines: `gc-onepager-*` + `gc-standalone-*` + `@media print` block, plus one edit to `.gc-modal-footer` justify-content).
- Docs updated: this entry; `docs/TASKS.md` Phase 3c.6 boxes ticked + new "Phase 3d — Archive (deferred from 3c.6)" section spec'd; `docs/DECISIONS.md` 2026-05-13 (Phase 3c.6 shipped) entry; `CHANGELOG.md` Unreleased / Phase 3c.6 entry; project `CLAUDE.md` Status line updated.
- Corpus state unchanged from 3c.5 (988 items · 887 Haiku-enriched · 900 embeddings · 184 games in dim · 55 per-ISO-week clusters + 63 legacy `week_id='all'`). `weekly_reports`: W19 row gained `html_content=41935 bytes`; W18 row gained `exec_summary_text=749 bytes` (W18 had no row before; one was inserted on the modal-degrade test via `exec_summary.get_or_generate`).
- **Two uvicorn processes running:** user's `:8001 --reload` (PIDs 35436 reloader + 22352 worker) is stale — reloader didn't pick up the new code (same orphan-worker pattern as last session; `/reports` still served 200 but `/reports/export` returned 404 and the modal endpoint 500ed on undefined template vars from a Jinja-only partial reload). My test instance `:8002` (background bs6sbv99b, no reload) serves the new code correctly. User to `Ctrl+C` `:8001` and re-launch to validate the 1-pager + export in their main session.
- **Anthropic spend this session: ~$0.001** (1 Haiku call for the W18 modal-degrade test; no Opus / no synthesis re-run / no relabel). Cumulative project: ~$7.56.

**Next session should:**
1. **Phase 4 — APScheduler automation.** Daily ingest + Monday-morning synthesis cron; catch-up logic on startup; run-log UI at `/runs`. Source CRUD via web forms.
2. **Optional Phase 3d — archive + markdown export** (deferred from 3c.6 scope). Mark down rendering from `synthesis_json` → `weekly_reports.markdown_content`. "Generate report" manual button (UI trigger for `scripts/run_synthesis.py`). Reports archive view at `/reports/{id}` showing the list of weekly_reports rows with timestamps.
3. **Optional hygiene (not blocking, unchanged from 3c.5):**
   - Backfill synthesis for W17 + W18 (~$1.80). Side benefit: sidebar week-list can flip from `available_weeks()` to `weekly_reports desc by generated_at` per the original 3c.5 walkthrough spec.
   - Drop the 63 legacy `week_id='all'` cluster rows.
   - Numeral-variant dedupe (Diablo IV ↔ Diablo 4, Endfield ↔ Arknights: Endfield).
   - Series-as-game cleanup.
   - Taxonomy drift audit in `_filter_genres` / `_filter_platforms`.
   - `Summer Game Fest = 1` casing-variant investigation.

**Open / blocked:**
- `:8001` reloader stuck on stale code. Same pattern as last session (file touch + 2s wait did not trigger reload). User restart required to validate the 3c.6 changes in their main session.
- Phase 4 APScheduler — next session's main candidate. No blockers.
- Sidebar week-list source flip — still waiting on W17/W18 synthesis backfill.

**Post-commit addendum (visual revision, same session):**
- User opened the modal in browser, screenshot revealed two problems: (1) content overflowed past the modal's white box — body scrolled inside the modal where the user wanted everything to fit in one viewport; (2) export buttons in the footer were below the visible fold so the user couldn't see them. Asked for the export button "at the top right next to the close button" and for the layout to be "more interactive/visual/infographic (not too much)".
- **Re-shipped under the same Phase 3c.6 banner:**
  - **Modal footer dropped.** Attribution moved to a one-line `gc-onepager-attribution` caption inline at the bottom of the body (right-aligned, 9.5px). Saves ~50px of vertical chrome.
  - **Export menu moved to header.** `<details><summary>Export ▾</summary>` CSS-only dropdown positioned `position: absolute; top: 12px; right: 50px` so it sits to the left of the `.gc-modal-close` × button (which stays at `right: 14px`). Panel pops below with two anchors: "Save as PDF" + "Download HTML". Native `<details>` open/close — no JS. `::-webkit-details-marker { display: none }` strips the default chevron; we add our own `gc-onepager-export-caret`. Header `padding-right` bumped to 130px to clear both buttons.
  - **Stat tile row added** — 4 tiles (`items`, `sources`, `top game · N`, `top genre · N`) at the top of the body. Picks up `top_games_for_week(limit=1)` + `top_genres_for_week(limit=1)` from existing services. Adds infographic feel without going overboard; saves the existing inline stats-strip from being verbose.
  - **Biggest deks dropped.** Numbered list now shows title + source pills only — each item ~2 lines vs. ~5 before. The dek text was the single largest vertical-space contributor in the screenshot.
  - **Two-col Risks/Community → three-col MM/Risks/Community.** Market momentum moved INTO the columns instead of being its own row. Saved one full section's worth of vertical space. Column ratio: 1.5fr / 1fr / 1fr (MM gets more width since its category chips eat horizontal space). `gc-onepager-itemtitle--clip` ellipsis truncates the title within each column.
  - **Type scale shrunk throughout.** Lead paragraph 15px → 12.5px. Numlist 13px → 12.5px. Bul list 13px → 11.5px. Section labels 10px → 9px (still uppercase tracked). Chip fonts 9px → 8px. Stat tile values 17px (number) / 14px (name) with 9px uppercase label below. Roughly 25% vertical compression vs. the first cut.
  - **Stale W19 `html_content` cache invalidated** (one-line `UPDATE weekly_reports SET html_content = NULL`) so the next export re-renders against the new layout.
  - **`gc-modal-footer` rule reverted to original `justify-content: flex-end`** since we no longer use the footer (the prior `space-between` tweak is dead now).
- **Verified on fresh `:8001 --reload` (port killed + restarted; same uvicorn `--reload` instance the user runs):** W19 modal 200/6971 bytes (down from 8747 — 20% smaller), 4 stat tiles, 3-col layout present, twocol absent, export dropdown + summary + panel + 2 anchors, 7 `gc-onepager-itemtitle--clip` clipped titles, 0 dek references, footer absent, attribution caption present. W18 modal 200/2191 bytes degraded: stat tiles still render (top game/genre work without synthesis), Haiku paragraph + nosynth note + CLI hint visible, export dropdown hidden. W19 export HTML 200/42401 bytes (slightly bigger than 41935 from new CSS + tiles markup). PDF 200/42507 with auto-print injected. Test HTML saved to `exec_summary_W19.html` in project root for the user's visual review.
- **`:8001` is now running fresh code** (killed both `:8001` + `:8002` on user request; restarted `:8001` with `--reload` to be the user's main instance). No orphan workers this time since I killed the multiprocessing.spawn child too.
- **No additional Anthropic spend this revision** — the W19 modal load reused the existing exec_summary cache; only the layout HTML changed.

**Rev 3 (third pass, same session):** User opened the export, reported the standalone HTML rendered too wide (horizontal scroll) and didn't look like an A4 page; Export button visually generic (not orange-themed like the rest of the UI); Haiku paragraph "again too much text in a single paragraph"; redundancy across the page; fonts on the standalone too small. Re-shipped:
- **Stat tiles dropped from both modal + standalone.** The `top game · N` tile duplicated Biggest #1, and `top genre · N` typically duplicated a phrase in the Haiku paragraph. `build_payload` no longer computes `top_game` / `top_genre`. Router fallback context cleaned up to match.
- **Haiku paragraph sentence-split.** New `app/services/export.split_into_paragraphs(text, group=2)` helper splits the exec paragraph at `". "` boundaries and groups every 2 sentences into a `<p>`. Renders as multiple `<p>` inside `.gc-onepager-lead`. For a typical 4-sentence Haiku output → 2 paragraphs with breathing room between.
- **Standalone export → A4 portrait paper.** `.gc-standalone-doc { width: 210mm; min-height: 297mm; margin: 0 auto; padding: 18mm 16mm; background: white; box-shadow: 0 6px 24px rgba(0,0,0,0.10); }`. Body wraps the doc with `background: var(--gc-canvas)` so on-screen the doc visually sits as a paper sheet on a light-gray canvas. `@page { size: A4 portrait; margin: 14mm }` lock for the print path; print rules also strip the box-shadow + canvas background + reset doc to fill the paper.
- **Standalone fonts bumped ~10%.** Modal stays compact (12.5–13px scale); standalone gets a `.gc-standalone-doc .gc-onepager-*` cascade that pushes lead to 14px / numlist to 14px / buls to 13px / section labels to 10.5px / chips to 9.5px. More readable as a printed/exported document while keeping the modal tight.
- **Modal layout flipped from 3-col cross-cut to vertical-stacked sections + 2-col Risks|Community at the end.** MM moves out of the cross-cut strip and gets its own full-width section. Source pills + bullets get more horizontal room; "horizontal scroll" complaint resolved.
- **Header layout: title + range inline.** Replaced the stacked `gc-modal-title` + `gc-onepager-rangestrip` (two visual lines) with a single `.gc-onepager-titleline` (title · range), saving one line of chrome.
- **Export button repainted orange.** `.gc-onepager-export-menu > summary` is now `background: var(--gc-accent); color: var(--gc-fg-on-accent); border: none;` — matches the existing `.gc-cta` style (the same orange Exec-summary CTA in the header). Hover/open uses `var(--gc-accent-hover)`. Panel hover state uses `var(--gc-accent-soft)` background + accent text.
- **Modal `gc-onepager-titlesep` separator** between week label and range — small `·` in border-strong color.
- **CSS deadcode dropped:** `.gc-onepager-stats`, `.gc-onepager-stat`, `.gc-onepager-stat-val`, `.gc-onepager-stat-val--name`, `.gc-onepager-stat-lab`, `.gc-onepager-threecol`, `.gc-onepager-rangestrip`. Replaced by `.gc-onepager-titleline` + `.gc-onepager-titlesep` + `.gc-onepager-titlerange` + reinstated `.gc-onepager-twocol`.
- **Verified on user's `:8001 --reload`** (the user started uvicorn themselves after I gave the command last turn — PID 41728, picked up the reload cleanly): W19 modal 200/6371 bytes; export 200/42786 bytes; `<p>` count in lead = 2; export embeds `width: 210mm` + `min-height: 297mm` + `@page { size: A4 portrait }`; orange-accent rules served by `/static/app.css`. Fresh export saved to `exec_summary_W19.html` (43931 bytes) for visual inspection.
- **Out of scope, surfaced for next session:** Dashboard (`/`) + Clusters (`/clusters`) + Sources (`/sources`) UI re-skin to match the polished `/reports` design system. Today they all extend `base.html` (Phase 1-2 scaffolding) which is why they look like raw HTML tables. A future phase should either move them to a `.gc-shell`-based layout, or delete them entirely if engineer-inspection isn't a real product surface anymore.

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

**Post-commit addendum (after `48ebd5e`):**
- **`:8001` restart cleared the stuck reloader.** First two restart attempts served 500s because two orphan WatchFiles multiprocessing-spawn workers from the original stuck reloader (PIDs 41336 + 13240) had inherited the `:8001` listen socket via Windows socket-handle inheritance — even though their parent reloader PIDs were dead per Get-Process, the children kept the port bound. **Gotcha for next restart:** orphan workers have `CommandLine` set to the bare `multiprocessing.spawn` token (no `uvicorn` substring), so filtering only by `*uvicorn*` misses them. Use `'uvicorn|multiprocessing.spawn'` and exclude unrelated projects (`pulse-check`, `http.server`, the user's other `:8000` uvicorn). Once cleared, the fresh `--reload` spawn was clean: reloader PID 35436, worker PID 22352.
- **All 3 weeks verified 200 on `:8001`** with full structural counts (W19: 10 cards / 3 Biggest / 5 MM / 1 heated + 2 celebrating + narrative CS / 2 risks / 0 esports honest empty / 1 drama / 5 watch / 72 drawer triggers / 4 nav routes / corpus stats `988 · 55 · 30` / zero occurrences of any dead class. W18 + W17: 7 "Awaiting synthesis" prompts each, chrome + Hottest + Trends + Releases intact). Drawer + exec-summary fragments both 200; exec-summary attributes to `claude-opus-4-7`.
- **User opened `/reports?week=2026-W19` in browser and confirmed the layout visually.** No regressions reported.

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
