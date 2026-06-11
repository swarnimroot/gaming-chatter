"""Exec-summary modal: Haiku 4.5 1-paragraph TLDR of the week.

Phase 3c.3. The modal calls `get_or_generate(session, week_id)` on first open;
the paragraph is persisted to `weekly_reports.exec_summary_text` keyed by
`week_start` so subsequent opens for the same week serve from cache without
hitting the Anthropic API. Phase 3c.4 will own the deep synthesis pass on
Opus 4.7 — this service stays focused on the lightweight modal headline.

Inputs assembled from existing services.reports queries (week stats + top
genres + top platforms + top games + best Trends risers) so this module
stays read-only against the corpus and doesn't duplicate any aggregation.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import anthropic
from sqlalchemy import text as _sqltext
from sqlmodel import Session, select

from app.config import ANTHROPIC_EXEC_SUMMARY_MODEL, ANTHROPIC_TIMEOUT
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


# System block — stable across weeks, prompt-cached. The minimum cacheable
# prefix on Haiku 4.5 is currently above this length so caching no-ops
# harmlessly today; will activate automatically if the prompt grows.
_SYSTEM_PROMPT = """You are an editor writing a single-paragraph weekly read-out for a personal gaming-news aggregator.

OUTPUT FORMAT — strict:
- Exactly one paragraph.
- 3 to 5 sentences. No bullet lists, no headings, no markdown formatting.
- Lead sentence states the biggest concrete signal of the week (the most-mentioned game, dominant platform, or biggest spike) — name it specifically.
- Follow with one or two sentences on supporting signals (top genres, notable risers, sentiment direction) — only mention items that appear in the input data.
- Close with one sentence on what's worth watching next week, drawn from upcoming releases or rising trends visible in the data.

VOICE:
- Factual and terse. No hype, no marketing language, no rhetorical questions.
- No first-person, no second-person, no editorializing ("amazing", "must-watch", "fans will love").
- Use specific names — game titles, genres, platforms. Avoid generic phrases like "various games" or "many studios".

HARD RULES:
- Do not invent any game title, studio, person, number, or event that is not in the input.
- Do not speculate about anything not shown.
- If a section in the input is empty or sparse, simply omit it from the paragraph rather than padding.
- Do not start with "This week..." or "In gaming this week...". Start with the strongest signal directly.

OUTPUT: only the paragraph text. No preamble, no surrounding quotation marks, no model commentary."""


def _format_input(
    week_label: str,
    week_range: str,
    stats: dict,
    genres: list[tuple[str, int]],
    platforms: list[tuple[str, int]],
    top_games: list[dict],
    trends: dict,
) -> str:
    lines: list[str] = []
    lines.append(f"Week: {week_label} ({week_range})")
    lines.append(f"Corpus: {stats.get('stories', 0)} stories from {stats.get('sources', 0)} sources.")

    if top_games:
        gs = ", ".join(f"{g['name']} ({g['count']})" for g in top_games[:5])
        lines.append(f"Most-mentioned games: {gs}.")

    if genres:
        gs = ", ".join(f"{n} ({c})" for n, c in genres[:5])
        lines.append(f"Top genres: {gs}.")

    if platforms:
        ps = ", ".join(f"{n} ({c})" for n, c in platforms[:6])
        lines.append(f"Top platforms: {ps}.")

    if trends.get("has_prior"):
        risers: list[str] = []
        for tab_key, label in [
            ("games_current", "current games"),
            ("games_upcoming", "upcoming games"),
            ("genres", "genres"),
            ("platforms", "platforms"),
            ("live_service", "live-service games"),
            ("events", "events"),
        ]:
            rows = trends.get(tab_key) or []
            ups = [r for r in rows if r["tone"] == "up"][:2]
            if ups:
                bits = ", ".join(f"{r['name']} {r['delta_display']}" for r in ups)
                risers.append(f"{label}: {bits}")
        if risers:
            lines.append("Week-over-week risers — " + "; ".join(risers) + ".")

    return "\n".join(lines)


def _build_input_text(session: Session, week_id: str) -> str:
    label, rng = report_q.week_label_and_range(week_id)
    stats = report_q.week_stats(session, week_id)
    genres = report_q.top_genres_for_week(session, week_id, limit=5)
    platforms = report_q.top_platforms_for_week(session, week_id, limit=6)
    top_games = report_q.top_games_for_week(session, week_id, limit=5)
    trends = report_q.trends_for_week(session, week_id, limit=5)
    text = _format_input(label, rng, stats, genres, platforms, top_games, trends)

    upcoming = report_q.upcoming_releases(session, week_id, limit=8)
    if upcoming:
        bits = ", ".join(f"{r['name']} ({r['display_date']})" for r in upcoming[:6])
        text += f"\nUpcoming releases mentioned: {bits}."
    return text


def _load_cached(session: Session, week_id: str) -> Optional[WeeklyReport]:
    week_start, week_end = report_q.iso_week_bounds(week_id)
    row = session.exec(
        select(WeeklyReport).where(WeeklyReport.week_start == week_start)
    ).first()
    return row


def _call_haiku(user_text: str) -> str:
    try:
        message = _get_client().messages.create(
            model=ANTHROPIC_EXEC_SUMMARY_MODEL,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_text}],
        )
    except anthropic.APIError as e:
        raise ValueError(f"anthropic exec-summary API error: {e}") from e

    cost.record(ANTHROPIC_EXEC_SUMMARY_MODEL, message.usage, phase="exec_summary")
    blocks = [b.text for b in message.content if getattr(b, "type", None) == "text"]
    if not blocks:
        stop = getattr(message, "stop_reason", "unknown")
        raise ValueError(f"anthropic exec-summary returned no text (stop_reason={stop})")
    return "\n".join(blocks).strip()


def get_or_generate(
    session: Session,
    week_id: str,
    force: bool = False,
) -> dict:
    """Return the cached or freshly-generated paragraph for `week_id`.

    Returns a dict: {text, model, generated_at, from_cache, week_label}.
    `force=True` regenerates even if a cached row exists (useful after corpus
    re-enrichment; not exposed in the UI yet).
    """
    label, _ = report_q.week_label_and_range(week_id)
    cached = _load_cached(session, week_id)
    if cached and cached.exec_summary_text and not force:
        return {
            "text": cached.exec_summary_text,
            "model": cached.exec_summary_model or ANTHROPIC_EXEC_SUMMARY_MODEL,
            "generated_at": cached.exec_summary_generated_at,
            "from_cache": True,
            "week_label": label,
        }

    user_text = _build_input_text(session, week_id)
    log.info("exec-summary cache miss for %s — calling %s", week_id, ANTHROPIC_EXEC_SUMMARY_MODEL)
    paragraph = _call_haiku(user_text)
    now = datetime.utcnow()

    week_start, week_end = report_q.iso_week_bounds(week_id)
    if cached is None:
        cached = WeeklyReport(
            week_start=week_start,
            week_end=week_end,
            exec_summary_text=paragraph,
            exec_summary_model=ANTHROPIC_EXEC_SUMMARY_MODEL,
            exec_summary_generated_at=now,
            status="exec_summary_only",
        )
        session.add(cached)
    else:
        cached.exec_summary_text = paragraph
        cached.exec_summary_model = ANTHROPIC_EXEC_SUMMARY_MODEL
        cached.exec_summary_generated_at = now
        session.add(cached)
    session.commit()

    return {
        "text": paragraph,
        "model": ANTHROPIC_EXEC_SUMMARY_MODEL,
        "generated_at": now,
        "from_cache": False,
        "week_label": label,
    }
