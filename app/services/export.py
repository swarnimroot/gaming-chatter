"""Executive 1-pager export — standalone HTML with inlined CSS (Phase 3c.6).

Shared payload builder used by both the modal endpoint (live /reports view)
and the export endpoint (downloadable HTML / print-to-PDF).

The standalone HTML body uses the same `.gc-onepager-*` styles as the modal,
plus a `.gc-standalone-*` chrome wrapper and a `@media print` block. CSS is
inlined into the document so the export is self-contained — no separate
asset request, no theme drift, works as an email attachment.

Caching: rendered HTML persists to `weekly_reports.html_content` keyed by
`week_start`. Subsequent exports read from the column. `force=True` refreshes.
The cache stores the *non-auto-print* variant; the PDF route injects the
auto-print `<script>` tag after the cache read so we don't duplicate-cache.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import text as _sqltext
from sqlmodel import Session, select

from app.config import STATIC_DIR
from app.db.models import WeeklyReport
from app.services import reports as report_q

_CSS_PATH = Path(STATIC_DIR) / "app.css"
_cached_css: Optional[str] = None


def inline_css(refresh: bool = False) -> str:
    """Return the app.css contents, cached at module level.

    `refresh=True` re-reads from disk — used by --reload dev workflows that
    want the standalone export to pick up live CSS edits without restarting.
    """
    global _cached_css
    if _cached_css is None or refresh:
        _cached_css = _CSS_PATH.read_text(encoding="utf-8")
    return _cached_css


def split_into_paragraphs(text: str, group: int = 2) -> list[str]:
    """Group sentence-split text into N-sentence visual paragraphs.

    Phase 3c.6 revision: the Haiku exec paragraph is 4-5 sentences and reads
    as a wall of text in the 1-pager. Splitting every 2 sentences into a
    separate <p> gives natural breathing room without changing the content.
    """
    if not text:
        return []
    sentences = [s.strip() for s in text.split(". ") if s.strip()]
    if not sentences:
        return [text]
    fixed = [s if s.endswith(".") else s + "." for s in sentences[:-1]]
    fixed.append(sentences[-1])
    return [" ".join(fixed[i:i + group]) for i in range(0, len(fixed), group)]


def build_payload(
    session: Session,
    week_id: str,
    exec_text: str,
    exec_model: str,
    exec_generated_at: Optional[datetime],
    exec_from_cache: bool,
) -> Optional[dict]:
    """Build the 1-pager render context from synthesis_json + exec summary.

    Returns None if synthesis hasn't run for this week (caller should
    short-circuit: export endpoint returns 409, modal renders a degraded body).
    """
    label, rng = report_q.week_label_and_range(week_id)
    stats = report_q.week_stats(session, week_id)

    # Stat tiles — items / sources / top game / top genre.
    top_games = report_q.top_games_for_week(session, week_id, limit=1)
    top_genres = report_q.top_genres_for_week(session, week_id, limit=1)
    top_game = (
        {"name": top_games[0]["name"], "count": top_games[0]["count"]}
        if top_games else {"name": "—", "count": 0}
    )
    top_genre = (
        {"name": top_genres[0][0], "count": top_genres[0][1]}
        if top_genres else {"name": "—", "count": 0}
    )

    week_start, _ = report_q.iso_week_bounds(week_id)
    row = session.exec(_sqltext(
        "SELECT synthesis_json, synthesis_model, synthesis_generated_at "
        "FROM weekly_reports WHERE week_start = :s"
    ).bindparams(s=week_start)).first()

    if not row or not row[0]:
        return None
    try:
        data = json.loads(row[0])
    except (TypeError, ValueError):
        return None

    biggest: list[dict] = []
    if data.get("biggest"):
        cluster_ids = [int(b["cluster_id"]) for b in data["biggest"][:3]]
        pills = report_q.source_pills_for_clusters(session, cluster_ids)
        biggest = [
            {
                "title": b["title"],
                "dek": b["dek"],
                "sources": pills.get(int(b["cluster_id"]), [])[:3],
            }
            for b in data["biggest"][:3]
        ]

    market = [
        {"title": m["title"], "note": m["note"], "category": m["category"]}
        for m in (data.get("market_momentum") or [])[:3]
    ]
    risks = [
        {"title": r["title"], "note": r["note"], "level": r["severity"]}
        for r in (data.get("risks") or [])[:2]
    ]
    cs = data.get("community_sentiment") or {}
    heated = [
        {"title": c["title"], "note": c["note"]}
        for c in (cs.get("heated_about") or [])[:1]
    ]
    celebrating = [
        {"title": c["title"], "note": c["note"]}
        for c in (cs.get("celebrating") or [])[:1]
    ]

    synthesis_generated_at = row[2]
    synthesis_model = row[1]

    # Display string for the standalone footer.
    if synthesis_generated_at:
        try:
            sg = synthesis_generated_at if isinstance(synthesis_generated_at, datetime) else datetime.fromisoformat(str(synthesis_generated_at))
            generated_display = sg.strftime("%b %d, %Y %H:%M UTC")
        except Exception:  # noqa: BLE001
            generated_display = str(synthesis_generated_at)
    else:
        generated_display = "—"

    return {
        "week_label": label,
        "week_range": rng,
        "week_id": week_id,
        "stats": {"stories": stats["stories"], "sources": stats["sources"]},
        "top_game": top_game,
        "top_genre": top_genre,
        "exec_text": exec_text,
        "exec_paragraphs": split_into_paragraphs(exec_text, group=2),
        "exec_model": exec_model,
        "exec_generated_at": exec_generated_at,
        "exec_from_cache": exec_from_cache,
        "synthesis_ran": True,
        "synthesis_model": synthesis_model,
        "generated_at_display": generated_display,
        "biggest": biggest,
        "market_momentum": market,
        "risks": risks,
        "heated_about": heated,
        "celebrating": celebrating,
    }


def load_cached_html(session: Session, week_id: str) -> Optional[str]:
    """Return cached html_content for the week, or None."""
    week_start, _ = report_q.iso_week_bounds(week_id)
    row = session.exec(
        select(WeeklyReport).where(WeeklyReport.week_start == week_start)
    ).first()
    if row and row.html_content:
        return row.html_content
    return None


def save_cached_html(session: Session, week_id: str, html_text: str) -> None:
    """Persist the rendered standalone HTML to weekly_reports.html_content.

    Caller is responsible for committing; we assume the same session also
    populated exec_summary fields and just append to that row.
    """
    week_start, week_end = report_q.iso_week_bounds(week_id)
    row = session.exec(
        select(WeeklyReport).where(WeeklyReport.week_start == week_start)
    ).first()
    if row is None:
        row = WeeklyReport(
            week_start=week_start, week_end=week_end,
            html_content=html_text, status="exported",
        )
        session.add(row)
    else:
        row.html_content = html_text
        session.add(row)
    session.commit()


def inject_auto_print(html_text: str) -> str:
    """Append an auto-fire window.print() script to a cached HTML doc.

    Used by the PDF export path to flip cached standalone HTML into a
    print-on-load document without re-rendering the whole template.
    """
    script = (
        '<script>window.addEventListener("load",function(){'
        'setTimeout(function(){window.print();},100);});</script>'
    )
    if "</body>" in html_text:
        return html_text.replace("</body>", script + "</body>", 1)
    return html_text + script
