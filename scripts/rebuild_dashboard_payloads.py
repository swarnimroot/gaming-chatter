"""Phase 3c.35 — precompute & persist the /reports dashboard payload for every
synthesized week.

The /reports route used to recompute `_build_week_payload(...)` on every click
(~2.5s direct, ~5s via HTTP). Synthesized weeks are static — Opus + critic ran
once, the corpus is frozen — so we serialize the region='' payload once and
let the route apply the cheap region filter in-memory on read.

Usage:
    python scripts/rebuild_dashboard_payloads.py             # all synthesized weeks (skip already-cached)
    python scripts/rebuild_dashboard_payloads.py 2026-W21    # one week
    python scripts/rebuild_dashboard_payloads.py --force     # ignore existing cache, overwrite all

Idempotent: re-running without --force is a no-op on weeks already cached.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows cp1252 stdout safety (mirrors run_synthesis.py).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)

from sqlalchemy import text as _sqltext  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db.init import init_db  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.services import dashboard as dashboard_svc  # noqa: E402
from app.services import reports as report_q  # noqa: E402

log = logging.getLogger("rebuild_dashboard_payloads")

# Idempotent migrations up-front — standalone script must not depend on the
# FastAPI lifespan hook.
init_db()


def _list_synthesized_weeks(session: Session) -> list[tuple[str, bool]]:
    """Return [(week_id, has_payload), ...] for every synthesized week in
    descending order (newest first)."""
    rows = session.exec(_sqltext("""
        SELECT week_start, dashboard_payload_json
        FROM weekly_reports
        WHERE status = 'synthesized'
        ORDER BY week_start DESC
    """)).all()
    out: list[tuple[str, bool]] = []
    for week_start, payload in rows:
        # week_start is stored as datetime/iso-string in sqlite.
        if hasattr(week_start, "isocalendar"):
            iso = week_start.isocalendar()
            week_id = f"{iso[0]}-W{iso[1]:02d}"
        else:
            # ISO-string path — parse out year + ISO week.
            from datetime import datetime
            dt = datetime.fromisoformat(str(week_start).replace(" ", "T").split(".")[0])
            iso = dt.isocalendar()
            week_id = f"{iso[0]}-W{iso[1]:02d}"
        out.append((week_id, bool(payload)))
    return out


def _rebuild_one(session: Session, week_id: str) -> int:
    """Compute + persist + commit the dashboard payload for `week_id`.
    Returns serialized payload size in bytes."""
    payload = dashboard_svc.compute_and_cache_payload(session, week_id)
    session.commit()
    # Read back the stored length for the log line.
    week_start, _ = report_q.iso_week_bounds(week_id)
    row = session.exec(_sqltext(
        "SELECT length(dashboard_payload_json) FROM weekly_reports WHERE week_start = :s"
    ).bindparams(s=week_start)).first()
    return int(row[0]) if row and row[0] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "week_id", nargs="?", default=None,
        help="Optional ISO week id (e.g. 2026-W21). Defaults to all synthesized weeks.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Recompute and overwrite even if dashboard_payload_json is already populated.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        all_weeks = _list_synthesized_weeks(session)
        if not all_weeks:
            log.warning("no synthesized weeks found in weekly_reports — nothing to do")
            return 0

        if args.week_id:
            target = [(w, has) for (w, has) in all_weeks if w == args.week_id]
            if not target:
                log.error(
                    "%s is not a synthesized week (synthesized weeks: %s)",
                    args.week_id, ", ".join(w for w, _ in all_weeks),
                )
                return 2
            todo = target
        else:
            todo = all_weeks

        log.info(
            "=== rebuild_dashboard_payloads start (force=%s, targets=%d) ===",
            args.force, len(todo),
        )

        built = 0
        skipped = 0
        failed = 0
        for week_id, has_payload in todo:
            if has_payload and not args.force:
                log.info("[skip] %s — payload already cached (use --force to overwrite)", week_id)
                skipped += 1
                continue
            t0 = time.time()
            try:
                size = _rebuild_one(session, week_id)
                built += 1
                log.info(
                    "[ok]   %s — %d bytes in %.2fs",
                    week_id, size, time.time() - t0,
                )
            except Exception as e:  # noqa: BLE001 — surface but keep going
                failed += 1
                log.error("[fail] %s — %s", week_id, e)
                session.rollback()

        log.info(
            "=== rebuild_dashboard_payloads done: built=%d skipped=%d failed=%d ===",
            built, skipped, failed,
        )
        return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
