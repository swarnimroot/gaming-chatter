"""GET /eval — synthesis-quality scoring form. Phase 3c.25.

Split layout: left pane reuses `_report_grid.html` to show the active week's
synthesis cards verbatim; right pane is a sticky form with F/S/B radios per
card + per-card note + free-text "Missing" textarea + live aggregate footer.

Save-on-change endpoints (HTMX `hx-post` from each input):
  POST /eval/score   — upsert (week, card, dim) → score [pass|concern|fail|na]
                       Returns the re-rendered aggregate fragment so the
                       footer tallies update without a full reload.
  POST /eval/note    — upsert (week, card) → note text. Returns 204.
  POST /eval/missing — upsert week → missing text. Returns 204.

Reuses several private helpers from `app.routers.reports`. That underscore
prefix is a Python convention, not enforcement; cross-module use is
intentional for /eval to mirror /'s context exactly. See DECISIONS
2026-05-20 (in-app eval form).
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import TEMPLATES_DIR
from app.db.models import EvalCardScore, EvalMeta, WeeklyReport
from app.db.session import engine
from app.services import eval_feedback as eval_feedback_svc
from app.routers.reports import (
    _build_sources_meta,
    _build_week_payload,
    _format_ago,
    _latest_ingest_dt,
    _latest_workflow_dt,
)
from app.services import reports as report_q
from app.services.chrome import failing_sources_count, nav_items_for

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
log = logging.getLogger(__name__)


# Card ordering on the form — matches the WeeklySynthesis Pydantic schema in
# app/services/synthesis.py. `exec_paragraph` covers the critic-revised
# `exec_summary_paragraph` field (stored in weekly_reports.exec_summary_text).
EVAL_CARDS = [
    "biggest",
    "hottest_reasons",
    "market_momentum",
    "community_sentiment",
    "risks",
    "esports",
    "drama",
    "release_notes",
    "watch",
    "exec_paragraph",
]

EVAL_SCORES = ["pass", "concern", "fail", "na"]
EVAL_DIMS = ["F", "S", "B"]

# Glyph rendered on each pip and in the aggregate row.
PIP_GLYPHS = {"pass": "✓", "concern": "~", "fail": "✗", "na": "—"}

# Phase 3c.27 — display labels matching what the user sees on the LEFT pane,
# plus the anchor id (in `_report_grid.html`) the right-side row links to so
# clicking a card name scrolls the left pane to that card. `exec_paragraph`
# lives in the exec-summary modal, not the grid, so it has no anchor.
EVAL_CARD_DISPLAY = {
    "biggest":             {"label": "Biggest stories",       "anchor": "card-biggest"},
    "hottest_reasons":     {"label": "Hottest games — reasons", "anchor": "card-hottest"},
    "market_momentum":     {"label": "Market momentum",       "anchor": "card-market-momentum"},
    "community_sentiment": {"label": "Community sentiment",   "anchor": "card-community"},
    "risks":               {"label": "Industry risks",        "anchor": "card-risks"},
    "esports":             {"label": "Esports & streaming",   "anchor": "card-esports"},
    "drama":               {"label": "Controversy tracker",   "anchor": "card-drama"},
    "release_notes":       {"label": "Release radar — notes", "anchor": "card-releases"},
    "watch":               {"label": "Watch next week",       "anchor": "card-watch"},
    "exec_paragraph":      {"label": "Exec summary paragraph", "anchor": None},
}


def _load_scores(session: Session, week_id: str) -> dict:
    """Return {card: {F, S, B, note}} for every card in EVAL_CARDS.

    Missing rows fill in with None values so the template can render unchecked
    radio groups uniformly.
    """
    rows = session.exec(
        select(EvalCardScore).where(EvalCardScore.week_id == week_id)
    ).all()
    by_card = {
        row.card: {"F": row.f_score, "S": row.s_score, "B": row.b_score, "note": row.note}
        for row in rows
    }
    return {
        c: by_card.get(c, {"F": None, "S": None, "B": None, "note": None})
        for c in EVAL_CARDS
    }


def _load_missing(session: Session, week_id: str) -> str:
    row = session.get(EvalMeta, week_id)
    return row.missing if row and row.missing else ""


def _stale_info(session: Session, week_id: str) -> dict:
    """Detect if synthesis re-ran AFTER the most recent eval score for this week.

    Both timestamps come from existing columns — no schema change. Returns
    `{stale, synth_at, scored_at}`. stale=False when either timestamp is
    missing (no synth yet, or week never scored) so the banner stays hidden.
    """
    try:
        week_start, _ = report_q.iso_week_bounds(week_id)
    except (ValueError, IndexError):
        return {"stale": False, "synth_at": None, "scored_at": None}

    synth_at = session.exec(
        select(WeeklyReport.synthesis_generated_at)
        .where(WeeklyReport.week_start == week_start)
    ).first()
    scored_at = session.exec(
        select(func.max(EvalCardScore.updated_at))
        .where(EvalCardScore.week_id == week_id)
    ).first()

    if synth_at is None or scored_at is None:
        return {"stale": False, "synth_at": synth_at, "scored_at": scored_at}
    return {"stale": synth_at > scored_at, "synth_at": synth_at, "scored_at": scored_at}


def _compute_aggregate(scores: dict) -> dict:
    """Tally pass/concern/fail/na/blank counts per dim across all cards."""
    agg = {d: {s: 0 for s in EVAL_SCORES + ["blank"]} for d in EVAL_DIMS}
    for s in scores.values():
        for dim in EVAL_DIMS:
            v = s.get(dim)
            if v in EVAL_SCORES:
                agg[dim][v] += 1
            else:
                agg[dim]["blank"] += 1
    return agg


def _aggregate_fragment(request: Request, week_id: str):
    """Render just the aggregate partial — swapped in by HTMX after each save."""
    with Session(engine) as session:
        scores = _load_scores(session, week_id)
        aggregate = _compute_aggregate(scores)
    return templates.TemplateResponse(
        request, "_eval_aggregate.html",
        {"aggregate": aggregate, "scores_order": EVAL_SCORES, "pip_glyphs": PIP_GLYPHS},
    )


@router.get("/eval", name="eval_view")
def eval_view(request: Request, week: str = ""):
    """Render the eval form for the selected week.

    Defaults to the most recently clustered week. Renders an empty shell when
    the corpus has no clustered weeks yet (matches reports.html's
    empty-corpus path).
    """
    with Session(engine) as session:
        week_ids = report_q.available_weeks(session)

        if not week_ids:
            return templates.TemplateResponse(
                request, "eval.html",
                {"week": None, "weeks_index": [], "active_week_key": "",
                 "nav_items": nav_items_for(request, "eval"),
                 "last_pull": "—", "last_workflow": "—",
                 "sources_meta": {}, "region": "", "region_active": False,
                 "scores": {}, "missing": "",
                 "aggregate": _compute_aggregate({}),
                 "cards_order": EVAL_CARDS, "scores_order": EVAL_SCORES,
                 "pip_glyphs": PIP_GLYPHS,
                 "card_display": EVAL_CARD_DISPLAY,
                 "stale_info": {"stale": False},
                 "feedback_block": "",
                 "feedback_count": 0,
                 "failing_sources_count": failing_sources_count(session)},
            )

        active_key = week if week in week_ids else week_ids[0]

        weeks_index = []
        for k in week_ids:
            label, rng = report_q.week_label_and_range(k)
            weeks_index.append({"key": k, "label": label, "range": rng, "is_active": k == active_key})

        week_data = _build_week_payload(session, active_key, region="")
        sources_meta = _build_sources_meta(session)

        scores = _load_scores(session, active_key)
        missing = _load_missing(session, active_key)
        aggregate = _compute_aggregate(scores)
        # Same feedback block synthesis.py prepends to the next critic pass —
        # surfaced here so the user sees what the loop is actively learning.
        feedback_failures = eval_feedback_svc.gather_recent_failures(session, active_key)
        feedback_block = eval_feedback_svc.format_critic_block(feedback_failures)

        return templates.TemplateResponse(
            request, "eval.html",
            {
                "week": week_data,
                "weeks_index": weeks_index,
                "active_week_key": active_key,
                "nav_items": nav_items_for(request, "eval"),
                "last_pull": _format_ago(_latest_ingest_dt(session)),
                "last_workflow": _format_ago(_latest_workflow_dt(session)),
                "sources_meta": sources_meta,
                "region": "",
                "region_active": False,
                "scores": scores,
                "missing": missing,
                "aggregate": aggregate,
                "cards_order": EVAL_CARDS,
                "scores_order": EVAL_SCORES,
                "pip_glyphs": PIP_GLYPHS,
                "card_display": EVAL_CARD_DISPLAY,
                "stale_info": _stale_info(session, active_key),
                "feedback_block": feedback_block,
                "feedback_count": len(feedback_failures),
                "failing_sources_count": failing_sources_count(session),
            },
        )


def _upsert_score(session: Session, week_id: str, card: str, dim: str, score: str) -> None:
    row = session.get(EvalCardScore, (week_id, card))
    attr = f"{dim.lower()}_score"
    now = datetime.utcnow()
    if row is None:
        row = EvalCardScore(week_id=week_id, card=card, updated_at=now)
        setattr(row, attr, score)
        session.add(row)
    else:
        setattr(row, attr, score)
        row.updated_at = now
    session.commit()


def _upsert_note(session: Session, week_id: str, card: str, note: str) -> None:
    row = session.get(EvalCardScore, (week_id, card))
    now = datetime.utcnow()
    if row is None:
        session.add(EvalCardScore(week_id=week_id, card=card, note=note or None, updated_at=now))
    else:
        row.note = note or None
        row.updated_at = now
    session.commit()


def _upsert_missing(session: Session, week_id: str, missing: str) -> None:
    row = session.get(EvalMeta, week_id)
    now = datetime.utcnow()
    if row is None:
        session.add(EvalMeta(week_id=week_id, missing=missing or None, updated_at=now))
    else:
        row.missing = missing or None
        row.updated_at = now
    session.commit()


@router.post("/eval/score", name="eval_save_score")
def eval_save_score(
    request: Request,
    week_id: str = Form(...),
    card: str = Form(...),
    dim: str = Form(...),
    score: str = Form(...),
):
    if card not in EVAL_CARDS or dim not in EVAL_DIMS or score not in EVAL_SCORES:
        raise HTTPException(status_code=400, detail="Invalid card / dim / score")
    with Session(engine) as session:
        _upsert_score(session, week_id, card, dim, score)
    return _aggregate_fragment(request, week_id)


@router.post("/eval/note", name="eval_save_note")
def eval_save_note(
    week_id: str = Form(...),
    card: str = Form(...),
    note: str = Form(""),
):
    if card not in EVAL_CARDS:
        raise HTTPException(status_code=400, detail="Invalid card")
    with Session(engine) as session:
        _upsert_note(session, week_id, card, note.strip())
    return Response(status_code=204)


@router.post("/eval/missing", name="eval_save_missing")
def eval_save_missing(
    week_id: str = Form(...),
    missing: str = Form(""),
):
    with Session(engine) as session:
        _upsert_missing(session, week_id, missing.strip())
    return Response(status_code=204)
