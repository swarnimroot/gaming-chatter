"""One-off: dump top-N clusters by score for Phase 3b ranking review."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    sql = text(
        """
        SELECT score, source_count, member_count,
               strftime('%Y-%m-%d', latest_published_at) AS latest, label
        FROM clusters
        WHERE week_id = 'all'
        ORDER BY score DESC NULLS LAST, member_count DESC
        LIMIT :n
        """
    )
    with engine.connect() as conn:
        rows = list(conn.execute(sql, {"n": n}))
    print(f'{"score":>7}  {"src":>3}  {"n":>3}  {"latest":>10}  label')
    for score, src, members, latest, label in rows:
        print(f"{score:>7.2f}  {src:>3}  {members:>3}  {latest:>10}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
