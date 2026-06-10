"""Anthropic API clients for the per-item enrichment + cluster-label paths.

- Per-item enrichment (`enrich_item`) and per-game tagging (`tag_game`) on
  Haiku 4.5 — lock-override of 2026-05-12 (see docs/DECISIONS.md).
- Cluster labels (`label_cluster`) on Sonnet 4.6 — Phase 3c.4 migration off
  Ollama qwen2.5:7b.

Embeddings stay on Ollama (`nomic-embed-text`, 768-dim).

Reuses EnrichmentData + SYSTEM_PROMPT + taxonomies from app.services.ollama
so there is a single source of truth for the schema and prompt text.
"""
from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import (
    ANTHROPIC_CLUSTER_LABEL_MODEL,
    ANTHROPIC_ENRICH_MODEL,
    ANTHROPIC_TIMEOUT,
    ENRICH_BODY_CHAR_CAP,
)
from app.services.ollama import (
    GAME_TAG_SYSTEM_PROMPT,
    GameTagData,
    REGIONS,
    SYSTEM_PROMPT,
    EnrichmentData,
)
from app.services import cost

log = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy-init module-level client. SDK reads ANTHROPIC_API_KEY from env."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=ANTHROPIC_TIMEOUT)
    return _client


def _truncate(text: str, cap: int) -> tuple[str, bool]:
    if not text:
        return "", False
    if len(text) <= cap:
        return text, False
    return text[:cap], True


def enrich_item(title: str, body: str, source_label: str) -> EnrichmentData:
    """Call Anthropic Haiku 4.5 for per-item enrichment.

    Drop-in replacement for ollama.enrich_item — identical signature & return.
    Raises ValueError on any transport / schema / bounds failure so the
    existing _persist_failed() path in enrich.py keeps working unchanged.
    """
    body_text, truncated = _truncate(body or "", ENRICH_BODY_CHAR_CAP)
    if truncated:
        log.info(
            "enrich body truncated for '%s' (orig=%d chars, cap=%d)",
            title[:60], len(body), ENRICH_BODY_CHAR_CAP,
        )

    user_prompt = f"Source: {source_label}\nTitle: {title}\n\nBody:\n{body_text or '(no body)'}"

    try:
        message = _get_client().messages.parse(
            model=ANTHROPIC_ENRICH_MODEL,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
            output_format=EnrichmentData,
        )
    except anthropic.APIError as e:
        raise ValueError(f"anthropic API error: {e}") from e
    except ValidationError as e:
        raise ValueError(f"anthropic response failed schema: {e}") from e

    cost.record(ANTHROPIC_ENRICH_MODEL, message.usage)
    data = getattr(message, "parsed_output", None)
    if data is None:
        stop = getattr(message, "stop_reason", "unknown")
        raise ValueError(f"anthropic returned no parsed output (stop_reason={stop})")

    if not -1.0 <= data.sentiment_score <= 1.0:
        raise ValueError(f"sentiment_score out of range: {data.sentiment_score}")

    return data


CLUSTER_LABEL_SYSTEM_PROMPT = """You label a cluster of gaming-news articles that all cover the same story or topic.

Rules:
- 4-10 words, plain prose, neutral editorial tone. No marketing voice, no quotes, no trailing punctuation.
- Name the actual subject (game, company, event, policy), not meta-words like "articles", "news", or "coverage".
- If the cluster spans multiple sub-topics, pick the dominant one rather than coining a hybrid.

Examples of good labels:
- "Mixtape indie game critical reception"
- "Greedfall studio Spiders shutting down"
- "Star Fox 64 remake announced for Switch 2"
- "Steam Controller restock after sellout"
- "Sony rolls out PlayStation age verification UK"
- "Gamescom 2026 trailer roundup"

Return your label in the structured `label` field. No additional commentary."""


class ClusterLabelData(BaseModel):
    label: str = Field(..., description="4-10 word neutral label for the cluster")


def label_cluster(titles: list[str], tldrs: list[str]) -> str:
    """Generate a single-line label for a cluster via Anthropic Sonnet 4.6.

    Drop-in replacement for ollama.label_cluster — identical signature & return.
    Caller pre-subsamples to CLUSTER_LABEL_SAMPLE items (cluster_window does this).
    Raises ValueError on any transport / schema / validation failure so the
    existing fallback path in cluster_window keeps working unchanged.
    """
    lines: list[str] = []
    for t, s in zip(titles, tldrs):
        title = (t or "").strip()
        tldr = (s or "").strip()
        if title and tldr:
            lines.append(f"- {title}\n  {tldr}")
        elif title:
            lines.append(f"- {title}")
    user_prompt = "Articles in this cluster:\n\n" + "\n".join(lines)

    try:
        message = _get_client().messages.parse(
            model=ANTHROPIC_CLUSTER_LABEL_MODEL,
            max_tokens=256,
            system=[
                {
                    "type": "text",
                    "text": CLUSTER_LABEL_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
            output_format=ClusterLabelData,
        )
    except anthropic.APIError as e:
        raise ValueError(f"anthropic label_cluster API error: {e}") from e
    except ValidationError as e:
        raise ValueError(f"anthropic label_cluster response failed schema: {e}") from e

    cost.record(ANTHROPIC_CLUSTER_LABEL_MODEL, message.usage)
    data = getattr(message, "parsed_output", None)
    if data is None:
        stop = getattr(message, "stop_reason", "unknown")
        raise ValueError(f"anthropic label_cluster returned no parsed output (stop_reason={stop})")

    label = data.label.strip()
    if not label:
        raise ValueError("anthropic label_cluster returned empty label")
    return label


YT_PRESCREEN_SYSTEM_PROMPT = """You decide whether a YouTube video is relevant to a gaming-news weekly brief.

Relevant: video games, gaming hardware, the games industry (companies, layoffs, business deals), gaming culture / community, esports, streamers/creators-as-news, game-adjacent tech (engines, controllers).

Not relevant: movies, TV shows, anime, music, sports, politics, lifestyle, vlogs, sponsored non-gaming content, unrelated tech reviews (laptops/phones not for gaming).

You receive only the title and the YouTube description. Decide on those alone — do NOT speculate about what might be in the video.

When in doubt (description is too short or ambiguous), prefer relevant=true (we'd rather analyze and discard later than miss a relevant item).

Return: {relevant: bool, reason: short string explaining why — one sentence max}."""


class YTPrescreenData(BaseModel):
    relevant: bool = Field(..., description="True if the video is gaming-related and worth deeper analysis.")
    reason: str = Field("", description="One-sentence explanation of the decision.")


def prescreen_yt_relevance(title: str, description: str) -> YTPrescreenData:
    """Cheap Haiku call: is this YouTube item gaming-relevant per title+description?

    Used to gate whisper-CPU transcript fetching. If relevant=False, the caller
    persists status='skipped' with a reason and skips transcript work entirely.

    Fails-open: on API/transport error the caller treats it as relevant=True
    rather than losing items to API hiccups.
    """
    user_prompt = f"Title: {title.strip() or '(no title)'}\n\nDescription:\n{(description or '').strip()[:2000] or '(no description)'}"

    try:
        message = _get_client().messages.parse(
            model=ANTHROPIC_ENRICH_MODEL,
            max_tokens=256,
            system=[
                {
                    "type": "text",
                    "text": YT_PRESCREEN_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
            output_format=YTPrescreenData,
        )
    except anthropic.APIError as e:
        raise ValueError(f"anthropic prescreen API error: {e}") from e
    except ValidationError as e:
        raise ValueError(f"anthropic prescreen response failed schema: {e}") from e

    cost.record(ANTHROPIC_ENRICH_MODEL, message.usage)
    data = getattr(message, "parsed_output", None)
    if data is None:
        stop = getattr(message, "stop_reason", "unknown")
        raise ValueError(f"anthropic prescreen returned no parsed output (stop_reason={stop})")
    return data


def tag_game(game_name: str) -> GameTagData:
    """Call Anthropic Haiku 4.5 to tag a game with lifecycle + live_service.

    Drop-in replacement for ollama.tag_game. Raises ValueError on any failure.
    """
    user_prompt = f"Game: {game_name}"
    try:
        message = _get_client().messages.parse(
            model=ANTHROPIC_ENRICH_MODEL,
            max_tokens=128,
            system=[
                {
                    "type": "text",
                    "text": GAME_TAG_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
            output_format=GameTagData,
        )
    except anthropic.APIError as e:
        raise ValueError(f"anthropic tag_game API error: {e}") from e
    except ValidationError as e:
        raise ValueError(f"anthropic tag_game response failed schema: {e}") from e

    cost.record(ANTHROPIC_ENRICH_MODEL, message.usage)
    data = getattr(message, "parsed_output", None)
    if data is None:
        stop = getattr(message, "stop_reason", "unknown")
        raise ValueError(f"anthropic tag_game returned no parsed output (stop_reason={stop})")
    return data


REGION_TAG_SYSTEM_PROMPT = """You tag a gaming-news item with a region focus.

Return ONLY valid JSON with one field:
- region_focus: array of region tags from [americas, europe, asia], or [].

Tag a region ONLY when the news is ANCHORED in it — regulatory action,
region-specific event, region-only release / pricing, region-specific
business or operational news.

Company HQ alone is NOT enough — a Japanese studio's worldwide reveal is
[], not ["asia"]. Worldwide announcements / trailers / launches / gameplay
news are [].

Multi-tag for cross-region stories (e.g. a CN buyer acquiring an EU target
-> ["asia","europe"]).

Worked examples:
- "FTC sues Microsoft over Activision deal" -> ["americas"]
- "Capcom delays game in Japan only" -> ["asia"]
- "Tencent acquires Norwegian studio Funcom" -> ["asia","europe"]
- "EU passes new game-rating law" -> ["europe"]
- "GTA 6 trailer drops Nov 5" -> []          (worldwide launch)
- "Nintendo Direct September recap" -> []   (event is global despite JP host)
- "Halo Season 8 patch notes" -> []         (gameplay, no regional angle)

Output JSON only. No prose, no code fences."""


class RegionTagData(BaseModel):
    region_focus: list[str] = Field(default_factory=list)

    @field_validator("region_focus", mode="before")
    @classmethod
    def _filter(cls, v):
        if not isinstance(v, list):
            return []
        seen: list[str] = []
        for r in v:
            if isinstance(r, str):
                r_norm = r.strip().lower()
                if r_norm in REGIONS and r_norm not in seen:
                    seen.append(r_norm)
        return seen


PCGAMER_RELEASES_SYSTEM_PROMPT = """You extract upcoming PC game release dates from a PC Gamer "upcoming games" calendar article.

Return ONLY valid JSON with one field:
- releases: array of objects with {name, release_date}.

Rules for `name`:
- Use the canonical game name as it appears in the article (preserve casing, drop subtitle if redundant).
- Skip non-game entries: hardware, DLC unless standalone, expansions referenced only in passing, retrospectives.
- Skip games mentioned in narrative ONLY when no date or date-range is present for them.
- One row per distinct game. De-dup if the article lists the same game in multiple sections.

Rules for `release_date` — output exactly one of these formats:
- "YYYY-MM-DD"  (specific day, e.g. "2026-07-15")
- "YYYY-MM"     (month known but no day, e.g. "2026-08")
- "Qn-YYYY"     (quarter only, e.g. "Q3-2026" — n in [1,2,3,4])
- "YYYY"        (year only, e.g. "2026")
- "TBA"         (article explicitly says TBD/TBA/unknown/no date)

If the article gives a window like "Spring 2026" or "Holiday 2026", normalize:
- Spring → Q2 / Summer → Q3 / Fall|Autumn → Q4 / Winter|Holiday → Q4 (or Q1 of next year if explicit).
- "Early 2026" → Q1-2026; "mid 2026" → Q2-2026 or Q3-2026 (pick Q3); "late 2026" → Q4-2026.
- Ambiguous "2026" with no further hint → "2026".

Worked examples (input phrase → output):
- "Resident Evil Requiem launches February 27, 2026" → {name: "Resident Evil Requiem", release_date: "2026-02-27"}
- "Hollow Knight: Silksong — Coming Spring 2026" → {name: "Hollow Knight: Silksong", release_date: "Q2-2026"}
- "Half-Life 3 (TBA)" → {name: "Half-Life 3", release_date: "TBA"}
- "GTA 6 — 2026" (no further detail) → {name: "GTA 6", release_date: "2026"}

Output JSON only. No prose, no code fences. Aim for completeness — capture every game with a date in the article."""


class PCGamerRelease(BaseModel):
    name: str = Field(..., description="Canonical game name")
    release_date: str = Field(..., description="One of: YYYY-MM-DD / YYYY-MM / Qn-YYYY / YYYY / TBA")

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("release_date", mode="before")
    @classmethod
    def _normalize_date(cls, v):
        """Light client-side normalization — Haiku should already be in shape,
        but uppercase Q-prefix and trim whitespace so case drift doesn't sneak in.
        Strict validation (must match one of the 5 formats) lives in the script."""
        if not isinstance(v, str):
            return v
        s = v.strip()
        if s.upper() == "TBA":
            return "TBA"
        # Q3-2026 / q3 2026 / Q3 2026 → Q3-2026
        if len(s) >= 6 and s[0] in ("Q", "q") and s[1] in "1234":
            year_part = s[2:].lstrip(" -").strip()
            if year_part.isdigit() and len(year_part) == 4:
                return f"Q{s[1]}-{year_part}"
        return s


class PCGamerReleaseList(BaseModel):
    releases: list[PCGamerRelease] = Field(default_factory=list)


def tag_pcgamer_releases(body_text: str) -> list[PCGamerRelease]:
    """Call Anthropic Haiku 4.5 to extract (game, release_date) pairs from a
    PC Gamer upcoming-games article body. Single call per refresh; idempotent
    upstream (the script diffs against the game_releases table). Phase 3c.18.

    Raises ValueError on transport / schema failure.
    """
    user_prompt = f"Article body:\n\n{body_text}"
    try:
        message = _get_client().messages.parse(
            model=ANTHROPIC_ENRICH_MODEL,
            max_tokens=8192,  # full pcgamer 2026 calendar has ~100 entries → ~6K output tokens
            system=[
                {
                    "type": "text",
                    "text": PCGAMER_RELEASES_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
            output_format=PCGamerReleaseList,
        )
    except anthropic.APIError as e:
        raise ValueError(f"anthropic tag_pcgamer_releases API error: {e}") from e
    except ValidationError as e:
        raise ValueError(f"anthropic tag_pcgamer_releases response failed schema: {e}") from e

    cost.record(ANTHROPIC_ENRICH_MODEL, message.usage)
    data = getattr(message, "parsed_output", None)
    if data is None:
        stop = getattr(message, "stop_reason", "unknown")
        raise ValueError(f"anthropic tag_pcgamer_releases returned no parsed output (stop_reason={stop})")
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "max_tokens":
        log.warning(
            "tag_pcgamer_releases hit max_tokens — output may be truncated (got %d releases)",
            len(data.releases or []),
        )
    return list(data.releases or [])


IGN_RELEASES_SYSTEM_PROMPT = """You extract upcoming video game release dates from an IGN "Upcoming Games" calendar page.

Return ONLY valid JSON with one field:
- releases: array of objects with {name, release_date}.

Rules for `name`:
- Use the canonical game name as it appears on the page (preserve casing).
- Skip non-game entries: hardware, DLC unless standalone, expansion-only references, retrospectives.
- Skip "+1"/"+2"/"+N" badges between entries — those are related-item counters, not games.
- One row per distinct game. De-dup if a game appears multiple times.

Rules for `release_date` — output exactly one of these formats:
- "YYYY-MM-DD"  (specific day, e.g. "2026-07-15")
- "YYYY-MM"     (month known but no day, e.g. "2026-08")
- "Qn-YYYY"     (quarter only, e.g. "Q3-2026" — n in [1,2,3,4])
- "YYYY"        (year only, e.g. "2026" — use this when the page says "TBA/YYYY")
- "TBA"         (page says TBD/TBA with NO year)

IGN-specific date phrasings — normalize:
- "May 7, 2026" → "2026-05-07"
- "Q3/2026" or "Q3 2026" → "Q3-2026"
- "May 2026" (no day) → "2026-05"
- "TBA/2026" → "2026"  (year is known even though day isn't)
- "TBA" with no year → "TBA"

Worked examples (input phrase → output):
- "Hades II — May 7, 2026" → {name: "Hades II", release_date: "2026-05-07"}
- "Hollow Knight: Silksong — Q3/2026" → {name: "Hollow Knight: Silksong", release_date: "Q3-2026"}
- "Half-Life 3 — TBA/2026" → {name: "Half-Life 3", release_date: "2026"}
- "Project X — TBA" → {name: "Project X", release_date: "TBA"}

Output JSON only. No prose, no code fences. Aim for completeness — capture every game with a date on the page."""


def tag_ign_releases(body_text: str) -> list[PCGamerRelease]:
    """Call Anthropic Haiku 4.5 to extract (game, release_date) pairs from an
    IGN "Upcoming Games" calendar page body. Reuses the PCGamerRelease schema
    (shape-identical). Single call per refresh; idempotent upstream (the
    script diffs against the game_releases table). Phase 3c.24.

    Raises ValueError on transport / schema failure.
    """
    user_prompt = f"Page body:\n\n{body_text}"
    try:
        message = _get_client().messages.parse(
            model=ANTHROPIC_ENRICH_MODEL,
            max_tokens=8192,
            system=[
                {
                    "type": "text",
                    "text": IGN_RELEASES_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
            output_format=PCGamerReleaseList,
        )
    except anthropic.APIError as e:
        raise ValueError(f"anthropic tag_ign_releases API error: {e}") from e
    except ValidationError as e:
        raise ValueError(f"anthropic tag_ign_releases response failed schema: {e}") from e

    cost.record(ANTHROPIC_ENRICH_MODEL, message.usage)
    data = getattr(message, "parsed_output", None)
    if data is None:
        stop = getattr(message, "stop_reason", "unknown")
        raise ValueError(f"anthropic tag_ign_releases returned no parsed output (stop_reason={stop})")
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "max_tokens":
        log.warning(
            "tag_ign_releases hit max_tokens — output may be truncated (got %d releases)",
            len(data.releases or []),
        )
    return list(data.releases or [])


def tag_region(tldr: str) -> list[str]:
    """Call Anthropic Haiku 4.5 to extract region_focus from a tldr.

    Used by scripts/backfill_region.py to retro-tag existing enrichments
    without re-running the full enrich pass. Returns subset of
    {americas, europe, asia}; [] when no clear regional anchor.
    Raises ValueError on transport / schema failure.
    """
    user_prompt = f"TLDR: {tldr}"
    try:
        message = _get_client().messages.parse(
            model=ANTHROPIC_ENRICH_MODEL,
            max_tokens=128,
            system=[
                {
                    "type": "text",
                    "text": REGION_TAG_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
            output_format=RegionTagData,
        )
    except anthropic.APIError as e:
        raise ValueError(f"anthropic tag_region API error: {e}") from e
    except ValidationError as e:
        raise ValueError(f"anthropic tag_region response failed schema: {e}") from e

    cost.record(ANTHROPIC_ENRICH_MODEL, message.usage)
    data = getattr(message, "parsed_output", None)
    if data is None:
        stop = getattr(message, "stop_reason", "unknown")
        raise ValueError(f"anthropic tag_region returned no parsed output (stop_reason={stop})")
    return list(data.region_focus or [])
