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

## Report sections

| Section | Definition |
|---|---|
| Biggest Story | Single most important thing this week |
| Hottest Games | Ranked by mention velocity × signal |
| Industry Risks | Layoffs, regulatory, platform shifts (rubric refined in Phase 3) |
| Market Momentum | Release cadence, hype curves, sales chatter |
| WoW/MoM Trends | Entity-mention deltas across windows |
| Community Sentiment | Reddit post titles + bodies + YouTube descriptions; comment-thread depth deferred until PRAW is reapproved (rubric refined in Phase 3) |
| Watch-List | Emerging stories with rising trajectory but low absolute volume |

## Non-goals (initial scope)

- Multi-user, accounts, public sharing
- Push delivery (email/Discord) — deferred to "Later" phase
- Real-time updates — daily ingest is the cadence
- Mobile-specific UI — desktop browser on localhost
- Backfill of historical data — accept cold start
- Replacement for primary news consumption — this is a *digest*, not a feed reader

## Success criteria

- Weekly summary reads as genuinely useful, not generic aggregator slop
- Trend signals reflect real movement, not paraphrasing noise
- I open it Monday morning and don't bounce
- Setup-to-first-real-report < 2 weeks of build effort

## Cost target

LLM API spend: $1–5 / month. Ollama local does the volume work; Anthropic only does the weekly synthesis pass.
