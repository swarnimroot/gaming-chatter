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
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import text as _sqltext
from sqlmodel import Session

from fastapi.responses import Response

from app.config import TEMPLATES_DIR
from app.db.session import engine
from app.services import exec_summary as exec_summary_svc
from app.services import export as export_svc
from app.services import reports as report_q
from app.services.chrome import failing_sources_count, nav_items_for

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
log = logging.getLogger(__name__)

# Phase 3c.16 — region filter (mirrors clusters.py / dashboard.py constants).
_REGION_ALLOWED = {"americas", "europe", "asia"}


# ---------- Static chrome (sidebar nav) -------------------------------------
# Phase 3c.7: nav moved into `app/services/chrome.py` so Dashboard / Clusters /
# Sources can share it. `nav_items_for("weekly")` keeps this route's is_active.


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


def _parse_dt(val) -> datetime | None:
    """Coerce a datetime or ISO-string from sqlite into an aware UTC datetime."""
    if not val:
        return None
    try:
        dt = val if isinstance(val, datetime) else datetime.fromisoformat(str(val))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_ago(dt: datetime | None) -> str:
    """Format a UTC datetime as 'N min/h/d ago' for header chrome."""
    if dt is None:
        return "—"
    delta = datetime.now(timezone.utc) - dt
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return f"{mins} min ago"
    hrs = mins // 60
    if hrs < 48:
        return f"{hrs} h ago"
    return f"{hrs // 24} d ago"


def _latest_ingest_dt(session: Session) -> datetime | None:
    """Last successful ingest completion across all sources, or None."""
    row = session.exec(_sqltext(
        "SELECT MAX(completed_at) FROM run_log WHERE job_type='ingest' AND status='ok'"
    )).first()
    return _parse_dt(row[0] if row else None)


def _latest_workflow_dt(session: Session) -> datetime | None:
    """Last successful synthesis run = the user-visible 'workflow completion'."""
    row = session.exec(_sqltext(
        "SELECT MAX(synthesis_generated_at) FROM weekly_reports"
    )).first()
    return _parse_dt(row[0] if row else None)


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

    # Biggest stories — plural top-3, each with source pills + mention count
    # derived from cluster members so the template doesn't need a second query.
    if data.get("biggest"):
        cluster_ids = [int(b["cluster_id"]) for b in data["biggest"]]
        pills = report_q.source_pills_for_clusters(session, cluster_ids)
        ids_csv = ",".join(str(cid) for cid in cluster_ids)
        member_rows = session.exec(_sqltext(
            f"SELECT id, member_item_ids FROM clusters WHERE id IN ({ids_csv})"
        )).all()
        counts: dict[int, int] = {}
        for cid, mids_json in member_rows:
            try:
                counts[int(cid)] = len(json.loads(mids_json)) if mids_json else 0
            except (TypeError, ValueError):
                counts[int(cid)] = 0
        cards["biggest"] = [
            {
                "cluster_id": b["cluster_id"],
                "title": b["title"],
                "dek": b["dek"],
                "sources": pills.get(int(b["cluster_id"]), []),
                "mention_count": counts.get(int(b["cluster_id"]), 0),
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
            "category": w.get("category"),
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


def _filter_cards_by_region(session: Session, cards: dict, region: str) -> None:
    """Drop entries from every cluster-keyed card list whose cluster doesn't
    carry the requested region tag. Phase 3c.16.

    Collects every cluster_id referenced by synthesis_json in one pass, calls
    `cluster_regions()` once, then walks each card list in place. Cards
    without cluster_id linkage (hottest / releases / trends) are untouched —
    the template signals 'Not region-tagged' via the `region_active` flag.

    Special-cased entries:
      - community.narrative: whole-corpus prose; cleared on regional tabs.
      - watch[] without `cluster_id`: corpus-wide editorial; dropped.
    """
    from app.services.sections import cluster_regions

    cluster_ids: set[int] = set()
    for b in cards.get("biggest", []) or []:
        try:
            cluster_ids.add(int(b["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for m in cards.get("market_momentum", []) or []:
        try:
            cluster_ids.add(int(m["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for r in cards.get("risks", []) or []:
        try:
            cluster_ids.add(int(r["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for d in cards.get("drama", []) or []:
        try:
            cluster_ids.add(int(d["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for e in cards.get("esports", []) or []:
        try:
            cluster_ids.add(int(e["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    co = cards.get("community") or {}
    for c in co.get("heated_about", []) or []:
        try:
            cluster_ids.add(int(c["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for c in co.get("celebrating", []) or []:
        try:
            cluster_ids.add(int(c["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for w in cards.get("watch", []) or []:
        if w.get("cluster_id") is not None:
            try:
                cluster_ids.add(int(w["cluster_id"]))
            except (TypeError, ValueError):
                pass

    region_map = cluster_regions(session, list(cluster_ids)) if cluster_ids else {}

    def keep(cid) -> bool:
        try:
            return region in region_map.get(int(cid), set())
        except (TypeError, ValueError):
            return False

    cards["biggest"] = [b for b in cards.get("biggest", []) if keep(b.get("cluster_id"))]
    cards["market_momentum"] = [m for m in cards.get("market_momentum", []) if keep(m.get("cluster_id"))]
    cards["risks"] = [r for r in cards.get("risks", []) if keep(r.get("cluster_id"))]
    cards["drama"] = [d for d in cards.get("drama", []) if keep(d.get("cluster_id"))]
    cards["esports"] = [e for e in cards.get("esports", []) if keep(e.get("cluster_id"))]

    cards["community"] = {
        "narrative": None,  # whole-corpus prose — drop on regional tabs
        "heated_about": [c for c in co.get("heated_about", []) if keep(c.get("cluster_id"))],
        "celebrating": [c for c in co.get("celebrating", []) if keep(c.get("cluster_id"))],
    }

    # watch[] — drop entries without cluster_id (corpus-wide narrative),
    # filter the rest by region.
    cards["watch"] = [
        w for w in cards.get("watch", [])
        if w.get("cluster_id") is not None and keep(w.get("cluster_id"))
    ]


def _build_week_payload(session: Session, week_id: str, region: str = "") -> dict:
    """Assemble the full per-week card payload.

    Phase 3c.16: when `region` is one of {'americas','europe','asia'}, every
    cluster-keyed card list is filtered against `cluster_regions(...)` for the
    cluster_ids referenced by synthesis_json. Non-cluster cards (Hottest /
    Releases / Trends) are passed through unchanged — the template shows a
    'Not region-tagged' chip in their headers when `region_active` is true.
    """
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
        if region in _REGION_ALLOWED:
            _filter_cards_by_region(session, cards, region)

    return {
        "label": label,
        "range": rng,
        "stats": {"stories": stats["stories"], "sources": stats["sources"]},
        "cards": cards,
    }


# ---------- Route -----------------------------------------------------------

@router.get("/")
def reports_view(request: Request, week: str = "", region: str = ""):
    region_norm = region if region in _REGION_ALLOWED else ""
    region_active = bool(region_norm)
    with Session(engine) as session:
        week_ids = report_q.available_weeks(session)

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
                 "nav_items": nav_items_for(request, "weekly"),
                 "last_pull": "—", "last_workflow": "—",
                 "can_run_pipeline": True,
                 "sources_meta": {},
                 "region": region_norm, "region_active": region_active,
                 "exec_summary_hidden_for_region": region_active,
                 "failing_sources_count": failing_sources_count(session)},
            )

        active_key = week if week in week_ids else week_ids[0]

        weeks_index = []
        for k in week_ids:
            label, rng = report_q.week_label_and_range(k)
            weeks_index.append({"key": k, "label": label, "range": rng, "is_active": k == active_key})

        week_data = _build_week_payload(session, active_key, region=region_norm)
        sources_meta = _build_sources_meta(session)

        last_pull_dt = _latest_ingest_dt(session)
        last_workflow_dt = _latest_workflow_dt(session)
        # Pipeline button is enabled when last pull is missing OR > 6 days old.
        if last_pull_dt is None:
            can_run_pipeline = True
        else:
            can_run_pipeline = (datetime.now(timezone.utc) - last_pull_dt) > timedelta(days=6)

        return templates.TemplateResponse(
            request, "reports.html",
            {
                "week": week_data,
                "weeks_index": weeks_index,
                "active_week_key": active_key,
                "nav_items": nav_items_for(request, "weekly"),
                "last_pull": _format_ago(last_pull_dt),
                "last_workflow": _format_ago(last_workflow_dt),
                "can_run_pipeline": can_run_pipeline,
                "sources_meta": sources_meta,
                "region": region_norm,
                "region_active": region_active,
                "exec_summary_hidden_for_region": region_active,
                "failing_sources_count": failing_sources_count(session),
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

def _one_pager_context(session: Session, week_id: str, exec_result: dict) -> dict:
    """Build the 1-pager modal context. Phase 3c.6.

    Delegates to `export_svc.build_payload()`; when synthesis is absent,
    falls back to a Haiku-only context so the modal still renders.
    """
    payload = export_svc.build_payload(
        session, week_id,
        exec_text=exec_result["text"],
        exec_model=exec_result["model"],
        exec_generated_at=exec_result["generated_at"],
        exec_from_cache=exec_result["from_cache"],
    )
    if payload is not None:
        return payload

    label, rng = report_q.week_label_and_range(week_id)
    stats = report_q.week_stats(session, week_id)
    top_games = report_q.top_games_for_week(session, week_id, limit=1)
    top_genres = report_q.top_genres_for_week(session, week_id, limit=1)
    return {
        "week_label": label,
        "week_range": rng,
        "week_id": week_id,
        "stats": {"stories": stats["stories"], "sources": stats["sources"]},
        "top_game": ({"name": top_games[0]["name"], "count": top_games[0]["count"]}
                     if top_games else {"name": "—", "count": 0}),
        "top_genre": ({"name": top_genres[0][0], "count": top_genres[0][1]}
                      if top_genres else {"name": "—", "count": 0}),
        "exec_text": exec_result["text"],
        "exec_paragraphs": export_svc.split_into_paragraphs(exec_result["text"], group=2),
        "exec_model": exec_result["model"],
        "exec_generated_at": exec_result["generated_at"],
        "exec_from_cache": exec_result["from_cache"],
        "synthesis_ran": False,
        "synthesis_model": None,
        "generated_at_display": "—",
        "biggest": [], "market_momentum": [], "risks": [],
        "heated_about": [], "celebrating": [],
    }


def _exec_error_ctx(message: str) -> dict:
    return {
        "error": message, "week_label": "", "week_range": "", "week_id": "",
        "stats": {"stories": 0, "sources": 0},
        "top_game": {"name": "—", "count": 0}, "top_genre": {"name": "—", "count": 0},
        "exec_text": "", "exec_paragraphs": [],
        "exec_model": "", "exec_generated_at": None, "exec_from_cache": False,
        "synthesis_ran": False, "synthesis_model": None, "generated_at_display": "—",
        "biggest": [], "market_momentum": [], "risks": [],
        "heated_about": [], "celebrating": [],
    }


@router.get("/reports/exec-summary")
def reports_exec_summary(request: Request, week: str = ""):
    """Return the 1-pager modal fragment for a week (Phase 3c.6).

    Composition: existing Haiku paragraph (lead) + structured bullets from
    synthesis_json (Biggest top-3, Market Momentum top-3, two-col Risks /
    Community). Footer carries Export HTML / Export PDF actions.
    """
    if not week:
        return templates.TemplateResponse(
            request, "_exec_summary.html",
            _exec_error_ctx("Exec summary requires a week parameter."),
        )
    try:
        report_q.week_label_and_range(week)
    except (ValueError, IndexError):
        return templates.TemplateResponse(
            request, "_exec_summary.html",
            _exec_error_ctx(f"Unknown week id: {week!r}."),
        )

    with Session(engine) as session:
        try:
            result = exec_summary_svc.get_or_generate(session, week)
        except ValueError as e:
            log.warning("exec-summary generation failed for %s: %s", week, e)
            return templates.TemplateResponse(
                request, "_exec_summary.html", _exec_error_ctx(str(e)),
            )
        ctx = _one_pager_context(session, week, result)

    ctx["error"] = None
    return templates.TemplateResponse(request, "_exec_summary.html", ctx)


# ---------- Phase 3c.6: Standalone-HTML / PDF export ------------------------
# GET /reports/export?week=2026-W19&format=html|pdf[&force=1]
#   - html: served as attachment (Content-Disposition) — downloads to disk.
#   - pdf:  served inline with an auto-fire window.print() injection so the
#           browser print dialog appears immediately. User picks "Save as PDF".
# Rendered HTML is cached on weekly_reports.html_content (cache pattern mirrors
# exec_summary). PDF path injects auto-print after cache read; we never cache
# the auto-print variant so a future "preview standalone" reuse stays clean.

_EXPORT_FORMATS = {"html", "pdf"}


@router.get("/reports/export")
def reports_export(
    request: Request,
    week: str = "",
    format: str = "html",
    force: int = 0,
):
    """Export the executive 1-pager as standalone HTML or print-to-PDF."""
    fmt = format.lower()
    if fmt not in _EXPORT_FORMATS:
        return Response(
            content=f"Unsupported format: {format!r}. Use html or pdf.",
            status_code=400, media_type="text/plain",
        )
    if not week:
        return Response(
            content="Export requires a week parameter.",
            status_code=400, media_type="text/plain",
        )
    try:
        report_q.week_label_and_range(week)
    except (ValueError, IndexError):
        return Response(
            content=f"Unknown week id: {week!r}.",
            status_code=400, media_type="text/plain",
        )

    with Session(engine) as session:
        # Cache hit short-circuits the full render path when no refresh is asked.
        cached_html = None if force else export_svc.load_cached_html(session, week)
        if cached_html:
            html_text = cached_html
        else:
            # Render fresh. Reuses the Haiku exec paragraph (may hit Anthropic
            # if missing). Synthesis must already exist — we don't auto-run it.
            try:
                exec_result = exec_summary_svc.get_or_generate(session, week)
            except ValueError as e:
                return Response(
                    content=f"Exec summary unavailable: {e}",
                    status_code=502, media_type="text/plain",
                )
            payload = export_svc.build_payload(
                session, week,
                exec_text=exec_result["text"],
                exec_model=exec_result["model"],
                exec_generated_at=exec_result["generated_at"],
                exec_from_cache=exec_result["from_cache"],
            )
            if payload is None:
                return Response(
                    content=(
                        f"Synthesis hasn't run for {week}.\n"
                        f"Run: scripts/run_synthesis.py {week}\n"
                    ),
                    status_code=409, media_type="text/plain",
                )

            # Render the standalone doc with inlined CSS (no auto-print —
            # the cached variant stays usable for both export paths).
            payload["inline_css"] = export_svc.inline_css()
            payload["auto_print"] = False
            html_text = templates.get_template(
                "_report_standalone.html"
            ).render(payload)
            export_svc.save_cached_html(session, week, html_text)

    if fmt == "pdf":
        # Inject the auto-print script after cache read so the cache stays
        # canonical (one stored doc, two render modes).
        body = export_svc.inject_auto_print(html_text)
        return Response(content=body, media_type="text/html; charset=utf-8")

    # HTML: attachment download.
    filename = f"gaming-chatter-{week}.html"
    return Response(
        content=html_text,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
