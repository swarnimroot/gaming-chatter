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


SYSTEM_PROMPT = """You are an analyst summarizing a single gaming-news item for a personal aggregator.

Return ONLY valid JSON with these fields:
- tldr: 1-2 sentence neutral summary in plain prose. No marketing voice.
- entities: object with arrays games, companies, people. Use canonical names. Empty arrays are fine.
- category: exactly one of: news, leak, launch, industry, community, opinion, patch, review.
- sentiment_score: number from -1 (very negative) to 1 (very positive). 0 = neutral.
- sentiment_summary: one short sentence (<=15 words) explaining the sentiment.

Rules:
- Do not invent facts. If the body is short, give a short tldr.
- "industry" = business / layoffs / acquisitions / regulation. "community" = drama, controversy, fan reactions. "patch" = updates / bug fixes / balance changes. "review" = critical assessment of a released game / hardware.
- entities.people: only real named people (devs, executives, journalists, voice actors). Never include Reddit usernames, commenter handles, anonymous accounts, or names that look like underscored handles (e.g. "Responsible_Box_2422").
- Output JSON only. No prose, no code fences, no commentary."""


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
        chunks = _yt(url_or_id)
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
        "format": "json",
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
