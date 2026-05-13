"""GET /reports — claude.ai/design 'Gaming Chatter' weekly read-out.

Phase 3c.1 wires three cards to real per-ISO-week data from the DB:
  - Week overview (Card 1): stories + sources count, top genres + top platforms
                            mini-bars, net sentiment
  - Hottest games (Card 3): top-N games by mention count with platform /
                            lifecycle / live-service chips
  - Release radar (Card 11): upcoming-tagged games with structured release
                             dates (from IGN via Haiku, persisted in games dim)
                             and source pills

All other cards still render the design-bundle placeholder data; Phase 3c.4
will replace them with real synthesized output from Opus 4.7.

Locked variants: grid + comfortable + light + orange (#D9682B).
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import text as _sqltext
from sqlmodel import Session

from app.config import TEMPLATES_DIR
from app.db.session import engine
from app.services import reports as report_q

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
log = logging.getLogger(__name__)


# ---------- Sparkline geometry ----------------------------------------------

def sparkline_path(data: list[float], width: int = 80, height: int = 24) -> dict:
    """Mirror of the primitives.jsx Sparkline math: returns {points, area}."""
    if not data:
        return {"points": "", "area": ""}
    lo = min(min(data), 0)
    hi = max(max(data), 1)
    rng = hi - lo or 1
    x_step = width / (len(data) - 1) if len(data) > 1 else width

    def y(v: float) -> float:
        return height - 2 - ((v - lo) / rng) * (height - 4)

    pts = " ".join(f"{i * x_step:.2f},{y(v):.2f}" for i, v in enumerate(data))
    area = f"0,{height} {pts} {width},{height}"
    return {"points": pts, "area": area}


def delta_tone(value: str) -> str:
    if value.startswith("+"):
        return "up"
    if value.startswith("-") or value.startswith("−"):  # ASCII '-' or Unicode minus
        return "down"
    return "neutral"


# ---------- Static chrome (sidebar + nav) -----------------------------------

NAV_ITEMS = [
    {"id": "weekly",    "label": "Weekly read-out", "icon": "newspaper",    "is_active": True},
    {"id": "stories",   "label": "All stories",     "icon": "list",         "is_active": False},
    {"id": "watchlist", "label": "Watchlist",       "icon": "eye",          "is_active": False},
    {"id": "trends",    "label": "Trends",          "icon": "trending-up",  "is_active": False},
    {"id": "sources",   "label": "Sources",         "icon": "rss",          "is_active": False},
    {"id": "archive",   "label": "Archive",         "icon": "archive",      "is_active": False},
]

# Sidebar user-block — placeholder until Phase 3c.5 swaps it for corpus stats.
USER = {"name": "Jordan T.", "initials": "JT"}


# ---------- Placeholder for non-3c.1 cards ----------------------------------
# Phase 3c.4 will replace these dicts with synthesized output keyed off real
# clusters. Reused for every real ISO week so the layout stays intact.

_PLACEHOLDER_OTHER: dict = {
    "biggest": {
        "title": "Phase 3c.4 will surface the highest-scoring cluster here",
        "dek": "This card renders the design-bundle placeholder until Opus 4.7 synthesis lands. The other cards below the Week overview, Hottest games, and Release radar are similarly placeholder — Phase 3c.1 only wired those three.",
        "sources": ["IGN", "Eurogamer", "VGC", "r/Games", "ResetEra"],
        "heat": 60, "confidence": 60, "relevance": 60,
        "sparkline": [12, 18, 22, 31, 48, 60, 70],
        "first_seen": "—",
        "threads": 0,
    },
    "risks": [
        {"title": "Industry risks — synthesis pending", "level": "med",
         "note": "Phase 3c.4 will produce real layoff / regulation / policy callouts from the corpus.",
         "trend": "stable"},
    ],
    "momentum_raw": {
        "steamCCU":    {"label": "Steam CCU",     "value": "—",  "delta": "+0%", "spark": [0, 0, 0, 0, 0, 0, 0]},
        "twitchHrs":   {"label": "Twitch hrs",    "value": "—",  "delta": "+0%", "spark": [0, 0, 0, 0, 0, 0, 0]},
        "gamePassNet": {"label": "Game Pass net", "value": "—",  "delta": "+0%", "spark": [0, 0, 0, 0, 0, 0, 0]},
        "psnNet":      {"label": "PSN net adds",  "value": "—",  "delta": "+0%", "spark": [0, 0, 0, 0, 0, 0, 0]},
    },
    "trends": {
        "wow": [{"label": "Trends card — Phase 3c.2", "value": "—", "tone": "neutral"}],
        "mom": [],
    },
    "watch": [{"day": "—", "item": "Watch-next-week — synthesis pending"}],
    "community": {
        "positive": 0, "neutral": 100, "negative": 0,
        "top_threads": [{"sub": "r/Games", "title": "Community sentiment — synthesis pending", "score": "—", "sentiment": 0}],
    },
    "studios": [{"studio": "Studio watch — synthesis pending", "event": "Phase 3c.4 will fill this card", "tone": "neutral", "date": "—"}],
    "platforms": [{"name": "Storefronts", "change": "Synthesis pending", "impact": "low", "tone": "neutral"}],
    "esports": {
        "top_stream": {"game": "—", "hrs": "—", "delta": "+0%"},
        "big_event":  {"name": "Esports — synthesis pending", "peak": "—"},
        "movers": [],
    },
    "drama": [{"title": "Controversy tracker — synthesis pending", "severity": "low",
               "recap": "Phase 3c.4 narrows this card to exec / PR drama from the corpus."}],
}

_MOMENTUM_KEYS = ["steamCCU", "twitchHrs", "gamePassNet", "psnNet"]


# ---------- Per-request helpers --------------------------------------------

def _build_sources_meta(session: Session) -> dict[str, dict]:
    """Map each source name to its UI pill kind (outlet / subreddit / youtube)."""
    rows = session.exec(_sqltext("SELECT name, type, url_or_handle FROM sources")).all()
    meta: dict[str, dict] = {}
    for name, type_, url in rows:
        if type_ == "youtube":
            kind = "youtube"
        elif "reddit.com" in (url or "") or name.startswith("r/"):
            kind = "subreddit"
        else:
            kind = "outlet"
        meta[name] = {"kind": kind}
    return meta


def _latest_ingest_at(session: Session) -> str:
    row = session.exec(_sqltext(
        "SELECT MAX(completed_at) FROM run_log WHERE job_type='ingest' AND status='ok'"
    )).first()
    val = row[0] if row else None
    if not val:
        return "—"
    # Format as relative-ish to keep the header tight.
    try:
        dt = val if isinstance(val, datetime) else datetime.fromisoformat(str(val))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        mins = int(delta.total_seconds() // 60)
        if mins < 60:
            return f"{mins} min ago"
        hrs = mins // 60
        if hrs < 48:
            return f"{hrs} h ago"
        return f"{hrs // 24} d ago"
    except Exception:  # noqa: BLE001
        return str(val)[:16]


def _build_week_payload(session: Session, week_id: str) -> dict:
    """Build the full per-week payload, overlaying real data on shared placeholder."""
    label, rng = report_q.week_label_and_range(week_id)
    stats = report_q.week_stats(session, week_id)
    genres = report_q.top_genres_for_week(session, week_id, limit=5)
    platforms = report_q.top_platforms_for_week(session, week_id, limit=6)
    hottest_all = report_q.top_games_for_week(session, week_id, limit=5)
    hottest_current = report_q.top_games_for_week(session, week_id, limit=5, lifecycle="existing")
    hottest_upcoming = report_q.top_games_for_week(session, week_id, limit=5, lifecycle="upcoming")
    releases = report_q.upcoming_releases(session, week_id, limit=10)

    cards = copy.deepcopy(_PLACEHOLDER_OTHER)
    cards["week"] = {
        "stories": stats["stories"],
        "sources": stats["sources"],
        "top_genres": genres,        # list[(name, count)]
        "top_platforms": platforms,  # list[(name, count)]
    }
    cards["hottest"] = {
        "all": hottest_all,
        "current": hottest_current,
        "upcoming": hottest_upcoming,
    }
    cards["releases"] = releases     # list of dicts (name, release_date, display_date, mention_count)

    return {
        "label": label,
        "range": rng,
        "summary": {
            "headline": (
                "Phase 3c.1 preview · real data for Week overview, Hottest games, "
                "and Release radar. Remaining cards await Phase 3c.4 synthesis."
            ),
            "stats": {
                "stories": stats["stories"],
                "sources": stats["sources"],
            },
        },
        "cards": cards,
    }


def _enrich_for_render(week: dict) -> dict:
    """Add sparkline geometry + delta tones the template macros expect."""
    cards = week["cards"]

    big = cards["biggest"]
    big["spark_path"] = sparkline_path(big["sparkline"], width=100, height=28)

    momentum_list = []
    for key in _MOMENTUM_KEYS:
        cell = dict(cards["momentum_raw"][key])
        tone = delta_tone(cell["delta"])
        cell["color"] = "var(--gc-success)" if tone == "up" else "var(--gc-danger)"
        cell["spark_path"] = sparkline_path(cell["spark"], width=56, height=20)
        momentum_list.append(cell)
    cards["momentum"] = momentum_list

    for m in cards["esports"]["movers"]:
        m["delta_tone"] = delta_tone(m["delta"])

    return week


# ---------- Route -----------------------------------------------------------

@router.get("/reports")
def reports_view(request: Request, week: str = ""):
    with Session(engine) as session:
        week_ids = report_q.available_weeks(session)

        # Empty-corpus fallback — renders the chrome with one blank week.
        if not week_ids:
            blank = {
                "label": "No clustered weeks yet",
                "range": "—",
                "summary": {"headline": "Run the ingest + cluster pipeline to populate this view.",
                            "stats": {"stories": 0, "sources": 0, "sentiment": 0}},
                "cards": {
                    "week": {"stories": 0, "sources": 0, "top_genres": [], "top_platforms": []},
                    "hottest": {"all": [], "current": [], "upcoming": []},
                    "releases": [],
                    **copy.deepcopy(_PLACEHOLDER_OTHER),
                },
            }
            return templates.TemplateResponse(
                request, "reports.html",
                {"week": _enrich_for_render(blank), "weeks_index": [],
                 "nav_items": NAV_ITEMS, "user": USER, "source_count": 0,
                 "refreshed_at": "—", "sources_meta": {}},
            )

        active_key = week if week in week_ids else week_ids[0]

        weeks_index = []
        for k in week_ids:
            label, rng = report_q.week_label_and_range(k)
            weeks_index.append({"key": k, "label": label, "range": rng, "is_active": k == active_key})

        week_data = _enrich_for_render(_build_week_payload(session, active_key))
        sources_meta = _build_sources_meta(session)

        return templates.TemplateResponse(
            request, "reports.html",
            {
                "week": week_data,
                "weeks_index": weeks_index,
                "nav_items": NAV_ITEMS,
                "user": USER,
                "source_count": len(sources_meta),
                "refreshed_at": _latest_ingest_at(session),
                "sources_meta": sources_meta,
            },
        )
