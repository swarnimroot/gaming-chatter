# Decisions log

Append-only. Newest entries on top. Each entry: date, decision, rationale, alternatives rejected.

---

## 2026-06-15 — Daily scheduler hardened for Modern Standby; Windows Task Scheduler deferred (in-process cron fires on time)

**Context — the 2026-06-11 23:00 daily silently never ran.** The laptop is a Modern Standby (S0) machine: with the screen off, Windows suspends desktop apps (uvicorn included) even though classic "sleep" is disabled and the lid is open + plugged in. When the APScheduler thread resumed past 23:00, APScheduler's default `misfire_grace_time=1s` classified the job as misfired and discarded it. No run, no error row — just a missing daily.

**Decisions:**
1. **`misfire_grace_time=None` on the daily cron** (`app/main.py`) — run the daily no matter how late the scheduler thread resumes after a suspend.
2. **The cron now targets `run_daily_pipeline_scheduled`** (`app/services/jobs.py`), a guarded wrapper that **skips if a daily started <12h ago with status `running`/`ok`/`degraded`** (a recent `failed` does NOT block — the other path may retry that night). `max_instances=1` + `_JOB_LOCK` already prevent *concurrent* runs; this adds *same-day* dedup so a late misfire replay (or a re-enabled Task Scheduler poke) can't run a second full daily and double-spend.
3. **Windows Task Scheduler artifacts kept but DEFERRED/UNUSED.** `scripts/daily_trigger.xml` + `scripts/trigger_daily.ps1` (modeled on pulse-check's proven daily-collect pair) + endpoint `POST /runs/trigger-scheduled/daily` provide an OS-level fallback — Task Scheduler is exempt from Modern Standby app suspension, so it would fire even if uvicorn is suspended at 23:00. **Not enabled:** the in-process cron fired *exactly on time 3/3 nights* (06-12/13/14, `job_runs` ids 8/9/10, `started_at` 04:00:00 UTC = 23:00 CDT), so the OS poke is currently unnecessary; a one-off `Register-ScheduledTask` attempt also failed on XML encoding. Artifacts are left ready-to-enable: if the cron ever misses due to suspension, register the task (fill the `PLACEHOLDER_*` paths, `Register-ScheduledTask`); the endpoint routes through the same guarded entry, so the cron + the poke dedup against each other and cannot double-run.

**Verified:** 8 unit tests (`tests/test_scheduled_guard.py`: no-prior-run runs, recent run skips, outside-window runs, recent-failed retries, skipped-rows don't mask/block, other job_names ignored); 3 consecutive on-time scheduled dailies + the first chained metered weekly (`job_runs` id 11, 2026-W24, $0.48) in the DB.

**Alternatives rejected:**
- **Rely on the default misfire grace.** Rejected — it silently drops runs on this hardware (the 06-11 miss).
- **A separate always-on watchdog/scheduler process.** Rejected — violates the single-Python-process constraint; Task Scheduler (an OS service, not our process) is the sanctioned fallback if needed.
- **Disable Modern Standby / force the machine fully awake.** Rejected — out of scope, fragile, and the software fix is sufficient.

## 2026-06-15 — Reddit unauthenticated RSS limit dropped to 1 req/60s per IP → serialize reddit fetches with a 65s rate-gate

**Context — all 9 non-first subreddit feeds started 429'ing on 2026-06-13.** The nightly daily went `degraded` for 3 consecutive runs (06-13/14/15) with "ingest: 9 source(s) errored"; every Reddit feed except the first-fetched (r/Games) returned `HTTP 429 Too Many Requests`. The ingest path had **zero throttling** — `ingest_all` loops sources with no sleep, and `tier1.rss.fetch_rss_feed` does a bare `httpx.get` (scrapers-lib's `core.rate_limiter` is not wired into tier1). So all 10 reddit feeds fired in a ~3s burst (~3 req/s).

**Proven via a controlled live test (header capture), NOT inferred:** A single isolated request returns `x-ratelimit-used: 1 / x-ratelimit-remaining: 0.0 / x-ratelimit-reset: 59` — i.e. **the unauthenticated budget for all of `www.reddit.com` is 1 request per 60s per IP**, one shared bucket across every subreddit. Confirmed: (a) isolated request = 200, so it is NOT an IP block; (b) 6s spacing still 429'd 9/10 (only the request that crossed the 60s rollover succeeded); (c) a rapid burst = first 200, rest 429. The **"why now" is proven**: on 06-11 the same code fetched 10 feeds successfully in 8s, which is mathematically impossible under a 1-req/60s limit — so Reddit lowered the limit server-side between 06-11 and 06-13. Reddit sends `x-ratelimit-reset` (seconds), not `Retry-After`.

**Decision — serialize reddit.com fetches behind a process-wide 65s rate-gate + a single 429 backstop that honors `x-ratelimit-reset`, implemented in this project's `app/services/scrapers.py` wrapper.** `_is_reddit_url` host-matches reddit.com/*.reddit.com; `_reddit_rate_gate` (threading.Lock + monotonic clock) blocks until ≥65s (60s window + 5s margin) since the last reddit request; `_fetch_reddit_rss` gates proactively then, on a residual 429, sleeps `x-ratelimit-reset + 2s` and retries once. Non-reddit RSS and YouTube are unchanged. Consequence: ~10 min of (idle, no-CPU/$) wall-clock added to ingest for 10 subreddits — acceptable for an unattended 23:00 run. `/runs` "Ingest only" confirm text updated from "~1 min" to "~10 min". Verified: 8 unit tests (host match, gate spacing, 429 retry honoring reset, fallback, non-429 propagation) + a live end-to-end run (two reddit feeds via `fetch_source` → both 200, gate spaced them 65s, zero 429s).

**Alternatives rejected:**
- **Authenticate via Reddit OAuth/PRAW for a higher limit (100 QPM).** Rejected — the Reddit API application was rejected for this project (see OPEN_QUESTIONS); not available.
- **Wider spacing in `ingest_all` only (e.g. sleep between sources).** Rejected — gating at the `scrapers.py` host level is narrower and protects every caller (manual `ingest_only` included), not just the daily loop.
- **Reduce the subreddit count to fit the budget.** Rejected — user policy is no ingestion caps that drop coverage; reddit RSS rolls off in ~25 items so daily capture matters.
- **Modify scrapers-lib to wire its `core.rate_limiter`.** Rejected — scrapers-lib is an external dep we don't modify from this project.

## 2026-06-10 (Phase 4 — activation + safety) — confirmation dialogs on `/runs` trigger actions

**Decision — Add `hx-confirm` to the 7 `/runs` "Run now" trigger buttons only; deliberately exclude the eval writes and the exec-summary "Generate".** Each "Run now" button previously fired its job on a single click with no guard — an accidental tap could kick a multi-hour, API-spending pipeline. All **7 trigger buttons** now show a browser confirm dialog (HTMX-native `hx-confirm`, no JS build step) stating **what the job does, its realistic runtime, and whether it spends Anthropic $**. Implementation: `app/routers/runs.py` `_TRIGGER_MAP` tuples gained a 4th element (the confirm one-liner), threaded through the `trigger_jobs` template context (handler unpack → 4-tuple); `app/templates/runs.html` got `hx-confirm="{{ job.confirm }}"` on both button forms. Realistic times sourced from `job_runs` history + the user's operational knowledge (Daily 4–6h, Enrich+embed 3–5h, Ingest 10–20m, Cluster 5–15m, Synthesis 5–10m, Weekly 5–10m, Release refresh 2–5m), replacing earlier wrong "~few min" guesses. Two honesty fixes made while wiring: `cluster_only` *does* spend Anthropic $ (Sonnet labels for new clusters); `enrich_only`'s multi-hour cost is Whisper transcription via `enrich_pending → fetch_youtube_transcript`.

**Why these two are NOT confirmed:**
- **Exec-summary "Generate" — the cache-nag rationale.** It generates only on a cache miss (a fraction of a cent) and then caches forever; every subsequent open serves from cache for free. `hx-confirm` fires on every click and can't distinguish a cached open from an uncached one, so confirming it would nag the user on every free reopen. Left unconfirmed by design.
- **Eval scoring / note / missing writes — cheap, local-only, reversible.** These are save-on-change local DB writes (no LLM, no external $, trivially reversible). A modal per click would wreck the scoring flow for zero protective value.

**Verified:** 7 `hx-confirm` attrs render live on `/runs`; `runs.py` parses; `_TRIGGER_MAP` unpacks; all 7 jobs build with non-empty confirm text.

**Alternatives rejected:**
- **Confirm every user-triggerable control app-wide.** Rejected — over-broad; the eval flow and the free cached exec-summary reopen would become hostile to use.
- **A custom JS modal instead of `hx-confirm`.** Rejected — `hx-confirm` is HTMX-native and honors the no-JS-build-step constraint.

---

## 2026-06-10 (Phase 4 follow-up) — per-run cost meter: thread-local exclusive accumulator; per-model pricing + cache multipliers; $0-on-unknown-model

**Decision 1 — Cost accounting is a THREAD-LOCAL stack with EXCLUSIVE (innermost-only) semantics, not a global counter or lock.** New `app/services/cost.py`: `open_run(run_id)` pushes an accounting frame onto the calling thread's stack; `record(model, usage)` adds one Anthropic response's token usage to the INNERMOST open frame only; `close_run(run_id)` pops down to and including the matching frame, prices it, and returns the totals. Wired via `open_run()` in `jobs._start_run` and `close_run()` in `jobs._finish_run`; one `cost.record(model, message.usage)` line at all 9 Anthropic call sites (`anthropic.py`: `enrich_item` / `label_cluster` / `prescreen_yt_relevance` / `tag_game` / `tag_pcgamer_releases` / `tag_ign_releases` / `tag_region`; `exec_summary.py::_call_haiku`; `synthesis.py::_opus_once`). 3 nullable columns (`input_tokens`, `output_tokens`, `cost_usd`) added to `job_runs` via the idempotent `_migrate_job_runs_columns` ALTER pattern in `app/db/init.py`; `/runs` renders a Cost column (`$X.XXXX`, tokens in tooltip), `—` when NULL (pre-meter rows).

**Why exclusive (innermost-only):** `run_daily_pipeline` calls `run_weekly_extension` INLINE (Decision 1 of the automation-wiring entry below), and the weekly opens its own `JobRun` while the daily row is still running — nested execution, two separate rows. Attributing tokens to the innermost open frame puts the Opus synthesis spend on the WEEKLY row and keeps it OFF the daily row, so the two rows sum without double-counting.

**Why thread-local (not a global stack or lock):** each orchestrator and its inline nested weekly run execute in one thread, while a concurrently-blocked "skipped" run sits on another thread. A thread-local stack confines each thread's accounting to itself, so a skipped run on another thread can never steal the active run's tokens (a single global top-of-stack could). Because each stack is only ever touched by its owning thread, no lock is needed. `record()` is a no-op when the calling thread has no open run (manual backfill scripts go unmetered rather than erroring).

**Leak handling:** `close_run(run_id)` folds any never-closed inner frames (a crashed sub-run) into the matching frame rather than dropping them; it's called from `_finish_run` even if the row vanished, so no frame leaks forward into the next run.

**Decision 2 — Per-model pricing table + cache multipliers live in code; unknown models cost $0 with a warning.** `PRICING` (USD per MILLION tokens, standard non-batch list, June 2026): `claude-haiku-4-5` = $1/$5 (in/out), `claude-sonnet-4-6` = $3/$15, `claude-opus-4-7` = $4/$20. Cached input is billed at **0.1x** the input rate (cache read) and **1.25x** (cache write). A model id absent from the table (e.g. an env-overridden model) is priced at **$0 with a logged warning**.

**Why:** the three model ids match the locked LLM split (CLAUDE.md), so the table is small and static. Pricing $0 + warn on an unknown id is the honest fail-soft: the run never crashes over a missing rate, and the warning surfaces the gap to fix the table rather than silently inventing a number.

**Verified:** imports compile; the migration applies and is idempotent (columns present after two `init_db()` runs); the stack unit test passes — nested weekly = $4.00 (Opus only), daily = $2.00 (Haiku only, no double-count), cache pricing $0.10, no-op when no run open, unknown-model = $0.

**Alternatives rejected:**
- **Global counter / single top-of-stack.** Rejected — a concurrently-blocked skipped run on another thread would mis-attribute the active run's tokens; nested daily/weekly would double-count.
- **A lock around a shared stack.** Rejected — unnecessary once accounting is thread-confined; adds contention for no correctness gain.
- **Hard-fail on an unknown model id.** Rejected — would crash a live pipeline run over a pricing-table gap; $0 + warning is the honest fail-soft.

**Not done (NOT Claude's action):** a live `/runs` trigger to populate a real cost row (spends real API $) and scheduler activation (flip `SCHEDULER_ENABLED=1` + restart) remain the user's actions.

---

## 2026-06-10 (Phase 4 — automation wiring) — weekly chained off daily; 23:00 daily; no-tz-migration (Option A); no full-corpus backfills on nightly; region `""` sentinel; r/GamesIndustry removed

**Decision 1 — Daily cron moves to 23:00 local; weekly is CHAINED off the daily (no standalone weekly cron).** Daily moved **07:00 → 23:00 local (CST)** so the brief is ready in the morning. The standalone `Mon 07:30` weekly cron is **removed**; instead, at the end of each daily run, `_previous_week_needs_synthesis()` checks whether the previous ISO week is closed-but-unsynthesized and, if so, calls `run_weekly_extension(week_id=...)` inline (the `threading.RLock` is re-entrant). `run_weekly_extension` gained an optional `week_id` param. Startup-catchup was simplified accordingly: the weekly branch + `_is_weekly_overdue` + weekly constants were removed (the daily chain covers it). (`app/main.py`, `app/services/jobs.py`.)

**Why:** A separate weekly cron could fire before that night's ingest finished (long catch-up nights, Whisper backlog), synthesizing a half-ingested week. Chaining the weekly to the *end* of the daily makes ordering deterministic regardless of ingest duration, and self-heals a missed run (the next daily notices the previous week is still unsynthesized and runs it). One trigger, one lock, one ordering guarantee.

**Decision 2 — No timezone migration ("Option A"): keep UTC week definitions.** The user's laptop is **CST/CDT (Texas)**. 11 PM Central is already next-day UTC, and the UTC week rolls over ~Sunday 6–7 PM Central, so the Sunday-night 23:00 daily briefs the just-closed UTC week → ready Monday morning. We keep `iso_week_bounds` / `weekly_reports.week_start` on UTC.

**Why / alternatives rejected:** A full local-week migration was a moderate change touching **15 `iso_week_bounds` call sites** + **5 load-bearing exact-equality `weekly_reports.week_start` lookups**, plus a data-migration of existing week rows. The 23:00-Central timing already lands the brief on the right week without any of that risk, so the migration buys nothing the schedule doesn't already deliver. Rejected.

**Decision 3 — The nightly pipeline must NOT run full-corpus backfills; full backfills are manual-only.** Two scope fixes:
- **Region scope:** the daily's `backfill_region` step is scoped to items enriched *this run* (`Enrichment.created_at >= run_started AND region_focus IS NULL`), not the whole untagged corpus. The full-corpus pass stays available only as `scripts/backfill_region.py`. (`app/services/jobs.py`.)
- **`retry_failed` scope:** the daily's 2nd enrich pass (`enrich_after_fetch`) re-enriches ONLY the items that just got article bodies (`enrich_pending(item_ids=...)`), not the whole skipped backlog. `enrich_pending` gained an `item_ids` param (`app/services/enrich.py`); `fetch_skipped_bodies` returns `fetched_ids` (`app/services/article_fetch.py`).

**Why:** The old behavior was a **silent recurring cost leak**. Region backfill re-ran ~10,495 Haiku calls/night because most NULL-region rows legitimately *have* no region and stay NULL → re-billed every single night, forever. `retry_failed=True` re-scanned every non-ok item nightly and re-ran Whisper over the entire YouTube backlog (~55 min stall observed). Both are correct as one-time/manual operations and wrong as per-night work.

**Cost rationale (recorded here as the justification for Decision 3):** normalized typical-night cost ≈ **$0.30 (~$120/yr) WITH the fixes**, vs **~$1,500/yr WITHOUT** (the region re-billing alone). Paid steps: enrich (Haiku, incl. YouTube transcript→Whisper-audio fallback), region-tag (Haiku), cluster labels (Sonnet), weekly synthesis+critic (Opus ~$0.11). Embeddings are local/free.

**Decision 4 — Region "no region" sentinel is `""` (empty string), not `NULL`.** `scripts/backfill_region.py` now stores a no-region result as `""` so its own `region_focus IS NULL` selector won't re-process already-evaluated rows (the docstring's idempotency claim is now actually true). All consumers already treat `""` like NULL (dashboard `.ilike`, sections skip-if-falsy), so no read-path change was needed.

**Why:** `NULL` is ambiguous — "not yet evaluated" vs. "evaluated, no region." Splitting those (`NULL` = pending, `""` = evaluated-empty) makes the backfill genuinely idempotent and stops it re-billing rows that have already been judged region-less.

**Decision 5 — r/GamesIndustry removed (source + data).** Reddit served our scraper a frozen `.rss` (newest entry 2026-03-23; 0 new items since 2026-05-21) — public-RSS throttling, not a code bug; the source-health grid surfaced it as `silent` (every fetch ok, 0 items). Removed from `sources.yaml` AND purged from the DB (source id=24 + 13 items + 13 raw_items + 13 enrichments + 5 run_log rows, FK-ordered). **NOT** `GamesIndustry.biz` (news site, id=9) — that is KEPT. Corpus → 31 active sources.

**Why / forward note:** A feed that hasn't moved in ~11 weeks contributes nothing but a permanent `silent` flag. Reddit public-RSS feeds are a **structural risk** — other subreddits may freeze the same way; watch the source-health grid for the next one.

**Alternatives rejected:**
- **Keep the standalone weekly cron (Decision 1).** Rejected — non-deterministic ordering vs. the daily; can synthesize a half-ingested week.
- **Full local-week timezone migration (Decision 2).** Rejected — 15 + 5 call sites + data migration for zero gain over 23:00-Central.
- **Keep full-corpus region backfill on the nightly (Decision 3).** Rejected — the headline ~$1,500/yr leak.
- **Disable r/GamesIndustry (`enabled=False`) instead of removing (Decision 5).** Rejected — a permanently frozen feed adds only noise; clean removal is honest. (Reversible — re-add to `sources.yaml` if Reddit un-throttles.)

---

## 2026-06-09 (later) (Phase 4 — operator console) — Recency source-health SHIPPED; silent-window = 14d; synthesis retry policy

**Decision 1 — Recency-based source health + single-source-of-truth `failing_sources_count`: NOW IMPLEMENTED** (was Decision 3 / "APPROVED — NOT YET IMPLEMENTED" in the earlier 2026-06-09 entry). New `source_health(session)` in `app/services/chrome.py` returns one row per source, verdict driven by **RunLog recency** (latest ingest attempt outcome + items produced in a rolling window): `disabled` (`Source.enabled` False) / `error` (most recent ingest RunLog `status='error'`) / `silent` (ran during the window but produced **0 new items across the whole window** — the "feed fetches but extracts nothing" silent death) / `idle` (no ingest run within 30d — **not** flagged) / `ok`. `failing_sources_count` is **rewritten** to derive from `source_health` (counts verdicts `error` or `silent`), **replacing** the old cumulative `error_count > 3` rule (which never decayed → cried wolf on already-recovered sources). This is the **single source of truth** shared by the global alert banner (every page) AND the new `/runs` source-grid. Old `FAILING_SOURCE_ERROR_THRESHOLD = 3` constant + the now-unused `from sqlalchemy import func` import removed. Grid rendered as a sorted table (problems first) on `/runs` via a `verdict_chip` macro in `runs.html`, styled in `app.css` (reuses `.gc-table`; red/yellow left-border accents on error/silent rows). Verified live on `:8001`.

**Why:** Closes the operator-trust gap from the earlier entry's Decision 3 — `error_count` is cumulative and never decays, so a source that errored 4× last month but has ingested cleanly since still tripped `error_count > 3`. Recency self-heals on recovery and is the same signal the grid needs, so both consumers share one definition rather than drifting apart.

**Decision 2 — Silent-window = 14 days (not 7).** Constant `SOURCE_VOLUME_WINDOW_DAYS = 14` (public) in `chrome.py`; the `/runs` grid label is driven off it (passed as `source_window_days`), not hardcoded, so it can't drift. Grid keys renamed `items_7d`/`runs_7d` → `items_window`/`runs_window` to stay honest. Result: VG247 → `ok`; r/GamesIndustry remains `silent` (genuinely 0 items in 14d).

**Why:** The VG247 investigation (see SESSION_LOG 2026-06-09) showed VG247's feed URL (`https://www.vg247.com/feed`) is correct and returns valid RSS — the site (now an IGN brand) has simply slowed to ~weekly publishing, so "0 items in 7 days" was the **true state, not a bug**. A legitimately low-volume source shouldn't trip "silent" on a normal quiet stretch; 14d means only a sustained two-week drought trips it.

**Decision 3 — Synthesis retry policy: bounded 3-attempt transient-only retry, app-level cap authoritative, fail loudly.** `_call_opus` in `app/services/synthesis.py` refactored into `_opus_once` (single attempt) + a bounded-retry `_call_opus`. Up to **3 attempts on TRANSIENT failures only** (`anthropic.APIConnectionError`/timeouts, `APIStatusError` 429 or 5xx, one-off malformed/unparseable structured output → internal `_SynthRetryable`/`ValidationError`) with exponential backoff (2s, 4s); **non-retryable** errors (4xx bad-request/auth/etc.) fail on attempt 1. After the cap it raises `ValueError` → orchestrator marks the `JobRun` `failed` → surfaced on `/runs` for a manual "Synthesis only" re-run. `with_options(max_retries=0)` disables the SDK's own retry layer so the app cap is the **only** retry source (no stacking). Unit-tested (success-on-retry / exhaustion / fast-fail all pass).

**Why:** Synthesis is the one expensive all-or-nothing call (~37k tokens / ~$0.11 per `synthesize_week`; worst case ~3× ≈ $0.33 then stop). Don't loop and burn tokens — retry only on genuinely transient failures, cap hard, then surface for a human rather than silently retrying forever.

**Alternatives rejected:**
- **Silent-window 7d.** Too noisy — false-flagged VG247 on a normal quiet stretch.
- **Per-source expected-volume baselines for the silent check.** More work for marginal gain; deferred.
- **Let the SDK retry layer stack with the app cap.** Rejected — two retry sources multiply attempts and obscure the real cap; disabled SDK retries so the app policy is authoritative.
- **Retry synthesis on any error / unbounded.** Rejected — burns tokens on non-transient (4xx) failures that will never succeed; fail-fast + manual re-run is cheaper and honest.

---

## 2026-06-09 (Phase 4 — operator console) — Run status must be earned; reconcile interrupted runs on boot; per-source health to go recency-based

**Decision 1 — Run status is EARNED by meeting explicit expectations, not GRANTED by absence-of-exception.** A `JobRun` that finishes without raising but **under-delivers** is now downgraded `ok → degraded` via `_evaluate_floors()` + `_apply_floor_status()` in `app/services/jobs.py` (wired into `run_daily_pipeline` / `run_weekly_extension` / `run_release_refresh` / `run_ingest_only` / `run_enrich_only`). Floors: ingest `errors>0` OR `fetched==0`; enrich/embed/enrich-after-fetch `failed>0`; **any non-blocking step** (`article_fetch`, `backfill_region`, `release_refresh_pcgamer`/`ign`) that recorded an `error` key. `degraded` renders as a warning chip `.gc-table-chip--warn`.

**Why:** The old contract was "if no orchestrator step threw, the run is green." But several steps are deliberately non-blocking (an article-fetch or region-backfill failure must not abort the pipeline), so their errors were swallowed silently and the run still showed `ok`. That's a false-positive: the operator glance lies green while a step quietly failed. Tying status to explicit per-step floors makes green mean "delivered what it was supposed to," and surfaces partial failures as `degraded` rather than hiding them. `failed`/`skipped` pass through unchanged.

**Decision 2 — Reconcile interrupted runs on every boot.** `reconcile_interrupted_runs()` (in `app/services/jobs.py`) runs from the `app/main.py` lifespan immediately after `init_db()`, **always** (independent of `SCHEDULER_ENABLED`). It marks any `JobRun` still `status='running'` → `'failed'` + `finished_at` + message `"interrupted — process exited before completion (auto-reconciled)"`.

**Why:** This is a single-process app (FastAPI + scheduler + pipeline in one uvicorn process — see the hard architectural constraints). Therefore a `running` `JobRun` row observed at startup is **definitionally dead**: the only process that could have been advancing it is the one that just started. Leaving it `running` would make the new health band show a phantom in-flight job forever. Validated in the wild this session: a user-triggered daily pipeline was killed mid-run (uvicorn PID 17572 + reload worker), and its 2 `running` rows were correctly auto-reconciled on the next reload.

**Decision 3 (NOW IMPLEMENTED — see 2026-06-09 (later) below) — Per-source health goes recency-based, replacing `error_count > 3`.** Per-source health will be driven by **RunLog recency** — did the source produce items recently? — **replacing** the cumulative `error_count > 3` rule in `app/services/chrome.py::failing_sources_count`. One source of truth, shared by the global alert banner AND the new operator-console source-grid. *(Built later the same day — see the 2026-06-09 (later) entry for the as-shipped verdict taxonomy + 14-day window.)*

**Why:** `error_count` is a cumulative counter that **never decays**. A source that errored 4× last month but has ingested cleanly every day since still trips `error_count > 3` and cries wolf in the alert banner. Recency ("has this source produced items in the last N runs / days?") reflects *current* health, self-heals when a source recovers, and is the same signal the new source-grid needs — so both consumers should share it rather than the grid inventing a second definition.

**Alternatives rejected:**
- **Keep status = no-exception (Decision 1).** Rejected — silently green on partial failure is exactly the operator-trust bug this console exists to kill.
- **Add a third terminal state only for blocking steps (Decision 1).** Rejected — the whole point is that *non-blocking* step failures are the ones being hidden; they must be what trips `degraded`.
- **Reconcile only when the scheduler is enabled (Decision 2).** Rejected — interrupted rows can exist regardless of automation (manual one-shots, user-triggered runs); the single-process invariant holds either way, so reconcile unconditionally.
- **A grace window / timestamp heuristic before reconciling (Decision 2).** Rejected — unnecessary given the single-process invariant; the row is dead the moment a new process boots.
- **Let the source-grid keep its own `error_count` view (Decision 3).** Rejected — two definitions of "failing source" drift apart; the banner and the grid must agree.

---

## 2026-06-09 — Home read-out picker sources from synthesized weeks; `_report_grid.html` mojibake repaired

**Decision:** The weekly read-out (`/`) week picker now lists only weeks that have a **`synthesized` `weekly_reports` row** — via a new `readout_weeks(session)` in `app/services/reports.py`, wired into `app/routers/reports.py` in place of `available_weeks()`. The in-progress current ISO week (which has clusters from the daily pipeline but no weekly synthesis yet) is therefore hidden from the read-out until its weekly synthesis runs. `/stories` and `/eval` keep using `available_weeks()` (cluster-derived) — they intentionally show live current-week data.

**Why:** With ingest + daily clustering running mid-week, the current week (e.g. W24 / Jun 8–14) showed up in the read-out as a near-empty, unsynthesized brief and became the default selection. Synthesis is the weekly job, so its presence is the natural "this week is complete" signal — the user's framing: *"the synthesized report is only supposed to be done weekly; if it isn't created, don't show the week."*

**Rationale:**
- **Resolves the long-deferred picker-source flip.** The Phase 3c.5 walkthrough originally specced the picker off `weekly_reports`, but it was kept on `available_weeks()` until W17/W18 synthesis existed (see SESSION_LOG 2026-05-13 / 3c.8). All shown weeks are now synthesized, so the flip is finally correct — done as a *new* function rather than mutating `available_weeks()`, since that helper is shared by `/stories` + `/eval`.
- **No elapsed-date check needed.** Gating purely on `status='synthesized'` is simpler than an `end_date <= today` rule and matches the operational reality that synthesis only runs on closed weeks (weekly cron / manual previous-week runs).

**Also repaired:** `app/templates/_report_grid.html` had double/mixed-encoded **mojibake** baked into the file bytes (`→`, `—`, `·`, `●` all corrupted, e.g. rendered `â†'`), plus a stray BOM. Root cause was a bad save/encoding round-trip on that one file — the DB and every other template were clean. Fixed via surgical byte-level replacement (per-run cp1252 reverse for the clean cases + an explicit byte swap for a mixed-codec `●` that used the undefined cp1252 slot `0x8F`). Final file is valid UTF-8 with only correct `· — → ●`.

**Alternatives rejected:**
- **Mutate `available_weeks()` globally.** Would also hide the current week from `/stories` + `/eval`, where live current-week data is wanted.
- **Gate on `end_date <= today` (elapsed) instead of synthesized.** Rejected per user — would surface an elapsed-but-unsynthesized week as an empty brief.
- **Whole-file cp1252 re-decode for the mojibake.** Unsafe — the file mixes correct and corrupted non-ASCII, and one mojibake run used `0x8F` (undefined in cp1252), so a blanket reverse fails / corrupts the good chars. Per-pattern byte replacement was the safe path.

---

## 2026-05-27 — Precompute the dashboard payload at synthesis time (Phase 3c.35)

**Decision:** When `synthesize_week()` finishes persisting synthesis_json, it also computes + persists the default-region `/reports` payload to a new `weekly_reports.dashboard_payload_json TEXT` column. The `/` route reads the cached payload (~6ms) and applies a region filter in-process; only weeks without a cached payload fall through to live compute.

**Why:** At 7× corpus growth, the live `_build_week_payload` chain was taking 5–15s per click on synthesized weeks even after the Bucket 6 query-plan fix (which got it to 2.5–3.4s). The user's framing was "durable" — wanted a persisted artifact, not an in-process LRU. Precompute makes Monday-morning read-out clicks feel instant; the cache lives in the DB so an app restart doesn't lose it.

**Rationale:**

- **Durable beats in-memory.** Caches that don't survive restart get re-hit on every cold boot, which on a personal-local app means every time the user reboots the laptop. A real column on `weekly_reports` is durable and visible (you can `SELECT length(dashboard_payload_json) FROM weekly_reports` to debug).
- **At synthesis time, not on first read.** Synthesis already runs at known intervals (Monday + on-demand). Tying the precompute to the synthesis hook means the cache always exists when the page wants to render. First-read-builds-cache would mean the first Monday morning click pays the 2.5–3s compute cost, then subsequent clicks are fast — the worst user moment to pay the cost.
- **Default region only, in-process region filter for others.** The 4 region tabs all serve from the same cached payload via `_filter_cards_by_region()` (~6ms). Storing 4 payloads per week would 4× the disk cost for marginal speedup.
- **Current week (W22) deliberately not precomputed.** The current week is mid-ingest — its synthesis hasn't run yet, so there's no cached payload, so `/` falls through to live compute. Acceptable: the per-click cost on a still-growing week is the price for honest data. Revisit if live compute on the current week becomes visibly slow.

**Implementation surface:** new `app/services/dashboard.py` (extracted from `routers/reports.py`); new column via additive ALTER + idempotent `init_db()` migration; synthesis hook is wrapped in non-fatal try/except (a precompute crash must not block the synthesis commit); read path in `/` route logs a soft warning when payload missing and falls through to live compute. Backfill script `scripts/rebuild_dashboard_payloads.py` (`--force` flag) is idempotent for ops use.

**Alternatives rejected:**

- **In-process LRU on `_build_week_payload`.** Not durable; restart-cold; doesn't help if the laptop closes overnight.
- **Materialized view / second table.** SQLite materialized views are emulated; second table costs a JOIN on every read. Single TEXT column is the cleanest shape.
- **Compute all 4 regions and cache each.** 4× disk cost; `_filter_cards_by_region` is fast enough that storing only the default is the right tradeoff.
- **Pre-Phase-4 just-rebuild-on-Monday-cron.** Phase 4 isn't active yet; until it is, synthesis runs are manual. Hooking precompute to the synthesis call rather than a cron means the cache stays consistent with synthesis regardless of automation state.

**Honest caveats:**

- The precompute call captures the synthesis output as it existed at synthesis time. If `_build_week_payload`'s downstream queries (e.g., `top_games_for_week`, `trends_for_week`) start returning different numbers later because more items get ingested into the same week's bin, the cached payload will go stale. Mitigation: re-run synthesis (which re-computes the cache) or use `scripts/rebuild_dashboard_payloads.py --force`. Acceptable for weeks that are "done" (past their ISO window); current-week behavior is already live-compute by design.
- The synthesis hook silently swallows precompute errors via `log.exception` → continues. This is intentional (a busted precompute must not block a successful synthesis commit), but means a regression in `_build_week_payload` could silently degrade Monday clicks. Worth checking the logs if /reports starts feeling slow on a fresh synth.

---

## 2026-05-27 — Force query-plan via `INDEXED BY` on the per-week aggregates (Phase 3c.35)

**Decision:** `_build_week_payload`-adjacent queries in `app/services/reports.py` now carry explicit `INDEXED BY ix_items_published_at` hints to force items-first joins instead of letting SQLite's planner choose. Also added a stable `(delta_pp, name)` tiebreaker inside `_merge_wow` to deterministic-ize previously hash-seed-dependent set unions.

**Why:** At 7× corpus growth (1,023 → 6,958 items) SQLite's planner started choosing games-first joins, scanning ~7,000 enrichments per game on the WoW aggregates. End-to-end `_build_week_payload` regressed from sub-second to 25–33s per call. Pinning the plan to items-first restored linear-in-items behavior; observed end-to-end runtime 25–33s → 2.5–3.4s (~10× speedup).

**Rationale:**

- **Planner drift is a known SQLite gotcha at this scale.** When `ANALYZE` statistics get stale or the cardinality curves cross a threshold, the planner can flip between two physically-different join orders. The drift was bidirectional in our smoke runs (some queries flipped back to items-first under different sample sizes). `INDEXED BY` makes the decision explicit and stable.
- **Determinism matters for the cache + the eval harness.** Without the `(delta_pp, name)` tiebreaker in `_merge_wow`, the same input set could produce a different top-5 ordering across runs because `set() | set()` Python ordering depends on the hash seed. HTML byte-identical across before/after for W19 + W21; W20 had one tied-pair swap (Saros ↔ Star Fox 64 in `live_service.rising`) — now deterministic.

**Alternatives rejected:**

- **Add more indexes.** SQLite would still need to choose between them. The hint is cheaper.
- **Force the plan via subquery / CTE rewrite.** Works but harder to read; the `INDEXED BY` annotation sits inline with the FROM clause and is self-documenting.
- **`ANALYZE` cron.** Would help in steady-state but doesn't address the drift between planner runs on the same statistics. Plus we don't have a cron infrastructure for it yet (Phase 4 is inert).

**Honest caveats:** `INDEXED BY` is a SQLite-specific clause that errors out if the named index is dropped (intentional — fail loud rather than silently degrade). A future schema migration that renames `ix_items_published_at` would need to update these hints; flagged in `docs/OPEN_QUESTIONS.md` as a small future-maintenance item.

---

## 2026-05-27 — Phase 4 automation locked to single-process APScheduler with daily 07:00 / weekly Mon 07:30 / startup catch-up (Phase 3c.35)

**Decision:** Phase 4 automation, when activated via `SCHEDULER_ENABLED=1`, runs a single `BackgroundScheduler` inside the same uvicorn process. Daily pipeline at 07:00 local, weekly extension at Monday 07:30 local (chained after daily). Catch-up on startup: daily overdue if >24h since last `started_at` (or crashed mid-flight); weekly overdue if today is Mon/Tue/Wed AND >8 days since last weekly run. `max_instances=1`, `coalesce=True`. A single `threading.RLock` in `app/services/jobs.py` serializes all paths (cron-fired, /runs-Run-now, startup catch-up); lock-miss persists `status='skipped'`.

**Why:** Same-process scheduler is what the project's hard architectural constraints already lock in — no worker queue, no separate service, no Docker. APScheduler ships an in-process `BackgroundScheduler` that fits exactly. The 07:00 / 07:30 timing pair gives the daily ingest 30 minutes to land before the Monday-morning synthesis fires on top of fresh data. Catch-up on startup handles the "laptop was off all weekend" case without manual intervention.

**Rationale:**

- **Single-process is the locked stack.** No new architectural surface area. APScheduler is already a dep (`pyproject.toml`) — wiring it up doesn't add anything to the install footprint.
- **07:00 local daily / 07:30 Monday weekly chained.** Daily is small (incremental ingest + enrich + cluster). Weekly is large (synthesis). 30 minutes of buffer between them is enough headroom for the daily to complete on a normal Monday; if daily is still running when weekly fires, the lock holds weekly until daily finishes (then weekly fires immediately — `coalesce=True` consolidates the queued runs).
- **Catch-up windows 24h / 8 days.** Daily's 24h matches "we expect this to fire every day"; the >8 day weekly window allows one full skipped Monday and still catches up on Tuesday or Wednesday morning the next time the app boots. Mon/Tue/Wed gating on weekly catch-up prevents triggering a stale synthesis on, say, Friday evening when the user opens the app for a different reason.
- **`status='skipped'` for lock-miss, not error.** A skipped run is informational ("the system was already busy"); persisting it as `error` would noise up the `/runs` page.

**Implementation surface:**

- `JobRun` SQLModel + `job_runs` table — orchestrator-level. Distinct from the pre-existing `RunLog` / `run_log` which is per-step.
- `app/services/jobs.py` — `run_daily_pipeline` / `run_weekly_extension` / `run_release_refresh` / `run_startup_catchup` orchestrators; granular `run_ingest_only` / `run_enrich_only` / `run_cluster_only` / `run_synthesis_only` for the /runs Run-now panel.
- `app/routers/runs.py` + `runs.html` — `/runs` page surfacing `job_runs` history + Run-now panel + HTMX expand-row for `details_json`. **Not added to sidebar nav** (deliberate scope cut to avoid the `chrome.py` edit + nav-validator dance); direct URL only.
- `app/main.py` lifespan — env-gated; default off. Activates only when `SCHEDULER_ENABLED=1` is present in `.env`.
- 3 scripts (`backfill_region.py` / `refresh_pcgamer_releases.py` / `refresh_ign_releases.py`) refactored to expose a `run(...)` callable so orchestrators can invoke them in-process. CLI behavior unchanged.

**Alternatives rejected:**

- **Separate scheduler service / cron / systemd timer.** Splits the process model. Disallowed by the locked architecture.
- **Per-job lock (not single RLock).** Two cron jobs could collide if granular jobs (e.g., a manual "Run enrich only" from /runs) overlap with a scheduled daily. Single lock is the safe default.
- **Always-on, no env gate.** The user wants explicit activation. Inert-by-default means a `git pull` of this code doesn't surprise-trigger jobs.
- **Run synthesis directly from APScheduler without orchestrator wrapping.** Loses the `job_runs` audit trail. The orchestrator wrapper is what makes /runs informative.

**Honest caveats:**

- **API failure surface during weekly auto-run.** Already-known from Phase 3c.0.5 — per-item enrichment now requires Anthropic API + key + non-rate-limit state. A Monday-morning outage will halt the weekly run. The orchestrator catches and persists `status='error'` + `message`; the user finds out via `/runs` rather than email/Discord (push delivery is deferred to "Later"). Acceptable for personal-local; revisit if it bites.
- **Catch-up logic uses `started_at` not `finished_at`.** A crashed-mid-flight daily counts as "ran" for the 24h window. Right call for "did we attempt today?", wrong call if you want "did we successfully complete today?". The `JobRun.status` column lets a future enhancement distinguish if needed.
- **`/runs` is direct-URL-only.** Anyone who doesn't know the URL won't find the page. Acceptable for a personal-local single-user tool; flagged as Task #9 (cosmetic styling) + a future nav-add when chrome.py is touched anyway.

---

## 2026-05-27 — Coerce out-of-taxonomy `category` values rather than failing the enrichment (Phase 3c.35)

**Decision:** `app/services/ollama.py::EnrichmentData._coerce_category` is now a `field_validator(mode='before')` that maps Haiku's YT-flavored category emissions (`preview`/`guide`/`gameplay` → `news`, `interview` → `industry`) instead of raising `ValueError`. The dead post-parse `_ALLOWED_CATEGORIES` enum checks in `ollama.py` and `anthropic.py` (+ the now-unused import in `anthropic.py`) have been removed.

**Why:** The recurring hard-fail loss documented in `docs/OPEN_QUESTIONS.md` ("category enum too narrow") was bleeding 5+ items per full corpus run since Phase 3c.0.5 — Haiku reliably emits YT-content-type words for video items, and the strict enum was raising and persisting them as `status='failed'`. Coercion preserves the item, applies a reasonable mapping, and follows the same Pydantic-validator pattern that's already in production for `WatchItem.category` (Phase 3c.22).

**Rationale:**

- **Coercion has precedent.** `WatchItem.category` already coerces unrecognized values to `event`. Adopting the same pattern keeps the codebase consistent.
- **Mapping over default-bucket.** A `preview` is closer to `news` than to any other locked value; an `interview` is closer to `industry`. Defaulting everything unrecognized to `news` would over-broaden that category. The explicit mapping is editorial.
- **Removing dead enum checks now (not later).** The pre-validator catches everything; the post-parse `if val not in _ALLOWED_CATEGORIES` was now unreachable. Dead code in a validator path is the worst kind — it suggests defensiveness that doesn't actually defend.

**Alternatives rejected:**

- **Widen `_ALLOWED_CATEGORIES`** (option (a) from the OQ entry). Would broaden the taxonomy lock without an editorial reason to do so. Downstream code (e.g., the `/sentiment` GROUP BY, the Trends Events tab) would have to learn about more values.
- **Tighten the Haiku prompt to never emit those words.** Already tried via prompt engineering; Haiku still emits content-type-specific values for clearly-content-type-specific items. The prompt isn't the right lever.
- **Drop YT items that get content-type categories.** Defeats the purpose of YT being a source.

**Implementation surface:** `app/services/ollama.py::EnrichmentData._coerce_category` (mode='before' validator); removed `_ALLOWED_CATEGORIES` post-parse check in `ollama.py` and `anthropic.py`; removed the now-unused `_ALLOWED_CATEGORIES` import in `anthropic.py`. Re-ran the 5 historical failures (IDs 15, 626, 630, 921, 979) — all flipped to `status='ok'`.

**Honest caveats:** The coercion is a one-way information loss — once `preview` becomes `news`, downstream can't tell which items were originally `preview`. Acceptable today (we don't expose category in any UI surface in a way that would benefit from preview-vs-news disambiguation). If a future feature wants that distinction, it would need a separate `content_type` or `video_subtype` field, not a re-broadening of `category`.

---

## 2026-05-27 — No whisper-duration cap on YT audio transcription (Phase 3c.35)

**Decision:** The Phase 3c.34 OPEN_QUESTIONS proposal to gate whisper-CPU transcription on a video-duration threshold is **rejected**. All YT items continue to be whisper-transcribed in full regardless of duration. Pre-screen (Haiku gaming-relevance check) remains the only filter in front of whisper.

**Why:** User explicitly rejected the gate. Quote: *"don't want to put any whisper duration gate, that would mean less data ingestion and possibility of missing some data."* A 2-hour podcast episode that turns out to contain a 30-minute studio-shutdown discussion would be lost under a 60-minute cap; that's exactly the kind of signal the synthesis is meant to surface.

**Rationale:**

- **Honest-data preference holds.** Capping is a data-loss heuristic; the user's stated preference is "ingest everything, let synthesis decide what matters."
- **Wall-time cost is paid once, by an automation job.** Phase 4 daily 07:00 fires while the laptop is presumably idle; a 3hr rebuild is acceptable for the initial backfill (one-time) and individual long videos in steady state add ~10min each (rare on the current channel mix; not zero, but bounded).
- **Pre-screen already handles the obvious-waste case.** Non-gaming videos (movie trailers, AI-news) are filtered upstream by the Haiku pre-screen at ~$0.0005/call; whisper never runs on them. The remaining whisper cost is on actually-gaming videos, which is the cost you want to pay.

**Alternatives rejected:**

- **Skip videos over N minutes.** Bleeds signal.
- **Cap the audio actually transcribed (first N minutes).** Bleeds signal mid-video.
- **Feature-flag audio fallback off for sources flagged as long-form.** Same as the cap — bleeds signal.

**Honest caveats:**

- Long-form podcast channels added in the future will inflate whisper runtime linearly. If/when a single source becomes responsible for, say, 4+ hours of whisper per daily run, the math may need re-examining. Not blocking today.
- The Phase 4 scheduler's `max_instances=1` ensures a still-running daily ingest can't trigger a second one on top of itself. If daily ever exceeds 24h, the next day's run would be queued by `coalesce=True` and fire as one. Worst case observable today: a daily that runs ~3h once a quarter when a backlog of long videos catches up. Acceptable.

---

## 2026-05-27 — Path A (yt-dlp) + Path B (sitemap recipes) shipped in parallel, not sequenced (Phase 3c.35)

**Decision:** The Phase 3c.35 backfill for W19–W21 was executed with `scripts/backfill_youtube.py` (Path A) and `scripts/backfill_news.py` (Path B) run in parallel (overlapping wall-time), not sequentially. Both fed into the same enrich+cluster+synth pipeline after the items landed.

**Why:** The two paths share no contention surface (different scrapers, different per-source rate limits, different DB tables initially via `raw_items`, eventual common `items`/`enrichments`). Sequencing them would have doubled wall-time without quality benefit.

**Rationale:**

- **Independent scrape paths.** Path A talks to YouTube via yt-dlp; Path B talks to news sites via per-site sitemap recipes. No shared upstream.
- **DB contention is low.** Both write to `raw_items` and `items` with the existing `(source_id, mention_id)` dedup. SQLite's WAL mode handles parallel writers acceptably at this scale.
- **Enrichment serializes naturally downstream.** Both paths leave items in `status='pending'` enrichment state; a single `enrich_pending(...)` call drains both pools together — no need to gate by source.

**Implementation surface:** Two separate scripts, run in two terminal windows. Each persists its own progress log. The shared `enrich_pending` + clustering + synthesis pass ran once at the end, against the combined pool.

**Alternatives rejected:**

- **Sequential A → B.** ~2× wall-time.
- **One unified backfill script with a `--source-kind={yt|news}` flag.** Tried briefly; the per-site recipe state in Path B is too different from yt-dlp's channel-enumeration state to share a sensible code path. Two scripts is the right shape.
- **Skip Path A and rely on the existing daily Atom feed.** Atom caps at ~15 items per channel; W19 + W20 needed older items.

**Honest caveats:** Running in parallel made the SESSION_LOG harder to write linearly — events from both paths interleave in time. Acceptable cost.

---

## 2026-05-21 — Haiku pre-screen gates whisper-CPU on YT items (Phase 3c.34)

**Decision:** Before any YT item's transcript is fetched, run a cheap Haiku call on the item's title + Atom description to decide whether the video is gaming-relevant. Non-gaming videos (movie/TV trailers, AI-news, sponsored non-gaming content) are persisted `status='skipped'` with reason `yt prescreen: not gaming-related (<reason>)` and never reach the whisper-CPU transcript step.

**Implementation:**

- `prescreen_yt_relevance(title, description) -> YTPrescreenData` in `app/services/anthropic.py`. Haiku 4.5, cached system prompt, `max_tokens=256`. Returns `{relevant: bool, reason: str}`.
- `app/services/enrich.py::_body_for_enrichment` return shape changed from `(body, label)` to `(body, label, prescreen_skip_reason)`. For YT items it calls the pre-screen first; on rejection it returns `("", label, "yt prescreen: not gaming-related (...)")`.
- `enrich_pending` checks the third tuple element before the body-min gate and persists `status='skipped'` with the reason.
- Two production callers updated for the new tuple: `scripts/rerun_enrichment.py`, `scripts/sample_haiku_enrichment.py`.

**Why:**

Whisper-CPU transcription costs ~60–90s of local CPU per YT item (the only working transcript path — captions are POT-gated, see the companion entry below). A non-gaming video pays that full cost only to produce a TLDR that synthesis discards anyway. The pre-screen costs ~$0.0005 and ~1s per item and removes that waste. On the Phase 3c.34 rebuild it correctly rejected 4 of ~90 YT videos (2 movie trailers, 2 AI-news) — a modest hit rate, but the wall-time saved on a full-corpus rebuild is real and the dollar cost is negligible.

**Design choices:**

- **Haiku, not a regex heuristic.** A keyword/regex filter is free but ~70% accurate and brittle on cross-promotional / TV-crossover edge cases; Haiku is ~95% accurate and won't discard a niche-but-relevant video. $0.04 per full rebuild is below noise.
- **At enrich-time, not ingest-time.** Rejected items still get an `enrichments` row (`status='skipped'` + reason) — an audit trail. Filtering at ingest would mean rejected items never appear in the DB at all.
- **Fails open.** On any Haiku API error the pre-screen returns "treat as relevant" and the item proceeds to the transcript path — a transient API blip must not silently drop items.
- **Narrow criterion.** The prompt scopes "relevant" to video games / the games industry / gaming hardware / gaming culture / esports; it explicitly excludes movies, TV, music, sports, general tech. When the description is too thin to judge, it prefers `relevant=true` (analyze-and-discard beats miss).

**Alternatives rejected:** regex/keyword heuristic (accuracy); enrich-from-description-first then transcript-on-demand-if-low-confidence (doubles the Haiku call count, harder to get a clean signal from); ingest-time filtering (no audit trail).

**Honest caveat:** the pre-screen judges from the Atom description, which YouTube channels write with varying care. A misleadingly-titled gaming video with a sparse description could be wrongly rejected — mitigated by the fail-toward-relevant tie-break, but not eliminated. Worth spot-checking `status='skipped'` rows with `yt prescreen:` reasons periodically.

---

## 2026-05-21 — YT transcripts already wired at enrich-time via whisper-CPU audio fallback (Phase 3c.34)

**Decision (clarification, not a code change):** Phase 3c.34's verification confirmed that `app/services/enrich.py::_body_for_enrichment` (lines 38–44) already calls `fetch_youtube_transcript(vid, audio_fallback=True)` on every YT item at enrich-time, and uses that transcript as the body passed to Haiku. The TLDR signal for YT items in the existing corpus is transcript-derived, not description-derived. The Phase 3c.33 SESSION_LOG note "No YT transcript-fetching yet" was stale/incorrect — the code has been doing this since at least Phase 3c.14 (when the `[youtube-audio]` extras were added). No code change in 3c.34; this entry corrects the documentation drift.

**Empirical reach (probe 2026-05-21 on 12 post-fix YT items, 2 per channel):**

- **Captions-only path (`audio_fallback=False`): 0 / 12 returned non-empty.** YouTube's caption endpoint is now 100% POT-gated for our environment. The free / fast path no longer works.
- **Audio-fallback path (`audio_fallback=True`, whisper-CPU): 4 / 5 sampled produced usable transcripts before the 10-min probe timeout cut off.** The 1 failure was a trailer with no spoken content (10-char transcript = "PEGI 7 you" → fell below `ENRICH_BODY_CHAR_MIN=200` → correctly `status=skipped`).
- **Wall time per item (whisper-CPU):**
  - Short trailers: ~15–20s
  - Short reviews / shorts (~3 min video): ~10s
  - Long reviews (~10 min video): ~95s
  - Long-form podcasts (~1 hour video): ~620s (~10 min)
  - Estimated median across mixed feed: 60–90s
- **Transcript length distribution (audio-fallback path):** 10 / 1,122 / 741 / 10,061 / 61,281 chars in the 5 items that completed before the probe timed out.

**Why this matters for the corpus wipe:**

A full re-ingest of all 6 YT channels (~15 items each = ~90 items per cycle) at median ~60–90s whisper-CPU each = roughly **1.5–2.5 hours of local CPU** just for YT transcripts in the post-wipe rebuild. Acceptable for a one-time rebuild; would block APScheduler's hourly cycle if it landed in the middle of one. Hourly steady-state cost is lower because the per-source dedup key `(source_id, mention_id)` keeps re-ingest count down to whatever's actually new each hour (typically 0–3 items).

**Alternatives rejected:**

- **Persist transcripts to `items.body_text` at ingest-time** (the Phase 3d parking-note design). Cleaner architecturally — would make enrichment idempotent on re-run instead of paying whisper cost every time `_body_for_enrichment` is called. Deferred to a future phase. The current enrich-time fetch is not idempotent across re-enriches, but in practice enrich runs once per item and the result is durable in `enrichments.tldr`, so the re-run cost is a hypothetical we don't pay.
- **Cache transcripts locally between runs.** Same effect as the previous bullet via a different mechanism (separate transcript-cache table). Same deferral.
- **Drop audio fallback and accept that YT only contributes when the rare item has captions.** Would silently drop ~all YT signal under current POT-gating. Defeats the purpose of YT sources.

**Honest caveats:**

- `_body_for_enrichment` calls `audio_fallback=True` *every time* it's invoked for a YT item. If the same item is re-enriched (e.g., via `enrich_pending(force=True)` or `retry_failed=True`), whisper-CPU runs again. Mitigation today: don't re-enrich YT items casually. Real fix: ingest-time persistence (deferred).
- Whisper-CPU output quality depends on local audio decoding — speech-to-text accuracy on heavily-edited gameplay audio or low-quality podcast captures could mangle proper nouns (game titles, dev studio names). Spot-checked TLDRs from the existing post-fix cohort look clean (specific game titles correct: "Borderlands", "DoW IV", "Zoum", "Disco Elysium", "Olivia in Lone Echo", "Jack Baker in Resident Evil 7"), so quality is acceptable in practice. Worth re-checking after a few weeks of steady-state data.
- The 1 long-form podcast item (Game Informer, 1hr+ video) took ~10 min of whisper-CPU on its own. If a YT channel pivots heavily toward podcasts, the wall-time math degrades. Currently most of the 6 channels publish short-form content (reviews / news shorts / trailers).
- Captions may un-gate in the future if YouTube changes its POT enforcement. The captions-first path in `tier1.youtube.fetch_youtube_transcript` continues to try captions before falling back to audio — no code change needed if/when that happens.

---

## 2026-05-21 — YouTube channels stored as hardcoded Atom feed URLs (not @handles) (Phase 3c.33)

**Decision:** YT sources in `sources.yaml` store the full Atom feed URL (`https://www.youtube.com/feeds/videos.xml?channel_id=UC…`), not the `@handle`. `resolve_youtube_feed`'s existing `"feeds/videos.xml" in handle_or_url` pass-through (`app/services/scrapers.py:32`) short-circuits the regex-based HTML scrape entirely. Adding a new YT source now requires a one-time channel_id lookup; the manual procedure is documented below.

**Why:**

The previous approach scraped `https://www.youtube.com/@Name` HTML and matched `_CHANNEL_ID_RE = r'"channelId":"(UC[\w-]+)"'` (primary) then `_CHANNEL_PATH_RE = r"channel/(UC[\w-]+)"` (fallback) against the page bytes. Two compounding problems made this silently unreliable:

1. **YouTube removed `"channelId":"UC..."` from @-handle page HTML** at some point between 2026-05-07 (initial verification) and 2026-05-21 (today's failure). Re-probing each @-handle page returned **zero** matches for the primary regex. Fall-through hit `_CHANNEL_PATH_RE`.
2. **The fallback regex picks the *first* `/channel/UC…` URL anywhere in the 2.3 MB page**, not specifically the canonical channel link. On modern YouTube that first occurrence is often a recommended-channel sidebar entry, not the @handle's own canonical channel.

Verified 2026-05-21: of the 6 YT sources, only @IGN's resolved channel_id matched its current canonical (lucky — IGN's canonical link happens to be the first `/channel/UC…` URL in its page). The other 5 (@GameSpot / @gameinformer / @YongYea / @PCGamer / @GameranxTV) all resolved to *different real channels* — we'd been silently ingesting videos from unrelated channels under those publisher labels for an unknown number of weeks (the regression landed when YouTube last reshuffled the @handle page HTML, presumably between 2026-05-07 and 2026-05-21).

**Alternatives rejected:**

- **Patch the regex to prefer `<link rel="canonical" href="https://www.youtube.com/channel/UC…">`.** Would have worked today, but the underlying brittleness — depending on YouTube's HTML layout staying stable — remains. The canonical-link pattern is more durable than the existing regexes but still failable on the next YouTube reshuffle.
- **Add yt-dlp as a dep for `--print id @handle`.** Robust mechanically, but adds a heavyweight subprocess + dep we don't otherwise need (yt-dlp is already pulled in via the `[youtube-audio]` extra from Phase 3c.14, but invoking it as a subprocess for ID resolution is a different code path from the import-time usage in `tier1.youtube`).
- **Use the YouTube Data API (`channels.list?forHandle=`).** Authoritative + permanent, but requires API key + quota awareness, which punctures the "no credentials" stance.
- **LLM call (Haiku) to resolve `@handle → channel_id` with verification step.** Works as a one-time lookup helper for new sources but doesn't address the existing wrong-channel data, and risks hallucinated IDs without verification. Defer if/when frictionless source-adding becomes a recurring goal.
- **Drop YouTube entirely.** Loses 6 source feeds and the cross-source YT/Reddit/RSS clustering coverage they'd contribute.

The hardcode approach trades a 30-second one-time channel_id lookup per new YT source for elimination of an entire silent-failure class. Channel IDs are YouTube's permanent primary key (handles are mutable nicknames per YouTube's own docs). Remaining failure modes that could invalidate a stored ID: channel deletion, channel suspension, ownership transfer (Game Informer's 2024 GameStop-to-new-owner transfer did NOT change the channel_id; verified 2026-05-21). All of these would surface immediately as empty feeds — operationally rarer than the silent wrong-channel resolution we just eliminated.

**Implementation:**

- `sources.yaml` — 6 YT entries' `handle:` field changed from `@Name` to the full feed URL. Header comment updated. Block-level comment above the YT section explains the rationale for future maintainers.
- DB `sources` table — direct UPDATE on rows 25-30 to set `url_or_handle` to the full feed URLs + clear `last_error` / reset `error_count`. The seeder (`app/utils/yaml_loader.py`) is insert-only on `(type, url_or_handle)` — it doesn't reconcile existing rows when the yaml changes, so the DB had to be updated separately.
- No code change to `app/services/scrapers.py` — the `"feeds/videos.xml" in handle_or_url: return handle_or_url` pass-through at line 32 handles this case as-is.

**Manual verification procedure** (carry forward when adding new YT sources):

For each `@handle`, fetch `https://www.youtube.com/@Name`, extract the canonical channel ID from `<link rel="canonical" href="https://www.youtube.com/channel/UC...">`, then fetch that channel's Atom feed and confirm the `<title>` matches the expected publisher name. Bare-minimum manual procedure; could be formalized into a small helper script if YT source additions become frequent.

**Honest caveats:**

- Wrong-channel items already in the corpus (sources 26-30, ingested between roughly mid-May and 2026-05-21) are not cleaned up by this decision. Slated for the corpus wipe in the next session (Phase 3c.34), gated on a 4-step verification that the YT ingest + enrich + synth end-to-end chain works as intended with the corrected URLs.
- Channel IDs are permanent on YouTube's side but not immune to operational events (deletion, suspension, rebrand→new channel). Defensive habit: re-verify every few months by fetching each Atom feed and confirming `<title>` still matches expectations. Drift is loud (empty feed or wrong publisher name), not silent.
- Adding a 7th YT source now requires a manual channel_id lookup. Acceptable friction given the failure class this eliminates. A future LLM-with-verification helper could automate the lookup if the friction starts mattering.

---

## 2026-05-20 — Eval scores feed back into the critic prompt (Phase 3c.30)

**Decision:** When `synthesize_week()` runs its Pass 2 (critic), prepend a `=== PAST HUMAN CONCERNS ===` block to the critic's user message. The block is built from recurring (card, dim) failure patterns in `eval_card_scores` over the last 4 weeks. The same block is rendered on `/eval` in a collapsible `<details>` panel for transparency — what the user sees is what the critic gets.

**Why the reversal of the earlier "I'd avoid feeding eval back to synthesis" recommendation** (made earlier the same session, before the user pushed back):

The "avoid" cited Goodhart's Law — when a measure becomes a target, it ceases to be a good measure. On reflection, Goodhart bites when a *proxy* diverges from the true objective. In this setup the eval IS the objective: single user, in-context (no fine-tuning), user re-scores fresh content each week. The closed loop is healthy — if Opus games one dim, the other two suffer and the user marks them down. No benchmark to overfit to; no proxy to diverge from.

**Design choices:**

- **Inject into the critic prompt, not the synthesis prompt.** Synthesis = generate from corpus, keep it focused. Critic = quality enforcement; past human-flagged concerns belong there alongside the existing static rules.
- **Recent window — last 4 weeks only.** Stale taste shouldn't compound forever. Year-rollover handled by treating each year as 52 weeks (W53 years lose at most one week of lookback — acceptable for a heuristic).
- **Threshold — only patterns with ≥2 fails/concerns on the same (card, dim).** Single fails are noise; ≥2 is a real recurring concern.
- **Include the note text verbatim**, tagged with the week_id (up to 3 example notes per pattern). The *why* teaches more than the score — "recap repeated the headline" lands, "B=fail" doesn't.
- **`na` and `pass` ignored** — empty cards aren't feedback; pass carries no actionable signal.
- **Transparency on `/eval`** — collapsible `<details>` renders the exact same block the critic will see. User stays calibrated; no black-box loop.

**Implementation files:**

- `app/services/eval_feedback.py` (new, ~110 lines): `gather_recent_failures()` + `format_critic_block()`.
- `app/services/synthesis.py:629–645` — Pass 2 prepends `past_concerns` to the existing `critic_user`. Lazy-imports `eval_feedback` to keep cycles loose.
- `app/routers/eval.py` — computes the same block per request; passes `feedback_block` + `feedback_count` to the template.
- `app/templates/eval.html` — `{% if feedback_block %}<details class="gc-eval-feedback">...` at the top of `.gc-eval-form-wrap`.

**Cost:** ~$0.01–0.02 extra per critic run. At most ~10 patterns × 3 notes × ~30 tokens ≈ 900 tokens prepended. Negligible vs the ~$0.30/week baseline.

**Kill-switch:** if 4 weeks in the per-week aggregate pass-rate hasn't climbed, the loop isn't helping — remove the prepend in `synthesis.py` and the panel in `eval.html`. The eval scoring data itself stays untouched (always re-derivable).

**Risks accepted (smaller than the original "avoid" implied):**

1. **Over-correction.** Opus reads "factuality concerns on biggest" → hedges every claim → Brevity drops. Caught in aggregate within a week.
2. **Style monoculture.** Opus internalizes the user's voice. For a *personal* tool, that's the goal, not a bug.
3. **Confirmation bias on the user's side.** They may score more leniently knowing Opus "tried to fix" what they flagged. Mitigated only by the transparency panel — user can see exactly what the critic was told.
4. **Contradictory notes across weeks.** Each note carries its `week_id`, so Opus weighs context, not abstract rules.

**Future trigger to revisit:** if the per-week aggregate pass-rate plateaus or contradicts the notes, kill the prepend and reassess. Per the kill-switch above.

---

## 2026-05-20 — Synthesis eval harness — in-app `/eval` form (Phase 3c.25)

**Decision:** Score synthesis quality through a new `/eval` page in the dashboard. Two new SQLite tables (`eval_card_scores`, `eval_meta`) persist scores; the page reuses the weekly `_report_grid.html` partial on the left and a sticky HTMX form on the right — save-on-change radios for F/S/B per card, per-card note, free-text Missing textarea, live aggregate footer.

**Why the reversal (same day as the markdown decision below):**
- Editor↔browser context-switching friction undervalued in the morning's markdown call. The Pass/Concern/Fail glyphs (`✓ ~ ✗`) aren't keyboard-accessible — every cell would need copy-paste from a reference or remembering markdown table syntax. Friction in a discretionary-effort workflow → workflow gets abandoned.
- HTMX + Jinja stack was already in place; marginal cost of one more route was ~90 min, not a green-field build.
- Save-on-change UX gives instant per-cell persistence; markdown required remembering to save the editor file.

**Implementation:**
- `_report_grid.html` extracted from `reports.html` (no behavioral change to `/`) so both `/` and `/eval` can include it.
- `EvalCardScore(week_id, card)` + `EvalMeta(week_id)` SQLModels. Composite PK on EvalCardScore — one row per (week, card) holds `f_score`, `s_score`, `b_score`, `note`.
- POST `/eval/score` returns the re-rendered aggregate fragment for HTMX swap; POST `/eval/note` and `/eval/missing` return 204 (fire-and-forget).
- Nav: new "Eval" item between Sources and About in `NAV_ITEMS_BASE` (`clipboard-check` lucide icon).
- Rubric / glyphs / 3-point scale unchanged from the superseded entry below — only the substrate changed.

**Markdown skeletons** at `evals/W{17–20}.md` archived to `evals/.archive/` (not deleted, in case a future export path needs them).

**Revisit when:** 8+ weeks scored AND aggregate becomes hard to eyeball → add a trend view that reads from `eval_card_scores`. Until then, the per-week aggregate footer is enough.

---

## 2026-05-20 — Synthesis eval harness — markdown over in-app form [SUPERSEDED]

**STATUS:** Superseded by the in-app `/eval` entry above, decided same day after surfacing UX friction in walkthrough planning.

**Decision:** Score synthesis quality by hand using per-week markdown templates in `evals/W{nn}.md`. Defer in-app form / `eval_scores` table / aggregation script.

**Why:**
- 4 weekly reports in corpus (W17–W20) → no aggregation pain to solve yet
- Single user; no UX requirement to share scores
- Critic pass already enforces factuality of cluster_ids, entity names, marketing-verb prose. Human eval is for what the critic could miss — subtle attribution chains, signal vs filler, padding the critic missed
- Markdown lets `grep "✗" evals/*.md` surface repeat failures → prompt-fix candidates

**Rubric:** 3 dimensions per card (Factuality / Signal / Brevity), 3-point scale (✓ pass / ~ concern / ✗ fail). Plus one free-text "Missing" field per week. Coverage/recall deliberately under-scored.

**Revisit when:** ≥8 weeks scored AND a pattern emerges that wants trend lines → consider `scripts/eval_aggregate.py` (~30 LOC) or in-app form (3–4 hrs).

---

## 2026-05-20 (Phase 3c.24) — Region-tab spinner alignment + IGN as second `game_releases` source + Release Radar dual-link

**Scope:** Three items in one session. (a) Region-tab spinner on `/` was visually extruding past the pill — structural fix via a wrapper, not a positioning tweak. (b) IGN release-date ingestion shipped as the second `game_releases` source (carry-over from 3c.18); pcgamer remains primary via the already-locked `SOURCE_PRIORITY`. (c) Release Radar card on `/` exposes both PCGamer + IGN calendar URLs as stacked ghost links. Changes land in `app/templates/reports.html`, `app/static/app.css`, `app/services/anthropic.py`, `app/db/models.py` (docstring only), and a new `scripts/refresh_ign_releases.py`. Total spend ~$0.08 (IGN Haiku passes only). See SESSION_LOG.md 2026-05-20 (Phase 3c.24) for the full file-by-file shape.

**Locked decisions:**

- **Region-tab spinner placed outside the pill nav, not inside.** Wrap the `<nav class="gc-region-tabs">` + spinner `<span>` in a new sibling-grouping `<div class="gc-region-tabs-row">` (inline-flex, gap 10px, align-items center, carries the bottom margin). Rationale: the prior layout had the spinner as a 5th flex child of the nav with `margin-left: 10px`, which made `inline-flex` silently extend the pill background around the spinner — but with no padding, no per-cell divider, and a circular spinner shape, it visually read as an "extrusion past Asia" rather than a contained element. Lifting the spinner out makes the pill width a pure function of `N` tabs — adding a future region tab (Oceania / India / etc.) just widens the pill, spinner placement stays untouched. Spinner is `opacity:0` (not `display:none`), so its 14px slot is always reserved → no layout shift on click. Rejected: absolutely-positioning the spinner with `position: absolute; right: -24px` (magic numbers; brittle to font/zoom changes); adding `padding-right` + a divider inside the pill to "frame" the spinner (still leaves the visual anomaly when the pill grows on tab-add; doesn't decouple width from spinner); a different indicator UX entirely (spinner on the active tab text → button click feedback) — would have been correct but bigger blast radius than warranted by the bug.

- **IGN preprocessor strips `TBA/<year>` entries before Haiku.** `_strip_tba_year_lines(body)` matches `^\s*TBA\s*[/ ]\s*\d{4}\s*$` and also pops the immediately-preceding name line (IGN's body extract renders name+date on consecutive lines). On the smoke run, 953 of ~1,250 entries matched. Rationale: without this, Haiku's 8K output cap would truncate (~1,250 entries × ~22 tokens each = ~27K output tokens — over 3× the budget). The TBA/year entries carry no actionable signal beyond the year alone — `derive_lifecycle(release_date, today)` returns `'upcoming'` for any future-year date and `None` for an in-progress current-year placeholder, which is the same outcome as having no row at all for those games. Dropping them costs nothing useful and saves ~3× the cost. Rejected: bumping `max_tokens` to 32K (Haiku 4.5 supports it but the cost would scale ~3×; uses more cache space; and the TBA entries genuinely add no signal); chunking the body at month boundaries with N Haiku calls (more LOC + multi-call orchestration for the same outcome); keeping `TBA/<year>` and emitting it to Haiku as `"<year>"` (would have produced 953 noise rows in `game_releases` for games we likely don't care about).

- **Reuse `PCGamerReleaseList` schema for IGN; don't rename to a generic name.** The {name, release_date} Pydantic shape is fully generic and the validators handle the IGN-format inputs unchanged. `tag_ign_releases(body_text)` reuses the schema as-is; function name provides log-grep separation between the two sources. Rationale: renaming the schema to `ReleaseEntryList` (or similar) would touch the existing pcgamer code path for zero behavior gain, and risks a silent break on a frozen pattern. The pcgamer-flavored class name is a cosmetic quibble; the IGN function's return type annotation reads `list[PCGamerRelease]` which is slightly awkward but pragmatic. Rejected: rename + backward-compat alias (more code for no functional benefit); fork to `IGNRelease` / `IGNReleaseList` (~30 LOC of duplication for zero behavioral difference).

- **PCGamer remains primary in `SOURCE_PRIORITY = ["pcgamer", "ign"]`; no flip considered.** Rationale: pcgamer's `/games/new-pc-games-2026/` is an editor-curated calendar — longer-form, fewer entries (~286), higher signal per entry. IGN's `/upcoming/games` is a higher-volume crowd-sourced calendar dominated by long-tail indie titles. On the 29-game May overlap the dates agree, so the priority is moot for current data; but for future conflicts we have no reason to prefer IGN. Rejected: flipping order (would silently push IGN-curated dates over the editorially-curated pcgamer ones); first-write-wins (would create non-deterministic priority based on refresh ordering).

- **Release Radar card dual-link uses an inline `<div style="…">` flex column, not a new CSS class.** Two-link case = the smallest possible UI change for a card-header action; introducing a new `.gc-card-action-stack` class would be premature abstraction for a single use site. Rationale: per CLAUDE.md's "no half-finished abstractions" rule — three similar lines is better than a class that exists for one caller. If a future card wants a stacked-link header action, extract then. Rejected: new `.gc-card-action-stack` class with `display: flex; flex-direction: column; align-items: flex-end; gap: 4px` (cleaner CSS-wise but premature); `<br>` between the two `<a>` (no vertical-rhythm control, no alignment override).

**Implementation notes (for future readers):**
- `app/db/models.py:74` `GameRelease` docstring updated from "current sources: 'pcgamer'. IGN deferred." to "current sources: 'pcgamer' (3c.18) + 'ign' (3c.24)." `models.py:84` source-comment line `# 'pcgamer' | 'ign'` was already correct since 3c.18.
- The IGN `--keep-tba` CLI flag is intentionally surfaced even though the default is to strip — gives a one-flag escape hatch if a future refresh ever needs to capture TBA/year entries (e.g. for an audit-only run).
- The `_existing_by_name(session)` helper in the IGN script intentionally filters `source == SOURCE` (i.e. `'ign'`). This means the IGN script only diffs against IGN rows, never against pcgamer rows — which is correct (the priority resolution happens at read time via `release_date_for()`, not at write time).
- One-off observation worth recording: the IGN smoke-run probe of the `_check.py` verification script returned 29-game overlap between sources. Initial dry-run reported 33 in the same SQL, then 29 on re-query — both queries identical. Most likely a session-cache or refresh-ordering fluke; both are valid snapshots of the same underlying data. Not worth chasing.
- The doc-sweep subagent hit 3 consecutive `529 Overloaded` errors when spawned during this session; doc updates were authored in-main-context instead. Pattern is worth noting because the parallel-worktree pattern from 3c.19 / 3c.20 / 3c.21 implicitly depends on the spawn channel being healthy; if it persistently fails, the parallel pattern degrades to sequential in-context.

**Verification:** Region-tab live-test on `:8001/` — clicking tabs no longer shows the extruded spinner; pill encloses only the 4 tabs; spinner appears cleanly to the right with 10px gap. IGN dry-run: 953 TBA stripped → 298 parsed → 0 dropped → all would be NEW. IGN real run: 299 inserted (one entry's run-to-run drift between dry-run and real-run, consistent with the prior pcgamer ~0.3% drift observation), 2 dim syncs, ~46 s wall. `release_date_for()` returns correct dates on 5 sample shared games. Release Radar regex extract from boot-served `/` page returned both `PCGamer →` and `IGN →` as expected.

**Spend this session:** ~$0.08 (2× IGN Haiku passes, dry-run + real). Cumulative project: ~$11.46 (was ~$11.38 after 3c.23).

---

## 2026-05-19 (Phase 3c.23, latest, same session as 3c.22) — Trends card bidirectional (rising + declining) + games-collapse; sentiment rows clickable → right-drawer

**Scope:** Two user-requested changes on top of the late-session 3c.21 / 3c.22 polish. (1) Trends card on `/` flipped from top-N-by-`delta_pp`-DESC to **bidirectional** (top-5 rising + top-5 declining per tab); Games tab collapsed to a single combined view (Hottest card still carries the current/upcoming split). (2) `/sentiment` rows became clickable, opening the same right-drawer pattern as `/`. Changes land in `app/services/reports.py` (return-shape change + new drawer kind + new window-mode kwargs), `app/routers/reports.py` (drawer endpoint signature), `app/templates/reports.html` (Trends panes restructure), `app/templates/sentiment.html` (row → label conversion + drawer infrastructure duplication). No new CSS, no new LLM calls, no schema change. See SESSION_LOG.md 2026-05-19 (Phase 3c.23) for the full file-by-file shape.

**Locked decisions:**

- **Trends bidirectional via dict shape, not parallel lists.** `_merge_wow()` returns `{"rising": [...limit], "declining": [...limit]}` as a single dict — rising = positive `delta_pp` sorted DESC, declining = negative `delta_pp` sorted ASC, neutrals dropped from both buckets. Rationale: keeps the dispatcher contract simple (1 return value vs. a side-channel list); call sites just access `.rising` / `.declining`. Neutrals dropped from both buckets — they'd visually clutter both ends without adding signal. Rejected: parallel `top_N_rising_wow` + `top_N_declining_wow` functions (would have doubled the 5-caller surface area for the same data shape); a single list with sign-bucketing done in the template (puts business logic in Jinja).

- **Games tab collapsed to a single combined view (`lifecycle=None`).** `trends_for_week()` payload dropped `games_current` + `games_upcoming` keys, replaced with a single `games` list (lifecycle filter = None — all games regardless of release-date status). Per user request. Rationale: the Hottest card still carries the current/upcoming split — that's a different card with a different lens (Hottest = "which games are getting volume *now*"; Trends = "which games are accelerating/decelerating WoW"). The split on Trends was visually redundant with Hottest and made the Games tab feel busier than its bidirectional siblings. Rejected: keeping all three (Current + Upcoming + combined) — 3-sub-section tab vs. 2-sub-section tab made the Games tab visually anomalous.

- **Drawer `kind=category` added to the existing `/reports/drawer` endpoint, not a new endpoint.** `_DRAWER_KINDS` set in `app/services/reports.py` gains `category`; new SQL branch in the `items_for_entity_in_week()` if-chain filters on `LOWER(TRIM(e.category)) = LOWER(:v)`. `_DRAWER_KIND_LABELS` gains `"category": "Category"`. Rationale: the drawer template + slide-in CSS + state-radio toggle pattern are already proven on `/`; adding a SQL branch is ~15 LOC vs. a parallel endpoint with its own template + CSS. Rejected: a new `/sentiment/drawer` endpoint with its own simpler template (more code, more state to maintain, same UX).

- **Drawer accepts `?from=YYYY-MM-DD&to=YYYY-MM-DD` as a window-mode alternative to `?week=YYYY-Www`.** `from` aliased via `Query(alias="from")`. When both provided: parse to datetimes, treat `to` as inclusive (add +1 day for exclusive end), pass `start` / `end` kwargs into `items_for_entity_in_week`. The function-level `(start, end)` kwargs are also exposed on `items_for_entity_in_week()` so future callers can use either mode. Error paths added for bad date strings and the "neither week nor from/to" case. Rationale: `/sentiment` is date-range-based (Phase 3c.17 picker), not week-based — forcing it to translate to a synthetic `week_id` for the drawer would have been a wrong-shape adapter. The dual-mode endpoint matches `/sentiment`'s `parse_date_range` precedence (week_id > from/to > default). Rejected: forcing `/sentiment` to compute a `week_id` from the picked range (loses precision when the range spans multiple weeks).

- **Sentiment drawer markup duplicated from `reports.html`, not extracted to a shared partial.** Drawer state radios + overlay + panel duplicated into the bottom of `sentiment.html`'s `main_content` block (must be siblings of each other for the CSS `:checked ~ .gc-drawer-panel` slide-in selector to work). Modal radios NOT included (no exec-summary on `/sentiment`). Rationale: low blast radius for now — only 2 pages use the drawer; a shared `_drawer_panel.html` partial is a future cleanup pass when a third page wants in. The duplicated markup is ~30 lines and the visual + interaction tests cross-validate both copies. Rejected: extracting `_drawer_panel.html` partial in this phase (premature DRY — only 2 callers, and the `reports.html` version carries the exec-summary modal radios as siblings while `sentiment.html` doesn't).

**Implementation notes (for future readers):**
- The `_merge_wow()` shape change ripples through 5 callers in `app/services/reports.py` (`top_genres_wow` / `top_platforms_wow` / `top_games_wow` / `top_live_service_wow` / `top_events_wow`). The Jinja `trend_rows(rows, kind)` macro itself stayed flat-list — each pane now invokes it twice (once for rising, once for declining) with a `.gc-trend-subhead` divider in between.
- `.gc-trend-subhead` is reused from the prior Current/Upcoming Games-tab pattern; no new CSS shipped.
- The drawer kind-dispatch in `items_for_entity_in_week()` is an if-chain rather than a registry — fine for 5 kinds today, but worth refactoring into a kind → SQL-builder dict if the count grows past 8.
- `category` values are Haiku-locked: `news / industry / community / launch / patch / review / opinion / leak`. The smoke caveat (initial probe used `value=industry-news`) cost ~2 minutes — worth documenting that the value-side taxonomy is enforced by the enrichment pipeline, not by the drawer endpoint.

**Verification:** Routes 200 on `/`, `/sentiment`, `/reports/drawer?kind=category&value=industry&from=2026-05-12&to=2026-05-19`, `/reports/drawer?kind=cluster&value=262&week=2026-W20` (back-compat). 10 `.gc-trend-subhead` refs on `/` (5 tabs × 2 subsections). Trends games sample: 5 rising + 5 declining with `prior_count > current_count` on every declining row. Drawer `kind=category value=industry` returns 25 items (cap), 125 class refs total.

**Spend this session:** $0 — no LLM calls. Cumulative project: ~$11.38 (unchanged from 3c.22).

---

## 2026-05-19 (Phase 3c.22, same session as 3c.21) — Watch-list polish: category chips on the Watch card + day-specificity push in the Opus prompt

**Scope:** Tighten the Watch card on `/` so each item carries a small color-coded `category` chip + a more day-specific timing label. Changes land in `app/services/synthesis.py` (prompt + Pydantic schema + critic rule), `app/routers/reports.py` (card context plumbing), `app/templates/reports.html` (chip render), `app/static/app.css` (chip styles). One Opus re-synth on W20 to verify the new shape; W17 / W18 / W19 left untouched for backward-compat. See SESSION_LOG.md 2026-05-19 (Phase 3c.22) for the full file-by-file shape.

**Locked decisions:**

- **Watch[] category taxonomy locked at 5 values: `release | drama | business | community | event`.** Small enough to color-code memorably (one token per value, distinct semantic flavors), broad enough to catch any "thing worth watching this week" without forcing Opus into awkward shoehorning. Defaults to `event` if Opus emits anything else — the Pydantic `field_validator` coerces silently rather than failing the whole synthesis on a stray label. Rejected: a 3-value taxonomy (too coarse — `release` and `event` would collapse and lose the most-common-case distinction); an 8+ value taxonomy (more granular but harder to color-code memorably; would push the chip toward a noun rather than a flag).

- **Day enum tightened to 8 strict values (`Mon`-`Sun` + `TBA`); variants coerced via a forgiving normalizer, NOT a strict Pydantic `Literal`.** Variants like `Mid-week`, `Weekend`, `Saturday`-spelled-out get coerced (best-effort to the closest enum value, or `TBA` if ambiguous). Rationale: a strict `Literal` would force a $0.30 Opus retry on any stray value (the Pydantic retry path round-trips the whole synthesis, not just the watch[] section). The normalizer captures intent cheaply. Rejected: strict `Literal` (cost penalty on every stray value); free-form string (already what we had — defeats the day-specificity push).

- **Backward-compat preserved at the template level rather than re-synthing all 4 weeks.** Older `synthesis_json` rows (W17 / W18 / W19) lack the `category` field; the template renders without chips via `{% if w.category %}`. Page still 200 on all three older weeks. Rationale: $0.30 × 3 = $0.90 saved on re-synth + zero risk to historical archive consistency (re-synth would regenerate the entire synthesis_json, not just the watch[] section). The archive remains a frozen record of what was synthesized at the time. Rejected: forced backfill re-synth on the three older weeks (cost + archive-consistency risk).

- **Watch-card category chip rendered inline at the head of item prose, not as a new layout column.** Each item's row now reads `[chip] title — body`. Rationale: avoids any grid-template changes to the Watch card; chip is small (10px font, uppercase, bordered) and reads as a category prefix rather than a competing visual element. Rejected: a new `<th>`-style first column with chips (grid surgery + visual weight competing with title); a colored left border per item (less scannable than an explicit chip).

- **Critic rule 7 added specifically targeting watch[].** Verifies groundedness (item should tie to corpus signal, not generic editorial), category enum membership, and day-specificity preference. Rationale: prior critic rules were sectional-by-implication — rule 1 covers groundedness across all sections but doesn't explicitly call out watch[]'s tendency to drift into generic "keep an eye on…" prose. Making the rule explicit reduces drift. W20 verification: critic pruned 7 → 6 watch items, dropping the one without cluster_id grounding. Healthy signal — see OPEN_QUESTIONS.md for the watch-over-time caveat. Rejected: leaving the sectional-by-implication coverage and hoping for the best (the explicit rule is ~3 lines of prompt text — cheap insurance).

**Implementation notes (for future readers):**
- The router fix in `app/routers/reports.py` `cards["watch"]` dict comprehension (~line 244) is load-bearing: without passing `category` through from synthesis_json into the card context, the new field would be stripped before reaching the template. Caught during smoke render — prompt + Pydantic edits looked right but chips didn't appear; trace led back to the dict-comprehension scope.
- CSS chips reuse existing tokens — no new design tokens introduced (`--gc-success` for release, `--gc-danger` for drama, `--gc-accent` for business, `--gc-warning` for community, muted fallback for `event`).
- Both the cluster-linked `<label>` variant and the static `<div>` variant of the Watch row were updated. Easy to miss the second on the next iteration — the row currently exists in two shapes because cluster_id-bearing rows are clickable (`<label for="drawer-toggle">`) and the others are static.

**Verification:** W20 re-synth via `python scripts/run_synthesis.py 2026-W20 --force` — ~112 s wall, 7 emitted, 6 after critic. Days: 2 Tue, 1 Fri, 3 TBA (both Tue entries grounded to actual May 19 release dates; Fri to May 22 LEGO Batman). Categories: 3 release / 2 business / 1 community. Live render at `:8011`: 6 `.gc-watch-chip` refs on `/`, distributed 3/0/2/1/0 across release/drama/business/community/event. W17 / W18 / W19 still 200 with no chips (backward-compat verified).

**Spend this session:** $0.30 (one Opus synthesis + critic pass on W20). Cumulative project: ~$11.38 (was $11.08 after 3c.21).

---

## 2026-05-19 (Phase 3c.19 / 3c.20 / 3c.21, late-session, parallel worktree agents) — Source-failure UI banner + Trends mini-bar + Sentiment view + parallel-worktree workflow meta-decision

**Scope:** Three narrow polish items off the Phase 5 backlog, built simultaneously by three Claude Code worktree agents branched off the `9f4deb7` (Phase 3c.18) master HEAD, then cherry-picked back onto master in phase order (`52218eb` → `8974be9` → `ad0541f`). All three are UI / SQL / template work — no LLM calls, no schema change. See SESSION_LOG.md 2026-05-19 (Phase 3c.19 / 3c.20 / 3c.21) for the per-phase file lists + verification.

**Locked decisions:**

- **Source-failure banner threshold = strict `> 3`, not `>= 3`.** Empirically 1–2 transient errors per source are noise (a YouTube 503 on a single fetch can leave `error_count = 1` until the next successful pull); >3 indicates a persistent issue worth surfacing. The constant lives at `app/services/chrome.py:FAILING_SOURCE_ERROR_THRESHOLD = 3` and is referenced by `failing_sources_count(session)`. Rejected: `>= 3` (would have surfaced every 3-error transient blip); a user-configurable threshold (overkill for single-user local app).

- **Banner placement inside `.gc-main`, not above `.gc-shell`.** Banner width = main column width, not full viewport. The sidebar stays a separate visual zone; a top-of-shell banner would have visually overlapped the sidebar header in the small-window case. Rationale also matches the existing component model (header / cards / footer all live inside `.gc-main`). Rejected: full-shell banner above sidebar (visual overlap risk); fixed-position toast (would have required dismiss-state persistence we don't want to engineer for single-user).

- **Trend mini-bar is zero-line-centered, not left-anchored magnitude.** Each bar has a midline; positive deltas grow right of midline (green), negative grow left (red), neutral hugs the midline (gray). Reading the bar gives both direction and magnitude at a glance. Rejected: left-anchored magnitude (`width = abs(delta)`, color = sign) — loses sign info at a quick glance; user would have to read the colored number alongside, defeating the purpose of an inline visualization.

- **Mini-bar clamp at 12pp = 100% of half-width.** Real-corpus deltas rarely exceed 8pp (a single big-event week peaks at ~10pp in the existing trends table); clamping at 12 gives a small visual headroom above the natural max and prevents one outlier from compressing all the other bars to invisibility. The clamp lives in the Jinja `trend_bar(delta_pp, tone)` macro. Rejected: dynamic max-per-tab (would mean a 5-point delta looks "big" on a sparse week and "small" on a busy week — inconsistent reading across tabs); unclamped (one 20pp delta would render every other bar as a 2px sliver).

- **Sentiment view = per-category aggregate, not per-item.** Item-level sentiment is already visible on `/stories` (each row carries a sentiment_score chip). The aggregate (`AVG(sentiment_score) + COUNT(*) GROUP BY enrichments.category`, sorted by avg DESC) is the new value-add — surfaces which categories are running positive/negative across a window. Tone bucketed at ±0.05 (anything in `[-0.05, 0.05]` reads as neutral). Rejected: per-item duplication of `/stories` content (no new value); time-series chart of sentiment over weeks (deferred — would need a separate window-stepping data path).

- **Sentiment date-range pattern reused, not re-invented.** Phase 3c.17's `parse_date_range(from_str, to_str, week_id, default_days, now)` + flatpickr UI inherited via `shell_base.html` are imported as-is. `sentiment.html` uses a `<form>` + `gc:daterange-picked` listener for full-page nav rather than a fragment swap, because the page is a single card — no list to swap. Default window = last 30 days (matches `/clusters`). Back-compat `?week_id=` shim works through the same helper; garbage params fall back to default 30d. Rejected: a new picker variant tuned for a single-card page (would have duplicated the 3c.17 logic for negligible UX benefit).

- **Meta-decision: parallel worktree agents are usable for narrow-scoped polish items; review of each agent's output before merging is required.** The three phases here were independent (different files, no shared logic) and individually small (≤10 files each, no architectural change), which made the parallel approach a good fit — saved real wall-clock time over a sequential build. **Honest caveat:** 2 of 3 agents mistakenly wrote to the main repo working tree before self-reverting and re-doing their work inside their assigned worktree — caught before the cherry-picks ran but illustrates the risk. **Forward rule:** explicit review of each agent's diff before merging — don't rubber-stamp; cross-check that the agent stayed in its assigned worktree.

**Implementation notes (for future readers):**
- Banner singular/plural grammar lives inside `_alert_banner.html` (`1 source is erroring` / `N sources are erroring`); no helper needed.
- `about.py` newly gained a `Session` dependency it didn't previously have — `failing_sources_count(session)` needs DB access. Pattern mirrors the other 4 routers.
- `app/static/app.css` got three append-at-EOF blocks (one per phase); the cherry-pick conflicts were resolved by concatenating in phase order. No new design tokens introduced by any of the three phases — all three reuse existing `--gc-warning` / `--gc-success` / `--gc-danger` / `--gc-fg3` / `--gc-border` etc.
- `chrome.py` auto-merged: 3c.19 added the helper + constant; 3c.21 added a nav entry between Clusters and Sources (icon `activity`, route name `sentiment_view`). Disjoint regions of the file.

**Verification:** Per-phase smoke tests in SESSION_LOG.md 2026-05-19 (Phase 3c.19 / 3c.20 / 3c.21). Quick summary: banner hidden when healthy / appears with correct count + link when forced; 54 `.gc-trend-bar` refs on `/` (5 Trends tabs × ~10–12 rows); `/sentiment` 200 on default + explicit `?from`/`?to` + back-compat `?week_id=` + garbage; 67 `.gc-sentiment` refs on the page; sentiment nav link in `/stories` shell; `/sentiment` in `/openapi.json`.

**Spend this session:** $0 — no LLM calls across all three phases. Cumulative project: ~$11.08 (unchanged from 3c.18).

---

## 2026-05-19 (Phase 3c.18, very-later) — Authoritative `game_releases` table (pcgamer-sourced) + derived lifecycle; `games.release_date`/`lifecycle` demoted to synced cache

**Scope:** The morning's pcgamer carry-over ("one-shot Haiku parse on the static list page → upsert `games.release_date`") was reframed into a properly-architected source-of-truth table. The driving insight: lifecycle ('existing' vs. 'upcoming') is a function of `release_date < today`, NOT a Haiku name-only guess — which fixes the prior corpus noise where *BioShock* (2007) and *Aliens: Fireteam Elite* (2021) were tagged 'upcoming' from the name alone (Haiku training-cutoff staleness + name-only ambiguity). New table `game_releases` + new service `app/services/release_dates.py` + new script `scripts/refresh_pcgamer_releases.py` + new `tag_pcgamer_releases()` helper on `app/services/anthropic.py`. No UI change.

**Locked decisions:**

- **Authoritative source-of-truth table, not Haiku-tagged column.** `game_releases` (composite PK `(game_name_lc, source)`) becomes the canonical source. `games.release_date` + `games.lifecycle` are kept as a **synced cache** — overwritten by `sync_games_dim(...)` after each refresh — so existing readers (Release Radar card, `top_games_for_week`, etc.) keep working unchanged. Rationale: Haiku name-only guesses were demonstrably wrong (BioShock, Aliens: Fireteam Elite); an editorially-curated external source is the proper fix. Rejected: replacing `games.release_date` with a JOIN-through-resolver everywhere — would touch every consumer; the cache lets us land the fix without a wider refactor.

- **Lifecycle is derived, not stored.** `derive_lifecycle(release_date, today)` is a pure function in `app/services/release_dates.py` — None/TBA → None; future/current → 'upcoming'; past → 'existing'. Reuses the existing `is_future_or_unknown` for boundary semantics. Stored in `games.lifecycle` only as a synced cache (recomputed and overwritten on each refresh). Rationale: lifecycle changes on the calendar day a game ships — a static column lies the day after release. Derived is honest. Rejected: storing lifecycle on `game_releases` instead — same staleness problem at one remove.

- **Multi-source schema from day one, pcgamer ingestion only this round.** The `source` column on `game_releases` accepts `'pcgamer' | 'ign'` from the schema's first day. IGN ingestion (parallel script, ~50 LOC, same shape) is deferred. Rationale: don't paint into a corner — adding a `source` column later would require backfilling 286 rows and adjusting the PK. Rejected: a single-source pcgamer-only table — same row migration cost when IGN lands.

- **pcgamer > ign on conflict.** Codified as `SOURCE_PRIORITY = ['pcgamer', 'ign']` in `app/services/release_dates.py`; `release_date_for(session, name)` walks the priority list and returns first-with-row. Rationale: pcgamer's list is editorially curated; IGN's release dates were already shown to be partially React-rendered (Phase 3c.1) and less structured. Rejected: most-recently-updated wins — would cause flapping when both sources are present and one updates more often.

- **Drop `raw_label` from the `PCGamerReleaseList` Pydantic schema for output-budget fit.** The article yielded 286 entries; with `raw_label` included, Haiku's structured output exceeded the 8192 max_tokens cap and truncated mid-JSON. The column was kept in the DB schema (`game_releases.raw_label TEXT NULL`) for future use — an "extended output" mode, chunked ingest, or a debug pass that fills it in. Rationale: shipping a working ingest path beats a perfect-but-truncated one; the column is cheap to leave NULL today. Rejected: chunking the article in half and running Haiku twice — more code, more state to merge, and the 286-entry article fits cleanly without `raw_label`. Rejected: dropping `raw_label` from the SQL schema too — would lose the option to backfill later.

- **Diff-driven row writes, but Haiku is still called every run.** The script INSERTs new rows / UPDATEs only when `release_date` actually changed / no-ops otherwise. But the upstream Haiku parse runs unconditionally on every invocation — ~$0.04/run regardless of whether pcgamer changed. An ETag/Last-Modified short-circuit (skip the Haiku call when the article hasn't changed since the last refresh) is a Phase 4 nicety, flagged in OPEN_QUESTIONS. Rationale: at $0.04/refresh and roughly weekly cadence, the headroom is ~$2/yr — not worth the complexity in v1. Rejected: caching the article body locally and diffing in Python — same complexity as ETag without the upstream signal.

**Implementation notes (for future readers):**
- The `idempotency proof` run #2 immediately after #1 showed `0 new / 1 updated / 285 unchanged`. The 1 update is Haiku run-to-run drift on a single entry, not a bug. Tolerable for now; flagged in OPEN_QUESTIONS to watch over time.
- `games.release_date` + `games.lifecycle` are written by `sync_games_dim(session, game_name_lc)` only when values actually changed (idempotent). Of our 184 games, 23 matched pcgamer (case-insensitive name); 18 needed updates (5 already correct, no-op).
- Article fetch goes through `scrapers_lib.tier1.article.fetch_article` (trafilatura + Chrome TLS impersonation). The WebFetch tool was tried first and couldn't get past pcgamer's nav chrome; trafilatura via scrapers-lib returned 28,701 chars of clean body cleanly.

**Verification:** Smoke-tested live with two real-write runs back-to-back. Run #1: 286 inserts on empty table; 23 games matched / 18 updated in `games` dim. Run #2 immediately after: 0 new / 1 updated / 285 unchanged. Sample correct lifecycle flips: *Mixtape* (2026-05-07) → existing; *Subnautica 2* (2026-05-14) → existing; *Forza Horizon 6* (2026-05-19, today) → upcoming; *007 First Light* (2026-05-27, future) → upcoming. `--dry-run` mode prints the would-write diff without touching DB.

**Spend this session:** $0.04 dry-run + 2 × $0.04 real runs ≈ ~$0.12. Cumulative project: ~$11.08 (was $10.96 after 3c.17).

---

## 2026-05-19 (Phase 3c.17) — Date-range picker (vendored flatpickr) replaces the ISO-week dropdown on `/stories` + `/clusters`

**Scope:** The previous `<select name="week_id">` ISO-week dropdown on `/stories` and `/clusters` was the long-tail UX gap from the Phase 3c.9 → 3c.12 cluster of changes. Replaced with an airline-style date-range picker driven by **flatpickr 4.6.13** vendored into `app/static/vendor/flatpickr/`. Routers rewritten to accept `?from`/`?to`; a back-compat `?week_id=` shim is retained so the existing footer "see all" links on `/reports` keep working unchanged. No LLM call, no schema change.

**Locked decisions:**

- **flatpickr vendored, not npm-built, not a custom picker, not native `<input type="date"> × 2`.** Three alternatives were on the table: (a) two native `type="date"` inputs — no range UX, browser-variant rendering, no presets without custom JS; (b) a custom HTMX/Jinja picker — ~200 lines for competent range UX, and we'd still be inventing range-selection semantics; (c) flatpickr's range plugin — ~21 KB gz, one-liner JS init, well-trodden. Picked (c). Per CLAUDE.md's "no JS build step" rule, the min files (`flatpickr.min.js` + `flatpickr.min.css`) are vendored under `app/static/vendor/flatpickr/` and loaded via `<link>` + `<script>` in `shell_base.html` — zero npm, zero toolchain. User explicitly approved the new vendored dep per the global rule on new deps / architectural changes.
- **Cluster filter semantic: "any member in range."** A cluster is included on `/clusters?from=X&to=Y` if **any** of its `member_item_ids` has `published_at ∈ [X, Y)`. Considered + rejected: **all-members-in-range** (too strict — a cluster spanning the date boundary would vanish when the window is narrower than the cluster's date span, which is the common case for week-aligned windows); **majority-in-range** (hard to explain, introduces boundary flicker when one item flips sides). Rationale: matches the "show me what was happening in this window" mental model; cross-week clusters correctly surface in both adjacent ranges (a story that broke on Sunday and was still being covered on Tuesday belongs in both this-week and last-week views). Implemented via SQLite `json_each` over `member_item_ids` (no `Item.cluster_id` FK exists; computing this in Python by union of cluster JSON arrays would be O(n²) on busy weeks).
- **Back-compat `?week_id=` shim retained** in both `app/routers/dashboard.py` and `app/routers/clusters.py`. `parse_date_range(from_str, to_str, week_id, default_days, now)` translates `week_id` → from/to internally. Rationale: the weekly read-out's 7 "see all stories this week →" footer links (`?week_id={{ active_week_key }}`) and any external bookmarks pointing to `?week_id=2026-W19` keep working without a template touch. No change required to `reports.html` macros. The eyebrow on the destination page renders the translated date range so the user sees "2026-05-04 → 2026-05-10" rather than the opaque week id.
- **Defaults: `/stories` = last 7d; `/clusters` = last 30d.** `_DEFAULT_WINDOW_DAYS = 7` on dashboard.py matches the prior 3c.9 behavior — no regression for the user. `_DEFAULT_WINDOW_DAYS = 30` on clusters.py approximates the prior default's density (which was a per-ISO-week multi-week list across all weeks with clusters). Considered: 14d on `/clusters` for symmetry with the prior 2-ISO-week visible default — rejected because the prior list view actually showed all 4 weeks W17–W20, and 30d gets closer to that density without being unbounded.
- **Presets server-rendered, not JS-computed.** `_preset_links()` returns from/to strings per preset (Last 7d / Last 30d / This week / All time, where All time = 2020-01-01 → today). Template emits as `<button class="gc-preset" data-from data-to>` buttons; the inline init JS only wires the click → hidden-input write + custom-event fire. Rationale: avoids any tz/DST drift between the Python process and whatever browser/locale the user is in. Same reason eyebrow display strings are server-computed in `parse_date_range`.

**Implementation notes (for future readers):**
- The `end` field returned by `parse_date_range` is **exclusive** (user-picked end day + 1). SQL filters use `published_at < end` so the user-picked day is inclusively covered. `to_display` shows the user-picked day, not `end`.
- The hidden `name="from"` input is the HTMX trigger source: it listens for `hx-trigger="gc:daterange-picked from:#date-range-display"`. Both the flatpickr `onClose` handler and the preset-button click handler dispatch the same `gc:daterange-picked` event from `#date-range-display`. Single trigger surface → simpler HTMX semantics than firing from both elements.
- Init JS is page-safe (bails if `#date-range-display` or `flatpickr` is missing) so `/`, `/about`, `/sources` are unaffected even though `shell_base.html` ships the script tags globally.

**Verification:** Smoke-tested live on `:8002`. All combinations 200: `/stories` (default), `/stories?from=2026-05-12&to=2026-05-19`, `/clusters` (default 30d), `/clusters?from=2026-05-04&to=2026-05-10`, `/clusters?week_id=2026-W19` (back-compat → eyebrow "2026-05-04 → 2026-05-10", 122 clusters via any-member-in-range), `/clusters?region=americas&from=…&to=…` (region tab still works with date filter). HTMX fragment branch returns the correct partial. `/static/vendor/flatpickr/flatpickr.min.{js,css}` serve 200. `/`, `/about`, `/sources` untouched routes still 200.

**Spend this session:** $0 — no LLM calls. Cumulative project: ~$10.96 (unchanged from 3c.16).

---

## 2026-05-19 (Phase 3c.16, later) — Region tabs on `/` weekly read-out: filter-existing `synthesis_json`, no per-region Opus pass

**Scope:** Add the same 4-tab region filter (Global / Americas / Europe / Asia) to the weekly read-out at `/`. Re-use the per-cluster region overlay (`cluster_regions()`) shipped earlier today in 3c.15. No new LLM call — cards filter in-place against the cluster_ids referenced by `synthesis_json`.

**Locked decisions:**

- **Filter-existing, not per-region synthesis.** Same call as the 3c.15 deferred-item: corpus is too thin per region for per-region Opus calls (3× weekly cost for 3 weaker reports). When a regional tab reliably has ≥30–40 items/week, revisit. Today's read-out cards just go sparse on regional tabs — honest signal of coverage shape, not synthetic regional content.
- **Inlined `<nav>` tab strip in `reports.html`, NOT the shared `_region_tabs.html` partial.** The shared partial uses `hx-include="[name='q'],[name='section'],[name='week_id']"` (selectors that don't exist on `/`) and assumes a fragment response. `/` has no `HX-Request` branch — it always returns the full template — so the tab must use `hx-select="body"` to extract just the rendered body from a full-page response. Adding both behaviors to the shared partial would overload it for the stories/clusters case; inlining keeps each page's tab logic local and obvious. Mild duplication accepted.
- **Full-body swap (`hx-target="body" hx-select="body"`).** The header exec-summary CTA flips visibility with region; a sub-tree swap of `#readout-body` would leave the header CTA stale. Full-body is the smallest swap that keeps the page coherent. The route is a single template render — no observable perf cost.
- **Hide exec-summary CTA on regional tabs; show inline note in its place.** The summary prose was generated against the whole corpus; showing the CTA as if it were region-specific would mislead. Note copy: *"Exec summary covers the whole-corpus week. Switch to Global to read it."*
- **"Not region-tagged" chip on Hottest games / Trends / Release Radar card headers when `region_active`.** These cards aggregate by game-name or entity-name, not cluster_id — they cannot be filtered by region tag without extending the games dim with a region column (deferred). Showing the cards unchanged with the chip is the honest middle ground: it tells the user "this dimension isn't region-aware yet" rather than silently hiding the cards or pretending they're filtered. Rejected: hiding the cards (worse UX); silently filtering (would zero everything because games dim has no region).
- **Watch[] without `cluster_id` dropped on regional tabs.** Some watch entries are corpus-wide editorial ("this week we're watching the Steam summer sale…") without an anchoring cluster. On regional tabs they don't carry the region semantics, so they're dropped rather than rendered as ambiguous.
- **Community narrative cleared on regional tabs.** Whole-corpus prose; the heated-about / celebrating lists remain (filtered by region).

**Verification:** Smoke-tested live on `:8001`. All 4 tabs return 200; active-class on correct tab; exec-summary CTA hidden on regional tabs (file-text icon count: 1 Global / 0 Asia); 3 "Not region-tagged" chips per regional tab; card empty-state count increases on regional tabs (5 / 6 / 7 / 9 for Global / Americas / Asia / Europe).

**Spend this session:** $0 — no LLM calls. Cumulative project: ~$10.96 (unchanged from 3c.15).

---

## 2026-05-19 (Phase 3c.15) — Region tagging: content-inferred per-item `region_focus` (Haiku) + 4-tab filter on `/stories` and `/clusters`; cluster region = union of member tags

**Scope:** Add a `region_focus` field to per-item enrichment (Haiku call already in flight — incremental prompt + schema change, no new API call), backfill the 1412 already-enriched items via a one-shot Haiku pass on existing `tldr` text, and surface a 4-tab filter (Global / Americas / Europe / Asia) on `/stories` and `/clusters`. Cluster region is computed on-the-fly as the union of member-item tags (no new column on `clusters`), mirroring the Phase 3c.12 section-overlay pattern.

**Locked decisions:**

- **Content-inferred, not source-attributed.** Region is set by Haiku from the item's body/tldr, not by the publication's HQ. Rationale: source bias ≠ content focus — IGN.com covers Japanese games regularly; tagging by publisher would mislabel half the corpus. Source-level tagging (a `sources.region` column) is deferred as a useful *secondary* dimension once Asian sources are added — see deferred item in OPEN_QUESTIONS.
- **Tag values: comma-separated subset of `{americas, europe, asia}`, or NULL.** Three-region split chosen for tab-bar sanity (4 tabs total incl. Global) and because the corpus signal isn't granular enough to support country-level tagging without slop. Multi-value supported because plenty of stories straddle regions (e.g., a Capcom Tokyo press conference with Western release implications → `asia,americas`). NULL means "no regional anchor" — a story about a game's mechanics, an industry-wide trend, or a non-geographic topic.
- **No `global` tag value.** Items without a regional anchor are NULL, not `'global'`. Rationale: avoids name collision with the Global tab (which is "show all, don't filter"). A `'global'` tag would have created the ambiguous question "does the Global tab show only `'global'`-tagged items, or everything?" — by making it strictly absence-of-filter, the semantics are unambiguous.
- **Strict tag matching for regional tabs.** The Americas tab shows items with `americas` in their `region_focus` set — nothing else. NULL-tagged items appear *only* in Global. Rejected: showing NULL items in every regional tab as "could be anywhere" — defeats the filter; the user clicked Americas because they wanted Americas. Rejected: showing NULL items as a fallback when a regional tab is sparse — silent mis-filtering.
- **Global tab is unfiltered, NOT a bucket of "untagged."** Default tab. No `region_focus` predicate in the query. Same data as today's `/stories` and `/clusters` views.
- **Cluster region is computed on-the-fly, not stored.** New helper (likely `cluster_regions(session, cluster_ids) -> dict[int, set[str]]`) walks `member_item_ids` and unions their `region_focus` tags. Mirrors `items_in_section` from Phase 3c.12. Rationale: cluster membership is already incremental (Phase 3c.12); persisting region on `clusters` would require backfill on every incremental cluster update. The on-the-fly cost is a single indexed lookup per cluster page render. Rejected: column on `clusters` — write-amplification + risk of staleness.
- **Backfill is a Haiku one-shot on existing `tldr` text** (`scripts/backfill_region.py`), idempotent (skip rows where `region_focus IS NOT NULL`). Cheaper than re-running full enrichment on 1412 items because the prompt only asks for the region field and the input is the already-condensed tldr (~50–100 tokens) rather than the full body. Estimated cost: ~$0.15–0.25.
- **Cluster region as simple union accepted for v1.** A 1-stray-Asia-item cluster could carry an Asia chip on `/clusters`. Flagged as a watch-item; tightening to a ≥2-member threshold (or proportional `≥30% of members`) is a one-line change if noise is observed.
- **Per-region synthesis deferred.** Region is a filter dimension in v1, not a synthesis input. The weekly read-out remains one global summary per ISO week. Rationale: the corpus is still thin per-region (esp. Asia until source mix diversifies); per-region synthesis would multiply Opus cost 3× and produce three weaker summaries instead of one solid one. Revisit once each regional tab has ≥30–40 items/week.
- **Honest scope note.** Corpus today is English/US/UK-heavy. The Asia tab will be near-empty at launch. Feature ships anyway because a thin tab is the honest signal that source coverage is missing — surfacing the gap is more useful than hiding it. Tab-empty state copy: "No region-tagged items yet — coverage depends on your source mix."

**Verification:** Pending implementation.

**Spend this session:** Pending. Estimated ~$0.15–0.25 for the 1412-item Haiku backfill; ongoing Haiku marginal cost on new ingest is negligible (the existing per-item call returns one extra field).

---

## 2026-05-15 (later) — YouTube audio-transcribe path integrated (scrapers-lib 1.7.0 + `[youtube-audio]` extra); per-item enrichment quality improved, cross-source clustering unchanged

**Scope:** Wired up scrapers-lib v1.7.0's new yt-dlp + faster-whisper audio fallback. 3-line app change + one imperative install of the optional extra; spike-tested on 3 yesterday-`IpBlocked` IDs; backfilled the 35 YT items enriched on 2026-05-14 (when ~19 caption fetches hit `BlockedError(IpBlocked)`); re-embedded, re-clustered W20, force-resynthesized W20.

**Locked decisions:**

- **`audio_fallback=True` always.** `app/services/ollama.py:fetch_youtube_transcript` passes it on every call; upstream short-circuits when captions succeed, so no extra cost when they work. Rejected: a feature flag — single-user local app, never going to toggle.
- **Model: `small.en`** (upstream brief's default). Adequate on the noisy spike-test sample (horror-trailer vocal stings → `"...don'taaaaaaaa!!!"`, Haiku still tagged correctly). Rejected: `medium.en` for a quality bump — 2–3× CPU cost, no observable gain on our title-heavy corpus.
- **`pyproject.toml` pin: `"scrapers-lib>=1.7.0"`**, with the `[youtube-audio]` extra installed imperatively (`pip install -e "..\scrapers-lib[youtube-audio]"`). Rejected: declaring the extra in pyproject — extra pulls 5 heavy runtime deps (ctranslate2, faster-whisper, PyAV, onnxruntime, hf-xet) that aren't needed for the app to run if YT ingest is off. Accepted fragility: clean re-install of the project's deps needs the imperative command re-run separately.
- **No length cap, no quality floor.** Audio fallback will burn `audio_minutes × ~30–50 s` of CPU on a multi-hour video (acceptable for current channel mix; flagged in OPEN_QUESTIONS for the day we add long-form sources). A short gibberish transcript can still pass `if transcript:` to Haiku — not observed as a failure mode this session, flagged in OPEN_QUESTIONS for future hardening.

**Verification (35-item backfill on the 2026-05-14 YT enrichment set):**
- **Re-enrich totals:** `ok=34 / skipped=1` (item 1567 — audio path returned empty too; existing `ok` row preserved by the targeted-id path's preserve-on-no-progress logic).
- **Audio-fallback firings:** 6 of 35 (caption endpoint was less bot-gated today than yesterday's 19/35; the audio path covered the 6 that still blocked). Caption-success rate today: 28/34 vs. yesterday's ~16/35.
- **Wall-clock:** ~71 min for re-enrich (first audio rescue ~89 s including ~40 s of model download + load; subsequent rescues ~30–60 s/video at steady state per upstream brief). 3.5 min for post-processing.
- **Cluster effect:** ~zero cross-source pollination. 33 of 35 backfilled items remain singletons (`items_appended_existing=0 / clusters_new_created=0 / items_orphaned=330`). Audio transcripts didn't bridge the YT-vs-news vocab gap at the 0.85 cosine threshold — matches OPEN_QUESTIONS 2026-05-14's honest-framing prediction.
- **Per-item enrichment quality:** measurably improved. All 35 backfilled items sit in the 8-category locked taxonomy (`community 14 / industry 9 / review 6 / opinion 2 / news 2 / launch 2`); 0 out-of-taxonomy `'guide'/'preview'/'interview'` slippage on the set. Honest caveat: we overwrote yesterday's enrichments in place, so we can't fully attribute the gain to the audio path vs. today's stabler caption endpoint. Direction is correct.
- **W20 synth:** force-resynthesized fresh (Opus 4.7 + critic, 6246 chars JSON). Bucket counts: `biggest=3 / hottest_reasons=5 / market_momentum=5 / community_sentiment=1 / risks=0 / esports=0 / drama=0 / release_notes=3 / watch=5`. Yesterday's counts weren't retained (in-place UPDATE), so a direct delta isn't possible; the zero risks/esports/drama buckets reflect this week's actual signal.

**Spend this session:** ~$0.38 LLM (~$0.03 Haiku re-enrich × 35 + ~$0.35 Opus synth + critic). $0 audio path (local CPU). Cumulative project: ~$10.66.

---

## 2026-05-15 — Path-prefix support via FastAPI `root_path`; static files served as a Route (not a Mount); orphan `base.html` deleted; nav fail-fast validator

**Scope:** App needed to be reachable via Tailscale Funnel at `https://laptop-aknevrti.taile7462c.ts.net/gaming-chatter`. Tailscale strips the `/gaming-chatter` prefix before forwarding to localhost. Three coupled changes: (a) all template URLs switched from hardcoded `/path` strings to `request.url_for(...)` driven by FastAPI's `root_path` (env var `GC_ROOT_PATH`, default empty for local dev); (b) `app.mount("/static", StaticFiles(...))` replaced with a regular `@app.get("/static/{path:path}")` route because Mount + root_path interact badly; (c) the orphaned legacy `app/templates/base.html` deleted, and a fail-fast nav validator added to the lifespan hook.

**Locked decisions:**

- **URL prefix is controlled by `GC_ROOT_PATH` env var**, read via `os.getenv` in `app/main.py` and passed to `FastAPI(root_path=...)`. Empty default = no prefix = local dev at `localhost:8001/`. `.env` sets it to `/gaming-chatter` for the Tailscale Funnel deployment. Rejected: hardcoding `/gaming-chatter` in templates (the prior state) — same brittleness the refactor was meant to escape. Rejected: uvicorn's `--root-path` CLI flag instead of FastAPI's constructor arg — empirically identical behavior in TestClient, and the FastAPI constructor approach keeps configuration with the code rather than scattered across launch commands.

- **All app URLs go through `request.url_for(...)`.** 15 files modified (templates, routers, `app/services/chrome.py`). Nav rendering moved from static `href` strings in `NAV_ITEMS_BASE` to runtime resolution via `nav_items_for(request, active_id)` — signature change updates 5 call sites. Internal `RedirectResponse(url="/...")` calls (5 of them across `clusters.py`, `sources.py`, `enrich.py`) now construct their target via `request.url_for(...)`. Rejected: leaving redirects hardcoded — same bug class on a different rendering path.

- **Static files served as a FastAPI route, NOT via `app.mount(...)`.** When `root_path` is set, Starlette's `Mount.matches()` builds the child scope's `root_path` as `outer_root_path + mount_path` (e.g., `/gaming-chatter/static`). `StaticFiles.get_path()` then tries to strip that prefix from the request path — but for proxy-stripped requests (`/static/app.css`), the path doesn't start with `/gaming-chatter/static`, so the strip becomes a no-op and StaticFiles resolves `STATIC_DIR/static/app.css` (one directory too deep → 404) instead of `STATIC_DIR/app.css`. A regular `@app.get("/static/{path:path}", name="static")` route doesn't hit this interaction — Route matching is `root_path`-aware in the standard way, and `request.url_for('static', path=...)` still works from templates unchanged. Cost: marginally slower than StaticFiles' optimized Mount (FastAPI pipeline per request) and a hand-rolled path-traversal guard, but for a single-user local app with ~5 static files this is invisible. Rejected: configuring Tailscale Funnel to preserve the prefix — `tailscale funnel --set-path` strips by default and there's no documented preserve mode. Rejected: keeping the Mount and accepting the 404 — defeats the purpose of the refactor.

- **Forward rule: do not add `app.mount(...)` calls while `root_path` is set.** Any future feature wanting a sub-app, plugin UI, second static directory, or admin mount must use FastAPI routes instead. A blocking comment in `app/main.py` near the static route documents the trap; this DECISIONS entry is the long-form rationale. Reason: the Mount/root_path interaction is silent — it'll work fine in local dev (where `GC_ROOT_PATH` is empty) and break only at deploy time, exactly the way the static bug did.

- **`app/templates/base.html` deleted.** Pre-Phase-3c.7 legacy nav shell, not extended by any live template (`shell_base.html` superseded it). Still had hardcoded `/static/app.css` and `/clusters` paths and would have re-introduced the prefix bug if anyone resurrected it (e.g., as a starting template for a new page). Confirmed `grep -rn "extends.*base\.html"` shows only `shell_base.html` is extended; safe to delete. Rejected: keeping it as "documentation of the old approach" — `shell_base.html` and DECISIONS.md cover that.

- **Startup-time nav validator in the lifespan hook.** Every `route` name referenced in `NAV_ITEMS_BASE` is resolved via `app.url_path_for(...)` at boot; if any fails, the app refuses to start with a clear `RuntimeError`. Converts a silent post-deploy 500 (rename a router function, forget to update NAV_ITEMS_BASE) into a loud boot-time crash. Rejected: leaving validation to runtime — first user-visible failure would be a 500 on a nav-rendered page, only after deploy. Rejected: a full route-name check across all `request.url_for(...)` callers in templates — would need template static-analysis tooling we don't have; the nav validator catches the most common refactor case (renaming a top-nav function) without that complexity.

**Verification:**
- Local smoke test (root mount, `GC_ROOT_PATH` unset): all routes return 200; generated URLs are bare (`/static/app.css`).
- Local smoke test (with `GC_ROOT_PATH=/gaming-chatter`): all routes 200; bare paths `/static/app.css` and `/static/img/alienware-head-light.svg` also serve 200 via the new route (proxy-stripped path scenario); generated URLs are prefixed (`/gaming-chatter/static/app.css`); path-traversal probe `/static/../config.py` 404s as expected.
- Public URL `https://laptop-aknevrti.taile7462c.ts.net/gaming-chatter` renders with full styling (CSS + favicon load; nav + HTMX endpoints work).
- Nav validator: app boots clean with the 5 current NAV_ITEMS_BASE entries (`reports_view`, `dashboard`, `clusters_view`, `list_sources`, `about`); raises `RuntimeError` with the offending name if any nav entry references a missing route.

**Spend this session:** zero LLM cost (refactor + docs only).

---

## 2026-05-14 (Phase 3c.9 → 3c.12 shipped) — Stories rename · /stories URL · header tags · Run-pipeline button · cluster toggle · section overlay (multi-chip) · dropdowns · incremental clustering · legacy clusters dropped

**Scope:** UX cleanups (corpus sidebar removed, Dashboard renamed to Stories), home-page header chrome (last pull / last workflow chips + Run pipeline button), `/clusters` cluster-cards/list toggle + section chips + section + week dropdowns, "See all stories this week →" footer links on the 7 editorial home cards, same dropdowns on Stories, first end-to-end pipeline run (~$1.29) + W19 re-synth, incremental cluster_window + skip-synth-when-unchanged, multi-chip rendering per cluster (every section a cluster appears in, not just primary), 63 legacy `week_id='all'` clusters dropped, favicon link.

**Locked decisions:**

- **Corpus sidebar block deleted from both `_sidebar.html` and `reports.html`**, plus all `corpus_stats(session)` calls dropped from `reports.py` / `about.py` / `sources.py` / `clusters.py` / `dashboard.py` template contexts. The helper itself stays in `services/reports.py` — three cheap COUNT queries, easy to bring back if a future surface wants them. Rejected: keeping the calls "just in case" — dead code rots, and the user explicitly said "not needed."
- **Nav label "Dashboard" → "Stories"; route URL `/dashboard` → `/stories`; file path stays `app/routers/dashboard.py`.** The file rename was deferred to keep blast-radius small (the file name is internal; HTMX `hx-get` URLs all point to `/stories` now, and there's only one import in `main.py` to fix later). Rejected: full rename including the file — pure churn for a one-line readability win.
- **Stories scoped to trailing 7 days, no row cap.** The old `_ITEM_LIMIT = 50` was deceptive: header said "988 items" while list showed 50. Filtering to `published_at >= now - 7 days` makes the header (now "267 items · last 7 days") match what the user sees, and rendering ~267 rows is fine for a single-user local table. Week dropdown adds explicit per-ISO-week filtering for digging into specific weeks. Rejected: keep the 50-row cap with pagination — adds UI surface for a problem (corpus size) that doesn't exist at this scale.
- **`/clusters` default flipped from `week_id='all'` → multi-week (excludes legacy `week_id='all'`).** Pre-3c.9 the route defaulted to the legacy 63-row partition that wasn't tied to any week's read-out. New default: all per-ISO-week clusters across weeks, with the dropdown allowing per-week filtering. Explicit `?week_id=all` still works. **Then the 63 legacy `week_id='all'` rows were deleted from the DB** (with a JSON backup at `data/legacy_clusters_backup_20260514_023447.json`) since they were pre-Phase-3c spaghetti that flagged as cleanup back in Phase 3c.4. Rejected: keep them indefinitely — they polluted dashboards and confused counts without adding value.
- **Last-pull / last-workflow chips + Run-pipeline button on `/` header**, with a 6-day enable gate on the button. "Last pull" = `MAX(completed_at)` from `run_log WHERE job_type='ingest' AND status='ok'`. "Last workflow" = `MAX(synthesis_generated_at)` from `weekly_reports` (last user-visible read-out generation). Button enabled iff `now - last_pull > 6 days` OR last_pull is null — guards against accidental double-runs while remaining clickable on a fresh corpus. Rejected: in-process lock without UI gating — would let the user click 100 times in a minute even if only one actually fires, confusing UX.
- **`/pipeline/run-full` as a BackgroundTasks-driven endpoint with a module-level `threading.Lock`.** Returns a small HTML fragment via HTMX `hx-swap=outerHTML` to replace the button with a "Running… refresh in ~5 min" status. If lock is held, returns 409 + a "busy" chip. Rejected: APScheduler now — Phase 4 work, deferred. Rejected: split-process worker queue — violates CLAUDE.md "single Python process" lock.
- **`/clusters` view toggle = CSS-only radio inputs.** Both Cluster-cards and List views render in HTML; sibling `#view-list:checked ~ #clusters-list .gc-clusters-cards { display: none }` swaps. Rejected: HTMX server-side view-state — adds a roundtrip for what's pure presentation, and the data is already in context. Rejected: JS — no JS build step on this project (HTMX + Jinja only).
- **Editorial section chips on `/clusters` — list-of-sections per cluster, all rendered.** Phase 3c.10/3c.11 used a primary-section-wins model (Biggest > Risks > Drama > MM > Community > Esports > Watch). Phase 3c.12 flipped to "all sections, sorted by priority": a cluster that's Biggest #1 + Community-celebrating + Watch-Mon now renders three chips. Why: the primary-wins model silently masked W20's 4 community-tagged clusters (all 4 happened to ALSO be tagged in higher-priority sections), making it look on `/clusters` like community was empty when it wasn't. Multi-chip is the honest representation. Filter `?section=X` also inclusive — matches any cluster whose section list contains X. Stories item-section filter (`items_in_section`) inherits the same inclusive matching. Rejected: keep primary chip + reveal others on hover — fancier UI, doesn't help on touch / accessibility. Rejected: tweak priority order (e.g., community ahead of MM) — band-aid; multi-chip is the real fix.
- **Section + Week dropdowns added to BOTH `/clusters` and `/stories`** (HTMX-driven, `hx-include` pulls in the sibling filters). On Stories, the section filter computes the candidate item-id set by calling `items_in_section(session, available_weeks(session), section)` which walks the synthesis_json across all available weeks, picks clusters matching the section, and unions their `member_item_ids`. "Not surfaced" returns items in clusters that exist but aren't in any editorial section. Week dropdown options: clusters use `available_weeks(session)`; stories add "Last 7 days" as the default. Rejected: HTMX-driven multi-select filtering with chips — heavier UI; for a 4-week corpus the dropdown is plenty.
- **Per-card "See all stories this week →" footer link on 7 editorial cards** (Biggest / MM / Community / Risks / Drama / Esports / Watch — skipped on Hottest / Trends / Release because those are per-entity, not per-cluster). Link → `/clusters?week_id={active_week_key}` with no section pre-filter so the user lands on the full per-week cluster list with chips visible; they can use the section dropdown if they want to narrow. Rejected: pre-filter to the card's section — collapses to the same 3-5 items already on the home page, defeating the "show me more" purpose.
- **Incremental clustering replaces destructive rebuild for pipeline runs.** New `cluster_window_incremental(start, end, week_id)` appends newly-embedded items to their best-matching existing cluster (cosine ≥ 0.85 on centroid), creates fresh clusters only for items that don't fit. **Preserves existing cluster IDs and labels** — synthesis_json references stay valid across runs. Only new clusters get Sonnet labels. Rejected: keep destructive rebuild and just re-synth every week — wastes ~$0.20-0.40 of Sonnet labels per run for clusters that haven't changed, and forces re-synth of prior weeks (costly + churns the editorial picks). The destructive `cluster_window` stays in the codebase for `scripts/run_cluster.py` and the `POST /clusters/run` endpoint (use cases that want a clean rebuild).
- **Pipeline skips synthesis when current week's cluster set didn't materially change.** After incremental cluster step, if `items_appended_existing == 0 AND clusters_new_created == 0`, the synthesis step is skipped entirely. Saves ~$0.35 Opus cost on no-op pipeline re-runs. Prior week's synthesis is never auto-re-run regardless (user pref: "leave old read-outs stable"). Rejected: always re-synth — wastes Opus on weeks where nothing changed. Rejected: auto re-synth when prev week changed materially — adds cost without user demand; manual `--force` re-synth is one CLI line.
- **Cumulative spend on this session: ~$2.34** (W17 backfill $0.35 in 3c.8 + W18 backfill $0.35 in 3c.8 + pipeline $1.29 + W19 re-synth $0.35 + misc Haiku ~$0.001). Project cumulative ~$9.90.

**Verification (`:8001 --reload`):**
- All endpoints 200. Multi-chip rendering verified by inspecting W20 (5 clusters with 2-3 chips each — Capcom record profits = Biggest #1 + Community celebrating; Subnautica 2 leak = Biggest #3 + Community heated + Watch TBA; Kickstarter adult ban = Risk med + Community heated; Capcom revivals = MM structural + Community celebrating + Watch TBA; CCP Games rebrand = MM structural + Watch TBA). Community chip totals: W19 went 1→3, W20 went 0→4.
- Section filter inclusive: `?section=community` on `/clusters?week_id=2026-W20` now returns 4 cards (was 0). Same on Stories.
- Incremental cluster test (called directly after pipeline): processed 427 W19 + 312 W20 items, appended 6 + 7 to existing clusters, created 0 new clusters, called 0 Sonnet labels, cost $0. Cluster IDs untouched. The 13 appends are genuine matches that were missed by the destructive pass's within-week connected-components (they're singletons in their own week but match an existing centroid above 0.85 — broader rescue).

---

## 2026-05-13 (Phase 3c.8 shipped) — Card reorder, mention badges, scrollable releases, /about, W17/W18 backfill

**Phase 3c.8 scope:** Tighten the `/` weekly read-out (card reorder, Biggest mention counts, release radar scroll), add `/about` as an infographic explainer of the pipeline, fix the sidebar corpus-stats truncation, and backfill weekly synthesis for the two earlier weeks (W17, W18) so the sidebar Read-out tabs are real reports, not "Awaiting synthesis" placeholders.

**Locked decisions:**

- **Card order on `/` is locked.** Top group (span-2 Biggest + Hottest + Market momentum + Trends + Community sentiment) unchanged. Bottom group reordered to **Industry risks → Controversy tracker → Esports & streaming → Release radar → Watch next week**. Rationale (user-driven): cluster risk-themed cards (risks + controversy) together, then forward-looking cards (release + watch) together, with esports as the bridge. Rejected: a router-side ordering knob in `_apply_synthesis` — order is a presentational concern and template iteration order is the only thing the cards' flat dict layout depends on, so a template-block swap is the right level.
- **Biggest mention count is derived at render-time from `clusters.member_item_ids`, not added to the synthesis JSON schema.** A small inline `SELECT id, member_item_ids FROM clusters WHERE id IN (...)` in `_apply_synthesis` returns the cluster member counts; the template renders them as `gc-mention-badge` chips alongside the existing source pills inside `gc-biggest-sources`. Rejected: extending the `WeeklySynthesis` Pydantic schema with a `mention_count` field and re-running Opus for W17/W18/W19. Reason: count is a corpus fact, not an editorial judgement — there's no reason to spend Opus tokens on a number that's already in the DB. Also, deriving at render-time gives us the badge on W17 + W18 immediately without another synthesis re-run after the backfill.
- **Release radar: height-capped scrollable container, not a Jinja slice.** "Show top 6 at a time, scrollable within that card size" interpreted as: visible-window of ~6 with overflow-scroll for the remaining items, not a hard 6-cap. The existing `upcoming_releases(..., limit=10)` query stays the same; new `.gc-row-list--scrollable` class (`max-height: 320px; overflow-y: auto`) caps the visible height. Rejected: `{% for r in releases[:6] %}` slice — would have hidden 4 future-release items entirely with no UI affordance to reach them. Rejected: increasing the query limit and slicing in Python — same problem at a different layer.
- **Sidebar truncation fix: tighten padding + `overflow-y: auto` fallback, not structural reflow.** Pre-3c.8 sidebar layout was `display: flex; flex-direction: column; height: 100%` with `.gc-sb-bottom { margin-top: auto }`. The combination correctly anchored the corpus stats at the bottom but had no scrollback affordance when total content exceeded viewport height, so the corpus block got clipped on shorter screens. Fix: net ~20px of padding savings (`16px 8px → 12px 8px 8px` on `.gc-sidebar`, 12 → 8 on `.gc-sb-bottom` padding-top, `10px 12px → 8px 12px 4px` on `.gc-sb-corpus`), plus `overflow-y: auto` on `.gc-sidebar` and `flex-shrink: 0` on `.gc-sb-bottom`. The padding savings more than offset the new 5th nav item (~33px); the overflow-y handles long-tail very-short viewports. Rejected: restructuring the sidebar into "scrollable middle (weeks + nav) + fixed bottom" — would have required a new flex wrapping container around two of the existing sections; not worth the structural churn when ~20px of padding does the job for the common case.
- **`/about` is a 5-stage horizontal pipeline + glossary, not a narrative explainer.** Per user "infographic and visual, not scrolling/text death." Five equal-width cards (Ingest / Enrich / Cluster / Synthesize / Render), each with a colored top-border for visual stage-coding (blue / purple / green / accent / gray), a 44×44 circular Lucide icon, a beginner-friendly one-sentence description, and a dashed-border tech-detail line. CSS `::after` chevrons between cards visualize data flow. Below the flow: two side-by-side panels — a 6-term glossary (RSS / LLM / Embedding / Clustering / Sentiment / Critic pass — defined in plain non-technical language) and a "Stack & numbers" panel (Python/FastAPI, SQLite, HTMX, Ollama, Anthropic, ~$0.35/week, single-process, local-only). The whole page fits on one screen at ≥1080px. Responsive: 2-col stack at <1080px (chevrons hidden), full single-column at <640px. Rejected: a `/docs` or `/architecture` page with multi-paragraph prose — outsider visitor would face a wall of unfamiliar terms (RSS, LLM, embedding, cluster, etc.) and a long scroll. The 5-stage flow with a paired glossary teaches the pipeline in a single glance.
- **About route is its own router file (`app/routers/about.py`).** Matches the convention: each top-level route gets its own router. Rejected: shoving the `/about` GET into `reports.py` — `reports.py` already mixes the `/` view, the drawer fragment, the exec-summary modal, and the export endpoints; adding an unrelated About route would have grown that file's responsibility surface further.
- **Nav item add is one line in `chrome.py`.** Added `{"id": "about", "label": "About", "icon": "info", "href": "/about"}` to `NAV_ITEMS_BASE`. Both the shared `_sidebar.html` and the hardcoded sidebar in `reports.html` iterate `nav_items` so neither template needed to change. This validates the Phase 3c.7 `chrome.py` abstraction — the cost of adding a nav item is now O(1).
- **Historical raw-item backfill rejected for W17.** W17 has 4 clusters (77 items); thin for synthesis. The user asked "based on data we have, or if more scraping is needed." Investigation: `scrapers-lib` tier1 modules (`rss`, `youtube`, `article`) have no date-range parameters; RSS feeds only return recent items; the Reddit PRAW path is unavailable (API rejected). Conclusion: the corpus for past weeks is fixed at whatever was captured during those weeks — backfill of raw items isn't possible without changing the scraping architecture. This matches the CLAUDE.md "out of scope: backfill of historical data — accept cold start" lock. Synthesized W17 from the 4 available clusters anyway — Opus handled the thin corpus gracefully (3 biggest / 2 MM / 2 risks / 0 esports / 0 drama / 5 watch); some bottom-row sections rendered the empty-state "No stories in this week's corpus" message rather than fabricating.
- **Synthesis backfill cost ~$0.70 (W17 + W18), not $1.80.** CLAUDE.md's $1.80 figure budgeted for cluster relabel + synthesis + critic for both weeks. In practice, cluster relabeling was already done in Phase 3c.4 (no NULL labels), so only the two Opus passes per week ran. Actual: $0.35/week × 2 weeks = $0.70. Updates the project's cumulative spend estimate from ~$7.56 to ~$8.26.

**Verification (`:8001 --reload`):**
- `/?week=2026-W19` → 200 / 59242 bytes. Card-header substring index sequence: Industry risks (45374) < Controversy tracker (47534) < Esports (48726) < Release radar (49180) < Watch next week (55211) ✓. 3 mention badges in Biggest. `gc-row-list--scrollable` class on release radar.
- `/?week=2026-W18` → 200 / 55762 bytes. Same card-order pattern. 3 mention badges. Synthesis-driven cards (Biggest / MM / risks / 1-item drama) populated.
- `/?week=2026-W17` → 200 / 50084 bytes. Same card-order pattern. 3 mention badges. Thin-corpus cards (esports / drama empty) render their "No stories in this week's corpus" empty state — no fabrication.
- `/about` → 200 / 8003 bytes. `gc-about-flow` present, all 5 stage cards (`gc-about-step--ingest/enrich/cluster/synth/render`), glossary present (6 terms), stack panel present.
- About active in sidebar nav: ✓.
- W17 + W18 sidebar Read-out tabs now lead to real reports (not "Awaiting synthesis" placeholders).
- No orphan WatchFiles gotcha this session; uvicorn `:8001` reloaded cleanly across all edits.

**Anthropic spend this session:** ~$0.70 (W17 + W18 Opus + critic). Cumulative ~$8.26.

---

## 2026-05-13 (Phase 3c.7 shipped) — UI consistency + live search

**Phase 3c.7 scope:** Routing swap (`/` = home = weekly read-out), Dashboard / Clusters / Sources re-skinned to share the `/reports` design system, HTMX live-search on each of the three engineer-inspection pages.

**Locked decisions:**

- **`/` is the weekly read-out; `/dashboard` is the raw items table.** Pre-3c.7 the layout was `/` → raw items table, `/reports` → polished read-out. Flipping makes the actual product surface (the read-out) the home URL. Internal HTMX sub-endpoints stay at `/reports/exec-summary`, `/reports/drawer`, `/reports/export` — kept the namespace because (a) they're fragment endpoints, not user-facing routes, and (b) renaming them would have churned all the existing HTMX trigger attributes for zero gain. Rejected: redirecting `/reports` → `/` for backward-compat — this is a personal local tool with no external links to break.
- **Light re-skin chosen over full `gc-row` card style for the inspection pages.** Each non-home page (Dashboard / Clusters / Sources) wraps content in the shared shell (sidebar + header chrome) and uses the gc design tokens (Arial Nova font, orange accent, surface/border colors), but the actual content stays as a table or labeled-list — what fits the page's purpose. Rejected: converting Dashboard items to `gc-row` cards in the Hottest/Trends visual pattern. Reason: Dashboard is engineer-inspection, not editorial — a table at ~25px/row is denser and easier to scan than a card at ~80px/row.
- **`shell_base.html` does NOT cover `reports.html`.** The Reports page keeps its own inlined shell because its sidebar has a per-week Read-out section that the other pages don't have, and its header has a different actions/breadcrumb shape. The shared chrome covers Dashboard / Clusters / Sources only. Rejected: forcing reports.html to extend shell_base too — would have required heavy block-overriding for the week-list + Exec-summary CTA, increasing fragility for no rendering benefit.
- **Sidebar partial conditionally renders the week-list block** based on `weeks_index` being in context (truthy). Dashboard / Clusters / Sources don't pass it; only the reports route does. One template, two render modes. Rejected: two separate sidebar files; the divergence is one block of ~10 lines and the conditional reads cleanly.
- **`app/services/chrome.py` is the single source of truth for the nav.** `NAV_ITEMS_BASE` + `nav_items_for(active_id)` helper. All four routes call this. Rejected: duplicating NAV_ITEMS in each router; if a fifth route is added (e.g. `/runs` in Phase 4), it's one line in `chrome.py` instead of four places.
- **One HTMX endpoint per page, branching on `HX-Request` header.** Live-search uses `hx-get="/dashboard?q=..."` (same path as the full page) with a server-side `if request.headers.get("HX-Request"): return fragment`. Rejected: separate `/api/dashboard` or `/dashboard/fragment` routes — would have doubled the URL surface for no semantic gain. The fragment-detection idiom is HTMX-canonical.
- **300ms keyup debounce** on the search input. Standard HTMX pattern (`hx-trigger="keyup changed delay:300ms"`). Rejected: shorter delays (50-100ms) — would have fired requests on every keystroke without measurable UX gain on a SQLite ILIKE that already returns in <10ms locally.
- **`hx-push-url="true"` on the search input** so the URL stays in sync as the user types. Filtered searches are bookmarkable / shareable / back-button-able. Rejected: keeping the URL bare and only mutating the DOM — would have broken the "share this filtered view" affordance with no benefit.
- **Drawer pill rendered inline as `<span class="gc-pill">` (not via the `source_pill` macro).** The macro emits `<a class="gc-pill" href="#">`; nesting it inside the drawer's outer `<a class="gc-drawer-item" href="..." target="_blank">` produced two empty bordered rectangles per item (browser parser auto-closes the outer `<a>` when it sees the inner one). The `<span>` inline keeps the pill's visual styling without the invalid nesting. Other callers of `source_pill` (Biggest stories on the home page) are not inside another `<a>` so they keep the macro's `<a>` form.

**Verification (`:8001 --reload`):**
- `/` → 200 / 58706 bytes (weekly read-out).
- `/dashboard` → 200 / 54282 bytes; `?q=nintendo` → 200 / 55085 bytes (filtered to 50 most-recent matching items).
- `/clusters?week_id=2026-W19` → 200 / 82616 bytes (38 cluster cards); `?q=indie` → 200 / 13851 bytes (filtered to the Griffin-Gaming / Mixtape / Studio-Ricochet clusters).
- `/sources` → 200 / 24160 bytes; `?q=reddit` → 200 / 10919 bytes (filtered to r/* subreddit sources).
- `/reports` → 404 (routing swap verified).
- HX-Request fragment branch verified — no `<aside>` sidebar in the response when `HX-Request: true` is set.
- Sidebar correctly shows `is-active` on the matching nav item per page.
- Drawer rendered with `<span class="gc-pill">` × 5 (was `<a class="gc-pill">` × 5 before); empty rectangles gone.

No Anthropic spend this phase. Cumulative ~$7.56.

---

## 2026-05-13 (Phase 3c.6 shipped) — Executive 1-pager + standalone HTML / PDF export

**Phase 3c.6 scope:** Upgrade the "Exec summary" modal from a single Haiku paragraph to a structured 1-pager, and add Export HTML / Export PDF actions inside it. Persists rendered HTML to `weekly_reports.html_content` (the column reserved during Phase 3c.4). No new model spend — the 1-pager pulls from existing `synthesis_json`.

**Locked decisions:**

- **Modal body is the 1-pager; existing header CTA reused.** The header "Exec summary" button already exists from Phase 3c.3. Same `<label for="modal-open" hx-get="/reports/exec-summary?...">` trigger; only the response shape changes. Reason: the user's mental model is "one button for the read-out" — adding a second button or a dropdown would have introduced ambiguity. Rejected: a dedicated "Export" header button next to "Exec summary". The export buttons live inside the modal footer instead, so the user always previews before exporting.
- **1-pager composition: existing Haiku paragraph (lead) + structured bullets pulled from `synthesis_json`.** Sections: Biggest top-3 (numbered list + dek + source pills) → Market momentum top-3 (with category chip) → two-col Risks top-2 / Community (1 heated + 1 celebrating). Zero new LLM spend. Rejected: a new Opus call re-synthesizing the existing synthesis as a tight exec briefing (~$0.30/wk). Reason: the Haiku paragraph + structured bullets already fits on a page; running another LLM pass to "re-voice" the same data would have been pure cost.
- **PDF strategy: browser print dialog, not WeasyPrint.** `format=pdf` serves the same standalone HTML inline with `<script>window.print()</script>` injected after `</body>`; the OS print dialog appears and the user picks "Save as PDF". Rejected: server-side WeasyPrint (real PDF, one-click download) — adds ~50MB of cairo / pango deps, has Windows install quirks, and the locked stack is "single Python process, minimal deps". The print-dialog approach costs the user one extra click in exchange for zero new deps; acceptable on a personal local tool.
- **One stored doc, two render modes.** The cached `html_content` is the plain HTML (no auto-print script). The PDF route injects auto-print *after* the cache read via `export_svc.inject_auto_print()`. Rejected: caching the PDF-variant HTML separately, or computing two cache keys. Reason: a single canonical doc is simpler and avoids stale-cache divergence.
- **W17 / W18 (no synthesis) graceful degrade.** Modal renders the Haiku paragraph + a one-line `<code>scripts/run_synthesis.py {week}</code>` hint inside a dashed box; export buttons hidden via `{% if synthesis_ran %}`. Server-side guard still returns 409 on the export endpoint as defense-in-depth (URL-shared exports can't bypass the UI gate). Rejected: partial export of just Hottest / Trends / Releases for un-synthesized weeks. Reason: the 1-pager *is* the synthesis — without it, the exported file would be a misleading half-document.
- **Markdown export deferred to Phase 3d.** The `weekly_reports.markdown_content` column stays unused for now. Reason: the user's request was specifically "HTML or PDF in the modal" — no use case surfaced for a markdown artifact, and adding it would have inflated the modal footer with a third button. Will revisit only if needed.
- **Inline `<style>` blob, full `app.css` un-stripped (~33KB).** Standalone HTML embeds the entire `app.css` rather than computing a minimal subset. Reason: it's a personal local tool — 33KB is trivial, and a minimal-CSS pipeline (PurgeCSS or hand-curated subset) introduces drift risk. The export inherits all future CSS changes for free.
- **CSS file read cached at module level in `export_svc.inline_css()`.** First call reads `app/static/app.css` from disk; subsequent calls return the cached string. `refresh=True` re-reads for dev workflows. Rejected: reading from disk on every export (~15KB IO per call) — pointless when the file changes only on deploy. Rejected: bundling the CSS into a Python string at build time — no build step exists.
- **Export route uses `Response` directly, not `TemplateResponse`.** Because the response needs custom `Content-Disposition` for HTML download vs inline for PDF. Templates are still rendered via `templates.get_template().render()` but wrapped in a manual `Response` object. Idiomatic FastAPI; nothing fancy.

**Verification (`:8002` fresh uvicorn instance, no reload):**
- W19 modal: 200, 8747 bytes, 4 section labels, 10 list items (3+3+2+1+1), 2 export anchors, 3 MM category chips, 2 risk severity dots, 2 CS tags, two-col layout present, no-synth note absent.
- W18 modal (no synthesis): 200, 1724 bytes, 0 section labels, 0 export anchors, Haiku paragraph + nosynth note + run-synth CLI hint visible.
- W19 export HTML (cold): 200, 41935 bytes, `Content-Disposition: attachment; filename="gaming-chatter-2026-W19.html"`, no auto-print script.
- W19 export HTML (warm): 200, identical 41935 bytes — served from `weekly_reports.html_content` cache.
- W19 export PDF: 200, 42041 bytes (cold HTML + 106-byte auto-print script), no Content-Disposition (inline), `window.print()` script present before `</body>`.
- W18 export: 409 with plain-text "Synthesis hasn't run for 2026-W18 — Run: scripts/run_synthesis.py 2026-W18".
- Bad format: 400.
- DB: `weekly_reports.html_content` populated 41935 bytes after first W19 export.

**Anthropic spend this session: ~$0.001** (1 Haiku call for the W18 modal-degrade test which auto-generated a fresh exec_summary; no Opus, no synthesis re-run). Cumulative project: ~$7.56.

**`:8001` reloader was stuck again** (same orphan-worker pattern from last session — file touch + 2s wait didn't trigger reload; `/reports` worked because that endpoint hadn't changed but `/reports/export` returned 404 and the modal endpoint 500ed on undefined template vars from a partial Jinja reload). Verified on `:8002` fresh instance instead. User to restart `:8001` to validate in their main session.

**Visual revision (same day, after user reviewed first cut):** User's browser screenshot showed the 1-pager overflowing the modal's white box (body scrolling), and the export buttons in the footer were below the fold (invisible at the user's viewport height). User asked for "the export button at the top right next to the close button" and a "more interactive/visual/infographic (not too much)" layout. Re-shipped under the same Phase 3c.6 banner:

- **Export action moved from modal footer to header**, via a CSS-only `<details><summary>Export ▾</summary>` dropdown positioned `position: absolute; top: 12px; right: 50px` (sits left of the `.gc-modal-close` × at `right: 14px`). Panel pops below with `Save as PDF` + `Download HTML` anchors. Header `padding-right: 130px` clears both buttons. Rejected: native `<select>` (uglier styling, can't host anchor hrefs cleanly). Rejected: inline JS dropdown (locked stack is HTMX + Jinja only). The `<details>` element does open/close natively without script.
- **Modal footer dropped entirely.** Attribution caption moved to a 9.5px right-aligned `gc-onepager-attribution` line at the bottom of the body. Saves ~50px of fixed chrome → more room for content.
- **4-tile stat row added at top of body** (`items`, `sources`, `top game · N`, `top genre · N`). Reads from existing `top_games_for_week(limit=1)` + `top_genres_for_week(limit=1)`. Rationale: gives the 1-pager its "infographic" feel cheaply — no new query work, no new viz library. Rejected: a horizontal sparkline / mini-bar chart (locked walkthrough already deferred per-card sparkline geometry; reintroducing it here would have inverted that decision).
- **Biggest deks dropped from the modal** — single largest vertical-space contributor in the screenshot. Numbered list shows title + source pills only. The full deks still exist in `synthesis_json` and would surface in the cluster drawer if the user wanted to drill in. Rejected: CSS `line-clamp` to truncate deks visually — would have kept the dek tax (extra line per item) and looked uglier than just dropping the line.
- **Two-col Risks/Community → three-col MM/Risks/Community.** Market momentum joined the column strip instead of getting its own row. Saved one full section's vertical height. Column ratio `1.5fr 1fr 1fr` — MM gets more width since its category chips eat horizontal space. `gc-onepager-itemtitle--clip` ellipsis on titles inside columns.
- **Type scale shrunk ~25% overall** (lead 15→12.5px, numlist 13→12.5px, bul list 13→11.5px, section labels 10→9px, chip 9→8px). Stat tile values use a typographic hierarchy: 17px bold for numbers, 14px bold for names, 9px uppercase label.
- **Stale `html_content` cache for W19 invalidated** (one-line `UPDATE`) so the next export re-renders against the new layout. The cache-pattern itself stays canonical.

Total vertical compression: modal body went from ~700px to ~480px of content height (well under the 720p viewport minimum minus chrome). Export now visible without scrolling, dropdown next to close button as requested.

---

## 2026-05-13 (Phase 3c.5 shipped) — 9-card layout restructure: applied every locked walkthrough decision from 2026-05-12

**Phase 3c.5 scope** from the prior session's next-steps list: wire `/reports` to the full Phase 3c.4 synthesis output and apply every layout lock from the 2026-05-12 walkthrough. No new model calls; this is purely template + router + CSS structural work. Net result: the chrome trimmed to the walkthrough's spec, the 13-card grid cut to 10 (Card 1 / Card 8 / Card 9 dropped per spec; Trends was already re-instated as a single card so net is 10, not the walkthrough header's aspirational 9), and the four cards whose data was being stashed under `*_synth` keys (Biggest plural, MM, CS, Esports) became first-class render targets.

**Locked decisions (every one is from the 2026-05-12 walkthrough; this session is execution + a few small tactical micro-decisions called out below):**

- **Sidebar week-list source: kept `available_weeks()`** (clusters table) — the walkthrough spec said `weekly_reports desc by generated_at`, but the synthesis table currently has 1 row (W19) so switching would hide W17 + W18 from the picker. Decided to flip the source once the W17/W18 synthesis backfill runs (~$1.80; already on the optional-hygiene list). Stating this explicitly so the next session can audit and flip without rediscovery.
- **Empty-state messaging differentiates "synthesis hasn't run" vs "synthesis ran, list empty".** Gate: `synth_ran = week.cards.synthesis_meta`. When synthesis hasn't run for the week → action prompt with the exact CLI to run (`scripts/run_synthesis.py 2026-W18`). When synthesis ran and a card's list is honestly empty → topic-specific message ("No esports / streaming stories in this week's corpus" / "No exec / PR drama in this week's corpus" / "No layoff / regulation / legal stories in this week's corpus" / "No market-momentum stories in this week's corpus"). Reason: the same "Awaiting synthesis" string under both states misleads the reader.
- **Source pills on Biggest rows derived from cluster members, not synthesized.** New helper `source_pills_for_clusters(session, cluster_ids, limit=5)` queries `clusters.member_item_ids` → `items` → `sources` per cluster_id. Adds one extra query per `/reports` render (for the top-3 cluster_ids together). Rejected alternative: extend the synthesis Pydantic schema with a per-Biggest `sources: list[str]` field. Would have meant re-running W19 synthesis (~$0.90) with no editorial gain.
- **`gc-card-clickable` block deleted, not just unused.** The 3c.4 hover-tint card-as-whole click affordance was used only on the Biggest hero card; with the new plural row pattern using `gc-row-trigger` + `gc-biggest:hover`, the whole-card-clickable mechanism is dead code. Reverse decision possible if a future card wants whole-card click.
- **`_enrich_for_render` removed entirely.** All three things it did (Biggest hero sparkline geometry, momentum-cell sparkline geometry, esports.movers delta_tone) are no longer rendered. Sparkline-geometry helpers `sparkline_path` + `delta_tone` also removed. Reduces router surface by ~50 lines.
- **`_apply_synthesis` signature changed to take `session`** so the source-pills query lives next to the rest of the synthesis-to-card mapping. Alternative: caller pre-fetches pills and passes a dict. Rejected — the session is already available at the call site and the helper has a natural place to live.
- **Walkthrough header said 13→9, actual lock yields 10 cards.** Math: 13 originals - 3 dropped (Card 1, Card 8 Studio watch, Card 9 Storefronts) = 10. The walkthrough's "13→9" header was off-by-one — likely an inaccuracy in the moment, since the explicit per-card decisions sum to 10. Flagging here so it isn't relitigated later.
- **Jinja `corpus_stats['items']` bracket access, not `corpus_stats.items` attribute access.** Bug caught mid-verification: `dict.items()` is a built-in method, so Jinja's attribute-then-item resolution hits the method first and renders `<built-in method items of dict object at 0x...>`. Rejected alternative: rename the dict key. Bracket access is the smaller change and the only place this matters is the corpus-stats template block.

**Surfaced for next session:**
- The 7 "Awaiting synthesis" prompts on W17/W18 are an in-product callout for the W17/W18 synthesis backfill. Running `scripts/run_synthesis.py 2026-W17` + `... 2026-W18` would clear 14 prompts across the two weeks. Spend forecast: ~$1.80 (2× the W19 ~$0.90 run). Becomes the natural unlock for the sidebar-week-list source flip noted above.

**State:**
- Files modified: `app/services/reports.py` (+ `corpus_stats` + `source_pills_for_clusters` helpers), `app/routers/reports.py` (heavy refactor — see SESSION_LOG), `app/templates/reports.html` (Cards 2/4/6/10 rewritten; Cards 1/8/9 + standalone headline + footer hint + header toggles + sidebar CTA + avatar dropped; Risks trend chip dropped; empty-state pattern added across 6 cards), `app/static/app.css` (~17 dead blocks dropped + 5 new blocks added).
- No corpus / DB state change.
- No Anthropic spend.

**Rejected / reversed:**
- **Render Biggest as one hero + 2 secondary rows** — rejected. The walkthrough explicitly says "Top-3 clusters by score… top-3 are usually close in score and equally relevant; heroing one is a forced choice." Implemented as three equally-weighted rows.
- **Source pills via synthesis schema extension** — rejected; see above.
- **Switch sidebar to weekly_reports table per walkthrough spec** — deferred; see above.
- **Remove `gc-ghost-link` along with the other footer-hint cleanup** — the Calendar → link in Card 11 Release radar still uses it. Restored.

---

## 2026-05-13 (Phase 3c.4 shipped) — Synthesis (Opus 4.7 + critic) + Sonnet 4.6 cluster labels + cluster drawer

**Phase 3c.4 scope** from the prior session's next-steps list: ship the weekly synthesis pipeline (Opus 4.7 structured call + Opus 4.7 critic pass), migrate `label_cluster()` to Sonnet 4.6, wire the synthesis output into the `/reports` template, and extend the source drawer with a `kind=cluster` variant so Biggest / Risks / Drama / Watch rows drill into their cluster's articles.

**Locked decisions:**

- **One big structured Opus call, not per-section.** The synthesis returns a single `WeeklySynthesis` Pydantic instance covering all 9 cards (biggest plural, hottest_reasons, market_momentum, community_sentiment, risks, esports, drama, release_notes, watch + an exec_summary_paragraph). Per-section calls would 7-9× the cost; the PRD lock at $1-5/month and the 2026-05-11 lock at "~$0.30/run" both presume the single-call shape. Confirmed in this session — single call delivered the full schema in ~33s.
- **Critic returns the revised synthesis (drop-and-replace), not a critique-with-notes-then-merge.** Simpler control flow: synthesis pass → critic pass → persist the critic's output. Critic prompt explicitly tells the model to drop items that fail groundedness checks, fix section-placement mistakes (a layoff in MM belongs in risks, etc.), and tighten prose. In W19 first run the critic dropped 1 of 3 risks items (presumably out-of-scope) and preserved the rest.
- **Field max_length is a runaway-output guardrail, not a design cap.** First W19 run hit Pydantic validation failure on `hottest_reasons[1].reason` (158 chars vs my 140 cap) and `community_sentiment.narrative` (360 vs 320). Burned the synthesis-pass spend (~$0.40). Lesson: LLM output length is inherently soft; hard-capping at "design intent" creates brittle retries. Re-tuned every field's `max_length` to ~2x the editorial target (e.g. `reason` → 280, `narrative` → 700). Prompt still encodes the editorial intent ("≤140 chars; one sentence"); Pydantic only rejects egregious overruns.
- **Synthesis persistence: 3 new columns on `weekly_reports`** — `synthesis_json TEXT` (full Pydantic dump as JSON), `synthesis_model TEXT` (resolved model id), `synthesis_generated_at TIMESTAMP`. Idempotent migration in `_migrate_weekly_reports_columns()` mirrors the 3c.3 pattern. The existing `markdown_content` / `html_content` columns stay reserved for the eventual standalone-HTML export (Phase 3d).
- **Exec-summary modal switches authority on synthesis.** When `synthesize_week()` runs, it **overwrites** `exec_summary_text` + `exec_summary_model` + `exec_summary_generated_at` with the synthesis's `exec_summary_paragraph` and `claude-opus-4-7`. The 3c.3 Haiku-side modal endpoint still serves cached `exec_summary_text` — it just now serves the deeper Opus version once synthesis has run. Verified end-to-end: modal footer reads `cached · claude-opus-4-7 · generated May 13, 18:42 UTC`.
- **Sonnet 4.6 `label_cluster()` mirrors the `tag_game()` pattern.** New `ClusterLabelData` Pydantic + `CLUSTER_LABEL_SYSTEM_PROMPT` + `label_cluster(titles, tldrs)` in `app/services/anthropic.py`; `cluster.py` import swapped from `ollama` → `anthropic`. Prompt refined for Sonnet's tighter instruction-following: added "If the cluster spans multiple sub-topics, pick the dominant one" + a `Gamescom 2026 trailer roundup` example to model multi-item handling. `ANTHROPIC_CLUSTER_LABEL_MODEL` env-overridable, default `claude-sonnet-4-6`.
- **One-time relabel of all 55 per-week clusters.** New `--relabel-existing` flag on `scripts/run_cluster.py` re-labels every cluster row in place (no re-clustering — centroid, members, score, week_id untouched). Filters out the 63 legacy `week_id='all'` rows since their cleanup is deferred. Ran in 101s with 55/55 success and zero failures; ~$0.10 spend. Sonnet labels are visibly sharper than the qwen2.5:7b originals: "2K NFL and MLB game future" → "Take-Two exits NFL and MLB licensed sports games"; "Star Fox 64 remake announced for Switch 2" → "Star Fox 64 remake preorders live for Switch 2" (more specific current state).
- **Drawer extended with `kind=cluster`** alongside the existing `game / genre / platform / event` kinds. Value is the integer `cluster_id`; service fetches the cluster's `member_item_ids` JSON list, joins to items + sources + enrichments, returns the same per-article dict shape the other kinds use so the existing `_drawer.html` fragment renders unchanged. Drawer header swaps the bare numeric value with the cluster's `label` so it reads as a topic, not "Cluster 117". Row triggers wired in `reports.html`: Biggest hero card (whole card clickable; uses inline `onclick="document.getElementById('drawer-open').checked=true"` because `<label>` can't contain interactive form controls like the "Read in detail" button), Risks rows, Drama rows, Watch rows (only when `cluster_id` is present).
- **Synthesis output wired by router into the existing 13-card template, not into the locked 9-card layout.** `_apply_synthesis()` in `app/routers/reports.py` merges the synthesis JSON into the cards dict: Biggest → first item of the plural list (rest stashed under `cards["biggest_list"]` for Phase 3c.5); risks/drama/watch → adapted to the existing template row shapes; hottest_reasons/release_notes → overlaid onto top_games / upcoming_releases by case-insensitive game-name match. Shape mismatches (community_sentiment, market_momentum, esports) are stashed under `cards["*_synth"]` keys for Phase 3c.5 to render once the layout restructure lands.
- **Watch card lost its "+" Add-reminder button** (locked walkthrough decision: "no push delivery infra — out of scope per CLAUDE.md"). Replaced with an empty span to preserve the existing grid.

**Verified end-to-end on `:8001`:**

- **Relabel:** `python scripts/run_cluster.py --relabel-existing` — 55/55 success, 101s, ~$0.10. Sample W19 labels are sharper.
- **Synthesis dry-run:** `python scripts/run_synthesis.py 2026-W19 --dry-run` — input prompt ~40k chars / ~10k tokens, well within Opus's window.
- **Synthesis live:** `python scripts/run_synthesis.py 2026-W19` — synthesis pass returned biggest=3 MM=5 risks=3 esports=0 drama=1 watch=5; critic pass returned biggest=3 MM=5 risks=2 (dropped 1 out-of-scope item) esports=0 drama=1 watch=5. 57.7s total wall-clock. Persisted as 7395-char JSON.
- **First-run spend:** ~$1.30 actual (the burned synthesis call from the Pydantic-cap retry ~$0.40 + the second-attempt full run ~$0.90). Above the $0.45 forecast but inside the $1-5/month PRD target.
- **Router:** `/reports?week=2026-W19` 200, hero card title "Nintendo announces Star Fox 64 remake for Switch 2, dated June 25"; risks (2 items): "UK age-verification laws draw coordinated opposition" / "Wizardry IP ownership disputed between Atari and Drecom"; drama (1): "Mortal Kombat 2 producer attacks critics over negative reviews"; watch (5): specific releases + IP-dispute follow-up + Xbox lineup tracking. 7 cluster-drawer triggers + 14 reason/note sublines on Hottest/Releases rows.
- **Cluster drawer:** `/reports/drawer?kind=cluster&value=81&week=2026-W19` 200, header "Cluster · Star Fox 64 remake announced for Switch 2 · 7 items · Week of May 4, 2026"; lists the 7 actual articles in the cluster with source pills + outbound links.
- **Modal:** `/reports/exec-summary?week=2026-W19` 200; footer reads `cached · claude-opus-4-7 · generated May 13, 18:42 UTC`; paragraph names Star Fox 64 / Griffin Gaming Partners $100M fund / Pearl Abyss CCP Games $120M sale / Mixtape reviews / UK age-verification opposition — every specific number and entity grounded in the corpus.

**Rejected / dropped:**

- **Per-cluster synthesis text on `clusters.synthesis_text`** — would be ~55 extra Opus calls per week (~$15/wk) vs the single weekly synthesis. The drawer's existing kind=cluster path lists member articles directly, which is sufficient editorial context. Per-cluster narrative deferred indefinitely; revisit only if drawer feels too thin after a few weeks of use.
- **`:target` URL fragment for the Biggest hero card click** — `<label>` can't wrap the hero card because the card contains a "Read in detail" button (an interactive form control); the radio + `<label>` trick from 3c.3 doesn't work here. The Biggest card uses a one-line inline `onclick` to flip the radio + HTMX `hx-get` for the fetch. This is the only inline-JS use in the page; acceptable.
- **Full layout restructure to 9 cards in this session** — explicitly out of scope per the session-scope question. Card 1 ("This week in gaming") still renders; Card 8 (Studio watch) and Card 9 (Storefronts) still render as placeholders; the standalone headline block above the grid still renders. All deferred to Phase 3c.5.
- **Pre-generating synthesis up-front in the route handler** — would force every `/reports` load to wait on Opus on first miss. Lazy + cached + manually-triggered via `scripts/run_synthesis.py` is the right shape for a personal-local app; Phase 4 will move the trigger to the Monday APScheduler job.
- **Critic returns a critique-then-merge** — modeled but rejected. Drop-and-replace is one call simpler and avoids merge ambiguity (which critique points override which original fields?).
- **Locking `max_length` at the design-cap value** — first W19 run made the case against it. Soft prompts + 2x guardrails is the right shape.

**Data layer additions:**

- `app/db/models.py`: `WeeklyReport` gains `synthesis_json TEXT`, `synthesis_model TEXT`, `synthesis_generated_at TIMESTAMP` (all Optional).
- `app/db/init.py`: `_migrate_weekly_reports_columns()` extended idempotently with the 3 new columns.
- `app/config.py`: `ANTHROPIC_CLUSTER_LABEL_MODEL` (default `claude-sonnet-4-6`), `ANTHROPIC_SYNTHESIS_MODEL` (default `claude-opus-4-7`).
- `app/services/anthropic.py`: `ClusterLabelData` Pydantic + `CLUSTER_LABEL_SYSTEM_PROMPT` + `label_cluster()`.
- `app/services/cluster.py`: import swap (`ollama` → `anthropic`).
- `app/services/reports.py`: `_DRAWER_KINDS` set extended with `"cluster"`; `items_for_entity_in_week()` extended with the `cluster` branch (resolves `value` as int cluster_id, fetches member_item_ids JSON, joins to items/sources/enrichments).
- `app/services/synthesis.py` (new module, ~590 lines): `WeeklySynthesis` Pydantic hierarchy (10 nested classes + 2 Literal enums), `_SYNTHESIS_SYSTEM_PROMPT` + `_CRITIC_SYSTEM_PROMPT` (~5k chars combined), `_build_input_dict()` + `_format_input_for_prompt()` input assembler, `_call_opus()` SDK wrapper, public `synthesize_week(session, week_id, force=False) -> dict`. System block carries `cache_control: ephemeral` marker (forward-compatible with prompt caching once the prefix grows past Opus's cacheable minimum).
- `app/routers/reports.py`: `_load_synthesis()` + `_apply_synthesis()` overlay logic; `_DRAWER_KIND_LABELS` extended with `"cluster": "Cluster"`; drawer endpoint resolves cluster id → label for the header display.
- `scripts/run_cluster.py`: `--relabel-existing` flag + `_relabel_existing()` helper (filters out legacy `week_id='all'` rows).
- `scripts/run_synthesis.py` (new): CLI driver with `--force` and `--dry-run` flags. Calls `init_db()` at import so the script works without the FastAPI lifespan.
- `app/templates/reports.html`: Biggest hero card wrapped with `gc-card-clickable` + inline radio-toggle when `cluster_id` present. Risks / Drama rows conditionally rendered as `<label>` triggers when `cluster_id` present. Watch rows conditionally rendered as `<label>` triggers (and the "+" Add-reminder button removed).
- `app/static/app.css`: `.gc-card-clickable` + `:hover` rule, `.gc-row-reason` (Hottest/Releases sublines), `.gc-row-trigger:hover` extended to color `.gc-risk-title / .gc-drama-title / .gc-row-item`.

**Surfaced (not fixed) — `r.trend` field still rendered.**

The existing Risks template still includes `<span class="gc-risk-trend">{{ r.trend }}</span>` reading from a placeholder `"stable"` value the router-side adapter sets. Locked walkthrough decision was "trend chip dropped — 'rising' requires multi-week corpus we don't have yet." The chip is still in the DOM and now reads `stable` for every risk. Drop in the Phase 3c.5 template cleanup.

---

## 2026-05-13 (Phase 3c.3 shipped) — Source drawer + Exec-summary modal port

**Phase 3c.3 scope** from the prior session's next-steps list: port the right-side Source Drawer and the Exec-summary modal from `.tmp_design_bundle/`, wire row clicks (Hottest / Trends / Releases) into the drawer, and put a Haiku 4.5 paragraph behind the exec-summary modal trigger.

**Locked decisions:**

- **Drawer orientation: entity-drill, not source-drill.** The bundle's React `SourceDrawer` (`shell.jsx:186-280`) takes a single source name (e.g. "IGN") and lists what that source covered. The card-side click intent — "Mixtape +2.7pp" on Trends → see the articles that backed that mention — is the inverse. The port reuses the bundle's visual shell (440px right-slide aside, header + body + footer, dark backdrop) but flips the data model: drawer queries are keyed on `(kind, value, week_id)` where `kind ∈ {game, genre, platform, event}`. Source pills inside the drawer items still link out to the source, which gives back the bundle's source-side affordance from a different surface.
- **Drawer scope: Trends + Releases + Hottest.** The SESSION_LOG listed Biggest / Momentum / Risks / Trends / Releases, but the first three are still 3c.4 placeholders with no real entity to drill into. Hottest has identical row shape to Trends and real data behind it, so it's in scope too. Biggest / Momentum / Risks drawer wiring will land alongside their data in 3c.4.
- **Toggle mechanism: hidden radio + `<label for>` triggers (CSS-only state).** Two named radio groups at the top of `<body>` — `drawer-state` (`drawer-closed` checked default, `drawer-open`) and `modal-state` (`modal-closed` checked default, `modal-open`). Every clickable row is a `<label class="gc-row gc-row-trigger" for="drawer-open" hx-get="..." hx-target="#source-drawer-body">`; clicking flips the radio (CSS reveals the panel) and HTMX fires the fragment fetch at the same time. Close is a `<label for="drawer-closed">` on the overlay backdrop and on the × button. Mirrors the existing `.gc-hot-tabs` / `.gc-trend-tabs` radio pattern; zero new JS introduced.
- **HTMX wired into `reports.html`'s `<head>`** (`<script src="https://unpkg.com/htmx.org@2.0.3">`). The standalone template doesn't extend `base.html`, so HTMX has to load here independently. Drawer + modal triggers are the first HTMX users on this page; existing CSS-only tabs are untouched.
- **Exec-summary model: Anthropic Haiku 4.5.** Same model family as per-item enrichment. Costs ~$0.001 per cache-miss call; one call per week; 1-paragraph output. Sonnet 4.6 and Opus 4.7 rejected for this lightweight headline use; Opus 4.7 remains reserved for Phase 3c.4 deep synthesis + critic.
- **Exec-summary persistence: `weekly_reports` table.** Three idempotent columns added — `exec_summary_text TEXT`, `exec_summary_model TEXT`, `exec_summary_generated_at TIMESTAMP`. Cache key is `week_start` (Monday of the ISO week, derived from `iso_week_bounds()`). First open per week pays the Haiku call; every subsequent open serves from the DB. A separate `exec_summaries` table was rejected — `weekly_reports` already owns the week-grain and Phase 3c.4 will fill `markdown_content`/`html_content` on the same row.
- **Cache-bypass via `force=True` param** kept available on `exec_summary.get_or_generate()` for future re-generation after corpus re-enrichment. Not exposed in the UI yet — surfacing this is a 3c.5 polish question.
- **Exec-summary prompt voice: factual, terse, 3-5 sentences, no markdown, no first/second person, no hype words.** System prompt explicitly forbids fabricating game / studio / number / event values not in the input, and requires the lead sentence to name the strongest concrete signal of the week. Input is built per-call from `week_stats` + top 5 genres + top 6 platforms + top 5 games + Trends risers + top 6 upcoming releases — all from existing `services.reports` queries, no new aggregation duplicated. System block carries a `cache_control` marker (forward-compatible with prompt caching once it grows past Haiku's minimum cacheable prefix).

**Rejected:**

- **`:target` CSS via URL fragment** (`<a href="#source-drawer">`): rejected after a closer read — HTMX `hx-get` on an `<a>` `preventDefault`s the click, which suppresses the native hash navigation, so `:target` would never fire without an additional `hx-on::after-swap` setter. The radio + `<label>` trick achieves the same CSS-only state without any inline JS or hash pollution, and works identically for the drawer (single instance, content swap per click) and the modal.
- **Pre-rendering one drawer per possible entity in the page body**: rejected. Hot row counts vary per week (up to 5 per tab × 8 tabs ≈ 40 drawers for Trends alone) and the markup duplication wins nothing over a single shell + HTMX fetch.
- **Pre-generating the exec-summary in the route handler** (so the modal opens with the paragraph already filled): rejected. Forces every `/reports` load to wait on Haiku, even when the user never clicks "Exec summary". Lazy + cached is the right shape for a personal-local app.
- **A separate cron / batch step that fills exec-summaries up front**: deferred to Phase 4 alongside the Monday synthesis cron. Lazy-on-first-open is enough today.
- **Sonnet 4.6 or Opus 4.7 for the modal paragraph**: cost not justified for a 1-paragraph editorial intro. Haiku produced a clean read in the smoke test ("Star Fox dominated gaming coverage this week with 20 mentions and a 3.1 percentage-point rise…"). Sonnet stays reserved for 3c.4 cluster labels; Opus for 3c.4 synthesis + critic.
- **Showing the source-drill view (the bundle's original drawer) alongside the entity-drill view**: rejected. Two drawer flavors in one card grid would muddy the affordance; the bundle's source pills already link out to the source's URL/feed.

**Data layer additions:**

- `app/db/models.py` `WeeklyReport` — three new optional fields (`exec_summary_text` / `exec_summary_model` / `exec_summary_generated_at`).
- `app/db/init.py` — new `_migrate_weekly_reports_columns()` (idempotent ALTER pattern, mirrors `_migrate_games_columns()`).
- `app/services/reports.py` — new public `items_for_entity_in_week(session, kind, value, week_id, limit=25)` returning a list of dicts (id, title, url, published_at, when_display, tldr, sentiment_score, sentiment_summary, category, source_name, source_kind). Plus helpers `_drawer_source_kind()` and `_relative_when()`. Reuses the existing `json_each(e.entities, '$.games')` / `json_each(e.genres)` / `json_each(e.platforms)` / scalar-`e.event` patterns; nothing new at the SQL layer.
- `app/services/exec_summary.py` (new module) — `get_or_generate(session, week_id, force=False) -> dict`. Lazy Haiku 4.5 call, persistence to `weekly_reports`. Internal: `_build_input_text()` assembles a compact prompt body from `services.reports`; `_call_haiku()` wraps `client.messages.create()` with the system block + `cache_control`; `_load_cached()` looks up by `week_start`.
- `app/config.py` — `ANTHROPIC_EXEC_SUMMARY_MODEL` env-overridable, defaults to `claude-haiku-4-5`.

**Router / template additions:**

- `app/routers/reports.py` — two new endpoints: `GET /reports/drawer?kind=&value=&week=` returning the `_drawer.html` fragment; `GET /reports/exec-summary?week=` returning the `_exec_summary.html` fragment. Both handle bad inputs by rendering the same fragment with an `error` flag set. The `active_week_key` is now in the main `/reports` template context for trigger URLs.
- `app/templates/_drawer.html` (new) — header (kind eyebrow + entity name + meta), body (article cards: source pill + when + title + tldr + outbound `<a target="_blank">`), footer (placeholder note about 3c.4 deep synthesis). Uses `source_pill` from `_components.html`.
- `app/templates/_exec_summary.html` (new) — header (eyebrow + week label), body (single `<p class="gc-exec-paragraph">`), footer (`fresh|cached · model · generated-at` attribution).
- `app/templates/reports.html` — `<script>` tag for HTMX 2.0.3 in `<head>`; four hidden radio inputs as direct children of `<body>` (state radios for drawer + modal); drawer overlay + panel + close button + body wrap shell, modal overlay + card + close button + body wrap shell, all as direct children of `<body>`; three exec-summary trigger buttons (sidebar `.gc-sb-cta`, header `.gc-cta`, footer `.gc-ghost-btn`) rewritten as `<label for="modal-open" hx-get="...">`; `hot_rows()` macro rows rewritten as `<label class="gc-row gc-row--hottest gc-row-trigger" for="drawer-open" hx-get="...">`; `trend_rows()` macro takes a new `kind` parameter and wraps each row in a similar `<label>`; Releases row rewritten as a `<label>`.
- `app/static/app.css` — new block at end: `.gc-overlay-state` (hidden radio), `.gc-drawer-overlay` / `.gc-drawer-panel` / `.gc-drawer-close` / `.gc-drawer-header` / `.gc-drawer-title` / `.gc-drawer-meta` / `.gc-drawer-body-wrap` / `.gc-drawer-body` / `.gc-drawer-item` / `.gc-drawer-item-head` / `.gc-drawer-item-when` / `.gc-drawer-item-title` / `.gc-drawer-item-tldr` / `.gc-drawer-footer` / `.gc-drawer-foot-note`. Matching set for `.gc-modal-*`. `.gc-row-trigger` cursor + hover-tint shared between Hottest / Trends / Releases. `:checked ~ ` selectors on `#drawer-open` and `#modal-open` reveal each panel; overlays use `opacity + pointer-events` so the backdrop click still closes. `@media (prefers-reduced-motion: reduce)` disables the slide / fade transitions. HTMX `htmx-request` class drives a "loading…" / "Generating…" indicator inside each panel during fetch.

**Verified end-to-end on `:8001`:**

- `/reports?week=2026-W19` returns 200 with all wiring present (55 drawer triggers, 3 modal triggers, drawer + modal shells in markup).
- `/reports/drawer?kind=game&value=Mixtape&week=2026-W19` → 200, header `Game · Mixtape · 15 items · Week of May 4, 2026`, 15 article cards (Kotaku, Reddit, etc.) with source pills + tldrs + outbound links.
- `/reports/drawer?kind=genre&value=Action` → 200, 25 items (drawer limit). Same for `kind=platform&value=PC` (25 items), `kind=event&value=Summer Game Fest` (1 item).
- Empty / bad inputs return the fragment with the `error` flag; UI shows the empty-state row.
- `/reports/exec-summary?week=2026-W19` → first call 5.5s (Haiku cache miss), second call 2.1s (DB cache hit, `cached · claude-haiku-4-5`). DB row written: `week_start=2026-05-04`, `exec_summary_text` 635 chars, `model=claude-haiku-4-5`, `generated_at` set.
- Sample paragraph (W19): "Star Fox dominated gaming coverage this week with 20 mentions and a 3.1 percentage-point rise, driven by anticipation ahead of its June 25 release, while the remaster Star Fox 64 drew 12 mentions and a 2.2pp gain. Action and Adventure genres led discussion across 98 and 56 stories respectively, with PC platforms commanding 121 mentions and both Xbox and Nintendo platforms gaining ground week-over-week. Near-term attention is shifting toward May's release slate, including Thick As Thieves on May 20 and Batman & Robin on May 22, while MMO sentiment climbed 4.4pp with EVE Online picking up mentions alongside live-service tracking." Specific names, specific numbers, no fabrication, 3 sentences.

**Phase 3c.3 spend:** 1 Haiku call (~$0.001) during smoke test; cumulative project: ~$6.16, well under $500/yr ceiling.

**Surfaced (not fixed) — `Summer Game Fest` event tagging:**

- The drawer for `kind=event&value=Summer Game Fest` returned 1 item this week. Worth checking whether the corpus actually has only 1 Summer Game Fest mention or whether casing / phrasing variants are splitting the count. Not blocking 3c.4.

---

## 2026-05-13 (Phase 3c.2 shipped) — Trends card: 5-tab WoW mention-rate delta

**Phase 3c.2 scope** from the prior session's next-steps list: replace the Card 5 placeholder with a 5-tab Trends view (Games · Genres · Platforms · Live-service · Events). WoW only — MoM dropped pre-coding (locked 2026-05-12 walkthrough).

**Locked decisions:**

- **Delta math: mention-rate delta in percentage points.** Per-entity `(count_this / total_this) - (count_prev / total_prev)`, expressed as `+X.Xpp`. Chosen over raw count delta because corpus item volume swings 2–3× between visible weeks (W17 89 items, W18 189, W19 551); raw count would surface the busy week as positive for everything. Rate-delta normalizes that out.
- **New entries included.** Entities with zero prior-week mentions surface naturally — their prior rate is 0, delta equals their full this-week rate. This is exactly the "what's newly trending" signal a Trends card should expose.
- **Falling entries demoted, not dropped.** Sort is by signed `delta_pp DESC`, so negative-delta entities only show up when fewer than N (=5) positive movers exist. Entities with `count_this == 0` (gone-and-falling) are filtered — they'd skew the bottom without adding signal.
- **Threshold for tone:** `> +0.5pp` → up, `< -0.5pp` → down, else neutral. Below half a percentage point of corpus share is rounding noise, not movement.
- **Top-N = 5 per tab.** Matches Hottest's row count; trades exhaustive coverage for at-a-glance scannability.
- **Games tab has two stacked sub-sections** (Current + Upcoming) — not sub-tabs. Each runs its own filtered query against the games dim's `lifecycle` column.
- **Live-service tab is its own query** against the games dim (`g.live_service = 1`), not a chip filter on the Games tab. Surfaces the seasonal/battle-pass slice independently.
- **Events tab common-empty.** Per-pane `gc-row-empty` fallback ("No movement this week."). Most weeks have 0–2 events ever mentioned; that's a structural data property, not a bug.
- **Tab toggling: CSS-only radio pattern** (mirrors Hottest's `.gc-hot-tabs`). Five `<input type="radio" name="trend-tab">` inputs sibling to label + pane containers; `:checked ~` selectors flip the active label and pane. No JS, no HTMX call. Initial state: Games tab checked.
- **Empty-state gating: `has_prior` flag on the trends payload.** If `prev_total_items == 0`, the whole card renders a "Need 2 weeks of data" notice. In practice this only fires on empty-corpus runs — even the earliest visible cluster week (W17) has 20 items in its prior week W16.

**Rejected:**
- **Magnitude top-N** (sort by `abs(delta_pp)`): would interleave risers and fallers; muddies the "what's hot this week" read. Signed sort wins.
- **Filter to entities present in both weeks** (no new entrants): kills the most useful Trends signal — new game/event names that just broke. Rejected.
- **MoM tab alongside WoW:** locked out 2026-05-12. Will revisit if WoW proves insufficient after ≥4 weeks of clustered data.
- **Sub-tabs on Games tab** (Current / Upcoming as nested radios): adds CSS complexity; stacked sub-sections fit the card height and read just as cleanly.

**Data layer additions** (all in `app/services/reports.py`):
- `prev_week_id(week_id)` — handles year rollovers via `isocalendar()`.
- `week_item_total(session, week_id)` — denominator for rate calculations.
- `_tag_counts_for_week / _game_counts_for_week / _event_counts_for_week` — case-insensitive entity-count dicts keyed by `name.lower() → (display, count)`.
- `_merge_wow(cur, prev, cur_total, prev_total, limit)` — generic merge + sort, drops `cur_n == 0` rows.
- Five public `top_*_wow()` functions + a single `trends_for_week()` aggregator that returns the full 5-tab payload.

**Template / CSS:**
- Card 5 (`reports.html`) rewritten — new `.gc-trend-tabs` block with 5 inputs + labels + panes. Replaces the old `WoW · MoM` segmented toolbar in the card header (header now shows `Trends · WoW mention-rate delta` instead).
- Legacy `.gc-trend-tabs button` / `.is-active` rules deleted from `app.css`. New `:checked ~` rules added scoped to the five `#trend-tab-*` ids. Global `.gc-tab-input` / `.gc-tab-labels` / `.gc-tab-label` / `.gc-tab-pane` rules reused (unchanged from Phase 3c.1).
- New CSS: `.gc-trend-subhead` (uppercased mini-eyebrow for the Games sub-sections), `.gc-trend-name` (row name styling — replaces an inline style).

**Surfaced (not fixed) during Phase 3c.2 — out-of-taxonomy values still present in enrichments tags:**
- Genres column has rows like `MMO`, `Indie/Roguelike`, `Survival-horror`, `Multi-platform` despite the locked 12-genre taxonomy.
- Platforms column has `Multi-platform` despite the locked 6-platform taxonomy.
- Pydantic field validators in `app/services/ollama.py` were supposed to drop these, but they're showing up post-Haiku-backfill. Either the validators weren't ported through the Haiku enrichment path, or Haiku occasionally returns enums the validators silently allow.
- **Not fixed this session** — out of scope for the Trends layout work, and the values are honest reflections of what's in the DB. Either fix the validators + re-enrich, or add new entries to the taxonomy. Logged under "open hygiene" for the next session.

---

## 2026-05-12 (Phase 3c.1 shipped) — Real-data wiring for Week / Hottest / Releases + corpus-context retag of the games dim

**Phase 3c.1 scope** locked from the prior session's "Next session should" list: re-evaluate the three cards trimmed/dropped pre-tagging and wire each to real per-ISO-week data from the DB. Synthesis-derived narrative still deferred to 3c.4.

**Locked decisions per card:**

**Card 1 — "This week in gaming"** (dropped in 2026-05-12 walkthrough, now restored):
- KEEP, extended. Card-header title shows `N stories · M sources`. Body shows top-5 genres mini-bars + top-6 platforms mini-bars. **Net-sentiment block dropped** — composite "+X · Mixed" value wasn't actionable per user feedback.
- Rationale: walkthrough overlap concern (vs sidebar corpus stats) was theoretical when there was no week data. With real per-ISO-week aggregation Card 1 answers "what was this week about?"; sidebar shows "what's in the system." Different surfaces.

**Card 3 — "Hottest games"** (chips were trimmed pre-tagging, now restored AND extended with tabs):
- **3 tabs: All / Current / Upcoming.** Each tab fetches a separate top-5 from `top_games_for_week(lifecycle=...)`. CSS-only radio-driven toggling — no JS, no HTMX call.
- Per row: rank + game name + chip row (platform chips · `upcoming` chip when lifecycle=upcoming · `live-service` chip when applicable) + mention count.
- **"existing" chip explicitly NOT rendered** — existing is the default state per user call ("if nothing is mentioned that means it is current"). NULL-lifecycle also gets no chip; treated as default-current.
- Studio / heat-bar / WoW-delta / reason all dropped: studio is ambiguous in `entities.companies`, heat is synthetic, delta is the Trends card's job, reason is synthesis territory (Phase 3c.4).

**Card 11 — "Release radar"** (simplified, dates from corpus extraction, IGN as canonical reference):
- Per row: formatted date + game name. **No platform chip, no source pills, no mention-count, no "hype" bar.**
- Filter: include only rows where `release_date` is null/TBA, or parses to a date/quarter/year ≥ today. Past-dated games (delayed launches Haiku extracted stale dates for) hidden via `is_future_or_unknown()`.
- Card-header action: `Calendar →` link to `https://www.ign.com/upcoming/games`. Source of truth is external — corpus only surfaces dates that articles mention; IGN's curated calendar is the user-facing canonical reference.

**Data layer additions:**
- `games.release_date TEXT NULL` column via idempotent `_migrate_games_columns()` in `app/db/init.py`. Stores `YYYY-MM-DD` / `YYYY-MM` / `YYYY` / `Q1-YYYY..Q4-YYYY` / `TBA` / NULL.
- New `app/services/reports.py` module with per-ISO-week aggregation queries (`week_stats`, `top_genres_for_week`, `top_platforms_for_week`, `top_games_for_week(lifecycle=...)`, `upcoming_releases`, `format_release_date`, `is_future_or_unknown`). Uses `iso_week_bounds()` (Python `datetime.fromisocalendar`) instead of SQLite `strftime('%G-W%V', ...)` for portability across builds.
- All `entities.games` queries use case-insensitive joins (`LOWER(g.name) = LOWER(TRIM(je.value))`) and case-insensitive grouping so article-side casing variants ("Mixtape"/"MIXTAPE", "Bioshock"/"BioShock") collapse to a single row.

**Decision: corpus-context retag of all 189 games** (mid-session correction — Crimson Desert / Civilization 7 / Subnautica 2 / etc. surfaced as wrongly tagged `upcoming`):

- **Root cause:** original `populate_games_dim.py` + `tag_game()` passed **only the game name** to Haiku 4.5. Haiku's training cutoff is January 2026. Any game shipped between cutoff and 2026-05-12 falls back to Haiku's stale knowledge and gets misclassified.
- **Fix:** `scripts/retag_games_with_context.py`. Per-game Haiku call with 8–10 recent article titles + tldrs (corpus is Jan–May 2026, post-cutoff). Returns `{lifecycle, release_date, live_service}` derived from snippets, not training memory. System prompt explicitly instructs the model NOT to override the article evidence with training knowledge.
- **Result:** 129 of 189 games updated, 60 unchanged, 0 errors, ~4.4 min, ~$1 spend. Lifecycle distribution flipped from 131/28/30 (existing/upcoming/null) to 109/44/36. **50 games now have `release_date`** (was 10).
- **Crimson Desert specifically:** was `upcoming, NULL, live_service=true` → `existing, '2026', live_service=true`. `live_service` later manually flipped to `false` (Haiku read "Pearl Abyss adopted an MMO-style support model" too liberally — MMO-style update cadence ≠ live-service economy).

**Decision: 8 manual live-service flips** (post-retag spot review):
- `Civilization 7`, `Dead Cells`, `Phasmophobia`, `MindsEye`, `Magic: The Gathering` (franchise mention), `Dungeons & Dragons` (TTRPG franchise), `Battlefield 4`, `The Sims 4` — all flipped to `live_service=false`. None are battle-pass / season-pass / seasonal-warbond games; Haiku's live-service definition over-counted "regular updates" as service-model. Plus Crimson Desert (same reasoning). 57 → 49 live-service rows in dim.

**Decision: dedupe case-folded games in dim:**
- `scripts/dedupe_games_dim.py` — finds case-fold duplicate groups, picks canonical = casing with most mentions in `entities.games` (tiebreak: lexicographic), COALESCEs metadata onto canonical, deletes losers.
- 5 pairs collapsed: EVE Online / GreedFall / Invincible VS / LEGO Batman / Thick As Thieves. Dim went 189 → 184 rows.
- Paired with case-insensitive queries (above), the dedupe stays effective for future ingests — new article casings still join to the canonical row.

**Open data-hygiene items deferred:**
- Numeral-variant duplicates: `Diablo IV` / `Diablo 4`, `Diablo IV: Lord of Hatred` / `Diablo 4: Lord of Hatred`, `Endfield` / `Arknights: Endfield`. Case-fold dedupe doesn't catch these — needs Roman/Arabic numeral canonicalization + partial-vs-full-title detection.
- Series-vs-game entries in dim: `Resident Evil` / `The Witcher` / `Sonic the Hedgehog` / etc. The retag correctly returned `lifecycle=null` for these. Could be filtered out of the dim entirely.
- 36 NULL-lifecycle dim rows post-retag include franchises + genuinely unidentified games. Acceptable.

**Rejected alternatives:**
- **IGN /upcoming/games scraping** (initial date-extraction attempt): page is React/Next.js rendered. Only 1 of 5 sample upcoming games appeared in the static HTML, and that one (Subnautica 2) was at byte position 388K — past any practical truncation. Pivoted to corpus-context extraction. Kept the `Calendar →` link to IGN as the user-facing reference.
- **Re-tag name-only with a "trust article corpus" instruction in the prompt:** rejected — without article snippets present in the request, Haiku has no fresh signal to ground its answer.
- **Skip the retag, leave existing tags:** rejected — visible errors (Crimson Desert in upcoming, Civ 7 tagged live-service) would corrupt the Hottest tabs and Releases card.
- **Just retag the 28 upcoming-tagged games:** rejected (option offered to user; they chose full retag). Fixes only the most-visible direction of error; misses errors in the other direction (existing-tagged games that are actually upcoming, like the new Worms / Mortal Kombat titles surfaced by the retag).

**Cost summary (this session):** ~$1.15 Anthropic =
- IGN scrape + Haiku extraction dead-end: ~$0.05
- Corpus-context date extraction (10 games dated): ~$0.10
- Corpus-context retag (189 games re-profiled): ~$1.00

Inside the $500/yr Anthropic budget by a wide margin. Cumulative project spend through Phase 3c.1: ~$6.15.

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
