"""Re-tag all games in the dim using corpus context (not name-only).

`populate_games_dim.py` and the early `extract_release_dates.py` pass both
made the same mistake: they sent ONLY the game name to Haiku, leaving the
model to fall back on training cutoff (Jan 2026). Anything that shipped
between cutoff and today (2026-05-12) gets misclassified as 'upcoming'.

This script fixes that by pulling 8-10 recent article titles + tldrs from
the corpus per game, then asking Haiku to derive lifecycle + release_date
+ live_service from those snippets — not training memory. Articles are
Jan-May 2026 (post-cutoff), so they reflect current reality.

One Haiku call per game (~189 calls, ~$1, ~4 min wall-clock). Per-game
commit makes it resumable on Ctrl-C. Idempotent — only commits when a
value differs from what's already in the dim.

Usage:
    python scripts/retag_games_with_context.py             # full pass
    python scripts/retag_games_with_context.py --limit 5   # smoke test
    python scripts/retag_games_with_context.py --dry-run   # show diffs only
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
log = logging.getLogger("retag_games")


SYSTEM_PROMPT = """You profile a single video game using ONLY the recent gaming-news article snippets given to you.

The snippets are from January-May 2026, so they reflect current reality.
DO NOT use training knowledge to override what the articles state.

Return JSON with three fields:

1. lifecycle: one of "existing", "upcoming", or null.
   - "existing" = the game IS released on at least one platform RIGHT NOW.
     Cues in articles: "launched", "out now", "1.0 release", "reviews are in",
     "patch X.Y", "Season N begins", "early access begins", references to
     current player counts, in-game balance/economy discussion, reactions
     to live gameplay.
   - "upcoming" = the game has NOT yet released anywhere.
     Cues: "delayed to", "announced", "in development", "trailer revealed",
     "demo at [event]", "release window", "coming soon", "to be released",
     beta/alpha that is gated and not a sustained early-access.
   - null = snippets are too tangential or contradictory to tell.

2. release_date: a date string from the snippets, in one of these forms:
   - "YYYY-MM-DD" when a specific date is stated and confirmed
   - "YYYY-MM"    month + year only
   - "YYYY"       year only
   - "Q1-YYYY" / "Q2-YYYY" / "Q3-YYYY" / "Q4-YYYY" for quarter + year
   - "TBA"        if articles explicitly say TBA / TBD / "delayed indefinitely"
   - null         no date stated, OR the only date is clearly stale
                   (a delay supersedes the original)
   Use the CURRENT TARGET date. If an article says "originally May 2024 but
   delayed to Q1 2027", return "Q1-2027". Don't return "2024" — that's stale.
   If lifecycle is "existing" and the snippets cite the original launch date,
   you may return that as the release_date.

3. live_service: one of true, false, or null.
   - true  = seasonal / battle-pass / league / warbond content model with
             regular content drops. MMOs ARE live-service.
   - false = single-player, one-time purchase, even with DLC. Episodic
             story games are NOT live-service.
   - null  = snippets don't make this clear.

Worked examples:
  - Game: Crimson Desert. Snippets discuss launch player counts, MMO faction
    PvP, Season 1 content drops. -> lifecycle="existing", live_service=true.
  - Game: Marathon. Snippets discuss alpha leaks, art direction discourse,
    Bungie restructuring around the project. -> lifecycle="upcoming",
    release_date=null, live_service=null.
  - Game: Helldivers 2. Snippets discuss warbonds, balance patches, Major
    Orders. -> lifecycle="existing", live_service=true.
  - Game: Mina the Hollower. Snippets discuss delays and a new release
    window. -> lifecycle="upcoming", release_date=<the new window>.

Output JSON only. No prose."""


class GameProfile(BaseModel):
    lifecycle: Optional[str] = Field(default=None)
    release_date: Optional[str] = Field(default=None)
    live_service: Optional[bool] = Field(default=None)


def items_for_game(session: Session, name: str, limit: int = 10) -> list[tuple[str, str]]:
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


def profile_one(client: anthropic.Anthropic, name: str, snippets: list[tuple[str, str]]) -> Optional[GameProfile]:
    body_lines = [f"{i}. Title: {t}\n   Summary: {s}" for i, (t, s) in enumerate(snippets, 1)]
    user_msg = f"Game: {name}\n\nArticle snippets:\n" + "\n\n".join(body_lines)
    try:
        message = client.messages.parse(
            model=ANTHROPIC_ENRICH_MODEL,
            max_tokens=256,
            system=[{
                "type": "text", "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # no-op until prompt grows past 4096 tokens
            }],
            messages=[{"role": "user", "content": user_msg}],
            output_format=GameProfile,
        )
    except (anthropic.APIError, ValidationError) as e:
        log.warning("profile_one failed for %r: %s", name, e)
        return None
    data = getattr(message, "parsed_output", None)
    if data is None:
        return None
    if data.lifecycle not in {"existing", "upcoming", None}:
        data.lifecycle = None
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Process at most N games (sample).")
    parser.add_argument("--dry-run", action="store_true", help="Show diffs without committing.")
    args = parser.parse_args()

    client = anthropic.Anthropic(timeout=ANTHROPIC_TIMEOUT)

    with Session(engine) as session:
        games = session.exec(select(Game).order_by(Game.name)).all()
        if args.limit is not None:
            games = games[: args.limit]
        log.info("re-tagging %d games", len(games))

        t0 = time.time()
        updated = unchanged = no_snippets = errs = 0
        lc_flips = {"existing": 0, "upcoming": 0, "null": 0}

        for game in tqdm(games, desc="games", unit="game"):
            snippets = items_for_game(session, game.name, limit=10)
            if not snippets:
                no_snippets += 1
                continue
            profile = profile_one(client, game.name, snippets)
            if profile is None:
                errs += 1
                continue

            changed = False
            if profile.lifecycle != game.lifecycle:
                key = profile.lifecycle if profile.lifecycle else "null"
                lc_flips[key] = lc_flips.get(key, 0) + 1
                log.info("  %s: lifecycle %r -> %r (%d snippets)",
                         game.name, game.lifecycle, profile.lifecycle, len(snippets))
                if not args.dry_run:
                    game.lifecycle = profile.lifecycle
                changed = True
            if profile.release_date != game.release_date:
                log.info("  %s: release_date %r -> %r",
                         game.name, game.release_date, profile.release_date)
                if not args.dry_run:
                    game.release_date = profile.release_date
                changed = True
            if profile.live_service != game.live_service:
                log.info("  %s: live_service %r -> %r",
                         game.name, game.live_service, profile.live_service)
                if not args.dry_run:
                    game.live_service = profile.live_service
                changed = True

            if changed:
                if not args.dry_run:
                    session.add(game)
                    session.commit()
                updated += 1
            else:
                unchanged += 1

        elapsed = time.time() - t0
        log.info(
            "done in %.1fs: %d updated, %d unchanged, %d no-snippets, %d errors  (lifecycle flips %s)",
            elapsed, updated, unchanged, no_snippets, errs, lc_flips,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
