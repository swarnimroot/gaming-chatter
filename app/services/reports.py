"""Per-ISO-week aggregation queries for /reports.

Each function takes a Session + week_id (e.g. '2026-W19') and returns the
shape consumed by the reports router for the matching card. Per-week scope
is computed from items.published_at via ISO 8601 bounds — not strftime —
so it does not depend on the SQLite build supporting %G/%V.

Phase 3c.1 surfaces real data for three cards (week overview / Hottest /
Releases). The other cards remain on placeholder data until Phase 3c.4
synthesis lands.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlmodel import Session


def iso_week_bounds(week_id: str) -> tuple[datetime, datetime]:
    """Return [Mon 00:00, next-Mon 00:00) UTC bounds for an ISO 'YYYY-Www' id."""
    year_str, week_str = week_id.split("-W")
    year, week = int(year_str), int(week_str)
    monday = datetime.fromisocalendar(year, week, 1)
    return monday, monday + timedelta(days=7)


def parse_date_range(
    from_str: str,
    to_str: str,
    week_id: str,
    default_days: int,
    now: datetime | None = None,
) -> dict:
    """Resolve ?from / ?to / ?week_id query params into a datetime window.

    Precedence (first valid wins):
      1. `week_id` non-empty + parseable → iso_week_bounds(week_id). Back-compat
         shim for /reports footer links predating Phase 3c.17.
      2. `from_str` + `to_str` non-empty + parseable as 'YYYY-MM-DD' → use them.
      3. fallback → [today - (default_days - 1), today], inclusive of today.

    `to` is inclusive of the user-picked day; we add +1 day internally to get
    the exclusive upper bound so SQL `published_at < end` still covers the 19th.

    Returns dict: start (dt), end (dt, exclusive), from_display, to_display
    ('YYYY-MM-DD' strings always populated so the picker is never blank).
    """
    now = now or datetime.utcnow()

    if week_id:
        try:
            start, end_excl = iso_week_bounds(week_id)
            to_disp = (end_excl - timedelta(days=1)).strftime("%Y-%m-%d")
            return {
                "start": start, "end": end_excl,
                "from_display": start.strftime("%Y-%m-%d"), "to_display": to_disp,
            }
        except (ValueError, IndexError):
            pass

    if from_str and to_str:
        try:
            start = datetime.strptime(from_str, "%Y-%m-%d")
            end_inclusive = datetime.strptime(to_str, "%Y-%m-%d")
            if start <= end_inclusive:
                return {
                    "start": start, "end": end_inclusive + timedelta(days=1),
                    "from_display": from_str, "to_display": to_str,
                }
        except ValueError:
            pass

    end_inclusive = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end_inclusive - timedelta(days=default_days - 1)
    return {
        "start": start, "end": end_inclusive + timedelta(days=1),
        "from_display": start.strftime("%Y-%m-%d"),
        "to_display": end_inclusive.strftime("%Y-%m-%d"),
    }


def prev_week_id(week_id: str) -> str:
    """Return the ISO week id one week prior (handles year rollovers)."""
    start, _ = iso_week_bounds(week_id)
    prior = start - timedelta(days=7)
    iy, iw, _ = prior.isocalendar()
    return f"{iy}-W{iw:02d}"


def week_item_total(session: Session, week_id: str) -> int:
    """Total items published in the ISO week — denominator for mention-rate."""
    start, end = iso_week_bounds(week_id)
    row = session.exec(text(
        "SELECT COUNT(*) FROM items WHERE published_at >= :s AND published_at < :e"
    ).bindparams(s=start, e=end)).first()
    return int(row[0] or 0)


def available_weeks(session: Session) -> list[str]:
    """Distinct per-ISO-week ids that have at least one cluster.

    Excludes the legacy week_id='all' cross-corpus bucket (Phase 3b);
    cleanup of those 63 rows is deferred — they're still in the DB but
    shouldn't show up in the read-out picker.
    """
    rows = session.exec(text(
        "SELECT DISTINCT week_id FROM clusters "
        "WHERE week_id != 'all' "
        "ORDER BY week_id DESC"
    )).all()
    return [r[0] for r in rows]


def week_label_and_range(week_id: str) -> tuple[str, str]:
    """Format an ISO week id as ('Week of May 4, 2026', 'Apr 27 — May 3').

    Uses zero-stripped strftime so it works the same on Windows and POSIX
    (Windows strftime doesn't honor %-d).
    """
    start, end = iso_week_bounds(week_id)
    sunday = end - timedelta(days=1)
    label = f"Week of {start.strftime('%b %d, %Y').replace(' 0', ' ')}"
    rng = f"{start.strftime('%b %d').replace(' 0', ' ')} — {sunday.strftime('%b %d').replace(' 0', ' ')}"
    return label, rng


def week_stats(session: Session, week_id: str) -> dict:
    """Stories + distinct sources for the ISO week."""
    start, end = iso_week_bounds(week_id)
    row = session.exec(text(
        "SELECT COUNT(*), COUNT(DISTINCT source_id) "
        "FROM items WHERE published_at >= :s AND published_at < :e"
    ).bindparams(s=start, e=end)).first()
    return {"stories": row[0] or 0, "sources": row[1] or 0}


def _tagcount_for_week(session: Session, week_id: str, col: str, limit: int) -> list[tuple[str, int]]:
    """Generic top-N tagcount over a JSON-array enrichments column (genres or platforms)."""
    start, end = iso_week_bounds(week_id)
    sql = text(f"""
        SELECT TRIM(je.value) AS tag, COUNT(*) AS n
        FROM items i
        JOIN enrichments e ON e.item_id = i.id
        JOIN json_each(e.{col}) je ON e.status = 'ok' AND e.{col} IS NOT NULL
        WHERE i.published_at >= :s AND i.published_at < :e
        GROUP BY TRIM(je.value)
        ORDER BY n DESC
        LIMIT :lim
    """)
    rows = session.exec(sql.bindparams(s=start, e=end, lim=limit)).all()
    return [(t, n) for t, n in rows if t]


def top_genres_for_week(session: Session, week_id: str, limit: int = 5) -> list[tuple[str, int]]:
    return _tagcount_for_week(session, week_id, "genres", limit)


def top_platforms_for_week(session: Session, week_id: str, limit: int = 6) -> list[tuple[str, int]]:
    return _tagcount_for_week(session, week_id, "platforms", limit)


def net_sentiment_for_week(session: Session, week_id: str) -> int:
    """Mean sentiment_score on [-1, +1] scaled to [-100, +100] integer.

    Returns 0 when the week has no enriched items.
    """
    start, end = iso_week_bounds(week_id)
    row = session.exec(text("""
        SELECT AVG(e.sentiment_score) FROM items i
        JOIN enrichments e ON e.item_id = i.id
        WHERE i.published_at >= :s AND i.published_at < :e
          AND e.status = 'ok' AND e.sentiment_score IS NOT NULL
    """).bindparams(s=start, e=end)).first()
    avg = row[0] if row and row[0] is not None else 0.0
    return round(avg * 100)


def top_games_for_week(
    session: Session,
    week_id: str,
    limit: int = 5,
    lifecycle: str | None = None,
) -> list[dict]:
    """Top-N games by mention count this week.

    Args:
        lifecycle: None for all games; 'existing' or 'upcoming' restricts to
            games whose row in the games dim has that lifecycle. Games not in
            the dim (rare — <2 mentions when populate_games_dim ran) are
            included only for the unfiltered case.

    Returns dicts: {name, count, platforms (<=3), lifecycle, live_service, sources (<=5)}.
    Item-level counts are DISTINCT so multiple mentions in one article
    don't double-weight. Platforms are the union of items' platforms tags.
    """
    start, end = iso_week_bounds(week_id)
    # Case-insensitive grouping collapses article-side casing variants (e.g.
    # "Mixtape" / "MIXTAPE") onto a single row. Display name is the canonical
    # name from the games dim when available, falling back to the article's
    # casing for games that never made it into the dim (<2 mentions originally).
    if lifecycle is None:
        sql = """
            SELECT
              COALESCE(MAX(g.name), MIN(TRIM(je.value))) AS game,
              COUNT(DISTINCT i.id) AS n
            FROM items i
            JOIN enrichments e ON e.item_id = i.id
            JOIN json_each(e.entities, '$.games') je ON e.status = 'ok'
            LEFT JOIN games g ON LOWER(g.name) = LOWER(TRIM(je.value))
            WHERE i.published_at >= :s AND i.published_at < :e
            GROUP BY LOWER(TRIM(je.value))
            HAVING n > 0
            ORDER BY n DESC
            LIMIT :lim
        """
        rows = session.exec(text(sql).bindparams(s=start, e=end, lim=limit)).all()
    else:
        sql = """
            SELECT g.name AS game, COUNT(DISTINCT i.id) AS n
            FROM items i
            JOIN enrichments e ON e.item_id = i.id
            JOIN json_each(e.entities, '$.games') je ON e.status = 'ok'
            JOIN games g ON LOWER(g.name) = LOWER(TRIM(je.value)) AND g.lifecycle = :lc
            WHERE i.published_at >= :s AND i.published_at < :e
            GROUP BY g.name
            HAVING n > 0
            ORDER BY n DESC
            LIMIT :lim
        """
        rows = session.exec(text(sql).bindparams(s=start, e=end, lim=limit, lc=lifecycle)).all()
    games = [(name, n) for name, n in rows if name]
    if not games:
        return []

    results: list[dict] = []
    for name, count in games:
        # All per-game lookups are case-insensitive on the entities.games side
        # so the dedupe + case-collapse remains transparent here.
        plats = [r[0] for r in session.exec(text("""
            SELECT DISTINCT TRIM(pj.value)
            FROM items i
            JOIN enrichments e ON e.item_id = i.id
            JOIN json_each(e.entities, '$.games') gj ON LOWER(TRIM(gj.value)) = LOWER(:name)
            JOIN json_each(e.platforms) pj ON e.platforms IS NOT NULL
            WHERE i.published_at >= :s AND i.published_at < :e
              AND e.status = 'ok'
            ORDER BY 1
        """).bindparams(name=name, s=start, e=end)).all() if r[0]]

        srcs = [r[0] for r in session.exec(text("""
            SELECT DISTINCT s.name
            FROM items i
            JOIN sources s ON s.id = i.source_id
            JOIN enrichments e ON e.item_id = i.id
            JOIN json_each(e.entities, '$.games') je ON LOWER(TRIM(je.value)) = LOWER(:name)
            WHERE i.published_at >= :s AND i.published_at < :e
              AND e.status = 'ok'
            LIMIT 8
        """).bindparams(name=name, s=start, e=end)).all() if r[0]]

        dim = session.exec(text(
            "SELECT lifecycle, live_service FROM games WHERE LOWER(name) = LOWER(:name)"
        ).bindparams(name=name)).first()
        lifecycle = dim[0] if dim else None
        live_service = bool(dim[1]) if dim and dim[1] is not None else False

        results.append({
            "name": name,
            "count": count,
            "platforms": plats[:3],
            "lifecycle": lifecycle,
            "live_service": live_service,
            "sources": srcs[:5],
        })
    return results


def is_future_or_unknown(raw: str | None, today: datetime | None = None) -> bool:
    """True when a games.release_date value represents a future / unknown date.

    Used to drop past-dated games from the Release radar — they were tagged
    'upcoming' by Haiku from the game name alone, but corpus articles cite
    delayed / historic launches. Keeps null / 'TBA' / parseable-future values.
    """
    if not raw:
        return True
    s = str(raw).strip()
    if not s or s.upper() == "TBA":
        return True
    today = today or datetime.utcnow()
    today_year, today_month, today_day = today.year, today.month, today.day
    parts = s.split("-")
    # YYYY-MM-DD
    if len(parts) == 3:
        try:
            d = datetime.strptime(s, "%Y-%m-%d")
            return (d.year, d.month, d.day) >= (today_year, today_month, today_day)
        except ValueError:
            return True
    # Q[1-4]-YYYY  (quarters: Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec)
    if s.startswith("Q") and len(s) >= 7:
        try:
            quarter = int(s[1])
            year = int(s.split("-", 1)[1])
            end_month = quarter * 3
            return (year, end_month) >= (today_year, today_month)
        except (ValueError, IndexError):
            return True
    # YYYY-MM
    if len(parts) == 2:
        try:
            d = datetime.strptime(s, "%Y-%m")
            return (d.year, d.month) >= (today_year, today_month)
        except ValueError:
            return True
    # YYYY
    if len(parts) == 1 and parts[0].isdigit() and len(parts[0]) == 4:
        return int(parts[0]) >= today_year
    return True  # unknown format — keep so it stays visible


def format_release_date(raw: str | None) -> str:
    """Render a games.release_date value for display.

    Accepts 'YYYY-MM-DD' / 'YYYY-MM' / 'YYYY' / 'TBA' / None. Returns 'TBA'
    for null. Drops leading zeros so output is 'May 6' not 'May 06' on
    both Windows and POSIX.
    """
    if not raw:
        return "TBA"
    s = str(raw).strip()
    if s.upper() == "TBA":
        return "TBA"
    parts = s.split("-")
    try:
        if len(parts) == 3:
            dt = datetime.strptime(s, "%Y-%m-%d")
            this_year = datetime.utcnow().year
            fmt = "%b %d" if dt.year == this_year else "%b %d, %Y"
            return dt.strftime(fmt).replace(" 0", " ")
        if len(parts) == 2:
            dt = datetime.strptime(s, "%Y-%m")
            return dt.strftime("%b %Y")
        if len(parts) == 1 and parts[0].isdigit():
            return parts[0]
    except ValueError:
        pass
    return s


# ---------- Trends (WoW mention-rate delta) ---------------------------------
# Card 5. Each tab queries this-week counts + prior-week counts for the same
# dimension, normalizes by week item total, sorts by rate delta (percentage-
# point) DESC, and returns top-N rows. "Mention-rate delta" is locked over raw
# count delta because item volume swings 2-3x between weeks on this corpus
# (W17 89 items, W18 189, W19 551); raw count would surface the busy week's
# noise instead of actual movement.
#
# New entries (no prior-week mentions) surface naturally — prior rate = 0,
# delta = this-week rate. Falling entries can appear too (negative delta),
# but the DESC sort puts them last; with N=5 they typically don't show.


def _tag_counts_for_week(session: Session, week_id: str, col: str) -> dict[str, tuple[str, int]]:
    """Return {key_lower: (display, count)} for a JSON-array enrichments column.

    Locked-taxonomy columns (genres / platforms) don't actually have casing
    drift, but the lowered key keeps the merge symmetric with games/live-svc.
    """
    start, end = iso_week_bounds(week_id)
    rows = session.exec(text(f"""
        SELECT TRIM(je.value) AS tag, COUNT(*) AS n
        FROM items i
        JOIN enrichments e ON e.item_id = i.id
        JOIN json_each(e.{col}) je ON e.status = 'ok' AND e.{col} IS NOT NULL
        WHERE i.published_at >= :s AND i.published_at < :e
        GROUP BY TRIM(je.value)
    """).bindparams(s=start, e=end)).all()
    out: dict[str, tuple[str, int]] = {}
    for tag, n in rows:
        if not tag:
            continue
        key = tag.lower()
        out[key] = (tag, int(n))
    return out


def _game_counts_for_week(
    session: Session,
    week_id: str,
    lifecycle: str | None = None,
    live_service_only: bool = False,
) -> dict[str, tuple[str, int]]:
    """Return {name_lower: (display, count)} for game mentions in the week.

    Mirrors `top_games_for_week`'s case-insensitive grouping; canonical display
    comes from the games dim where present, otherwise from the article's casing.
    `lifecycle` filters via the games dim. `live_service_only` restricts to dim
    rows with live_service=1.
    """
    start, end = iso_week_bounds(week_id)
    where_extra = []
    if lifecycle is not None:
        where_extra.append("g.lifecycle = :lc")
    if live_service_only:
        where_extra.append("g.live_service = 1")
    join = "LEFT JOIN" if (lifecycle is None and not live_service_only) else "JOIN"
    extra_sql = (" AND " + " AND ".join(where_extra)) if where_extra and join == "JOIN" else ""

    if join == "LEFT JOIN":
        # No dim filter — keep games not in the dim (rare).
        sql = """
            SELECT
              COALESCE(MAX(g.name), MIN(TRIM(je.value))) AS game,
              COUNT(DISTINCT i.id) AS n
            FROM items i
            JOIN enrichments e ON e.item_id = i.id
            JOIN json_each(e.entities, '$.games') je ON e.status = 'ok'
            LEFT JOIN games g ON LOWER(g.name) = LOWER(TRIM(je.value))
            WHERE i.published_at >= :s AND i.published_at < :e
            GROUP BY LOWER(TRIM(je.value))
            HAVING n > 0
        """
        bind = {"s": start, "e": end}
    else:
        sql = f"""
            SELECT g.name AS game, COUNT(DISTINCT i.id) AS n
            FROM items i
            JOIN enrichments e ON e.item_id = i.id
            JOIN json_each(e.entities, '$.games') je ON e.status = 'ok'
            JOIN games g ON LOWER(g.name) = LOWER(TRIM(je.value)){extra_sql}
            WHERE i.published_at >= :s AND i.published_at < :e
            GROUP BY g.name
            HAVING n > 0
        """
        bind = {"s": start, "e": end}
        if lifecycle is not None:
            bind["lc"] = lifecycle

    rows = session.exec(text(sql).bindparams(**bind)).all()
    out: dict[str, tuple[str, int]] = {}
    for name, n in rows:
        if not name:
            continue
        out[name.lower()] = (name, int(n))
    return out


def _event_counts_for_week(session: Session, week_id: str) -> dict[str, tuple[str, int]]:
    """Return {event_lower: (display, count)} for the enrichments.event column."""
    start, end = iso_week_bounds(week_id)
    rows = session.exec(text("""
        SELECT TRIM(e.event) AS ev, COUNT(*) AS n
        FROM items i
        JOIN enrichments e ON e.item_id = i.id
        WHERE i.published_at >= :s AND i.published_at < :e
          AND e.status = 'ok'
          AND e.event IS NOT NULL
          AND TRIM(e.event) != ''
        GROUP BY TRIM(e.event)
    """).bindparams(s=start, e=end)).all()
    out: dict[str, tuple[str, int]] = {}
    for ev, n in rows:
        if not ev:
            continue
        out[ev.lower()] = (ev, int(n))
    return out


def _format_delta_pp(pp: float) -> tuple[str, str]:
    """Return (display, tone) for a percentage-point delta."""
    pp_r = round(pp, 1)
    if pp_r > 0.5:
        return (f"+{pp_r:.1f}pp", "up")
    if pp_r < -0.5:
        return (f"{pp_r:.1f}pp", "down")
    return (f"{pp_r:+.1f}pp" if pp_r else "±0pp", "neutral")


def _merge_wow(
    cur: dict[str, tuple[str, int]],
    prev: dict[str, tuple[str, int]],
    cur_total: int,
    prev_total: int,
    limit: int,
) -> list[dict]:
    """Compute rate-delta rows and return top-N sorted by delta DESC.

    Each row: {name, count, prev_count, delta_pp, delta_display, tone}.
    `count` is this-week absolute count (kept for tooltip / sanity); ranking is
    by rate delta. Entities with this-week count == 0 are dropped (falling-and-
    gone entities aren't useful in the read-out; they'd skew the bottom).
    """
    cur_total = max(cur_total, 1)
    prev_total = max(prev_total, 1)
    keys = set(cur) | set(prev)
    rows: list[dict] = []
    for k in keys:
        cur_disp, cur_n = cur.get(k, ("", 0))
        prev_disp, prev_n = prev.get(k, ("", 0))
        if cur_n == 0:
            continue
        cur_rate = cur_n / cur_total
        prev_rate = prev_n / prev_total
        delta_pp = (cur_rate - prev_rate) * 100
        delta_display, tone = _format_delta_pp(delta_pp)
        rows.append({
            "name": cur_disp or prev_disp,
            "count": cur_n,
            "prev_count": prev_n,
            "delta_pp": delta_pp,
            "delta_display": delta_display,
            "tone": tone,
        })
    rows.sort(key=lambda r: r["delta_pp"], reverse=True)
    return rows[:limit]


def top_genres_wow(session: Session, week_id: str, limit: int = 5) -> list[dict]:
    cur = _tag_counts_for_week(session, week_id, "genres")
    prev = _tag_counts_for_week(session, prev_week_id(week_id), "genres")
    return _merge_wow(cur, prev, week_item_total(session, week_id),
                      week_item_total(session, prev_week_id(week_id)), limit)


def top_platforms_wow(session: Session, week_id: str, limit: int = 5) -> list[dict]:
    cur = _tag_counts_for_week(session, week_id, "platforms")
    prev = _tag_counts_for_week(session, prev_week_id(week_id), "platforms")
    return _merge_wow(cur, prev, week_item_total(session, week_id),
                      week_item_total(session, prev_week_id(week_id)), limit)


def top_games_wow(
    session: Session,
    week_id: str,
    lifecycle: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """WoW mover-list for games. lifecycle in {None, 'existing', 'upcoming'}."""
    cur = _game_counts_for_week(session, week_id, lifecycle=lifecycle)
    prev = _game_counts_for_week(session, prev_week_id(week_id), lifecycle=lifecycle)
    return _merge_wow(cur, prev, week_item_total(session, week_id),
                      week_item_total(session, prev_week_id(week_id)), limit)


def top_live_service_wow(session: Session, week_id: str, limit: int = 5) -> list[dict]:
    cur = _game_counts_for_week(session, week_id, live_service_only=True)
    prev = _game_counts_for_week(session, prev_week_id(week_id), live_service_only=True)
    return _merge_wow(cur, prev, week_item_total(session, week_id),
                      week_item_total(session, prev_week_id(week_id)), limit)


def top_events_wow(session: Session, week_id: str, limit: int = 5) -> list[dict]:
    cur = _event_counts_for_week(session, week_id)
    prev = _event_counts_for_week(session, prev_week_id(week_id))
    return _merge_wow(cur, prev, week_item_total(session, week_id),
                      week_item_total(session, prev_week_id(week_id)), limit)


def trends_for_week(session: Session, week_id: str, limit: int = 5) -> dict:
    """Full 5-tab Trends payload for a week.

    has_prior=False means the prior ISO week has zero items — the whole card
    falls back to an empty state. In practice that only happens for synthetic
    empty-corpus runs since real-corpus active weeks always have a non-empty
    predecessor.
    """
    prev_id = prev_week_id(week_id)
    prev_total = week_item_total(session, prev_id)
    if prev_total == 0:
        return {"has_prior": False, "prev_week_id": prev_id}
    return {
        "has_prior": True,
        "prev_week_id": prev_id,
        "games_current": top_games_wow(session, week_id, lifecycle="existing", limit=limit),
        "games_upcoming": top_games_wow(session, week_id, lifecycle="upcoming", limit=limit),
        "genres": top_genres_wow(session, week_id, limit=limit),
        "platforms": top_platforms_wow(session, week_id, limit=limit),
        "live_service": top_live_service_wow(session, week_id, limit=limit),
        "events": top_events_wow(session, week_id, limit=limit),
    }


# ---------- Source drawer (Phase 3c.3) --------------------------------------
# Click a row on Hottest / Trends / Releases → drawer shows the articles that
# backed that entity in the week, with source pill + tldr + permalink. Reuses
# the same json_each + case-insensitive grouping that powers top_*_for_week.

_DRAWER_KINDS = {"game", "genre", "platform", "event", "cluster"}


def _drawer_source_kind(type_: str | None, url_or_handle: str | None, name: str | None) -> str:
    """Mirror the router's _build_sources_meta heuristic for a single row."""
    if (type_ or "").lower() == "youtube":
        return "youtube"
    if "reddit.com" in (url_or_handle or "") or (name or "").startswith("r/"):
        return "subreddit"
    return "outlet"


def _relative_when(published_at: datetime | None, now: datetime | None = None) -> str:
    """Human-readable freshness like '3 h ago' / '2 d ago' / '—'."""
    if not published_at:
        return "—"
    now = now or datetime.utcnow()
    if isinstance(published_at, str):
        try:
            published_at = datetime.fromisoformat(published_at)
        except ValueError:
            return str(published_at)[:16]
    delta = now - published_at
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min ago"
    hrs = mins // 60
    if hrs < 48:
        return f"{hrs} h ago"
    days = hrs // 24
    return f"{days} d ago"


def items_for_entity_in_week(
    session: Session,
    kind: str,
    value: str,
    week_id: str,
    limit: int = 25,
) -> list[dict]:
    """Articles backing a given entity (game/genre/platform/event) in an ISO week.

    Output is ordered newest-first. Each row carries enough fields for the
    drawer template: source pill + when + title + tldr + permalink + sentiment.
    """
    if kind not in _DRAWER_KINDS:
        raise ValueError(f"unknown drawer kind: {kind!r} (expected one of {_DRAWER_KINDS})")

    start, end = iso_week_bounds(week_id)

    if kind == "cluster":
        # `value` is the cluster_id as a string; fetch member_item_ids and
        # return their items. No week filter — the cluster row already lives
        # under one week_id, and we want all its members even if some have
        # boundary-spanning published_at.
        try:
            cluster_id = int(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"cluster drawer requires integer value, got {value!r}") from e
        row = session.exec(text(
            "SELECT member_item_ids FROM clusters WHERE id = :cid"
        ).bindparams(cid=cluster_id)).first()
        if not row or not row[0]:
            return []
        import json as _json
        try:
            member_ids = _json.loads(row[0])
        except (TypeError, ValueError):
            return []
        if not member_ids:
            return []
        placeholders = ",".join(str(int(x)) for x in member_ids[:limit])
        sql = f"""
            SELECT i.id, i.title, i.url, i.published_at,
                   e.tldr, e.sentiment_score, e.sentiment_summary, e.category,
                   s.name AS src_name, s.type AS src_type, s.url_or_handle AS src_url
            FROM items i
            LEFT JOIN enrichments e ON e.item_id = i.id
            JOIN sources s ON s.id = i.source_id
            WHERE i.id IN ({placeholders})
            ORDER BY i.published_at DESC
        """
        rows = session.exec(text(sql)).all()
        results: list[dict] = []
        for r in rows:
            results.append({
                "id": r[0],
                "title": r[1],
                "url": r[2],
                "published_at": r[3],
                "when_display": _relative_when(r[3]),
                "tldr": r[4],
                "sentiment_score": r[5],
                "sentiment_summary": r[6],
                "category": r[7],
                "source_name": r[8],
                "source_kind": _drawer_source_kind(r[9], r[10], r[8]),
            })
        return results

    if kind == "game":
        sql = """
            SELECT DISTINCT i.id, i.title, i.url, i.published_at,
                   e.tldr, e.sentiment_score, e.sentiment_summary, e.category,
                   s.name AS src_name, s.type AS src_type, s.url_or_handle AS src_url
            FROM items i
            JOIN enrichments e ON e.item_id = i.id
            JOIN sources s ON s.id = i.source_id
            JOIN json_each(e.entities, '$.games') je
                 ON e.status = 'ok' AND LOWER(TRIM(je.value)) = LOWER(:v)
            WHERE i.published_at >= :s AND i.published_at < :e
            ORDER BY i.published_at DESC
            LIMIT :lim
        """
    elif kind == "genre":
        sql = """
            SELECT DISTINCT i.id, i.title, i.url, i.published_at,
                   e.tldr, e.sentiment_score, e.sentiment_summary, e.category,
                   s.name AS src_name, s.type AS src_type, s.url_or_handle AS src_url
            FROM items i
            JOIN enrichments e ON e.item_id = i.id
            JOIN sources s ON s.id = i.source_id
            JOIN json_each(e.genres) je
                 ON e.status = 'ok' AND e.genres IS NOT NULL
                 AND LOWER(TRIM(je.value)) = LOWER(:v)
            WHERE i.published_at >= :s AND i.published_at < :e
            ORDER BY i.published_at DESC
            LIMIT :lim
        """
    elif kind == "platform":
        sql = """
            SELECT DISTINCT i.id, i.title, i.url, i.published_at,
                   e.tldr, e.sentiment_score, e.sentiment_summary, e.category,
                   s.name AS src_name, s.type AS src_type, s.url_or_handle AS src_url
            FROM items i
            JOIN enrichments e ON e.item_id = i.id
            JOIN sources s ON s.id = i.source_id
            JOIN json_each(e.platforms) je
                 ON e.status = 'ok' AND e.platforms IS NOT NULL
                 AND LOWER(TRIM(je.value)) = LOWER(:v)
            WHERE i.published_at >= :s AND i.published_at < :e
            ORDER BY i.published_at DESC
            LIMIT :lim
        """
    else:  # event — scalar column, case-insensitive match
        sql = """
            SELECT i.id, i.title, i.url, i.published_at,
                   e.tldr, e.sentiment_score, e.sentiment_summary, e.category,
                   s.name AS src_name, s.type AS src_type, s.url_or_handle AS src_url
            FROM items i
            JOIN enrichments e ON e.item_id = i.id
            JOIN sources s ON s.id = i.source_id
            WHERE i.published_at >= :s AND i.published_at < :e
              AND e.status = 'ok'
              AND e.event IS NOT NULL
              AND LOWER(TRIM(e.event)) = LOWER(:v)
            ORDER BY i.published_at DESC
            LIMIT :lim
        """

    rows = session.exec(text(sql).bindparams(s=start, e=end, v=value, lim=limit)).all()
    results: list[dict] = []
    for r in rows:
        results.append({
            "id": r[0],
            "title": r[1],
            "url": r[2],
            "published_at": r[3],
            "when_display": _relative_when(r[3]),
            "tldr": r[4],
            "sentiment_score": r[5],
            "sentiment_summary": r[6],
            "category": r[7],
            "source_name": r[8],
            "source_kind": _drawer_source_kind(r[9], r[10], r[8]),
        })
    return results


def upcoming_releases(session: Session, week_id: str, limit: int = 12) -> list[dict]:
    """Upcoming-tagged games mentioned in this week, ordered by release_date.

    Rows with a release_date sort first (ascending date); undated rows fall
    to the bottom ordered by mention count. Each row carries up to 5 source
    pills (sources that covered the game in this week).
    """
    start, end = iso_week_bounds(week_id)
    rows = session.exec(text("""
        SELECT g.name AS game, g.release_date, COUNT(DISTINCT i.id) AS n
        FROM items i
        JOIN enrichments e ON e.item_id = i.id
        JOIN json_each(e.entities, '$.games') je ON e.status = 'ok'
        JOIN games g ON LOWER(g.name) = LOWER(TRIM(je.value))
        WHERE i.published_at >= :s AND i.published_at < :e
          AND g.lifecycle = 'upcoming'
        GROUP BY g.name, g.release_date
        HAVING n > 0
        ORDER BY (g.release_date IS NULL), g.release_date ASC, n DESC
        LIMIT :lim
    """).bindparams(s=start, e=end, lim=limit)).all()

    results: list[dict] = []
    for name, release_date, n in rows:
        if not name:
            continue
        if not is_future_or_unknown(release_date):
            continue  # drop past-dated rows (delayed games tagged upcoming with stale dates)
        results.append({
            "name": name,
            "release_date": release_date,
            "display_date": format_release_date(release_date),
            "mention_count": n,
        })
    return results


def corpus_stats(session: Session) -> dict:
    """Corpus-wide counts for the sidebar bottom block (items / clusters / sources).

    Clusters count excludes the legacy week_id='all' bucket so the number
    matches what the read-out picker shows.
    """
    items = session.exec(text("SELECT COUNT(*) FROM items")).first()[0] or 0
    clusters = session.exec(text(
        "SELECT COUNT(*) FROM clusters WHERE week_id != 'all'"
    )).first()[0] or 0
    sources = session.exec(text("SELECT COUNT(*) FROM sources")).first()[0] or 0
    return {"items": int(items), "clusters": int(clusters), "sources": int(sources)}


def source_pills_for_clusters(
    session: Session,
    cluster_ids: list[int],
    limit_per_cluster: int = 5,
) -> dict[int, list[str]]:
    """Distinct source names per cluster, capped at limit_per_cluster.

    Used by the Biggest card to render source pills under each top-3 row.
    Returns {} for any cluster_id that has no member items.
    """
    if not cluster_ids:
        return {}
    import json as _json

    placeholders = ",".join(str(int(c)) for c in cluster_ids)
    rows = session.exec(text(
        f"SELECT id, member_item_ids FROM clusters WHERE id IN ({placeholders})"
    )).all()

    out: dict[int, list[str]] = {}
    for cid, mids_json in rows:
        try:
            mids = _json.loads(mids_json) if mids_json else []
        except (TypeError, ValueError):
            mids = []
        if not mids:
            out[int(cid)] = []
            continue
        id_ph = ",".join(str(int(x)) for x in mids)
        srows = session.exec(text(f"""
            SELECT DISTINCT s.name
            FROM items i JOIN sources s ON s.id = i.source_id
            WHERE i.id IN ({id_ph})
        """)).all()
        names = [r[0] for r in srows if r[0]]
        out[int(cid)] = names[:limit_per_cluster]
    return out
