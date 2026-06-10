"""Backfill region_focus on existing enriched items.

For each enrichment row with status='ok' and region_focus IS NULL, calls
Anthropic Haiku 4.5 with the existing tldr text to extract region tags
(subset of {americas, europe, asia} or empty). Truly idempotent — an evaluated
no-region row is stored as "" (NOT NULL), so re-runs skip BOTH tagged rows and
already-evaluated no-region rows. Phase 3c.15; "" sentinel added 2026-06-10.

Usage:
    python scripts/backfill_region.py --limit 10     # smoke-test batch
    python scripts/backfill_region.py                # full backfill
    python scripts/backfill_region.py --ids 1,2,3    # targeted item_ids
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)

from sqlmodel import Session, col, select  # noqa: E402

from app.db.models import Enrichment  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.services.anthropic import tag_region  # noqa: E402

log = logging.getLogger("backfill_region")


def _pending_rows(limit: int | None, ids: list[int] | None) -> list[tuple[int, str]]:
    """Return [(enrichment_id, tldr)] for rows needing region backfill."""
    with Session(engine) as session:
        stmt = select(Enrichment).where(
            Enrichment.status == "ok",
            col(Enrichment.region_focus).is_(None),
            col(Enrichment.tldr).is_not(None),
        )
        if ids:
            stmt = stmt.where(col(Enrichment.item_id).in_(ids))
        stmt = stmt.order_by(Enrichment.created_at.desc())
        rows = session.exec(stmt).all()
        if limit:
            rows = rows[:limit]
        return [(r.id, r.tldr or "") for r in rows]


def _summarize_distribution() -> dict[str, int]:
    """Count items per region tag across all status='ok' enrichments."""
    counts: dict[str, int] = {"americas": 0, "europe": 0, "asia": 0, "untagged": 0, "total": 0}
    with Session(engine) as session:
        rows = session.exec(
            select(Enrichment.region_focus).where(Enrichment.status == "ok")
        ).all()
        for r in rows:
            counts["total"] += 1
            if not r:
                counts["untagged"] += 1
                continue
            tags = {t.strip().lower() for t in r.split(",") if t.strip()}
            for region in ("americas", "europe", "asia"):
                if region in tags:
                    counts[region] += 1
    return counts


def run(limit: int | None = None, ids: list[int] | None = None) -> dict:
    """Importable orchestrator entry. Phase 4 jobs.py calls this.

    Mirrors the legacy CLI body — only the argparse + return-code shell
    moved out into `main()`. Returns the totals dict for callers that
    want to record per-step counts in JobRun.details_json.
    """
    t0 = time.time()
    log.info("=== backfill_region start (limit=%s) ===", limit)

    pending = _pending_rows(limit, ids)
    log.info("pending region-backfill rows: %d", len(pending))
    if not pending:
        log.info("nothing to do.")
        return {"attempted": 0, "ok": 0, "failed": 0, "tagged": 0, "untagged": 0, "pending": 0}

    totals = {"attempted": 0, "ok": 0, "failed": 0, "tagged": 0, "untagged": 0, "pending": len(pending)}

    try:
        from tqdm import tqdm
        iterator = tqdm(pending, desc="backfill_region", unit="row")
    except ImportError:
        iterator = pending

    for enrichment_id, tldr in iterator:
        totals["attempted"] += 1
        if not tldr.strip():
            totals["failed"] += 1
            log.warning("enrichment=%s has empty tldr; skipping", enrichment_id)
            continue
        try:
            tags = tag_region(tldr)
        except Exception as e:  # noqa: BLE001
            totals["failed"] += 1
            log.warning("tag_region failed for enrichment=%s: %s", enrichment_id, e)
            continue

        # "" = "evaluated, no region" (vs NULL = "not yet evaluated"). Storing the
        # empty-string sentinel is what makes re-runs idempotent: _pending_rows
        # selects region_focus IS NULL, so an evaluated no-region row is never
        # re-billed. All consumers treat "" the same as NULL (no region):
        # dashboard ilike won't match, sections skips falsy values. See
        # DECISIONS 2026-06-10.
        value = ",".join(tags) if tags else ""
        with Session(engine) as session:
            enr = session.get(Enrichment, enrichment_id)
            if enr is None:
                totals["failed"] += 1
                log.warning("enrichment=%s vanished mid-run; skipping", enrichment_id)
                continue
            enr.region_focus = value
            session.add(enr)
            session.commit()
        totals["ok"] += 1
        if tags:
            totals["tagged"] += 1
        else:
            totals["untagged"] += 1

    elapsed = time.time() - t0
    log.info("totals: %s", totals)
    log.info("=== backfill_region done; elapsed %.1fs ===", elapsed)
    return totals


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="Max enrichments to process")
    ap.add_argument(
        "--ids",
        type=str,
        default=None,
        help="Comma-separated item_ids to target directly",
    )
    args = ap.parse_args()

    targeted_ids: list[int] | None = None
    if args.ids:
        targeted_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        log.info("targeted-id mode: %d ids", len(targeted_ids))

    run(limit=args.limit, ids=targeted_ids)
    _print_distribution()
    return 0


def _print_distribution() -> None:
    dist = _summarize_distribution()
    print()
    print("=" * 60)
    print(f"Region distribution across {dist['total']} ok enrichments:")
    print(f"  americas: {dist['americas']}")
    print(f"  europe:   {dist['europe']}")
    print(f"  asia:     {dist['asia']}")
    print(f"  untagged: {dist['untagged']}")
    print("=" * 60)


if __name__ == "__main__":
    raise SystemExit(main())
