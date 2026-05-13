"""Dedupe case-folded duplicate rows in the games dim.

The `populate_games_dim.py` initial pass keyed games dim on the EXACT name
extracted from `entities.games`. SQLite TEXT primary keys are case-sensitive,
so "LEGO Batman" and "Lego Batman" landed as separate rows even though they
refer to the same game. Same for "Thick as Thieves" / "Thick As Thieves" etc.

This script:
  1. Finds case-fold groups in the games dim with more than one row.
  2. Picks a canonical row per group — the casing that's most mentioned in
     `enrichments.entities.games` (tiebreaker: lexicographically first).
  3. Merges metadata from the duplicates into canonical via COALESCE
     (non-null wins, canonical wins ties).
  4. DELETEs the non-canonical rows.

Idempotent: re-running on a deduped dim is a no-op.
Pair this with the case-insensitive grouping added to app/services/reports.py
so future case-variants in articles still join to the canonical dim row.

Usage:
    python scripts/dedupe_games_dim.py             # apply changes
    python scripts/dedupe_games_dim.py --dry-run   # report only
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db.models import Game  # noqa: E402
from app.db.session import engine  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("dedupe_games_dim")


def mention_count(session: Session, name: str) -> int:
    row = session.exec(text("""
        SELECT COUNT(*) FROM enrichments e, json_each(e.entities, '$.games') je
        WHERE e.status = 'ok' AND TRIM(je.value) = :name
    """).bindparams(name=name)).first()
    return row[0] if row else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with Session(engine) as session:
        all_games = session.exec(select(Game).order_by(Game.name)).all()
        groups: dict[str, list[Game]] = defaultdict(list)
        for g in all_games:
            groups[g.name.lower()].append(g)

        dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
        log.info("found %d case-fold duplicate groups (%d dim rows)",
                 len(dup_groups), sum(len(v) for v in dup_groups.values()))

        deleted = 0
        merged_fields = 0

        for lower_name, rows in dup_groups.items():
            # Choose canonical = casing with most mentions in entities.games
            scored = sorted(
                ((mention_count(session, r.name), r.name, r) for r in rows),
                key=lambda x: (-x[0], x[1]),
            )
            canonical = scored[0][2]
            losers = [r for _, _, r in scored[1:]]
            log.info(
                "  %s  canonical=%r (%d mentions) | dropping: %s",
                lower_name, canonical.name, scored[0][0],
                [(n, m) for m, n, _ in scored[1:]],
            )

            # Merge metadata (COALESCE on nulls — canonical wins ties)
            for field in ("lifecycle", "release_date", "live_service"):
                if getattr(canonical, field) is None:
                    for r in losers:
                        v = getattr(r, field)
                        if v is not None:
                            setattr(canonical, field, v)
                            log.info("    merged %s=%r from %r", field, v, r.name)
                            merged_fields += 1
                            break

            if not args.dry_run:
                session.add(canonical)
                for r in losers:
                    session.delete(r)
                session.commit()
            deleted += len(losers)

        log.info("done: %d dim rows deleted, %d fields merged (dry-run=%s)",
                 deleted, merged_fields, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
