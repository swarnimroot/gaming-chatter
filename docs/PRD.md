# Product Requirements — gaming-chatter

## Problem

Following gaming news across 30+ sources is high-effort, low-signal. RSS readers dump everything; "best of week" newsletters are generic and miss niches. I want a curated, synthesized view of what mattered this week — once a week, in one place, on my own laptop.

## Users

One: me. Local, no auth, no sharing (initial scope).

## Goals

1. Aggregate from 15 news sites + 10 subreddits + 6 YouTube channels daily.
2. Produce a weekly Monday-morning exec summary that reads like a thoughtful colleague's brief — not a news ticker, not generic aggregator slop.
3. Provide a live dashboard updating throughout the week with accumulating data + last week's summary on top.
4. Surface trends (WoW/MoM) on games and topics, not just headlines.
5. Make sources easy to add / remove / disable via a light admin UI.
6. Allow on-demand report regeneration and export-as-HTML.
7. Filter the live dashboard and clusters view by content region (Americas / Europe / Asia), so the digest can be narrowed to stories anchored in a specific market when the user has time to focus there.

## Report sections

| Section | Definition |
|---|---|
| Biggest Story | Single most important thing this week |
| Hottest Games | Ranked by mention velocity × signal |
| Industry Risks | Layoffs, regulatory, platform shifts (rubric to be locked in Phase 3c) |
| Market Momentum | Release cadence, hype curves, sales chatter |
| WoW/MoM Trends | Entity-mention deltas across windows |
| Community Sentiment | Reddit post titles + bodies + YouTube descriptions (PRAW rejected 2026-05-07 → RSS-only; comment-thread depth not available unless PRAW reapproves); rubric to be locked in Phase 3c |
| Watch-List | Emerging stories with rising trajectory but low absolute volume |

## Non-goals (initial scope)

- Multi-user, accounts, public sharing
- Push delivery (email/Discord) — deferred to "Later" phase
- Real-time updates — daily ingest is the cadence
- Mobile-specific UI — desktop browser on localhost
- Backfill of historical data — accept cold start
- Replacement for primary news consumption — this is a *digest*, not a feed reader
- Per-region weekly synthesis — region is a filter dimension on existing surfaces, not a separate synthesis pass. One global read-out per ISO week remains the unit of work.

## Success criteria

- Weekly summary reads as genuinely useful, not generic aggregator slop
- Trend signals reflect real movement, not paraphrasing noise
- I open it Monday morning and don't bounce
- Setup-to-first-real-report < 2 weeks of build effort

## Cost target

LLM API spend: ~$1–3 / month steady-state. Backfills or corpus rebuilds add ~$5–10 each.

Reflects the locked split (DECISIONS 2026-05-12 override): per-item enrichment + game tagging + region tagging + YT pre-screen run on Anthropic Haiku 4.5 (the volume work, but Haiku tokens are cheap); cluster labels on Sonnet 4.6; weekly synthesis + critic on Opus 4.7. Ollama (local, free) does embeddings (`nomic-embed-text`, 768-dim). The pre-2026-05-12 PRD target ($1–5/month with Ollama doing volume) is obsolete — the qwen2.5:7b structured-output trial exposed quality issues that justified moving per-item enrichment to Haiku, accepting ~3–5× monthly spend in return.
