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
