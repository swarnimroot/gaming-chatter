"""GET /reports — weekly read-out (9-card layout per 2026-05-12 walkthrough).

Card data sources:
  - Week / Hottest / Trends / Releases — real per-ISO-week aggregation from
    services.reports (Phases 3c.1 / 3c.2).
  - Biggest / Market momentum / Community sentiment / Risks / Esports /
    Drama / Watch — Opus 4.7 synthesis JSON on weekly_reports (Phase 3c.4).
    Weeks without a synthesis row render an empty-state row per card.

Sidebar:
  - Read-out picker (one per week with clusters, descending)
  - Navigate (4 routes: Weekly read-out, Dashboard, Clusters, Sources)
  - Corpus stats (items / clusters / sources) — Phase 3c.5

Locked variants: grid + comfortable + light + orange (#D9682B).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import text as _sqltext
from sqlmodel import Session

from app.config import TEMPLATES_DIR
from app.db.session import engine
from app.services import exec_summary as exec_summary_svc
from app.services import reports as report_q

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
log = logging.getLogger(__name__)


# ---------- Static chrome (sidebar nav) -------------------------------------

NAV_ITEMS = [
    {"id": "weekly",    "label": "Weekly read-out", "icon": "newspaper", "href": "/reports",  "is_active": True},
    {"id": "dashboard", "label": "Dashboard",       "icon": "gauge",     "href": "/",         "is_active": False},
    {"id": "clusters",  "label": "Clusters",        "icon": "shapes",    "href": "/clusters", "is_active": False},
    {"id": "sources",   "label": "Sources",         "icon": "rss",       "href": "/sources",  "is_active": False},
]


# ---------- Empty-state card shape ------------------------------------------

def _empty_cards() -> dict:
    """Default per-week card shape — used both for the empty-corpus fallback
    and as the base into which `_apply_synthesis` writes real data."""
    return {
        "biggest": [],
        "market_momentum": [],
        "community": {"narrative": None, "heated_about": [], "celebrating": []},
        "risks": [],
        "esports": [],
        "drama": [],
        "watch": [],
    }


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


def _load_synthesis(session: Session, week_id: str) -> dict | None:
    """Load the weekly_reports.synthesis_json row for the week, or None."""
    try:
        week_start, _ = report_q.iso_week_bounds(week_id)
    except (ValueError, IndexError):
        return None
    row = session.exec(_sqltext(
        "SELECT synthesis_json, synthesis_model, synthesis_generated_at "
        "FROM weekly_reports WHERE week_start = :s"
    ).bindparams(s=week_start)).first()
    if not row or not row[0]:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return {
        "data": payload,
        "model": row[1],
        "generated_at": row[2],
    }


def _apply_synthesis(session: Session, cards: dict, synth: dict) -> None:
    """Overlay synthesis JSON onto the per-week card dict in place.

    Writes directly to first-class keys (no `*_synth` stash — that was the
    3c.4 transition shape). Biggest rows get source pills derived from
    cluster members so the template can render them without a second query.
    """
    data = synth["data"]

    # Biggest stories — plural top-3, each with source pills derived from
    # cluster members so the template doesn't need a second query.
    if data.get("biggest"):
        cluster_ids = [int(b["cluster_id"]) for b in data["biggest"]]
        pills = report_q.source_pills_for_clusters(session, cluster_ids)
        cards["biggest"] = [
            {
                "cluster_id": b["cluster_id"],
                "title": b["title"],
                "dek": b["dek"],
                "sources": pills.get(int(b["cluster_id"]), []),
            }
            for b in data["biggest"]
        ]

    # Market momentum — row list (acquisitions / funds / platform-policy /
    # structural / people-moves).
    cards["market_momentum"] = [
        {
            "cluster_id": m["cluster_id"],
            "title": m["title"],
            "note": m["note"],
            "category": m["category"],
        }
        for m in data.get("market_momentum", [])
    ]

    # Community sentiment — narrative + heated/celebrating clusters.
    cs = data.get("community_sentiment")
    if cs:
        cards["community"] = {
            "narrative": cs.get("narrative"),
            "heated_about": [
                {"cluster_id": c["cluster_id"], "title": c["title"], "note": c["note"]}
                for c in cs.get("heated_about", [])
            ],
            "celebrating": [
                {"cluster_id": c["cluster_id"], "title": c["title"], "note": c["note"]}
                for c in cs.get("celebrating", [])
            ],
        }

    # Risks — severity bar + title + level badge + note; trend chip dropped.
    cards["risks"] = [
        {
            "cluster_id": r["cluster_id"],
            "title": r["title"],
            "level": r["severity"],
            "note": r["note"],
        }
        for r in data.get("risks", [])
    ]

    # Esports — row list of cluster-anchored items.
    cards["esports"] = [
        {
            "cluster_id": e["cluster_id"],
            "title": e["title"],
            "note": e["note"],
        }
        for e in data.get("esports", [])
    ]

    # Drama — narrow scope (exec/PR + studio feuds).
    cards["drama"] = [
        {
            "cluster_id": d["cluster_id"],
            "title": d["title"],
            "severity": d["severity"],
            "recap": d["recap"],
        }
        for d in data.get("drama", [])
    ]

    # Watch next week.
    cards["watch"] = [
        {
            "day": w["day"],
            "item": w["item"],
            "cluster_id": w.get("cluster_id"),
        }
        for w in data.get("watch", [])
    ]

    # Hottest games — overlay synthesis 1-line reasons by game-name match.
    if data.get("hottest_reasons"):
        reason_by_name = {r["game_name"].lower(): r["reason"] for r in data["hottest_reasons"]}
        for bucket in ("all", "current", "upcoming"):
            for game in cards["hottest"][bucket]:
                game["reason"] = reason_by_name.get(game["name"].lower())

    # Releases — overlay synthesis 1-line notes by game-name match.
    if data.get("release_notes"):
        note_by_name = {r["game_name"].lower(): r["note"] for r in data["release_notes"]}
        for r in cards["releases"]:
            r["note"] = note_by_name.get(r["name"].lower())

    cards["synthesis_meta"] = {
        "model": synth["model"],
        "generated_at": synth["generated_at"],
    }


def _build_week_payload(session: Session, week_id: str) -> dict:
    """Assemble the full per-week card payload."""
    label, rng = report_q.week_label_and_range(week_id)
    stats = report_q.week_stats(session, week_id)
    hottest_all = report_q.top_games_for_week(session, week_id, limit=5)
    hottest_current = report_q.top_games_for_week(session, week_id, limit=5, lifecycle="existing")
    hottest_upcoming = report_q.top_games_for_week(session, week_id, limit=5, lifecycle="upcoming")
    releases = report_q.upcoming_releases(session, week_id, limit=10)
    trends = report_q.trends_for_week(session, week_id, limit=5)

    cards = _empty_cards()
    cards["hottest"] = {
        "all": hottest_all,
        "current": hottest_current,
        "upcoming": hottest_upcoming,
    }
    cards["releases"] = releases
    cards["trends"] = trends

    synth = _load_synthesis(session, week_id)
    if synth is not None:
        _apply_synthesis(session, cards, synth)

    return {
        "label": label,
        "range": rng,
        "stats": {"stories": stats["stories"], "sources": stats["sources"]},
        "cards": cards,
    }


# ---------- Route -----------------------------------------------------------

@router.get("/reports")
def reports_view(request: Request, week: str = ""):
    with Session(engine) as session:
        week_ids = report_q.available_weeks(session)
        stats = report_q.corpus_stats(session)

        # Empty-corpus fallback — renders the chrome with one blank week.
        if not week_ids:
            blank = {
                "label": "No clustered weeks yet",
                "range": "—",
                "stats": {"stories": 0, "sources": 0},
                "cards": {
                    "hottest": {"all": [], "current": [], "upcoming": []},
                    "releases": [],
                    "trends": {"has_prior": False, "prev_week_id": "—"},
                    **_empty_cards(),
                },
            }
            return templates.TemplateResponse(
                request, "reports.html",
                {"week": blank, "weeks_index": [], "active_week_key": "",
                 "nav_items": NAV_ITEMS, "corpus_stats": stats,
                 "refreshed_at": "—", "sources_meta": {}},
            )

        active_key = week if week in week_ids else week_ids[0]

        weeks_index = []
        for k in week_ids:
            label, rng = report_q.week_label_and_range(k)
            weeks_index.append({"key": k, "label": label, "range": rng, "is_active": k == active_key})

        week_data = _build_week_payload(session, active_key)
        sources_meta = _build_sources_meta(session)

        return templates.TemplateResponse(
            request, "reports.html",
            {
                "week": week_data,
                "weeks_index": weeks_index,
                "active_week_key": active_key,
                "nav_items": NAV_ITEMS,
                "corpus_stats": stats,
                "refreshed_at": _latest_ingest_at(session),
                "sources_meta": sources_meta,
            },
        )


# ---------- Phase 3c.3: Source drawer fragment ------------------------------
# Click a row on Hottest / Trends / Releases → HTMX fetches this and swaps the
# response into #source-drawer-body. The :target / radio-driven panel handles
# slide-in visibility from CSS alone.

_DRAWER_KIND_LABELS = {
    "game": "Game",
    "genre": "Genre",
    "platform": "Platform",
    "event": "Event",
    "cluster": "Cluster",
}


@router.get("/reports/drawer")
def reports_drawer(request: Request, kind: str = "", value: str = "", week: str = ""):
    """Return the drawer fragment for an entity (game/genre/platform/event) in a week."""
    if kind not in _DRAWER_KIND_LABELS or not value or not week:
        return templates.TemplateResponse(
            request, "_drawer.html",
            {"error": "Drawer requires kind, value, and week parameters.",
             "kind_label": "", "value": "", "week_label": "", "items": []},
        )
    try:
        week_label, _ = report_q.week_label_and_range(week)
    except (ValueError, IndexError):
        return templates.TemplateResponse(
            request, "_drawer.html",
            {"error": f"Unknown week id: {week!r}.",
             "kind_label": _DRAWER_KIND_LABELS[kind], "value": value, "week_label": "", "items": []},
        )

    with Session(engine) as session:
        try:
            items = report_q.items_for_entity_in_week(session, kind, value, week, limit=25)
        except ValueError as e:
            return templates.TemplateResponse(
                request, "_drawer.html",
                {"error": str(e), "kind_label": _DRAWER_KIND_LABELS[kind],
                 "value": value, "week_label": week_label, "items": []},
            )

        # For kind=cluster, swap the bare cluster_id with the human-readable
        # cluster label so the drawer header reads as a topic, not "Cluster 117".
        display_value = value
        if kind == "cluster":
            try:
                row = session.exec(_sqltext(
                    "SELECT label FROM clusters WHERE id = :cid"
                ).bindparams(cid=int(value))).first()
                if row and row[0]:
                    display_value = row[0]
            except (ValueError, TypeError):
                pass

    return templates.TemplateResponse(
        request, "_drawer.html",
        {
            "kind_label": _DRAWER_KIND_LABELS[kind],
            "value": display_value,
            "week_label": week_label,
            "items": items,
            "error": None,
        },
    )


# ---------- Phase 3c.3: Exec-summary modal fragment -------------------------
# First open per week hits Haiku 4.5; result persists to weekly_reports row
# so subsequent opens are free.

@router.get("/reports/exec-summary")
def reports_exec_summary(request: Request, week: str = ""):
    """Return the exec-summary modal fragment (1-paragraph TLDR) for a week."""
    if not week:
        return templates.TemplateResponse(
            request, "_exec_summary.html",
            {"error": "Exec summary requires a week parameter.", "week_label": "",
             "text": "", "model": "", "generated_at": None, "from_cache": False},
        )
    try:
        report_q.week_label_and_range(week)  # validates the id shape
    except (ValueError, IndexError):
        return templates.TemplateResponse(
            request, "_exec_summary.html",
            {"error": f"Unknown week id: {week!r}.", "week_label": "",
             "text": "", "model": "", "generated_at": None, "from_cache": False},
        )

    with Session(engine) as session:
        try:
            result = exec_summary_svc.get_or_generate(session, week)
        except ValueError as e:
            log.warning("exec-summary generation failed for %s: %s", week, e)
            return templates.TemplateResponse(
                request, "_exec_summary.html",
                {"error": str(e), "week_label": "", "text": "", "model": "",
                 "generated_at": None, "from_cache": False},
            )

    return templates.TemplateResponse(
        request, "_exec_summary.html",
        {
            "error": None,
            "week_label": result["week_label"],
            "text": result["text"],
            "model": result["model"],
            "generated_at": result["generated_at"],
            "from_cache": result["from_cache"],
        },
    )
