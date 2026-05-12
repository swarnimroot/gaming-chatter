"""Standalone runner for clustering. Runs cluster_window over all ok-enrichments
and persists rows under week_id (default: 'all').

Usage:
    python scripts/run_cluster.py            # week_id='all' (legacy default)
    python scripts/run_cluster.py 2026-W18   # explicit week_id
    python scripts/run_cluster.py --per-week # enumerate ISO weeks in corpus,
                                             # call cluster_window once per week.
                                             # Existing week_id='all' rows are
                                             # NOT deleted; they coexist.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)

from sqlmodel import Session, col, select  # noqa: E402

from app.db.models import Item  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.services.cluster import cluster_window  # noqa: E402

log = logging.getLogger("cluster_runner")


def iso_week_id(d: datetime) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def iso_week_range(year: int, week: int) -> tuple[datetime, datetime]:
    # Monday 00:00 of the ISO week through the following Monday 00:00.
    start = datetime.fromisocalendar(year, week, 1)
    end = start + timedelta(days=7)
    return start, end


def _collect_iso_weeks() -> list[tuple[int, int]]:
    """Return sorted unique (iso_year, iso_week) tuples present in items.published_at."""
    seen: set[tuple[int, int]] = set()
    with Session(engine) as session:
        rows = session.exec(
            select(Item.published_at).where(col(Item.published_at).is_not(None))
        ).all()
    for dt in rows:
        if dt is None:
            continue
        iso = dt.isocalendar()
        seen.add((iso.year, iso.week))
    return sorted(seen)


def _run_per_week() -> int:
    weeks = _collect_iso_weeks()
    log.info("=== per-week clustering: %d ISO weeks found ===", len(weeks))
    cumulative = {"items": 0, "groups": 0, "labelled": 0, "label_failed": 0}
    t0 = time.time()
    for year, week in weeks:
        week_id = f"{year}-W{week:02d}"
        start, end = iso_week_range(year, week)
        log.info("--- cluster_window week_id=%s (%s .. %s) ---", week_id, start, end)
        totals = cluster_window(start=start, end=end, week_id=week_id)
        for k, v in totals.items():
            cumulative[k] = cumulative.get(k, 0) + v
        log.info("week_id=%s totals: %s", week_id, totals)
    log.info("per-week clustering done in %.1fs; cumulative: %s",
             time.time() - t0, cumulative)
    return 0


def _run_single(week_id: str) -> int:
    t0 = time.time()
    log.info("=== cluster_window start (week_id=%s) ===", week_id)
    totals = cluster_window(week_id=week_id)
    log.info("cluster_window done in %.1fs: %s", time.time() - t0, totals)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "week_id", nargs="?", default=None,
        help="Explicit week_id for a single-call run (default: 'all' when omitted).",
    )
    parser.add_argument(
        "--per-week", action="store_true",
        help="Enumerate ISO weeks in the corpus and run cluster_window per week.",
    )
    args = parser.parse_args()

    if args.per_week:
        if args.week_id is not None:
            parser.error("--per-week cannot be combined with a positional week_id")
        return _run_per_week()

    # Backward compat: no args -> legacy 'all'; positional arg -> that week_id.
    week_id = args.week_id if args.week_id is not None else "all"
    return _run_single(week_id)


if __name__ == "__main__":
    raise SystemExit(main())
