"""Weekly synthesis: Opus 4.7 produces the structured editorial content for
the 9-card weekly read-out (Phase 3c.4).

Two passes:
1. **Synthesis** — single Opus 4.7 structured call. Schema-constrained via the
   `WeeklySynthesis` Pydantic model so every section comes back with the
   exact field shape the router/template expects.
2. **Critic** — second Opus 4.7 call that takes the synthesis output + the
   original input data and returns a *revised* `WeeklySynthesis`. Critic
   verifies each item is grounded in input + tightens prose + drops any
   fabricated/loose claims. The critic-revised output is what gets persisted.

Output is dumped to `weekly_reports.synthesis_json`. The critic-revised
`exec_summary_paragraph` ALSO overwrites the existing 3c.3 Haiku
`exec_summary_text` / `_model` / `_generated_at` so the modal serves the
corpus-aware Opus version once synthesis has run.

Per-cluster narrative text is NOT a separate persistence — each card carries
its own `cluster_id` references; the drawer at `kind=cluster` looks up the
member articles directly.

Rubrics locked in DECISIONS 2026-05-11 + 2026-05-12 walkthrough:
- Industry risks: layoffs/closures + regulation/legal/policy. Exclude broader
  market shifts (those go to MM) and consumer-side pressures.
- Community sentiment: Reddit-only. Numeric anchor (mean sentiment) + 2-3
  sentiment_summary excerpts; narrative on top + heated/celebrating buckets.
- Drama: exec/PR blunders + studio feuds only. Community anger -> CS,
  business/legal -> Risks.
- MM (reshaped): acquisitions + funds + platform-policy + structural + people
  moves (absorbs old Studio Watch + Storefronts).
- Esports: surface what's actually in the corpus, no fabricated Twitch metrics.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import text as _sqltext
from sqlmodel import Session, select

from app.config import ANTHROPIC_SYNTHESIS_MODEL, ANTHROPIC_TIMEOUT
from app.db.models import WeeklyReport
from app.services import cost
from app.services import reports as report_q

log = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=ANTHROPIC_TIMEOUT)
    return _client


# ---------------------------------------------------------------------------
# Pydantic output schema — the WeeklySynthesis class is what Opus must return.
# Field-length limits encode the locked card row constraints from the
# 2026-05-12 walkthrough so we can never over-stuff a row at render time.
# ---------------------------------------------------------------------------

Severity = Literal["low", "med", "high"]
MMCategory = Literal["acquisitions", "funds", "platform-policy", "structural", "people-moves"]


# Field max_length values are generous guardrails-against-runaway-output, NOT
# strict design caps. The prompt encodes the editorial intent ("≤140 chars,
# one sentence") as a soft target; Pydantic only rejects egregious overruns
# (~2x the target). This avoids brittle re-runs when the model goes 10-20% over
# while still preventing 2000-char paragraphs from breaking the layout.


class BiggestStory(BaseModel):
    cluster_id: int = Field(..., description="ID of the cluster this story summarizes")
    title: str = Field(..., max_length=240, description="Editorial headline; no marketing voice")
    dek: str = Field(..., max_length=600, description="1-2 sentence elaboration grounded in cluster contents")


class HottestReason(BaseModel):
    game_name: str = Field(..., max_length=120, description="Exact game name as it appears in the corpus")
    reason: str = Field(..., max_length=280, description="1-line 'why hot this week' — names the concrete signal")


class MarketMomentumItem(BaseModel):
    cluster_id: int
    title: str = Field(..., max_length=240)
    note: str = Field(..., max_length=500)
    category: MMCategory = Field(..., description="Which momentum bucket this item belongs to")


class CommunityClusterRef(BaseModel):
    cluster_id: int
    title: str = Field(..., max_length=240)
    note: str = Field(..., max_length=420, description="What Reddit is reacting to, tone-anchored")


class CommunitySentimentSection(BaseModel):
    narrative: str = Field(
        ..., max_length=700,
        description="1-2 sentence pulse of Reddit-side reaction this week, grounded in sentiment_summary excerpts",
    )
    heated_about: list[CommunityClusterRef] = Field(
        default_factory=list, max_length=3,
        description="Clusters Reddit is most negatively reacting to (mean sentiment < 0)",
    )
    celebrating: list[CommunityClusterRef] = Field(
        default_factory=list, max_length=3,
        description="Clusters Reddit is most positively reacting to (mean sentiment > 0)",
    )


class IndustryRisk(BaseModel):
    cluster_id: int
    title: str = Field(..., max_length=240)
    note: str = Field(..., max_length=500)
    severity: Severity


class EsportsItem(BaseModel):
    cluster_id: int
    title: str = Field(..., max_length=240)
    note: str = Field(..., max_length=420)


class DramaItem(BaseModel):
    cluster_id: int
    title: str = Field(..., max_length=240)
    recap: str = Field(..., max_length=500)
    severity: Severity


class ReleaseNote(BaseModel):
    game_name: str = Field(..., max_length=120)
    note: str = Field(..., max_length=280)


_WATCH_DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "TBA"}
_WATCH_CATEGORIES = {"release", "drama", "business", "community", "event"}


class WatchItem(BaseModel):
    day: str = Field(..., max_length=12, description="One of: Mon, Tue, Wed, Thu, Fri, Sat, Sun, TBA")
    item: str = Field(..., max_length=360)
    cluster_id: Optional[int] = None
    category: str = Field(default="event", max_length=12,
                          description="One of: release | drama | business | community | event")

    @field_validator("day", mode="before")
    @classmethod
    def _normalize_day(cls, v):
        """Coerce loose day strings to the strict 8-value set. 'Mid-week' /
        'Weekend' / 'Tuesday' / unknown -> the nearest specific day or TBA.
        Forgiving by design — a normalization here avoids a $0.30 retry on
        a single bad day value."""
        if not isinstance(v, str):
            return "TBA"
        s = v.strip()
        if s in _WATCH_DAYS:
            return s
        lower = s.lower()
        for prefix, code in [
            ("mon", "Mon"), ("tue", "Tue"), ("wed", "Wed"), ("thu", "Thu"),
            ("fri", "Fri"), ("sat", "Sat"), ("sun", "Sun"),
        ]:
            if lower.startswith(prefix):
                return code
        # Mid-week / Weekend / etc. fall through to TBA (not actionable).
        return "TBA"

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, v):
        """Coerce to one of the 5 valid categories. Unknown -> 'event'."""
        if not isinstance(v, str):
            return "event"
        s = v.strip().lower()
        return s if s in _WATCH_CATEGORIES else "event"


class WeeklySynthesis(BaseModel):
    biggest: list[BiggestStory] = Field(
        ..., min_length=1, max_length=3,
        description="Top-3 clusters by editorial importance this week (NOT just by score)",
    )
    hottest_reasons: list[HottestReason] = Field(
        default_factory=list, max_length=5,
        description="1-line 'why hot' for each of the top-5 mentioned games this week",
    )
    market_momentum: list[MarketMomentumItem] = Field(
        default_factory=list, max_length=5,
        description="Acquisitions, funds, platform policy, structural shifts, people moves",
    )
    community_sentiment: CommunitySentimentSection
    risks: list[IndustryRisk] = Field(
        default_factory=list, max_length=4,
        description="Layoffs/closures + regulation/legal only; not market shifts",
    )
    esports: list[EsportsItem] = Field(
        default_factory=list, max_length=4,
        description="Esports/streaming stories present in this week's corpus",
    )
    drama: list[DramaItem] = Field(
        default_factory=list, max_length=3,
        description="Exec/PR blunders + studio feuds only; can be empty",
    )
    release_notes: list[ReleaseNote] = Field(
        default_factory=list, max_length=6,
        description="1-line note for each upcoming release mentioned this week",
    )
    watch: list[WatchItem] = Field(
        default_factory=list, max_length=7,
        description="Things worth tracking next week — derived from upcoming releases + WoW risers + ongoing stories",
    )
    exec_summary_paragraph: str = Field(
        ..., max_length=1600,
        description="3-5 sentence factual paragraph; same voice as the 3c.3 modal but corpus-aware",
    )


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM_PROMPT = """You are the editor of a personal gaming-news read-out, producing the structured content for the Monday-morning weekly report. The reader is a single technical user; the voice is a thoughtful colleague's brief, not a news ticker, not marketing copy, not editorial hot takes.

SECTIONS YOU PRODUCE (all fields required unless marked optional):

1. **biggest** (1-3 items). The most important stories of the week, plural. Each item: cluster_id (from the input), title (≤120 chars, editorial headline, no marketing), dek (1-2 sentence elaboration ≤280 chars). Order by editorial importance — not necessarily by raw score. If multiple clusters cover the same broad story, pick one and skip the others.

2. **hottest_reasons** (0-5 items). For each of the top-mentioned games listed in TOP_GAMES, write a 1-line `reason` (≤140 chars) explaining why it's hot this week. The reason must reference a concrete signal in the corpus — a launch, a controversy, a trailer, a delay, a player count surge. Do NOT pad with generic praise. Use EXACT game names as listed in TOP_GAMES.

3. **market_momentum** (0-5 items). Industry-business stories: acquisitions, funds raised, platform policy changes (Steam / Game Pass / PSN side), structural shifts, people moves (hires / departures / exec changes). Each item: cluster_id, title, note (≤220 chars), category in {acquisitions, funds, platform-policy, structural, people-moves}. Layoffs go to RISKS, not here. Community sentiment goes to community_sentiment, not here.

4. **community_sentiment**:
   - narrative (≤320 chars): 1-2 sentence pulse of Reddit-side reaction this week. Reference REDDIT_CLUSTERS' sentiment_summary excerpts; do not invent quotes or paraphrase beyond them.
   - heated_about (0-3 items): clusters whose REDDIT-MEMBER mean sentiment is most negative this week. Each: cluster_id + title + note tone-anchored to the actual Reddit reaction.
   - celebrating (0-3 items): same shape, most positive mean sentiment.
   - Use only REDDIT_CLUSTERS in this section — news-outlet and YouTube clusters belong to other sections.

5. **risks** (0-4 items). Layoffs/closures (studio shutdowns, layoff rounds, union actions) + regulation/legal/policy (Stop Killing Games, age-verification rulings, platform settlements). Each item: cluster_id, title, note (≤240 chars), severity in {low, med, high}. Severity is your judgment from the cluster's reach + escalation tone. Do NOT include broader market shifts (those go to market_momentum) or consumer-side pressures (those go to community_sentiment).

6. **esports** (0-4 items). Esports/streaming stories from the corpus. The corpus has NO structured Twitch / esports metrics — surface only the stories that actually appear in clusters. Each item: cluster_id, title, note. If nothing in the input concerns esports/streaming, return an empty list.

7. **drama** (0-3 items). Narrow scope: exec/PR blunders + studio feuds. Do NOT include community-tone-driven anger (that's community_sentiment) or business/legal stories (those are risks). Each item: cluster_id, title, recap (≤240 chars), severity. Often this list is empty — that's fine. Better to return [] than to stretch.

8. **release_notes** (0-6 items). For each upcoming release in UPCOMING_RELEASES, write a 1-line `note` (≤140 chars) reflecting what the corpus says about that release this week — new trailer? delay? platform reveal? Use EXACT game names from UPCOMING_RELEASES. Skip games without a concrete corpus signal this week rather than padding.

9. **watch** (5-7 items). Things worth tracking next week. Draw from UPCOMING_RELEASES (date-imminent items), Trends WoW risers (rising entities with low absolute volume), scheduled events, ongoing controversies/drama, or pending business outcomes. Each item: {day, item, category, cluster_id?}.
   - **day**: pick a specific weekday (`Mon`, `Tue`, `Wed`, `Thu`, `Fri`, `Sat`, `Sun`) when an article or release date grounds it (e.g. "launches May 27" → "Wed"). Only use `TBA` when no week-day inference is possible. Do NOT use `Mid-week` or `Weekend` — pick the most likely specific day instead.
   - **item**: ≤180 chars, prose describing the thing to watch AND why (what would shift, what to look for).
   - **category**: one of:
     - `release` — a game / DLC / expansion launching next week
     - `drama` — ongoing controversy / studio feud / exec PR situation that could escalate
     - `business` — M&A close, layoffs follow-up, regulatory deadline, financial filing
     - `community` — sentiment trend, mod release, content-creator moment to watch
     - `event` — scheduled showcase, esports tournament, dev stream, conference talk
   - **cluster_id**: integer reference into this week's CLUSTERS when the item directly continues an existing cluster story; omit for corpus-wide editorial. Mix at least one cluster-grounded item AND at least one corpus-wide item across the list.

10. **exec_summary_paragraph** (≤900 chars). A 3-5 sentence factual paragraph capturing the week. Lead with the biggest concrete signal (name it specifically — game, company, or event). Follow with one or two sentences on supporting signals (top genre / platform / sentiment direction). Close with one sentence on what's worth watching next week. No marketing language, no first/second person, no rhetorical questions, no hype words.

HARD RULES (apply to every field):
- Do NOT invent any game title, studio, person, number, or event that is not in the input.
- Do NOT speculate about anything not shown in the input.
- If a section has no qualifying input, return an empty list rather than padding.
- Every cluster_id you cite MUST appear in the CLUSTERS input. Do not invent IDs.
- Every game_name you cite MUST appear verbatim in TOP_GAMES or UPCOMING_RELEASES.
- Do NOT use marketing verbs: "stunning", "incredible", "must-watch", "groundbreaking", "exciting".
- Do NOT start any field with "This week...", "In gaming this week...", "Players are..." — start with the concrete subject directly.

OUTPUT: only the structured WeeklySynthesis JSON. No surrounding prose, no preamble."""


_CRITIC_SYSTEM_PROMPT = """You are a critic-editor reviewing the structured weekly read-out a junior editor just produced. You have access to the same source corpus they had. Your job is to return a TIGHTENED, GROUNDED revision of the synthesis with these specific checks:

1. **Verify groundedness.** For every claim in every field, confirm it can be traced to the input data. Drop or rewrite any item that names a game / studio / person / number not in the input.
2. **Verify cluster_id references.** Every cluster_id cited must exist in CLUSTERS. Drop items with bogus IDs.
3. **Verify game_name references.** Every game_name in hottest_reasons / release_notes must appear in TOP_GAMES / UPCOMING_RELEASES exactly. Fix casing or drop the item.
4. **Tighten prose.** Cut marketing verbs (stunning / incredible / must-watch / groundbreaking / exciting). Replace generic phrases ("various studios", "many fans") with concrete names.
5. **Enforce section scope.** A layoff in market_momentum belongs in risks. A community-anger item in drama belongs in community_sentiment.heated_about. A business deal in risks belongs in market_momentum. Move misplaced items.
6. **Enforce empty-state preference.** If a section's items are weak or stretched, drop the weakest rather than pad. Sections allow empty lists.
7. **Validate watch[] specifically.** Every watch item must derive from explicit signals in the input: UPCOMING_RELEASES with a date next week, WoW risers with momentum continuing, scheduled events in the corpus, ongoing-coverage threads still alive at week-end. Drop speculative items with no grounding. Prefer specific weekdays over `TBA` when a release date or scheduled event grounds the day. Verify each `category` value is one of {release, drama, business, community, event} — if anything else slipped through, infer the correct one from the item text.
7. **Tighten the exec_summary_paragraph.** Must lead with the strongest concrete signal naming a specific entity. 3-5 sentences. No first/second person, no hype.
8. **Preserve item count where possible.** Do not aggressively delete — but never keep an ungrounded or out-of-scope item.

Return the REVISED WeeklySynthesis JSON. Output only the JSON; no commentary."""


# ---------------------------------------------------------------------------
# Input builder — assembles the corpus snapshot per week
# ---------------------------------------------------------------------------

def _fetch_clusters_for_week(session: Session, week_id: str, limit: int = 12) -> list[dict]:
    """Fetch top-N clusters for the week, ordered by score DESC.

    Each cluster dict carries: id, label, member_count, source_count, score,
    member_item_ids (list[int]), latest_published_at (iso str).
    """
    rows = session.exec(_sqltext("""
        SELECT id, label, member_count, source_count, score, member_item_ids,
               latest_published_at
        FROM clusters
        WHERE week_id = :w
        ORDER BY score DESC NULLS LAST, member_count DESC
        LIMIT :lim
    """).bindparams(w=week_id, lim=limit)).all()
    out: list[dict] = []
    for r in rows:
        mids: list[int] = []
        try:
            mids = json.loads(r[5] or "[]")
        except (ValueError, TypeError):
            mids = []
        out.append({
            "id": int(r[0]),
            "label": r[1] or "",
            "member_count": int(r[2] or 0),
            "source_count": int(r[3] or 0),
            "score": float(r[4] or 0.0),
            "member_item_ids": mids,
            "latest_published_at": str(r[6]) if r[6] else None,
        })
    return out


def _fetch_cluster_members(
    session: Session,
    member_ids: list[int],
    sample_size: int = 5,
) -> list[dict]:
    """Fetch a sample of member items (title + tldr + source + sentiment + category)."""
    if not member_ids:
        return []
    sample = member_ids[:sample_size]
    placeholders = ",".join(str(int(x)) for x in sample)  # ids are ints — safe to inline
    rows = session.exec(_sqltext(f"""
        SELECT i.id, i.title, i.url, s.name, s.type, s.url_or_handle,
               e.tldr, e.sentiment_score, e.sentiment_summary, e.category
        FROM items i
        JOIN sources s ON s.id = i.source_id
        LEFT JOIN enrichments e ON e.item_id = i.id
        WHERE i.id IN ({placeholders})
    """)).all()
    out: list[dict] = []
    for r in rows:
        out.append({
            "id": int(r[0]),
            "title": r[1],
            "url": r[2],
            "source": r[3],
            "source_type": r[4],
            "source_is_reddit": "reddit.com" in (r[5] or "") or (r[3] or "").startswith("r/"),
            "tldr": r[6] or "",
            "sentiment_score": r[7],
            "sentiment_summary": r[8] or "",
            "category": r[9] or "",
        })
    return out


def _fetch_reddit_clusters(
    session: Session,
    week_id: str,
    limit: int = 8,
) -> list[dict]:
    """Clusters whose members are predominantly from Reddit sources.

    For each: mean sentiment over Reddit-source members + 2 sentiment_summary
    excerpts. CS section consumes this.
    """
    start, end = report_q.iso_week_bounds(week_id)
    rows = session.exec(_sqltext("""
        SELECT c.id, c.label, c.member_count, c.score, c.member_item_ids
        FROM clusters c
        WHERE c.week_id = :w
        ORDER BY c.score DESC NULLS LAST
        LIMIT :lim
    """).bindparams(w=week_id, lim=limit * 3)).all()

    out: list[dict] = []
    for r in rows:
        mids: list[int] = []
        try:
            mids = json.loads(r[4] or "[]")
        except (ValueError, TypeError):
            mids = []
        if not mids:
            continue
        placeholders = ",".join(str(int(x)) for x in mids)
        reddit_rows = session.exec(_sqltext(f"""
            SELECT e.sentiment_score, e.sentiment_summary, i.title, s.name, s.url_or_handle
            FROM items i
            JOIN sources s ON s.id = i.source_id
            LEFT JOIN enrichments e ON e.item_id = i.id
            WHERE i.id IN ({placeholders})
              AND (s.url_or_handle LIKE '%reddit.com%' OR s.name LIKE 'r/%')
              AND i.published_at >= :s AND i.published_at < :e
        """).bindparams(s=start, e=end)).all()

        if not reddit_rows:
            continue
        scores = [x[0] for x in reddit_rows if x[0] is not None]
        summaries = [(x[1], x[2]) for x in reddit_rows if x[1]]
        if not scores and not summaries:
            continue
        mean_sent = round(sum(scores) / len(scores), 3) if scores else 0.0
        out.append({
            "id": int(r[0]),
            "label": r[1] or "",
            "member_count": int(r[2] or 0),
            "score": float(r[3] or 0.0),
            "reddit_member_count": len(reddit_rows),
            "mean_sentiment": mean_sent,
            "sentiment_excerpts": [
                {"summary": s, "title": t} for s, t in summaries[:3]
            ],
        })
        if len(out) >= limit:
            break
    return out


def _build_input_dict(session: Session, week_id: str) -> dict:
    """Compose the full corpus snapshot for one week.

    Shape kept JSON-friendly so it round-trips through the model cleanly.
    """
    label, rng = report_q.week_label_and_range(week_id)
    stats = report_q.week_stats(session, week_id)
    genres = report_q.top_genres_for_week(session, week_id, limit=5)
    platforms = report_q.top_platforms_for_week(session, week_id, limit=6)
    top_games = report_q.top_games_for_week(session, week_id, limit=5)
    trends = report_q.trends_for_week(session, week_id, limit=5)
    upcoming = report_q.upcoming_releases(session, week_id, limit=8)

    clusters = _fetch_clusters_for_week(session, week_id, limit=12)
    for c in clusters:
        c["sample_members"] = _fetch_cluster_members(session, c["member_item_ids"], sample_size=5)
        # Trim member_item_ids out of the LLM input — we only need it server-side
        # for the drawer wiring. Don't pollute the prompt with IDs.
        del c["member_item_ids"]

    reddit_clusters = _fetch_reddit_clusters(session, week_id, limit=8)

    return {
        "week_id": week_id,
        "week_label": label,
        "week_range": rng,
        "stats": stats,
        "top_genres": [{"name": n, "count": c} for n, c in genres],
        "top_platforms": [{"name": n, "count": c} for n, c in platforms],
        "top_games": [
            {
                "name": g["name"],
                "count": g["count"],
                "platforms": g["platforms"],
                "lifecycle": g["lifecycle"],
                "live_service": g["live_service"],
                "sources": g["sources"],
            }
            for g in top_games
        ],
        "trends": trends,
        "upcoming_releases": [
            {
                "name": u["name"],
                "display_date": u["display_date"],
                "mention_count": u["mention_count"],
            }
            for u in upcoming
        ],
        "clusters": clusters,
        "reddit_clusters": reddit_clusters,
    }


def _format_input_for_prompt(data: dict) -> str:
    """Render the dict as a compact text block the model can scan.

    JSON-dump is fine for Opus, but we add a few human-readable section
    headers so the model doesn't have to navigate by JSON keys.
    """
    parts: list[str] = []
    parts.append(f"WEEK: {data['week_label']} ({data['week_range']})")
    parts.append(
        f"CORPUS: {data['stats']['stories']} stories from {data['stats']['sources']} sources."
    )

    if data["top_games"]:
        parts.append("\nTOP_GAMES (by mention count this week — use EXACT names):")
        for g in data["top_games"]:
            plats = ", ".join(g["platforms"]) if g["platforms"] else "—"
            tag_bits = []
            if g["lifecycle"]:
                tag_bits.append(g["lifecycle"])
            if g["live_service"]:
                tag_bits.append("live-service")
            tags = f" [{', '.join(tag_bits)}]" if tag_bits else ""
            parts.append(
                f"  - {g['name']} ({g['count']} mentions; platforms: {plats}){tags}"
            )

    if data["top_genres"]:
        parts.append("\nTOP_GENRES: " + ", ".join(
            f"{g['name']} ({g['count']})" for g in data["top_genres"]
        ))
    if data["top_platforms"]:
        parts.append("\nTOP_PLATFORMS: " + ", ".join(
            f"{p['name']} ({p['count']})" for p in data["top_platforms"]
        ))

    trends = data["trends"]
    if trends.get("has_prior"):
        # Phase 3c.23 reshaped trends_for_week: each tab now holds
        # {"rising": [...], "declining": [...]} rather than a flat list,
        # and games_current/games_upcoming collapsed into a single "games" key.
        # The rising sub-list is already filtered to positive delta_pp and
        # sorted DESC, so we just take the first 3.
        for tab_key, label in [
            ("games", "Games WoW risers"),
            ("genres", "Genre WoW risers"),
            ("platforms", "Platform WoW risers"),
            ("live_service", "Live-service WoW risers"),
            ("events", "Event WoW risers"),
        ]:
            tab = trends.get(tab_key) or {}
            ups = (tab.get("rising") or [])[:3]
            if ups:
                bits = ", ".join(f"{r['name']} {r['delta_display']}" for r in ups)
                parts.append(f"\n{label.upper()}: {bits}")

    if data["upcoming_releases"]:
        parts.append("\nUPCOMING_RELEASES (use EXACT names):")
        for u in data["upcoming_releases"]:
            parts.append(
                f"  - {u['name']} ({u['display_date']}; {u['mention_count']} corpus mentions)"
            )

    parts.append("\nCLUSTERS (cite by cluster_id; sample_members shows title + tldr per member):")
    parts.append(json.dumps(data["clusters"], indent=2, default=str))

    if data["reddit_clusters"]:
        parts.append("\nREDDIT_CLUSTERS (cluster summaries restricted to Reddit-source members; use these for community_sentiment):")
        parts.append(json.dumps(data["reddit_clusters"], indent=2, default=str))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Anthropic calls
# ---------------------------------------------------------------------------

# Synthesis is the one expensive, all-or-nothing Anthropic call (~37k tokens /
# ~$0.11 per synthesize_week — synth + critic). Per DECISIONS 2026-06-09 it gets
# a bounded retry: up to 3 attempts on TRANSIENT failures (timeouts, 429, 5xx,
# one-off malformed structured output) with exponential backoff, then fail
# loudly so the orchestrator marks the run failed and /runs surfaces it for a
# manual re-run. Non-transient errors (400/401/403/404/422 — they repeat
# identically) fail on the first attempt without burning further tokens.
_SYNTH_MAX_ATTEMPTS = 3
_SYNTH_BACKOFF_BASE_S = 2.0  # waits: 2s after attempt 1, 4s after attempt 2


class _SynthRetryable(Exception):
    """Internal marker: a synthesis failure worth retrying within the cap
    (currently: Opus returned no parseable structured output)."""


def _is_retryable_synth_error(exc: Exception) -> bool:
    """Classify a synthesis failure as transient (retry) vs. permanent (fail
    fast). Errors that would repeat identically are NOT retried."""
    # Transport-level (timeouts, dropped connections) — always worth a retry.
    # anthropic.APITimeoutError subclasses APIConnectionError.
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    # HTTP status errors: retry rate-limit (429) and server (5xx) only; a 4xx
    # bad-request/auth error would repeat identically, so let it fail fast.
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    # Malformed / unparseable structured output is usually one-off model
    # variance — a re-roll within the cap often succeeds.
    if isinstance(exc, (ValidationError, _SynthRetryable)):
        return True
    return False


def _opus_once(system_prompt: str, user_text: str, max_tokens: int) -> WeeklySynthesis:
    """One Opus structured-output call. Raises raw anthropic.* / ValidationError
    / _SynthRetryable for the retry wrapper to classify. `with_options(
    max_retries=0)` disables the SDK's own retry layer so `_call_opus` is the
    single, cost-capped source of retries."""
    message = _get_client().with_options(max_retries=0).messages.parse(
        model=ANTHROPIC_SYNTHESIS_MODEL,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_text}],
        output_format=WeeklySynthesis,
    )
    cost.record(ANTHROPIC_SYNTHESIS_MODEL, message.usage, phase="synthesis")
    data = getattr(message, "parsed_output", None)
    if data is None:
        stop = getattr(message, "stop_reason", "unknown")
        raise _SynthRetryable(f"no parsed output (stop_reason={stop})")
    return data


def _call_opus(system_prompt: str, user_text: str, max_tokens: int = 8192) -> WeeklySynthesis:
    """Opus structured-output call with a bounded transient-retry cap. Returns
    the parsed Pydantic instance; raises ValueError once retries are exhausted
    or on a non-retryable error (callers in synthesize_week / the orchestrators
    turn that into a failed JobRun, surfaced on /runs for manual re-run)."""
    for attempt in range(1, _SYNTH_MAX_ATTEMPTS + 1):
        try:
            return _opus_once(system_prompt, user_text, max_tokens)
        except Exception as exc:  # noqa: BLE001 — re-raised after classification
            retryable = _is_retryable_synth_error(exc)
            if not retryable or attempt == _SYNTH_MAX_ATTEMPTS:
                kind = "transient, retries exhausted" if retryable else "non-retryable"
                raise ValueError(
                    f"Opus synthesis failed after {attempt} attempt(s) "
                    f"[{kind}]: {type(exc).__name__}: {exc}"
                ) from exc
            backoff = _SYNTH_BACKOFF_BASE_S * (2 ** (attempt - 1))
            log.warning(
                "Opus synthesis attempt %d/%d failed (%s) - retrying in %.0fs: %s",
                attempt, _SYNTH_MAX_ATTEMPTS, type(exc).__name__, backoff, exc,
            )
            time.sleep(backoff)
    # Unreachable (loop either returns or raises) — satisfies the type checker.
    raise ValueError("Opus synthesis failed: exhausted retry loop")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _load_cached(session: Session, week_id: str) -> Optional[WeeklyReport]:
    week_start, _ = report_q.iso_week_bounds(week_id)
    return session.exec(
        select(WeeklyReport).where(WeeklyReport.week_start == week_start)
    ).first()


def synthesize_week(session: Session, week_id: str, force: bool = False) -> dict:
    """Run the synthesis + critic pass for `week_id` and persist the result.

    On cache hit (synthesis_json present and not force), return the cached
    payload without any API call.

    Returns: {synthesis: dict, model: str, from_cache: bool, generated_at: datetime,
              spend_tokens: dict | None}.
    """
    cached = _load_cached(session, week_id)
    if cached and cached.synthesis_json and not force:
        log.info("synthesis cache hit for %s", week_id)
        return {
            "synthesis": json.loads(cached.synthesis_json),
            "model": cached.synthesis_model or ANTHROPIC_SYNTHESIS_MODEL,
            "from_cache": True,
            "generated_at": cached.synthesis_generated_at,
            "spend_tokens": None,
        }

    log.info("synthesis cache miss for %s — running Opus + critic", week_id)
    input_data = _build_input_dict(session, week_id)
    user_text = _format_input_for_prompt(input_data)
    log.info("synthesis input assembled: ~%d chars", len(user_text))

    # Pass 1 — synthesis
    log.info("calling Opus synthesis pass…")
    synth_pass = _call_opus(_SYNTHESIS_SYSTEM_PROMPT, user_text)
    log.info(
        "synthesis pass OK: biggest=%d, MM=%d, risks=%d, esports=%d, drama=%d, watch=%d",
        len(synth_pass.biggest), len(synth_pass.market_momentum), len(synth_pass.risks),
        len(synth_pass.esports), len(synth_pass.drama), len(synth_pass.watch),
    )

    # Pass 2 — critic
    # Phase 3c.30: prepend recurring past concerns from /eval scoring so the
    # critic enforces the user's accumulated editorial taste, not just the
    # static rules in _CRITIC_SYSTEM_PROMPT. Empty when fewer than 2 fails on
    # any (card, dim) in the last 4 weeks → no prepend, no behavior change.
    from app.services.eval_feedback import format_critic_block, gather_recent_failures
    past_failures = gather_recent_failures(session, week_id)
    past_concerns = format_critic_block(past_failures)
    if past_concerns:
        log.info("critic: injecting %d past-concern pattern(s) from recent eval scoring", len(past_failures))

    critic_user = (
        (past_concerns + "\n\n" if past_concerns else "")
        + f"=== ORIGINAL SOURCE INPUT ===\n\n{user_text}\n\n"
        + f"=== SYNTHESIS TO REVIEW ===\n\n{synth_pass.model_dump_json(indent=2)}"
    )
    log.info("calling Opus critic pass…")
    revised = _call_opus(_CRITIC_SYSTEM_PROMPT, critic_user)
    log.info(
        "critic pass OK: biggest=%d, MM=%d, risks=%d, esports=%d, drama=%d, watch=%d",
        len(revised.biggest), len(revised.market_momentum), len(revised.risks),
        len(revised.esports), len(revised.drama), len(revised.watch),
    )

    payload = revised.model_dump()
    now = datetime.utcnow()
    week_start, week_end = report_q.iso_week_bounds(week_id)
    json_blob = json.dumps(payload, default=str)

    if cached is None:
        cached = WeeklyReport(
            week_start=week_start,
            week_end=week_end,
            synthesis_json=json_blob,
            synthesis_model=ANTHROPIC_SYNTHESIS_MODEL,
            synthesis_generated_at=now,
            # Overwrite the 3c.3 Haiku exec-summary fields with the deeper Opus
            # paragraph; the modal now serves the synthesis-aware version.
            exec_summary_text=revised.exec_summary_paragraph,
            exec_summary_model=ANTHROPIC_SYNTHESIS_MODEL,
            exec_summary_generated_at=now,
            status="synthesized",
        )
        session.add(cached)
    else:
        cached.synthesis_json = json_blob
        cached.synthesis_model = ANTHROPIC_SYNTHESIS_MODEL
        cached.synthesis_generated_at = now
        cached.exec_summary_text = revised.exec_summary_paragraph
        cached.exec_summary_model = ANTHROPIC_SYNTHESIS_MODEL
        cached.exec_summary_generated_at = now
        cached.status = "synthesized"
        session.add(cached)
    session.commit()

    log.info("synthesis persisted for %s (%d chars JSON)", week_id, len(json_blob))

    # Phase 3c.35 — precompute the dashboard payload now that synthesis_json
    # is on disk. The /reports route reads this cache instead of recomputing
    # `_build_week_payload` on every click. Failure here is non-fatal — log
    # and continue; the route will just fall through to live compute.
    try:
        from app.services import dashboard as dashboard_svc
        dashboard_svc.compute_and_cache_payload(session, week_id)
        session.commit()
        log.info("dashboard payload cached for %s", week_id)
    except Exception as e:  # noqa: BLE001 — cache failure must not break synthesis
        log.warning("failed to cache dashboard payload for %s: %s", week_id, e)
        session.rollback()

    return {
        "synthesis": payload,
        "model": ANTHROPIC_SYNTHESIS_MODEL,
        "from_cache": False,
        "generated_at": now,
        "spend_tokens": None,  # populated by callers that inspect message.usage
    }
