"""Dashboard payload assembly for the /reports weekly read-out.

Extracted from `app.routers.reports` in Phase 3c.35 so the synthesis hook and
the rebuild script can call the SAME builder the router uses — without the
router importing from a service module having to do a backward import.

Public surface:
  - `_empty_cards()` — base card-shape dict
  - `_load_synthesis(session, week_id)` — read weekly_reports.synthesis_json
  - `_apply_synthesis(session, cards, synth)` — overlay synthesis into cards
  - `_filter_cards_by_region(session, cards, region)` — drop entries by region
  - `_build_week_payload(session, week_id, region="")` — full builder
  - `REGION_ALLOWED` — the three-region set the filter accepts

Behavior preserved verbatim — these were lifted from reports.py with only the
module-private leading underscore retained for backwards compatibility (the
router re-exports them under the same names).
"""
from __future__ import annotations

import json

from sqlalchemy import text as _sqltext
from sqlmodel import Session

from app.services import reports as report_q

# Mirrors clusters.py / dashboard.py constants — the 3-region set we filter on.
REGION_ALLOWED = {"americas", "europe", "asia"}


# ---------- Empty-state card shape ------------------------------------------

def _empty_cards() -> dict:
    """Default per-week card shape — used both for the empty-corpus fallback
    and as the base into which `_apply_synthesis` writes real data."""
    return {
        "biggest": [],
        "market_momentum": [],
        "community": {"narrative": None, "heated_about": [], "celebrating": []},
        "risks": [],
        "esports": [],
        "drama": [],
        "watch": [],
    }


def _load_synthesis(session: Session, week_id: str) -> dict | None:
    """Load the weekly_reports.synthesis_json row for the week, or None."""
    try:
        week_start, _ = report_q.iso_week_bounds(week_id)
    except (ValueError, IndexError):
        return None
    row = session.exec(_sqltext(
        "SELECT synthesis_json, synthesis_model, synthesis_generated_at "
        "FROM weekly_reports WHERE week_start = :s"
    ).bindparams(s=week_start)).first()
    if not row or not row[0]:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return {
        "data": payload,
        "model": row[1],
        "generated_at": row[2],
    }


def _apply_synthesis(session: Session, cards: dict, synth: dict) -> None:
    """Overlay synthesis JSON onto the per-week card dict in place.

    Writes directly to first-class keys (no `*_synth` stash — that was the
    3c.4 transition shape). Biggest rows get source pills derived from
    cluster members so the template can render them without a second query.
    """
    data = synth["data"]

    # Biggest stories — plural top-3, each with source pills + mention count
    # derived from cluster members so the template doesn't need a second query.
    if data.get("biggest"):
        cluster_ids = [int(b["cluster_id"]) for b in data["biggest"]]
        pills = report_q.source_pills_for_clusters(session, cluster_ids)
        ids_csv = ",".join(str(cid) for cid in cluster_ids)
        member_rows = session.exec(_sqltext(
            f"SELECT id, member_item_ids FROM clusters WHERE id IN ({ids_csv})"
        )).all()
        counts: dict[int, int] = {}
        for cid, mids_json in member_rows:
            try:
                counts[int(cid)] = len(json.loads(mids_json)) if mids_json else 0
            except (TypeError, ValueError):
                counts[int(cid)] = 0
        cards["biggest"] = [
            {
                "cluster_id": b["cluster_id"],
                "title": b["title"],
                "dek": b["dek"],
                "sources": pills.get(int(b["cluster_id"]), []),
                "mention_count": counts.get(int(b["cluster_id"]), 0),
            }
            for b in data["biggest"]
        ]

    # Market momentum — row list (acquisitions / funds / platform-policy /
    # structural / people-moves).
    cards["market_momentum"] = [
        {
            "cluster_id": m["cluster_id"],
            "title": m["title"],
            "note": m["note"],
            "category": m["category"],
        }
        for m in data.get("market_momentum", [])
    ]

    # Community sentiment — narrative + heated/celebrating clusters.
    cs = data.get("community_sentiment")
    if cs:
        cards["community"] = {
            "narrative": cs.get("narrative"),
            "heated_about": [
                {"cluster_id": c["cluster_id"], "title": c["title"], "note": c["note"]}
                for c in cs.get("heated_about", [])
            ],
            "celebrating": [
                {"cluster_id": c["cluster_id"], "title": c["title"], "note": c["note"]}
                for c in cs.get("celebrating", [])
            ],
        }

    # Risks — severity bar + title + level badge + note; trend chip dropped.
    cards["risks"] = [
        {
            "cluster_id": r["cluster_id"],
            "title": r["title"],
            "level": r["severity"],
            "note": r["note"],
        }
        for r in data.get("risks", [])
    ]

    # Esports — row list of cluster-anchored items.
    cards["esports"] = [
        {
            "cluster_id": e["cluster_id"],
            "title": e["title"],
            "note": e["note"],
        }
        for e in data.get("esports", [])
    ]

    # Drama — narrow scope (exec/PR + studio feuds).
    cards["drama"] = [
        {
            "cluster_id": d["cluster_id"],
            "title": d["title"],
            "severity": d["severity"],
            "recap": d["recap"],
        }
        for d in data.get("drama", [])
    ]

    # Watch next week.
    cards["watch"] = [
        {
            "day": w["day"],
            "item": w["item"],
            "cluster_id": w.get("cluster_id"),
            "category": w.get("category"),
        }
        for w in data.get("watch", [])
    ]

    # Hottest games — overlay synthesis 1-line reasons by game-name match.
    if data.get("hottest_reasons"):
        reason_by_name = {r["game_name"].lower(): r["reason"] for r in data["hottest_reasons"]}
        for bucket in ("all", "current", "upcoming"):
            for game in cards["hottest"][bucket]:
                game["reason"] = reason_by_name.get(game["name"].lower())

    # Releases — overlay synthesis 1-line notes by game-name match.
    if data.get("release_notes"):
        note_by_name = {r["game_name"].lower(): r["note"] for r in data["release_notes"]}
        for r in cards["releases"]:
            r["note"] = note_by_name.get(r["name"].lower())

    cards["synthesis_meta"] = {
        "model": synth["model"],
        "generated_at": synth["generated_at"],
    }


def _filter_cards_by_region(session: Session, cards: dict, region: str) -> None:
    """Drop entries from every cluster-keyed card list whose cluster doesn't
    carry the requested region tag. Phase 3c.16.

    Collects every cluster_id referenced by synthesis_json in one pass, calls
    `cluster_regions()` once, then walks each card list in place. Cards
    without cluster_id linkage (hottest / releases / trends) are untouched —
    the template signals 'Not region-tagged' via the `region_active` flag.

    Special-cased entries:
      - community.narrative: whole-corpus prose; cleared on regional tabs.
      - watch[] without `cluster_id`: corpus-wide editorial; dropped.
    """
    from app.services.sections import cluster_regions

    cluster_ids: set[int] = set()
    for b in cards.get("biggest", []) or []:
        try:
            cluster_ids.add(int(b["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for m in cards.get("market_momentum", []) or []:
        try:
            cluster_ids.add(int(m["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for r in cards.get("risks", []) or []:
        try:
            cluster_ids.add(int(r["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for d in cards.get("drama", []) or []:
        try:
            cluster_ids.add(int(d["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for e in cards.get("esports", []) or []:
        try:
            cluster_ids.add(int(e["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    co = cards.get("community") or {}
    for c in co.get("heated_about", []) or []:
        try:
            cluster_ids.add(int(c["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for c in co.get("celebrating", []) or []:
        try:
            cluster_ids.add(int(c["cluster_id"]))
        except (KeyError, TypeError, ValueError):
            pass
    for w in cards.get("watch", []) or []:
        if w.get("cluster_id") is not None:
            try:
                cluster_ids.add(int(w["cluster_id"]))
            except (TypeError, ValueError):
                pass

    region_map = cluster_regions(session, list(cluster_ids)) if cluster_ids else {}

    def keep(cid) -> bool:
        try:
            return region in region_map.get(int(cid), set())
        except (TypeError, ValueError):
            return False

    cards["biggest"] = [b for b in cards.get("biggest", []) if keep(b.get("cluster_id"))]
    cards["market_momentum"] = [m for m in cards.get("market_momentum", []) if keep(m.get("cluster_id"))]
    cards["risks"] = [r for r in cards.get("risks", []) if keep(r.get("cluster_id"))]
    cards["drama"] = [d for d in cards.get("drama", []) if keep(d.get("cluster_id"))]
    cards["esports"] = [e for e in cards.get("esports", []) if keep(e.get("cluster_id"))]

    cards["community"] = {
        "narrative": None,  # whole-corpus prose — drop on regional tabs
        "heated_about": [c for c in co.get("heated_about", []) if keep(c.get("cluster_id"))],
        "celebrating": [c for c in co.get("celebrating", []) if keep(c.get("cluster_id"))],
    }

    # watch[] — drop entries without cluster_id (corpus-wide narrative),
    # filter the rest by region.
    cards["watch"] = [
        w for w in cards.get("watch", [])
        if w.get("cluster_id") is not None and keep(w.get("cluster_id"))
    ]


def _build_week_payload(session: Session, week_id: str, region: str = "") -> dict:
    """Assemble the full per-week card payload.

    Phase 3c.16: when `region` is one of {'americas','europe','asia'}, every
    cluster-keyed card list is filtered against `cluster_regions(...)` for the
    cluster_ids referenced by synthesis_json. Non-cluster cards (Hottest /
    Releases / Trends) are passed through unchanged — the template shows a
    'Not region-tagged' chip in their headers when `region_active` is true.
    """
    label, rng = report_q.week_label_and_range(week_id)
    stats = report_q.week_stats(session, week_id)
    hottest_all = report_q.top_games_for_week(session, week_id, limit=5)
    hottest_current = report_q.top_games_for_week(session, week_id, limit=5, lifecycle="existing")
    hottest_upcoming = report_q.top_games_for_week(session, week_id, limit=5, lifecycle="upcoming")
    releases = report_q.upcoming_releases(session, week_id, limit=10)
    trends = report_q.trends_for_week(session, week_id, limit=5)

    cards = _empty_cards()
    cards["hottest"] = {
        "all": hottest_all,
        "current": hottest_current,
        "upcoming": hottest_upcoming,
    }
    cards["releases"] = releases
    cards["trends"] = trends

    synth = _load_synthesis(session, week_id)
    if synth is not None:
        _apply_synthesis(session, cards, synth)
        if region in REGION_ALLOWED:
            _filter_cards_by_region(session, cards, region)

    return {
        "label": label,
        "range": rng,
        "stats": {"stories": stats["stories"], "sources": stats["sources"]},
        "cards": cards,
    }


# ---------- Phase 3c.35 — cached-payload read/write -------------------------

def load_cached_payload(session: Session, week_id: str) -> dict | None:
    """Return the cached `_build_week_payload(region='')` dict for a week, or
    None if no row / no cache. Performs a single SELECT + json.loads."""
    try:
        week_start, _ = report_q.iso_week_bounds(week_id)
    except (ValueError, IndexError):
        return None
    row = session.exec(_sqltext(
        "SELECT dashboard_payload_json FROM weekly_reports WHERE week_start = :s"
    ).bindparams(s=week_start)).first()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None


def save_cached_payload(session: Session, week_id: str, payload: dict) -> None:
    """Persist the unfiltered (region='') dashboard payload to
    weekly_reports.dashboard_payload_json. Caller commits.

    Uses `default=str` so datetime values (e.g. synthesis_meta.generated_at)
    serialize as ISO strings — the template only renders these, never does
    datetime arithmetic on them, so str round-tripping is safe."""
    try:
        week_start, _ = report_q.iso_week_bounds(week_id)
    except (ValueError, IndexError):
        return
    blob = json.dumps(payload, default=str)
    session.exec(_sqltext(
        "UPDATE weekly_reports SET dashboard_payload_json = :p WHERE week_start = :s"
    ).bindparams(p=blob, s=week_start))


def compute_and_cache_payload(session: Session, week_id: str) -> dict:
    """Build the region='' payload and persist it. Returns the payload.

    Idempotent: overwrites any prior cached value. Caller commits."""
    payload = _build_week_payload(session, week_id, region="")
    save_cached_payload(session, week_id, payload)
    return payload
