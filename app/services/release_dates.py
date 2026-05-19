"""Authoritative game release-date resolver (Phase 3c.18).

`game_releases` is the source-of-truth table (populated by external sources
like pcgamer.com via `scripts/refresh_pcgamer_releases.py`). This module
exposes:

- `release_date_for(session, name)`: source-priority lookup. pcgamer wins
  over ign on conflict.
- `derive_lifecycle(release_date, today)`: pure function — maps a
  release-date string to 'upcoming' (future / TBA-unknown) / 'existing'
  (past) / None (no date known, no opinion).
- `sync_games_dim(session, game_name_lc)`: writes the resolved release_date
  + derived lifecycle back to the matching `games` row so existing readers
  (Release Radar card, top_games_for_week, etc.) keep working without
  refactoring. The `games` columns are now a synced cache; this table is
  the canonical truth.
- `is_valid_release_date(s)`: strict format check used by the refresh script
  before writing (defense in depth — Haiku is also instructed to use these
  formats, but bad rows shouldn't leak past the validator).

Locked release_date formats (must match exactly):
  YYYY-MM-DD / YYYY-MM / Qn-YYYY (n in 1..4) / YYYY / TBA
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.db.models import Game, GameRelease
from app.services.reports import is_future_or_unknown

# Source priority — first that has a row wins. Add 'ign' (and others) here
# as ingestion scripts come online. Sources not listed are tried last in
# table-order, which is non-deterministic — keep this list complete.
SOURCE_PRIORITY = ["pcgamer", "ign"]


# ---- Format validation ----------------------------------------------------

_RE_YMD = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_YM = re.compile(r"^\d{4}-\d{2}$")
_RE_Y = re.compile(r"^\d{4}$")
_RE_Q = re.compile(r"^Q[1-4]-\d{4}$")


def is_valid_release_date(s: Optional[str]) -> bool:
    """True when `s` is None or matches one of the locked formats.

    None is treated as valid (= "no date known"). Empty string is invalid.
    """
    if s is None:
        return True
    if not isinstance(s, str) or not s:
        return False
    if s == "TBA":
        return True
    if _RE_YMD.match(s):
        # Reject impossible months/days early — strptime catches Feb 30 etc.
        try:
            datetime.strptime(s, "%Y-%m-%d")
            return True
        except ValueError:
            return False
    if _RE_YM.match(s):
        try:
            datetime.strptime(s, "%Y-%m")
            return True
        except ValueError:
            return False
    if _RE_Y.match(s):
        return True
    if _RE_Q.match(s):
        return True
    return False


# ---- Lookup + derivation --------------------------------------------------

def release_date_for(session: Session, name: str) -> Optional[str]:
    """Source-priority lookup. Returns release_date string from the highest-
    priority source that has a row for this game, or None if no row exists.

    `name` is case-insensitive against `game_name_lc`.
    """
    name_lc = (name or "").strip().lower()
    if not name_lc:
        return None
    rows = session.exec(
        select(GameRelease).where(GameRelease.game_name_lc == name_lc)
    ).all()
    if not rows:
        return None
    by_source = {r.source: r.release_date for r in rows}
    for src in SOURCE_PRIORITY:
        if src in by_source:
            return by_source[src]
    # Sources outside SOURCE_PRIORITY — return first encountered.
    return rows[0].release_date


def derive_lifecycle(
    release_date: Optional[str],
    today: Optional[datetime] = None,
) -> Optional[str]:
    """Map a release_date string to a lifecycle.

    - None / 'TBA' → None ("we don't know")
    - Future or current-period date → 'upcoming'
    - Past date → 'existing'

    Reuses the existing `is_future_or_unknown` helper for the future-or-past
    check so the boundary semantics stay consistent with the Release Radar
    card (which already filters past dates).
    """
    if release_date is None:
        return None
    if release_date == "TBA":
        return None
    if not is_valid_release_date(release_date):
        return None
    # is_future_or_unknown returns True for valid future dates AND for
    # unknown / unparseable values. Since we just validated, we only catch
    # the future-vs-past split here.
    return "upcoming" if is_future_or_unknown(release_date, today) else "existing"


# ---- Sync to games dim (backward-compat cache) ----------------------------

def sync_games_dim(session: Session, game_name_lc: str, commit: bool = True) -> bool:
    """Write the resolved release_date + derived lifecycle to the matching
    `games` row. Returns True when the row was found and updated, False when
    no `games` row exists for this name.

    The matching is case-insensitive (`LOWER(games.name) == game_name_lc`).
    Multiple `games` rows can share a name_lc only via casing variants
    (e.g. "Diablo IV" vs "Diablo 4" are distinct PKs by design); this updates
    all matches.

    Caller decides whether to commit (batched commits supported by passing
    commit=False, then calling session.commit() once at the end).
    """
    if not game_name_lc:
        return False

    rd = release_date_for(session, game_name_lc)
    lifecycle = derive_lifecycle(rd)

    # Find candidate `games` rows whose name (any casing) matches the lc key.
    candidates = session.exec(select(Game)).all()
    matched = False
    for g in candidates:
        if (g.name or "").strip().lower() == game_name_lc:
            # Only write when something actually changed — keeps re-runs idempotent.
            changed = False
            if g.release_date != rd:
                g.release_date = rd
                changed = True
            if g.lifecycle != lifecycle and lifecycle is not None:
                g.lifecycle = lifecycle
                changed = True
            if changed:
                session.add(g)
                matched = True
    if matched and commit:
        session.commit()
    return matched
