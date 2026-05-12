"""Populate the `games` dim table by tagging each game mention via Ollama.

Run AFTER the Phase 3c.0 re-enrichment completes. Reads entities.games from
ok enrichments, dedupes (TRIM), filters by minimum mention count, and tags
each unique game with lifecycle + live_service via ollama.tag_game().

Per-game commit makes this resumable on Ctrl-C.

Usage:
    python scripts/populate_games_dim.py                    # full run, tqdm
    python scripts/populate_games_dim.py --sample --limit 20
    python scripts/populate_games_dim.py --min-mentions 3
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlmodel import Session, select  # noqa: E402
from tqdm import tqdm  # noqa: E402

from app.db.models import Game  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.services.ollama import tag_game  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("populate_games_dim")


UNIQUE_GAMES_SQL = """
SELECT TRIM(value) AS name, COUNT(*) AS n
FROM enrichments, json_each(enrichments.entities, '$.games')
WHERE enrichments.status = 'ok'
GROUP BY TRIM(value)
HAVING n >= :min_mentions
ORDER BY n DESC
"""


def load_candidates(session: Session, min_mentions: int) -> list[tuple[str, int]]:
    rows = session.exec(
        text(UNIQUE_GAMES_SQL).bindparams(min_mentions=min_mentions)
    ).all()
    # Each row is (name, n). Filter empty names defensively.
    return [(name, n) for (name, n) in rows if name]


def load_existing(session: Session) -> set[str]:
    return set(session.exec(select(Game.name)).all())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N games (sample mode).",
    )
    parser.add_argument(
        "--sample", action="store_true",
        help="Print each tagging result line-by-line; implies resumable per-game commit.",
    )
    parser.add_argument(
        "--min-mentions", type=int, default=2,
        help="Only tag games appearing in >= M ok-enrichments (default: 2).",
    )
    args = parser.parse_args()

    t0 = time.time()
    totals = {"considered": 0, "skipped_existing": 0, "tagged": 0, "failed": 0}

    with Session(engine) as session:
        candidates = load_candidates(session, args.min_mentions)
        existing = load_existing(session)

        # Filter out already-tagged games (apply BEFORE --limit).
        to_process = [(name, n) for (name, n) in candidates if name not in existing]
        totals["skipped_existing"] = len(candidates) - len(to_process)

        if args.limit is not None:
            to_process = to_process[: args.limit]

        totals["considered"] = len(to_process)
        log.info(
            "populate_games_dim: %d candidates, %d already tagged, %d to process (min_mentions=%d, limit=%s)",
            len(candidates), totals["skipped_existing"], totals["considered"],
            args.min_mentions, args.limit,
        )

        iterator = to_process if args.sample else tqdm(to_process, desc="tagging games", unit="game")
        for name, n in iterator:
            try:
                tags = tag_game(name)
            except Exception as e:  # noqa: BLE001
                totals["failed"] += 1
                log.warning("tag_game failed for %r (mentions=%d): %s", name, n, e)
                continue

            try:
                session.add(Game(
                    name=name,
                    lifecycle=tags.lifecycle,
                    live_service=tags.live_service,
                ))
                session.commit()
                totals["tagged"] += 1
            except Exception as e:  # noqa: BLE001
                session.rollback()
                totals["failed"] += 1
                log.warning("DB insert failed for %r: %s", name, e)
                continue

            if args.sample:
                print(f"{name}\tlifecycle={tags.lifecycle}\tlive_service={tags.live_service}")

    elapsed = time.time() - t0
    log.info("populate_games_dim done in %.1fs: %s", elapsed, totals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
