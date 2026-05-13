"""Extract release dates for upcoming-tagged games from the corpus via Haiku.

Original plan (2026-05-12 morning) tried IGN's /upcoming/games page, but
the page is React-hydrated — only ~1 in 5 of our 28 upcoming games appear
in the static HTML, and the relevant section sits past position 388K
(too deep for any reasonable Haiku context window after truncation).

Pivoted to per-game corpus extraction: for each upcoming game, gather the
titles + tldrs of items mentioning it, pass to Haiku, ask for the release
date stated in those snippets (or null when none is stated). The 28 games
are guaranteed to be in the corpus — that's how they got tagged in
populate_games_dim — so coverage is bounded by whether dates were ever
mentioned in the articles, not by external page parsing.

One Haiku call per game (~28 calls, ~$0.10 total, ~90s wall-clock).
Idempotent: rows whose extracted value matches the current value are left
alone, so re-running is cheap and safe.

Usage:
    python scripts/extract_release_dates.py              # full run
    python scripts/extract_release_dates.py --limit 5    # first N games
    python scripts/extract_release_dates.py --dry-run    # show diffs only
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import anthropic  # noqa: E402
from pydantic import BaseModel, Field, ValidationError  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlmodel import Session, select  # noqa: E402
from tqdm import tqdm  # noqa: E402

from app.config import ANTHROPIC_ENRICH_MODEL, ANTHROPIC_TIMEOUT  # noqa: E402
from app.db.models import Game  # noqa: E402
from app.db.session import engine  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("extract_release_dates")


SYSTEM_PROMPT = """You extract video-game release dates from gaming-news article snippets.

You will be given:
- A game name.
- A list of recent article snippets (title + 1-2 sentence summary) that mention this game.

Find the release date as stated in those snippets. Return one of:
  - "YYYY-MM-DD"  when a specific calendar date is stated (e.g. "October 23, 2026" -> "2026-10-23")
  - "YYYY-MM"     when only month + year is stated (e.g. "October 2026" -> "2026-10")
  - "YYYY"        when only year is stated (e.g. "2026" -> "2026")
  - "Q1-YYYY" / "Q2-YYYY" / "Q3-YYYY" / "Q4-YYYY"   when only quarter + year is stated
  - "TBA"         when the snippets explicitly say TBA / TBD / "to be announced" / "delayed indefinitely"
  - null          when NO date is stated in any snippet, OR snippets conflict, OR you cannot tell

Rules:
- Use the MOST RECENT date stated. If an early snippet says "October 2026" and a later one says "delayed to Q1 2027", return "Q1-2027".
- A snippet that says "GTA VI launches Oct 2026" -> "2026-10".
- A snippet that says "Subnautica 2 enters Early Access this year" without a year-tied month -> null (too vague).
- Do NOT guess based on training knowledge. Use ONLY what the snippets state.

Output JSON only. No prose."""


class ReleaseDateResponse(BaseModel):
    release_date: Optional[str] = Field(default=None)


def items_for_game(session: Session, name: str, limit: int = 12) -> list[tuple[str, str]]:
    rows = session.exec(text("""
        SELECT i.title, e.tldr
        FROM items i
        JOIN enrichments e ON e.item_id = i.id
        JOIN json_each(e.entities, '$.games') je ON je.value = :name
        WHERE e.status = 'ok'
        ORDER BY (i.published_at IS NULL), i.published_at DESC
        LIMIT :lim
    """).bindparams(name=name, lim=limit)).all()
    return [(t or "", s or "") for t, s in rows]


def extract_one(client: anthropic.Anthropic, name: str, snippets: list[tuple[str, str]]) -> Optional[str]:
    if not snippets:
        return None
    body_lines = []
    for i, (title, tldr) in enumerate(snippets, 1):
        body_lines.append(f"{i}. Title: {title}\n   Summary: {tldr}")
    user_msg = f"Game: {name}\n\nArticle snippets:\n" + "\n\n".join(body_lines)

    try:
        message = client.messages.parse(
            model=ANTHROPIC_ENRICH_MODEL,
            max_tokens=128,
            system=[{"type": "text", "text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": user_msg}],
            output_format=ReleaseDateResponse,
        )
    except (anthropic.APIError, ValidationError) as e:
        log.warning("extract failed for %r: %s", name, e)
        return None

    data = getattr(message, "parsed_output", None)
    if data is None:
        return None
    return data.release_date


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Process at most N games.")
    parser.add_argument("--dry-run", action="store_true", help="Show diffs without committing.")
    args = parser.parse_args()

    client = anthropic.Anthropic(timeout=ANTHROPIC_TIMEOUT)

    with Session(engine) as session:
        games = session.exec(select(Game).where(Game.lifecycle == "upcoming")).all()
        if args.limit is not None:
            games = games[: args.limit]
        log.info("processing %d upcoming-tagged games", len(games))

        t0 = time.time()
        updates = unchanged = no_snippets = errs = 0

        for game in tqdm(games, desc="games", unit="game"):
            snippets = items_for_game(session, game.name, limit=12)
            if not snippets:
                no_snippets += 1
                continue
            try:
                new_date = extract_one(client, game.name, snippets)
            except Exception as e:  # noqa: BLE001
                errs += 1
                log.warning("extract_one threw for %r: %s", game.name, e)
                continue

            if new_date == game.release_date:
                unchanged += 1
                continue

            log.info("  %s: %r -> %r  (%d snippets)", game.name, game.release_date, new_date, len(snippets))
            if not args.dry_run:
                game.release_date = new_date
                session.add(game)
                session.commit()
            updates += 1

        elapsed = time.time() - t0
        log.info(
            "done in %.1fs: %d updated, %d unchanged, %d no-snippets, %d errors",
            elapsed, updates, unchanged, no_snippets, errs,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
