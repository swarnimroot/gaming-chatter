"""Anthropic Haiku 4.5 client for per-item enrichment.

Replaces the qwen2.5:7b Ollama path under the lock-override of 2026-05-12
(see docs/DECISIONS.md). Embeddings stay on Ollama.

Reuses EnrichmentData + SYSTEM_PROMPT + taxonomies from app.services.ollama
so there is a single source of truth for the schema and prompt text.
"""
from __future__ import annotations

import logging

import anthropic
from pydantic import ValidationError

from app.config import (
    ANTHROPIC_ENRICH_MODEL,
    ANTHROPIC_TIMEOUT,
    ENRICH_BODY_CHAR_CAP,
)
from app.services.ollama import (
    _ALLOWED_CATEGORIES,
    GAME_TAG_SYSTEM_PROMPT,
    GameTagData,
    SYSTEM_PROMPT,
    EnrichmentData,
)

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

    data = getattr(message, "parsed_output", None)
    if data is None:
        stop = getattr(message, "stop_reason", "unknown")
        raise ValueError(f"anthropic returned no parsed output (stop_reason={stop})")

    if data.category not in _ALLOWED_CATEGORIES:
        raise ValueError(f"category '{data.category}' not in allowed set")
    if not -1.0 <= data.sentiment_score <= 1.0:
        raise ValueError(f"sentiment_score out of range: {data.sentiment_score}")

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

    data = getattr(message, "parsed_output", None)
    if data is None:
        stop = getattr(message, "stop_reason", "unknown")
        raise ValueError(f"anthropic tag_game returned no parsed output (stop_reason={stop})")
    return data
