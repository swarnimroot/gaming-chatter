"""Refresh the authoritative `game_releases` table from PC Gamer's upcoming-games calendar.

One-shot script: fetches the PC Gamer article body, asks Haiku 4.5 for a
list of (name, release_date) pairs, and diffs against the existing rows in
`game_releases` (source='pcgamer'). Only writes rows that are new or have
a changed release_date — re-running with the same input yields zero writes.

After each changed row, calls `sync_games_dim` to mirror the resolved
release_date + derived lifecycle into the existing `games` table so the
Release Radar card and other consumers keep working without a refactor.

Usage:
    python scripts/refresh_pcgamer_releases.py             # full refresh
    python scripts/refresh_pcgamer_releases.py --dry-run   # parse + report, no writes
    python scripts/refresh_pcgamer_releases.py --limit 20  # cap parsed entries
    python scripts/refresh_pcgamer_releases.py --url URL   # override article URL

Phase 3c.18.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
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

from sqlmodel import Session, select  # noqa: E402

from app.db.models import GameRelease  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.services.anthropic import tag_pcgamer_releases  # noqa: E402
from app.services.release_dates import (  # noqa: E402
    is_valid_release_date,
    sync_games_dim,
)
from scrapers_lib.tier1.article import fetch_article  # noqa: E402

log = logging.getLogger("refresh_pcgamer_releases")

DEFAULT_URL = "https://www.pcgamer.com/games/new-pc-games-2026/"
SOURCE = "pcgamer"


def _fetch_body(url: str) -> str:
    """Fetch the article and return the extracted body text. Raises on failure."""
    log.info("fetching %s", url)
    mentions = fetch_article(url, timeout=30.0)
    if not mentions:
        raise RuntimeError(f"fetch_article returned empty list for {url}")
    body = (mentions[0].raw_text or "").strip()
    if not body:
        raise RuntimeError(f"fetch_article returned empty body for {url}")
    log.info("fetched body: %d chars (title=%r)", len(body), mentions[0].source_title)
    return body


def _existing_by_name(session: Session) -> dict[str, GameRelease]:
    """Load all current pcgamer rows keyed by game_name_lc for fast diffing."""
    rows = session.exec(
        select(GameRelease).where(GameRelease.source == SOURCE)
    ).all()
    return {r.game_name_lc: r for r in rows}


def run(url: str = DEFAULT_URL, limit: int | None = None, dry_run: bool = False) -> dict:
    """Importable orchestrator entry. Phase 4 jobs.py calls this.

    Returns the totals dict; raises RuntimeError on fetch/parse failure.
    """
    t0 = time.time()
    log.info("=== refresh_pcgamer_releases start (dry_run=%s) ===", dry_run)

    body = _fetch_body(url)
    parsed = tag_pcgamer_releases(body)

    if limit:
        parsed = parsed[:limit]
    log.info("Haiku returned %d parsed entries", len(parsed))

    # Filter to valid format (defense in depth — Haiku should already comply).
    valid_entries = []
    invalid = 0
    for r in parsed:
        if is_valid_release_date(r.release_date):
            valid_entries.append(r)
        else:
            invalid += 1
            log.warning(
                "dropping invalid release_date format: name=%r release_date=%r",
                r.name, r.release_date,
            )
    log.info("valid: %d, dropped (bad format): %d", len(valid_entries), invalid)

    totals = {
        "parsed": len(parsed),
        "invalid_dropped": invalid,
        "new": 0,
        "updated": 0,
        "unchanged": 0,
        "games_synced": 0,
    }

    if dry_run:
        log.info("--dry-run set; would-write preview:")
        with Session(engine) as session:
            existing = _existing_by_name(session)
            for r in valid_entries:
                key = r.name.strip().lower()
                prev = existing.get(key)
                if prev is None:
                    totals["new"] += 1
                    log.info("  NEW      %s :: %s", r.name, r.release_date)
                elif prev.release_date != r.release_date:
                    totals["updated"] += 1
                    log.info("  UPDATED  %s :: %s -> %s", r.name, prev.release_date, r.release_date)
                else:
                    totals["unchanged"] += 1
        _print_summary(totals, time.time() - t0)
        return totals

    # Real write path.
    now = datetime.utcnow()
    changed_keys: list[str] = []
    with Session(engine) as session:
        existing = _existing_by_name(session)
        for r in valid_entries:
            key = r.name.strip().lower()
            if not key:
                continue
            prev = existing.get(key)
            if prev is None:
                row = GameRelease(
                    game_name_lc=key,
                    source=SOURCE,
                    game_name=r.name.strip(),
                    release_date=r.release_date,
                    raw_label=None,
                    updated_at=now,
                )
                session.add(row)
                totals["new"] += 1
                changed_keys.append(key)
            elif prev.release_date != r.release_date:
                prev.release_date = r.release_date
                prev.game_name = r.name.strip()  # refresh display casing too
                prev.updated_at = now
                session.add(prev)
                totals["updated"] += 1
                changed_keys.append(key)
            else:
                totals["unchanged"] += 1
        session.commit()

        # Sync games dim for changed keys.
        for key in changed_keys:
            if sync_games_dim(session, key, commit=False):
                totals["games_synced"] += 1
        session.commit()

    _print_summary(totals, time.time() - t0)
    return totals


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", type=str, default=DEFAULT_URL, help="PC Gamer article URL")
    ap.add_argument("--limit", type=int, default=None, help="Cap parsed entries (smoke-test)")
    ap.add_argument("--dry-run", action="store_true", help="Parse + report only, no DB writes")
    args = ap.parse_args()

    try:
        run(url=args.url, limit=args.limit, dry_run=args.dry_run)
    except RuntimeError as e:
        log.error("fetch failed: %s", e)
        return 2
    except Exception as e:  # noqa: BLE001
        log.error("Haiku parse failed: %s", e)
        return 3
    return 0


def _print_summary(totals: dict, elapsed: float) -> None:
    print()
    print("=" * 60)
    print(f"refresh_pcgamer_releases summary  ({elapsed:.1f}s elapsed)")
    print(f"  parsed entries:         {totals['parsed']}")
    print(f"  dropped (bad format):   {totals['invalid_dropped']}")
    print(f"  new rows inserted:      {totals['new']}")
    print(f"  rows updated:           {totals['updated']}")
    print(f"  rows unchanged:         {totals['unchanged']}")
    print(f"  games dim rows synced:  {totals['games_synced']}")
    print("=" * 60)


if __name__ == "__main__":
    raise SystemExit(main())
