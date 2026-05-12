# Decisions log

Append-only. Newest entries on top. Each entry: date, decision, rationale, alternatives rejected.

---

## 2026-05-12 (later) — Override "Ollama-only for per-item work"; per-item enrichment moves to Anthropic Haiku 4.5; +Sonnet cluster labels +critic-pass synthesis

**Lock being overridden:** project CLAUDE.md → Hard architectural constraints → "**LLM split: Ollama local for per-item work, Anthropic API for synthesis only.** Do not introduce OpenAI, llama.cpp direct, or other providers." Also DECISIONS 2026-05-06 — "LLM strategy = hybrid Ollama (local) + Anthropic API … Local 14B for per-item enrichment + embeddings + cluster labels; Anthropic API for weekly synthesis only." Today's decision keeps the *no-OpenAI / no-llama.cpp-direct* part of the lock intact (Anthropic remains the only API provider), but flips per-item enrichment and cluster labels from Ollama to Anthropic.

**Decision:**
- **Per-item enrichment** uses **Anthropic Haiku 4.5** (replacing qwen2.5:7b on Ollama). Implemented in a new `app/services/anthropic.py` to be designed and signed off next session before the 988-item backfill.
- **Cluster labels** use **Anthropic Sonnet 4.6** (replacing the qwen2.5:7b `label_cluster()` JSON-mode path).
- **Synthesis** gains a **critic / editor pass via a second Opus 4.7 call** after the main Opus 4.7 synthesis run. The first call drafts the 10-section report; the second call tightens prose, removes filler, and surfaces inconsistencies.
- **Embeddings stay on local Ollama** (`nomic-embed-text` 768-dim). No change to `embed_text()` or the embedding storage shape.

**Rationale — concrete evidence, not vibes:**
1. **Quality.** Today's 10-item structured-output sample (qwen2.5:7b under JSON-schema constrained decoding) exposed quality issues that the prompt restructure did not fix:
   - Reddit username `Responsible_Box_2422` leaked into `entities.people` despite an explicit negative-example prompt rule against underscored handles.
   - *Minions & Monsters* (a movie, not a game) was tagged with `Indie/Roguelike` — model failed to recognize it as out-of-domain.
   - The three new fields (`genres[] / platforms[] / event`) had to be **forced** into output via JSON-schema constrained decoding; `format:"json"` plus prompt instructions alone weren't enough — qwen silently omitted them. Schema enforcement got them populated but the values themselves remained low-confidence.
2. **Runtime.** Structured-output mode pushed qwen2.5:7b to ~26s/item. Extrapolated, the 988-item backfill = ~7 hours, vs the originally-estimated 45 min for the non-constrained call. Haiku 4.5 measured ~5s/item via the Anthropic API ⇒ ~1.5 hours for the same backfill. **4–5× speedup** at a workload that's run weekly on ~200 fresh items.
3. **Cost.** One-time backfill via Haiku: ~$5–10 for 988 items. Ongoing: ~$100–200/yr for ~200 items/week. Sonnet cluster labels: ~$10/yr. Opus critic pass: ~$100/yr extra on top of the existing ~$15/yr Opus synthesis. **Total Anthropic spend estimate: ~$210–310/yr — under the user's stated $500/yr ceiling.**

**Tradeoff acknowledged:** the core ingest pipeline now depends on a working Anthropic API key + network availability for the per-item enrichment pass. Ollama's offline / no-API-key capability is lost for enrichment (still retained for embeddings). This is acceptable for a personal-local single-user project, but it does shift the failure surface — if the API key is rotated, expired, or rate-limited at the wrong moment, the weekly ingest halts.

**Implications:**
- Phase 4 APScheduler weekly auto-run will need the Anthropic API key in env (no graceful fallback to Ollama planned — would double-maintain two enrichment prompts).
- `app/config.py` will need new settings for the Anthropic client (model id, retry policy, etc.).
- `docs/ARCHITECTURE.md` needs updating after the Haiku migration lands — the "LLM split" section is the load-bearing one.
- The qwen-generated tags from today's aborted partial re-enrichment (~25–30 items) will be overwritten in the Haiku backfill — no separate rollback needed.

**Rejected:**
- **Keep qwen2.5:7b and tune the prompt harder.** Diminishing-returns expectation given today's evidence — underscored-handle bleed survived an explicit negative example, and a movie was tagged with game genres. Schema enforcement got the shape right but not the content.
- **Try a larger Ollama model (14B / 32B).** Already rejected on VRAM grounds in DECISIONS 2026-05-07 (12GB RTX 5070 headroom). Re-opening that decision would require either smaller batch sizes (slower) or model swap thrash (also slower).
- **Use Haiku for enrichment but keep Ollama for cluster labels.** Inconsistent — once the per-item lock is broken, there's no principled reason to keep cluster labels on the worse-quality path. Sonnet is also a tiny incremental cost (~$10/yr).
- **Skip the critic pass on synthesis.** Standard pattern in long-form Anthropic workflows. ~$100/yr is trivial vs the user-facing-quality moment of the weekly report.
- **Move embeddings to Anthropic too.** Anthropic has no embeddings endpoint; would require introducing a third provider (OpenAI embeddings or Voyage) and that violates the *no-OpenAI* half of the original lock without comparable evidence to justify it. `nomic-embed-text` on Ollama is performing fine.

**Addendum 2026-05-12 (Phase 3c.0.5 ship — actual observed values):**
- **Model string used:** `claude-haiku-4-5` (default; alias resolves to the latest Haiku 4.5 snapshot, no date-suffix needed per the Anthropic model-ID convention).
- **Anthropic SDK version:** `anthropic` 0.100.0 (installed; pyproject pinned at `>=0.40` covers it).
- **Throughput:** 988-item backfill ran in 39.5 min wall-clock at ~2.4 s/item — **faster than the 1.5-hour pre-flight estimate**. 10-item sample averaged ~3 s/item; bulk run averaged ~2.4 s/item, likely due to better TCP/connection reuse at scale.
- **Estimated spend on the backfill:** ~$3-4 (988 calls × ~1500 input + ~500 output tokens avg; $1/M input + $5/M output). Below the $5-10 ceiling estimated above. Total Phase 3c.0.5 session spend including 10-item sample + games-dim populate (189 calls, ~$0.60) ≈ **~$5**.
- **Quality outcomes:** Both known-bad cases visibly fixed in the sample diff (Minions movie no longer game-tagged; Reddit handle no longer in entities.people). Backfill preserved-row rate **1.4%** (13/988) — Haiku occasionally returned an out-of-taxonomy category like `'guide'`, which the existing `_ALLOWED_CATEGORIES` check rejected; the safety net kept the prior valid qwen row for those items. Acceptable; can be addressed by widening `_ALLOWED_CATEGORIES` or by a small targeted re-run.
- **Prompt caching:** the `cache_control: {"type":"ephemeral"}` marker on the system block is in place, but `SYSTEM_PROMPT` is ~855 tokens which is below Haiku 4.5's 4096-token minimum cacheable prefix. Caching **no-ops harmlessly** today. Forward-compatible: any future prompt growth past 4096 tokens activates caching automatically with no code change. **Cache-hit rate observed: 0%** (as expected for a sub-minimum prefix).
- **`tag_game()` also ported to Haiku.** Same `messages.parse(output_format=GameTagData, ...)` pattern. 189 games tagged in 3.6 min, 0 failures. Distribution: 131 existing / 28 upcoming / 30 null-unknown / 55 live-service.
- **Re-embed required after backfill** because the Haiku-rewritten tldrs are different text from the qwen tldrs the original embeddings were computed on. Implemented as: SQL `UPDATE enrichments SET embedding=NULL WHERE status='ok'` then `embed_pending()`. 900/900 in 37 min, 0 failures. Free (Ollama local).
- **Per-week clustering:** 55 new clusters across 2026-W17/W18/W19 (4/13/38). `label_cluster()` still on qwen2.5:7b — Sonnet 4.6 migration **deferred to Phase 3c.4**, bundled with synthesis.

---

## 2026-05-12 — `/reports` redesign walkthrough: 13→9 cards, Trends restored via 5-tab + tagging foundation, synthesis scope expanded vs PRD
**Decision:** Walked `/reports` section-by-section per the prior session's "Next session should" #1 and locked keep/drop/rework across the full surface. Net result: chrome trimmed, 13 cards → 9 (with one new shape and one reframe), Trends re-instated under a new 5-tab spec (the prior session had deferred Trends entirely), a 4-dimension tagging foundation made a hard prerequisite for Phase 3c synthesis, and the synthesis prompt schema expanded from PRD-locked 6 sections to 10 sections + an exec-summary pass. No code written this session — purely design locks.

### Chrome / shell
- **Sidebar nav → 4 routes only** (Weekly read-out / Dashboard / Clusters / Sources). Dropped Watchlist, Trends-nav, Archive, All-stories. Why: only link to pages that exist; placeholder items lie about app capability.
- **Sidebar week-list always rendered, max ~5 visible with inline scroll for older.** Populated from `weekly_reports` desc by `generated_at`. Why: single-entry list is fine for first run, auto-grows, capped height prevents bloat once N weeks accumulate.
- **Sidebar bottom = corpus stats (items / clusters / sources)**, replacing the user-avatar block from the design. Why: single-user personal app doesn't need an avatar; corpus stats are a real signal.
- **Sidebar "Generate exec summary" CTA removed** (deduped with header CTA, 3 → 1).
- **Header chrome trimmed to title + meta + single Exec-summary CTA.** Layout / density / theme toggles removed. Why: the four variants are already locked (grid + comfortable + light + orange `#D9682B`), so the toggles are decorative-only — removing them prevents dead-button UX.
- **Exec-summary CTA → modal ported from `exec-summary.jsx`**, backed by a second Anthropic pass producing a 1-paragraph tldr of the synthesized report. Why: user-visible quality moment; ~$0.05 extra per run trivial.
- **Standalone headline block above the grid removed.** The verdict-style headline folds into the Biggest-stories card title. Why: three layers of "headline" (standalone block + Biggest card + exec-summary) was overkill.
- **Footer hint block removed entirely.** Why: it referenced drag-to-reorder (already dropped from the port) and source-pill-drill (un-ported); the CTA already moved to header.
- **Source Drawer will be ported.** Right-side slide-in panel, opens on bullet/row click, shows the cluster's synthesized paragraph + member items with outbound links. Why: unlocks the "click a story to read more" interaction across multiple cards (Biggest, MM, Risks, etc.); replaces ad-hoc per-card detail views.

### Cards (13 → 9)
- **Card 1 "This week in gaming" — DROPPED.** Why: overlaps with the sidebar corpus stats just locked; threads/genres data unavailable from current schema.
- **Card 2 "Biggest stories" — REWORKED to plural.** Top-3 clusters by score. Row = rank badge + title + 1-line synth descriptor + source pills; click row → Source Drawer. Span-2 preserved. Dropped: sparkline, signal cluster (heat/conf/relevance), threads/velocity, freshness chip, "Read in detail" button. Why: top-3 are usually close in score and equally relevant — heroing one is a forced choice; sparklines/heat numbers are fabrication risks without real timeseries.
- **Card 3 "Hottest games" — TRIMMED.** Row = title + mention count + 1-line reason. Dropped: studio, platform, heat bar, delta. Revisited post-tagging (platform tag becomes real then).
- **Card 4 "Market momentum" — RESHAPED to row list.** Scope: acquisitions + funds + platform-side policy + structural shifts + people moves. Absorbs the dropped Studio Watch + Storefronts. Why: original 4-platform-sparkline layout didn't match the locked PRD scope from the 2026-05-11 industry-risks decision; list-shape matches the actual cluster signal.
- **Card 5 "Trends" — RE-INSTATED.** New 5-tab layout (see Trends section below). Reverses the 2026-05-11 "WoW-Trends deferred entirely from Phase 3c" decision, on the basis that the tagging foundation locked this session is the prerequisite the prior decision called out as missing.
- **Card 6 "Community sentiment" — REFRAMED.** No aggregate pos/neu/neg bar. New layout: synth narrative on top (1–2 sentences drawn from `sentiment_summary` excerpts) + 2 per-cluster polarized lists ("Reddit is heated about" / "Reddit is celebrating"), each row anchored to a cluster → drawer. Why: aggregate %s without reach weighting (RSS has no upvote/comment counts) and without a topic anchor mislead the reader ("41% positive about what?"); per-cluster sentiment is always topic-anchored and honest about what the data actually is (tone of Reddit posts, not community reactions).
- **Card 7 "Industry risks" — KEPT.** Row = severity bar + title + low/med/high badge + 1-line note + source pills. Trend chip dropped. Why: severity is a defensible synthesis judgment from cluster tldrs; "rising" requires multi-week corpus we don't have yet.
- **Card 8 "Studio watch" — DROPPED, folded into MM.** Why: layoffs already in Risks, M&A already in MM; residual scope (hires/exec departures) too thin for a dedicated card.
- **Card 9 "Storefronts" — DROPPED, folded into MM.** Why: platform-side policy already MM's scope.
- **Card 10 "Esports & streaming" — KEPT but honestly reframed.** Not Twitch metrics — the corpus has zero structured esports/streaming data sources. Card becomes a filtered cluster row list of esports/streaming stories from existing news + Reddit. Why: rather than fabricate top-stream hours and event peaks, surface what we actually have.
- **Card 11 "Release radar" — TRIMMED.** Row = date chip + title + 1-line note + source pills. Dropped: platform tag, hype meter. Synthesis extracts date from cluster text.
- **Card 12 "Drama / Controversy tracker" — NARROW SCOPE only.** Synthesis explicitly excludes community-tone-driven anger (→ CS) and business/legal (→ Risks). Card surfaces exec/PR blunders + studio feuds only. Risk accepted: some weeks the card will be empty.
- **Card 13 "Watch next week" — KEPT.** Row = day chip + 1-line item + source pills. Add-reminder button dropped (no push delivery infra — out of scope per CLAUDE.md).

### Trends card (new this session)
- **Trends re-instated for Phase 3c via a 5-tab layout: Games (sub: existing + upcoming) / Genres / Platforms / Live-service / Events.** WoW only — MoM stays dropped per the 2026-05-11 decision.
- **Ranking rule: top-N by WoW delta in mention rate.** Distinct from Hottest, which is top-N by absolute mention count this week. Why: prevents a Hottest vs Trends.Games-Existing collision where both tabs show the same top games.
- **Live-service vs Games tab overlap is intentional.** Games = "what's loud overall"; Live-service = "what's loud in the live-service segment". The same game can appear in both by design.
- **Empty-state policy: Events tab will frequently be sparse** (seasonal). Needs a clean empty-state design — deferred (see Still open).

### Tagging foundation
Phase 3c synthesis is **blocked** on the tagging work below. Why: half the design's editorial value is dimensional (genre / platform / lifecycle); building synthesis on top of an honest tag layer yields a much sharper output and retroactively makes the Hottest/Releases/Card-1 drops reversible.
- **4 new tag dimensions:**
  - `lifecycle` (existing / upcoming) — new `games` dim table, per-game property
  - `live_service` (bool) — same `games` dim table
  - `genres[]` — multi-valued, per-item, on `enrichments` (cap 3)
  - `platforms[]` — multi-valued, per-item, on `enrichments`
  - `event` — single-valued, per-item, nullable, on `enrichments`
- **Taxonomies locked:**
  - **Genres (12):** Action, Adventure, RPG, Shooter, Strategy, Simulation, Sports, Racing, Fighting, MMO, Survival-horror, Indie/Roguelike.
  - **Platforms (6):** PC, PlayStation, Xbox, Nintendo, Mobile, Multi-platform.
  - **Events (12 + Other):** Summer Game Fest, Gamescom, Tokyo Game Show, The Game Awards, State of Play, Nintendo Direct, Xbox Showcase, PC Gaming Show, EVO, BlizzCon, Future Games Show, Other-showcase.
- **Fuzzy-rule definitions:**
  - **Lifecycle.** "Existing" = released on ≥1 platform anywhere (early access counts as released; remasters are existing; cross-platform-delay items still tag game as existing). "Upcoming" = no release on any platform yet.
  - **Live-service** requires seasonal / battle-pass / league / warbond content model with regular content drops. Single-player games with DLC are NOT live-service. MMOs ARE live-service.
- **Multi-value cap:** max 3 genres per item.
- **Unknown / NULL handling:** Ollama values outside the taxonomy are dropped (not mapped to closest — mapping would lie). Items without a recognized game entity → lifecycle/live_service NULL → excluded from Trends tabs.
- **WoW baseline strategy:** the existing 988-item corpus will be re-binned into ISO weeks by `published_at`, yielding ~4–8 weeks of synthetic history. No waiting on the Phase 4 APScheduler weekly cuts. Why: lets Trends launch with real deltas on first run; the 2026-05-11 Trends-deferral was contingent on having no multi-week corpus, and this strategy creates one retroactively.
- **Multi-week clustering:** re-cluster per ISO week, replacing the existing `week_id='all'` global clustering. Accept that some stories span week boundaries; small-in-practice issue.

### Synthesis scope vs PRD
- The Phase 3c synthesis prompt schema went from **PRD-locked 6 sections to 10 sections + an exec-summary pass.** Net-new beyond PRD: Esports/streaming, Release radar, Drama (narrow), Trends (returned). This is an explicit, eyes-open choice — PRD remains the contract, this is a deliberate expansion of it driven by the walkthrough finding that the corpus has signal in those four shapes that's worth surfacing.
- **Visual monotony flag:** the strip-out left 7–8 cards in a similar "row list of clusters" shape. Accept as price of honesty, or reintroduce real visual variation (sentiment chips, severity bars, date strips) in a later CSS pass. Not resolved this session.

### Still open
- Source Drawer layout details (right-panel width, animation, click-outside behavior, content density)
- Exec-summary modal layout (modal shows just the summary, or full report + summary?)
- Per-week clustering parameter tuning for smaller per-week corpora (the 0.85 threshold was tuned against `week_id='all'`)
- Cluster boundary-spanning de-duplication (story published Sun lands in week N, follow-ups Mon land in week N+1)
- Trends "top N" cutoff per tab (Top 5? Top 10? minimum delta threshold?)
- Empty-state designs for sparse tabs (Events especially)

**Rejected / reversed:**
- **Keep the 13-card grid as ported and just write synthesis to fill it** — would force synthesis to either fabricate platform sparklines (MM), heat numbers (Biggest signal cluster), Twitch metrics (Esports), or aggregate sentiment %s (CS), all of which the corpus can't honestly produce. The walkthrough's job was to remove fabrication risks before locking the prompt.
- **Defer Trends to a later phase as the 2026-05-11 decision locked** — superseded once the tagging foundation was scoped this session. The prior decision's blocking condition (no dimensional tags) is now being resolved as a prerequisite, so the deferral no longer applies.
- **Keep the sidebar nav as designed (Watchlist / Trends / Archive / All-stories visible as placeholders)** — placeholders lie about capability; cleaner to remove until the routes exist.
- **Keep the sidebar avatar block** — single-user personal app, no identity to surface; corpus stats are a higher-value use of that real estate.

---

## 2026-05-11 — Port claude.ai/design "Gaming Chatter" to `/reports` with locked variants (grid + comfortable + light + orange `#D9682B`)
**Decision:** Port the claude.ai/design React/JSX prototype as a self-contained `/reports` view in the project. Locked variants (no in-app toggles): **layout=grid**, **density=comfortable**, **mode=light**, **accent=`#D9682B`** (editorial amber — `ACCENT_OPTIONS[3]` in the bundle). All 13 card components from `cards.jsx` rendered in the default order with placeholder data taken verbatim from `data.jsx`. Standalone HTML doc — `reports.html` does NOT extend `base.html`, since the design has its own full-bleed sidebar+main shell. Existing pages (`/`, `/sources`, `/clusters`) untouched: legacy CSS preserved on top of `app.css`, new design styles namespaced under `.gc-*` with `:root` CSS variables. Lucide icon CDN kept; React/Babel runtime stripped (server-rendered only).
**Why:** The design is the spec for both synthesis output shape AND the rendered weekly report. Building the synthesis prompt before knowing the rendering target was throwaway work — markdown-loose vs structured-JSON output is a function of what the template needs. Porting with placeholder data first lets us walk the surface section-by-section, trim/rework, and only then write the synthesis prompt to emit exactly the JSON the trimmed template consumes. Locking the four variants up front avoids carrying dead variant code into production.
**Computed orange values:** `accentSoft = hexMix(#D9682B, #FFFFFF, 0.86) = #FAEAE1` (badges, soft fills, active backgrounds). `accentHover = hexMix(#D9682B, #000000, 0.35) = #8D441C`. The sidebar's purple literals in `shell.jsx` (`rgba(95,0,248,0.22)` active background + `inset 2px 0 0 #5F00F8` left-edge shadow) are **hard-coded, not theme refs** — find/replaced to the orange equivalents in the port.
**Implementation simplifications vs the React prototype:** Dropped drag-to-reorder (server-side card order is fine), Tweaks panel (variants are locked), header layout/density/theme switchers (kept as static buttons since variants are locked), exec-summary modal (not yet ported — walkthrough decision), SourceDrawer side panel (same). Sidebar nav items beyond "Weekly read-out" are `href="#"` visual placeholders pending walkthrough.
**Rejected:** (a) **Replace `base.html` globally with the design shell** — cascades into Dashboard/Sources/Clusters which are functional and not in scope for this design change; (b) **Port all three layouts (feed/grid/magazine) + density modes + light/dark with runtime toggles** — adds maintenance burden for variants the user explicitly locked; (c) **Wait for the user to write synthesis-output JSON spec first then build the template** — inverts the working-backward-from-deliverable principle; the design IS the spec; (d) **Use a CSS framework (Tailwind, etc.) for the port** — design uses inline-style/token approach which translates cleanly to namespaced CSS classes with CSS variables.

---

## 2026-05-11 — WoW-Trends section deferred from Phase 3c entirely; future scope = WoW only (drop MoM)
**Decision:** The "WoW/MoM Trends" section in the PRD's 7-section list is **excluded from Phase 3c synthesis** and from the trimmed `/reports` walkthrough decisions for now. When it eventually lands, it will be **WoW only** (week-over-week), not MoM. Phase 3c ships with 6 sections — Biggest Story / Hottest Games / Industry Risks / Market Momentum / Community Sentiment / Watch-List.
**Why:** The user clarified that real trend tracking, as they intend it, isn't a per-cluster count — it's coverage volume per topical dimension (hottest games existing vs upcoming, genre, platform, live-service flag, etc.) and the week-over-week delta. Current enrichment captures only `entities.{games, companies, people}`, the 7-value `category` enum, and sentiment. **None of platform, genre, lifecycle, or live-service is tagged.** Building the trends section as described requires either (a) extending the enrichment prompt to emit those fields and re-enriching the 908 corpus, or (b) a synthesis-time tagging pass that runs an LLM over each cluster to derive those dimensions. Both are real work. Plus, computing WoW deltas needs multi-week corpus — current corpus is `week_id='all'`, ingest began ~2026-05-07. Decoupling preserves Phase 3c shipping on the 6 sections that work today; trends becomes its own design pass once user provides the full layout spec.
**Rejected:** (a) **Stub the section with "first run — no historical baseline"** — wastes Anthropic context tokens on a placeholder; (b) **Compute trivial WoW counts from `items.published_at` grouped by ISO week** — produces meaningless data on a 1-week corpus and doesn't match the user's intent (per-topic coverage deltas, not raw item counts); (c) **Build it now without the per-topic tagging** — produces a section that says "RPG mentions: ?" which is worse than no section; (d) **Build trends as MoM only** — same multi-week problem, and user specifically said WoW only.

---

## 2026-05-11 — Phase 3c rubric + model locks: regulation-inclusive risks; Reddit-only hybrid sentiment; Opus 4.7
**Decision:** Three Phase-3c synthesis design choices locked before any prompt code was written.

1. **Industry-risks rubric — "standard" scope:** include layoffs/closures (studio shutdowns, layoff rounds, union actions) **plus regulation/legal/policy** (Stop Killing Games, age verification, EU/UK rulings, settlements). Exclude broader market structural shifts (acquisitions, fund raises, platform-side policy changes) — those live in Market Momentum to keep section boundaries clean. Exclude consumer-side pressures (price hikes, store changes) — overlap with Hottest Games / Market Momentum.

2. **Community-sentiment rubric — Reddit-only, hybrid:** the section consumes per-cluster `mean(enrichments.sentiment_score)` computed over members whose source is Reddit (filter on `source.url_or_handle` containing `reddit.com`) **plus 2–3 `sentiment_summary` excerpts** from the same Reddit-source members. Anthropic gets both the numeric anchor and the qualitative vibe. "Community" is community-surfaced reaction, not editorial framing — news-outlet and YouTube-creator items are excluded.

3. **Synthesis model — Opus 4.7** (`claude-opus-4-7`). Once-weekly run, ~$0.30/run, ~$15/yr total. Synthesis is the "thoughtful colleague's brief" user-facing deliverable per PRD; quality dominates cost at this volume. Use prompt caching on the system block (invariant across weeks) via the `claude-api` skill when the SDK call lands.

**Why:**
- **Risks scope (b) matches the corpus signal.** The top-ranked clusters from the 2026-05-08 cluster_window run that read as "risks" are layoffs/closures (Spiders studio closure, WotC union recognition deadline) + regulation/legal (Sony PlayStation Store settlement, Stop Killing Games petition). Take-Two/BioShock disappointment and the Griffin $100M indie fund — also in the top — don't read as risks; they're market/business stories. Broader scopes (c)/(d) would blur into Market Momentum.
- **Sentiment as Reddit-only + hybrid mean+vibe.** "Community" semantically reads as the community speaking, which means Reddit posts. Including news/YouTube would conflate editorial framing with reader/community reaction. The numeric mean gives Anthropic a calibration anchor ("reaction: −0.34") so the qualitative prose stays honest; the sentiment_summary excerpts give Anthropic narrative texture so the section doesn't read as "community: negative" boilerplate. Reddit-source member counts per cluster will be thin (most clusters have 1–2 Reddit members) — acceptable since the section is a pulse, not a primary content driver.
- **Opus 4.7 over Sonnet 4.6** — 6× cost ratio (~$0.30 vs ~$0.05/run) but absolute cost trivial at once-weekly cadence. Cost target is $1–5/month; even Opus 4.7 weekly stays well under. The synthesis output IS the user-facing product on Monday morning.

**Rejected:**
- **Risks scope (a) — layoffs only:** real signal in the corpus extends past layoffs (Stop Killing Games, regulatory settlements) — too narrow.
- **Risks scope (c)/(d) — include acquisitions/funds or consumer-side:** blurs section boundaries with Market Momentum and Hottest Games.
- **Community sentiment as numeric mean only:** loses the vibe; reads as "community: −0.34" which is unhelpful.
- **Community sentiment as all-source hybrid:** mixes editorial framing with community reaction; the section name says "community", not "general reception."
- **Sonnet 4.6 for synthesis:** the cost saving (~$13/yr) doesn't outweigh the quality risk on the user-facing deliverable; iteration on the prompt can happen on Sonnet anyway if needed before locking to Opus for production runs.

---

## 2026-05-08 — Phase 3b cluster ranking heuristic: `sources × members / (1 + days_since_latest)`
**Decision:** Each cluster is scored at persistence time as `score = source_count * member_count / (1 + days_since_latest)`, where `days_since_latest` is fractional days between `datetime.utcnow()` and the most recent `published_at` among member items. The score plus its two non-trivial inputs (`source_count`, `latest_published_at`) are persisted on the `clusters` row (idempotent SQLite migration in `_migrate_clusters_columns`). `GET /clusters` sorts by `score DESC NULLS LAST, member_count DESC`.
**Why:** Matches the "cross-source × signal × recency" intent from PRD without introducing tunables. The session-log guidance was "simple multiplicative weights (1×1×1), tune after seeing real data." `1 / (1 + days)` is the simplest plausible recency factor — no tau, no exp, no log-volume dampening — and on the 908-item corpus produced an editorially defensible ranking on first run: Mixtape (5×5, today) at 12.79, Griffin Gaming Partners $100M fund (4×5) at 10.02, Take-Two/BioShock (4×4) at 7.75, Star Fox 64 remake (4×4) at 6.76, Steam Controller restock (4×4, 1d old) at 5.97. All 14 single-source long-tail clusters (YongYea Metal Gear playthrough, VG247 Diablo 4 Warlock series, Fallout 4 walkthrough, Game Informer weekly picks, etc.) sank to the bottom with scores < 1.0 — the demotion the prior session called out as the goal.
**Trade-off accepted:** The recency penalty is steep — a 7-day-old story divides by 8. The Spiders studio-closure cluster (5 sources × 5 members, 7 days old) lands at #13 (score 2.73) despite having maximal cross-source breadth. For weekly windows in Phase 3c, day-0 vs day-7 will differ by 8×, which may be too sharp. Tuning is deferred until the first weekly synthesis run reveals whether end-of-week stories are visibly under-represented in the report.
**Rejected:** (a) **Exponential decay `exp(-days/tau)`** with tau=3 — smoother falloff but introduces a tunable that "simple multiplicative weights" guidance explicitly asked us not to start with; (b) **Log-dampened volume `log(1+members)`** — would prevent mega-clusters from dominating but at this corpus size no cluster has >5 members, so the dampening doesn't activate meaningfully; (c) **Upvote/comment weighting** on member items — Reddit RSS doesn't carry score data and YouTube RSS doesn't carry view counts at ingest time, so the weight has no signal to draw from; (d) **Recompute-only path** that updates scores on existing rows without re-labelling — adds a parallel code path for one-off use; the 186s cluster_window rerun is acceptable.

---

## 2026-05-07 — Phase 3 clustering: connected-components on cosine, threshold 0.85, min size 2
**Decision:** Cluster ok-enriched items by connected-components on a thresholded cosine-similarity graph over the fp32 768-dim embeddings of their TL;DRs. Settings (in `app/config.py`): `CLUSTER_THRESHOLD=0.85`, `CLUSTER_MIN_SIZE=2`, `CLUSTER_LABEL_SAMPLE=8`. Per-cluster labels generated by qwen2.5:7b via the new `label_cluster()` helper (JSON-mode, ~3s/cluster).
**Why:** Exploration on the 908-item corpus tried thresholds 0.55–0.88. Anything ≤0.78 produced a giant 200+ item "gaming-ness" blob via chain-merge (transitive similarity in connected-components). 0.82 still left a 35-item mixed-topic blob. **0.85 was the lowest threshold where the giant blob fully fragmented and every top-10 group passed editorial inspection** (Mixtape reviews × 5 sources, Spiders studio closure × 5 sources, Star Fox 64 remake × 4 sources, Steam Controller restock × 4 sources, etc.). 0.88 fragmented real cross-source stories down to 2-item pairs and increased misses. First production run: 63 clusters / 157 items / 17.3% of corpus clustered; remainder is singletons (intended — they get filtered out of the weekly report by the upcoming ranking heuristic).
**Trade-off accepted:** Some clusters are single-source long-tail series — VG247's Diablo 4 Warlock coverage (5 articles), YongYea's Metal Gear Solid V playthrough series (4 videos). Editorially these are real groups but not "weekly news stories." Will get deprioritized by the cross-source × signal × recency ranking heuristic in the next phase, no need to filter at clustering time.
**Rejected:** (a) **Centroid-greedy / iterative clustering** — order-dependent; only worth the complexity if connected-components chains-merged at every threshold, which it didn't above 0.82; (b) **HDBSCAN / agglomerative clustering** — adds sklearn as a dep against ARCHITECTURE.md's "numpy cosine similarity" line, and provides no measurable lift at this corpus size; (c) **Embed body instead of TL;DR** — TL;DR embeddings already cluster well, body embeddings would dilute thematic similarity with boilerplate; (d) **Filter single-source clusters at clustering time** — premature; ranking is the right place for that.

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
