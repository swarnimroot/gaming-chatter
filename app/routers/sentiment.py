"""GET /sentiment — per-category aggregate sentiment view (Phase 3c.21).

Surfaces `AVG(Enrichment.sentiment_score)` grouped by `Enrichment.category`
across items in a chosen window. Default window is the last 30 days. Reuses
the `parse_date_range` helper + flatpickr date-range picker pattern from
`/stories` and `/clusters` (Phase 3c.17).

Sort: net average sentiment DESC by default (most positive category at top,
most negative at bottom). Categories with NULL/missing values are dropped.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import TEMPLATES_DIR
from app.db.models import Enrichment, Item
from app.db.session import get_session
from app.services.chrome import nav_items_for
from app.services.reports import parse_date_range

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_DEFAULT_WINDOW_DAYS = 30


def _tone_for_score(score: float) -> str:
    """Map a [-1, +1] sentiment score to a tone label used by CSS.

    Thresholds mirror the small-but-non-zero band used elsewhere in the
    codebase (e.g. trend deltas): values within ±0.05 read as neutral so
    we don't over-color a category that's basically flat.
    """
    if score >= 0.05:
        return "positive"
    if score <= -0.05:
        return "negative"
    return "neutral"


def _aggregate_sentiment(session: Session, start: datetime, end: datetime) -> list[dict]:
    """Return list of {category, avg_score, item_count, tone, bar_pct}.

    SQL: AVG(sentiment_score), COUNT(*) GROUP BY category — joined to items
    so the date filter applies. Categories with NULL category or NULL avg
    (no scored items) are dropped. Sorted by avg DESC.
    """
    stmt = (
        select(
            Enrichment.category,
            func.avg(Enrichment.sentiment_score).label("avg_score"),
            func.count(Enrichment.id).label("item_count"),
        )
        .join(Item, Item.id == Enrichment.item_id)
        .where(
            Item.published_at >= start,
            Item.published_at < end,
            Enrichment.category.is_not(None),
            Enrichment.sentiment_score.is_not(None),
        )
        .group_by(Enrichment.category)
        .order_by(func.avg(Enrichment.sentiment_score).desc())
    )
    rows = session.exec(stmt).all()

    out: list[dict] = []
    for category, avg_score, item_count in rows:
        if avg_score is None:
            continue
        score = float(avg_score)
        # bar_pct: map [-1, +1] → [0, 100] for a centered horizontal bar.
        # Anchor at 50 (neutral); extend left for negative, right for positive.
        bar_pct = max(0.0, min(100.0, (score + 1.0) * 50.0))
        out.append({
            "category": category,
            "avg_score": score,
            "item_count": int(item_count),
            "tone": _tone_for_score(score),
            "bar_pct": bar_pct,
        })
    return out


def _preset_links(now: datetime | None = None) -> list[dict]:
    """Date-range presets — same shape as dashboard/clusters routers."""
    now = now or datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%d"
    this_monday = today - timedelta(days=today.isoweekday() - 1)
    return [
        {"label": "Last 7d",
         "from": (today - timedelta(days=6)).strftime(fmt),
         "to":   today.strftime(fmt)},
        {"label": "Last 30d",
         "from": (today - timedelta(days=29)).strftime(fmt),
         "to":   today.strftime(fmt)},
        {"label": "This week",
         "from": this_monday.strftime(fmt),
         "to":   today.strftime(fmt)},
        {"label": "All time",
         "from": "2020-01-01",
         "to":   today.strftime(fmt)},
    ]


@router.get("/sentiment", name="sentiment_view")
def sentiment_view(
    request: Request,
    from_: str = Query("", alias="from"),
    to: str = "",
    week_id: str = "",  # back-compat shim — parse_date_range accepts it
    session: Session = Depends(get_session),
):
    """Per-category aggregate sentiment view."""
    date_range = parse_date_range(from_, to, week_id, _DEFAULT_WINDOW_DAYS)
    rows = _aggregate_sentiment(session, date_range["start"], date_range["end"])

    total_items = sum(r["item_count"] for r in rows)
    overall_avg = (
        sum(r["avg_score"] * r["item_count"] for r in rows) / total_items
        if total_items > 0 else None
    )

    ctx = {
        "nav_items": nav_items_for(request, "sentiment"),
        "rows": rows,
        "total_items": total_items,
        "category_count": len(rows),
        "overall_avg": overall_avg,
        "date_range": date_range,
        "presets": _preset_links(),
    }
    return templates.TemplateResponse(request, "sentiment.html", ctx)
