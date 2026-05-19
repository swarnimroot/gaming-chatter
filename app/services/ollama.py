"""Ollama HTTP client + per-item enrichment and embedding.

Single-process design: called from FastAPI BackgroundTasks running sequentially
against a local Ollama instance. httpx sync, no pooling beyond defaults.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx
import numpy as np
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import (
    ENRICH_BODY_CHAR_CAP,
    OLLAMA_EMBED_MODEL,
    OLLAMA_ENRICH_MODEL,
    OLLAMA_HOST,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_NUM_CTX,
)

log = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")

_ALLOWED_CATEGORIES = {
    "news", "leak", "launch", "industry", "community", "opinion", "patch", "review",
}

GENRES = {"Action","Adventure","RPG","Shooter","Strategy","Simulation",
          "Sports","Racing","Fighting","MMO","Survival-horror","Indie/Roguelike"}
PLATFORMS = {"PC","PlayStation","Xbox","Nintendo","Mobile","Multi-platform"}
EVENTS = {"Summer Game Fest","Gamescom","Tokyo Game Show","The Game Awards",
          "State of Play","Nintendo Direct","Xbox Showcase","PC Gaming Show",
          "EVO","BlizzCon","Future Games Show","Other-showcase"}
REGIONS = {"americas", "europe", "asia"}


class Entities(BaseModel):
    games: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)

    @field_validator("games", "companies", "people", mode="before")
    @classmethod
    def _dict_to_list(cls, v):
        if isinstance(v, dict):
            return list(v.keys())
        return v


class EnrichmentData(BaseModel):
    tldr: str
    entities: Entities
    category: str
    sentiment_score: float
    sentiment_summary: str
    genres: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    event: Optional[str] = None
    region_focus: list[str] = Field(default_factory=list)

    @field_validator("genres", mode="before")
    @classmethod
    def _filter_genres(cls, v):
        if not isinstance(v, list):
            return []
        return [g for g in v if isinstance(g, str) and g in GENRES][:3]

    @field_validator("platforms", mode="before")
    @classmethod
    def _filter_platforms(cls, v):
        if not isinstance(v, list):
            return []
        return [p for p in v if isinstance(p, str) and p in PLATFORMS]

    @field_validator("event", mode="before")
    @classmethod
    def _filter_event(cls, v):
        if isinstance(v, str) and v in EVENTS:
            return v
        return None

    @field_validator("region_focus", mode="before")
    @classmethod
    def _filter_region_focus(cls, v):
        if not isinstance(v, list):
            return []
        seen: list[str] = []
        for r in v:
            if isinstance(r, str):
                r_norm = r.strip().lower()
                if r_norm in REGIONS and r_norm not in seen:
                    seen.append(r_norm)
        return seen


SYSTEM_PROMPT = """You are an analyst summarizing a single gaming-news item for a personal aggregator.

Return ONLY valid JSON with these fields:
- tldr: 1-2 sentence neutral summary in plain prose. No marketing voice.
- entities: object with arrays games, companies, people. Use canonical names. Empty arrays are fine.
- category: exactly one of: news, leak, launch, industry, community, opinion, patch, review.
- sentiment_score: number from -1 (very negative) to 1 (very positive). 0 = neutral.
- sentiment_summary: one short sentence (<=15 words) explaining the sentiment.
- genres: array (max 3) of strings from the genres taxonomy below. [] if not about a specific game.
- platforms: array of strings from the platforms taxonomy below. [] if no platform mentioned.
- event: one string from the events taxonomy below, or null. null unless reporting from a listed event.
- region_focus: array from [americas, europe, asia], or []. Tag only when news is *anchored* in that region (regulators, region-specific events, region-only releases, region-specific business news). Company HQ alone is NOT enough.

Rules:
- Do not invent facts. If the body is short, give a short tldr.
- "industry" = business / layoffs / acquisitions / regulation. "community" = drama, controversy, fan reactions. "patch" = updates / bug fixes / balance changes. "review" = critical assessment of a released game / hardware.
- entities.people: only real named people (devs, executives, journalists, voice actors). Never include Reddit usernames, commenter handles, anonymous accounts, or names that look like underscored handles (e.g. "Responsible_Box_2422").

- genres taxonomy (most-defining first, max 3):
    [Action, Adventure, RPG, Shooter, Strategy, Simulation, Sports, Racing,
     Fighting, MMO, Survival-horror, Indie/Roguelike]
  If the game blends genres (e.g. action-RPG), pick the 2-3 most defining; do NOT list all.

- platforms taxonomy:
    [PC, PlayStation, Xbox, Nintendo, Mobile, Multi-platform]
  List each named platform individually (e.g. a PC + PS5 game -> ["PC","PlayStation"]).
  Use "Multi-platform" ONLY when the source explicitly says "cross-platform" or "multi-platform"
  without naming specific platforms.

- events taxonomy:
    [Summer Game Fest, Gamescom, Tokyo Game Show, The Game Awards, State of Play,
     Nintendo Direct, Xbox Showcase, PC Gaming Show, EVO, BlizzCon, Future Games Show,
     Other-showcase]
  Set ONLY if the article is reporting from or directly about one of these events.
  A trailer that "premiered at Summer Game Fest" -> event="Summer Game Fest".
  A generic patch note with no event context -> event=null.
  Unknown showcases / minor publisher streams -> event="Other-showcase".

- region_focus taxonomy:
    [americas, europe, asia]
  Tag a region only when the news is ANCHORED in it — regulatory action, region-specific event,
  region-only release / pricing, region-specific business or operational news.
  Company HQ alone is NOT enough — a Japanese studio's worldwide reveal is [], not ["asia"].
  Multi-tag for cross-region stories (e.g. CN buyer + EU target -> ["asia","europe"]).
  Worked examples:
    - "FTC sues Microsoft over Activision deal" -> ["americas"]
    - "Capcom delays game in Japan only" -> ["asia"]
    - "Tencent acquires Norwegian studio Funcom" -> ["asia","europe"]
    - "EU passes new game-rating law" -> ["europe"]
    - "GTA 6 trailer drops Nov 5" -> []          (worldwide launch)
    - "Nintendo Direct September recap" -> []   (event is global despite JP host)
    - "Halo Season 8 patch notes" -> []         (gameplay, no regional angle)

Out-of-taxonomy rule: if a value doesn't fit the lists above, OMIT it.
Do NOT map "MOBA"->"Strategy", do NOT map "Switch"->"Nintendo" (model: just output "Nintendo"),
do NOT map "Linux/Steam Deck"->"PC" (omit it).

Worked examples:
  - Helldivers 2 warbond patch (PC + PS5) ->
      genres=["Shooter"], platforms=["PC","PlayStation"], event=null
  - Final Fantasy XVI PC port announced at State of Play ->
      genres=["RPG","Action"], platforms=["PC"], event="State of Play"
  - Vampire Survivors crossover DLC ->
      genres=["Indie/Roguelike"], platforms=["Multi-platform"], event=null
  - EA Q1 layoffs report (no specific game) ->
      genres=[], platforms=[], event=null
  - Reddit thread on a leaked MOBA project ->
      genres=[], platforms=[], event=null   (MOBA not in taxonomy -> drop)
  - Game Awards 2025 winners recap ->
      genres=[], platforms=[], event="The Game Awards"

Output JSON only. No prose, no code fences, no commentary."""


def _enrichment_json_schema() -> dict:
    """Build a JSON schema for Ollama structured-output constrained decoding.

    Derived from EnrichmentData.model_json_schema() but with all 9 fields marked
    required so the model cannot silently omit genres/platforms/event/region_focus.
    """
    schema = EnrichmentData.model_json_schema()
    schema["required"] = [
        "tldr", "entities", "category", "sentiment_score", "sentiment_summary",
        "genres", "platforms", "event", "region_focus",
    ]
    return schema


def _truncate(text: str, cap: int) -> tuple[str, bool]:
    if not text:
        return "", False
    if len(text) <= cap:
        return text, False
    return text[:cap], True


def extract_video_id(url: str) -> Optional[str]:
    """Pull the 11-char YouTube video ID from a watch/short/embed URL."""
    m = _VIDEO_ID_RE.search(url or "")
    return m.group(1) if m else None


def fetch_youtube_transcript(url_or_id: str) -> str:
    """Fetch transcript via tier1.youtube. Returns concatenated text or '' on failure.

    Every failure mode (no captions, blocked, private, age-gated) returns ''.
    Caller falls back to whatever body_text was captured at ingest.
    """
    try:
        from scrapers_lib.tier1.youtube import fetch_youtube_transcript as _yt
    except ImportError:
        log.warning("scrapers_lib.tier1.youtube not importable; skipping transcript")
        return ""
    try:
        chunks = _yt(url_or_id, audio_fallback=True)
    except Exception as e:  # noqa: BLE001
        log.warning("youtube transcript fetch failed for %s: %s", url_or_id, e)
        return ""
    if not chunks:
        return ""
    return " ".join(getattr(c, "raw_text", "") for c in chunks if getattr(c, "raw_text", None))


def enrich_item(title: str, body: str, source_label: str) -> EnrichmentData:
    """Call Ollama enrichment model. Raises on transport / parse / schema failure."""
    body_text, truncated = _truncate(body or "", ENRICH_BODY_CHAR_CAP)
    if truncated:
        log.info(
            "enrich body truncated for '%s' (orig=%d chars, cap=%d)",
            title[:60], len(body), ENRICH_BODY_CHAR_CAP,
        )

    user_prompt = f"Source: {source_label}\nTitle: {title}\n\nBody:\n{body_text or '(no body)'}"
    payload = {
        "model": OLLAMA_ENRICH_MODEL,
        "prompt": user_prompt,
        "system": SYSTEM_PROMPT,
        "format": _enrichment_json_schema(),
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_ctx": OLLAMA_NUM_CTX,
            "temperature": 0.2,
        },
    }
    r = httpx.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=180.0)
    r.raise_for_status()
    response_text = r.json().get("response", "")

    try:
        raw = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"ollama returned non-JSON: {response_text[:200]!r}") from e

    try:
        data = EnrichmentData(**raw)
    except ValidationError as e:
        raise ValueError(f"ollama JSON failed schema: {e}") from e

    if data.category not in _ALLOWED_CATEGORIES:
        raise ValueError(f"category '{data.category}' not in allowed set")
    if not -1.0 <= data.sentiment_score <= 1.0:
        raise ValueError(f"sentiment_score out of range: {data.sentiment_score}")

    return data


class GameTagData(BaseModel):
    lifecycle: Optional[str] = None      # 'existing' | 'upcoming' | None
    live_service: Optional[bool] = None  # True | False | None

    @field_validator("lifecycle", mode="before")
    @classmethod
    def _filter_lifecycle(cls, v):
        return v if v in {"existing", "upcoming"} else None


def _game_tag_json_schema() -> dict:
    schema = GameTagData.model_json_schema()
    schema["required"] = ["lifecycle", "live_service"]
    return schema


GAME_TAG_SYSTEM_PROMPT = """You are a game-tagging specialist for a gaming-news aggregator.

Given a single game name, return ONLY valid JSON with these two fields:
- lifecycle: one of "existing", "upcoming", or null.
- live_service: one of true, false, or null.

Lifecycle rules:
- "existing" = the game has been released on at least one platform anywhere.
  Early access counts as released. Remasters/remakes are existing.
  A cross-platform-delay item where one platform shipped is still existing.
- "upcoming" = the game has NOT been released on any platform yet.
- null = you genuinely don't recognize the game or cannot tell.

Live-service rules:
- true = the game has a seasonal / battle-pass / league / warbond content model
  with regular content drops. MMOs ARE live-service.
- false = single-player or one-time-purchase titles, even if they have DLC.
  Episodic story games are NOT live-service. Roguelikes with one-time content are NOT.
- null = unknown / cannot tell.

Worked examples:
- "Helldivers 2" -> {"lifecycle": "existing", "live_service": true}
- "Fortnite" -> {"lifecycle": "existing", "live_service": true}
- "World of Warcraft" -> {"lifecycle": "existing", "live_service": true}
- "The Witcher 3" -> {"lifecycle": "existing", "live_service": false}
- "Baldur's Gate 3" -> {"lifecycle": "existing", "live_service": false}
- "GTA VI" -> {"lifecycle": "upcoming", "live_service": null}
- "Mina the Hollower" -> {"lifecycle": "upcoming", "live_service": false}
- "Pragmata" -> {"lifecycle": "existing", "live_service": false}
- "Vampire Survivors" -> {"lifecycle": "existing", "live_service": false}
- "Some Random Indie Nobody Has Heard Of" -> {"lifecycle": null, "live_service": null}

Output JSON only. No prose, no code fences, no commentary."""


def tag_game(game_name: str) -> GameTagData:
    """Call Ollama to tag a single game with lifecycle + live_service flags.

    Raises on transport / parse / schema failure. Caller decides whether to
    log+skip or fail.
    """
    log.info("tag_game: %s", game_name)
    user_prompt = f"Game: {game_name}"
    payload = {
        "model": OLLAMA_ENRICH_MODEL,
        "prompt": user_prompt,
        "system": GAME_TAG_SYSTEM_PROMPT,
        "format": _game_tag_json_schema(),
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_ctx": OLLAMA_NUM_CTX,
            "temperature": 0.2,
        },
    }
    r = httpx.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=180.0)
    r.raise_for_status()
    response_text = r.json().get("response", "")
    log.debug("tag_game response for %s: %s", game_name, response_text)

    try:
        raw = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"ollama tag_game returned non-JSON: {response_text[:200]!r}") from e

    try:
        data = GameTagData(**raw)
    except ValidationError as e:
        raise ValueError(f"ollama tag_game JSON failed schema: {e}") from e

    return data


CLUSTER_LABEL_SYSTEM_PROMPT = """You label a group of gaming-news articles that all cover the same story or topic.

Return ONLY valid JSON: {"label": "<short phrase>"}

Rules:
- 4-10 words, plain prose, neutral tone. No marketing voice, no quotes, no trailing punctuation.
- Name the actual subject (game, company, event), not meta-words like "articles" or "news".
- Examples of good labels:
  - "Mixtape indie game critical reception"
  - "Greedfall studio Spiders shutting down"
  - "Star Fox 64 remake announced for Switch 2"
  - "Steam Controller restock after sellout"
  - "Sony rolls out PlayStation age verification UK"
- Output JSON only. No prose, no code fences, no commentary."""


def label_cluster(titles: list[str], tldrs: list[str]) -> str:
    """Generate a single-line label for a cluster from its member titles + tldrs.

    Caller decides how many examples to pass; this function does not subsample.
    Raises on transport / parse / schema failure.
    """
    lines = []
    for t, s in zip(titles, tldrs):
        title = (t or "").strip()
        tldr = (s or "").strip()
        if title and tldr:
            lines.append(f"- {title}\n  {tldr}")
        elif title:
            lines.append(f"- {title}")
    user_prompt = "Articles in this cluster:\n\n" + "\n".join(lines)

    payload = {
        "model": OLLAMA_ENRICH_MODEL,
        "prompt": user_prompt,
        "system": CLUSTER_LABEL_SYSTEM_PROMPT,
        "format": "json",
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_ctx": OLLAMA_NUM_CTX,
            "temperature": 0.2,
        },
    }
    r = httpx.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=120.0)
    r.raise_for_status()
    response_text = r.json().get("response", "")

    try:
        raw = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"ollama label returned non-JSON: {response_text[:200]!r}") from e

    label = raw.get("label", "")
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"ollama label missing/empty: {raw!r}")
    return label.strip()


def embed_text(text: str) -> bytes:
    """Return embedding as fp32 numpy bytes for storage as BLOB."""
    text_capped, _ = _truncate(text or "", ENRICH_BODY_CHAR_CAP)
    payload = {
        "model": OLLAMA_EMBED_MODEL,
        "prompt": text_capped,
        "keep_alive": OLLAMA_KEEP_ALIVE,
    }
    r = httpx.post(f"{OLLAMA_HOST}/api/embeddings", json=payload, timeout=60.0)
    r.raise_for_status()
    vec = r.json().get("embedding")
    if not vec:
        raise ValueError("ollama embeddings response missing 'embedding' field")
    return np.asarray(vec, dtype=np.float32).tobytes()
