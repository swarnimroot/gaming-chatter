"""Editorial-section overlay helpers — shared between /clusters and /stories.

Phase 3c.11: extracted from `app/routers/clusters.py` so the Stories page can
also filter by editorial section.

A cluster's "sections" are all the editorial cards it landed in on the weekly
read-out (Biggest / MM / Risks / Community / Esports / Drama / Watch). A
cluster cited from multiple sections gets a chip for EACH (Phase 3c.12 — was
"primary section only" in 3c.10/3c.11). Sections are returned in priority
order: biggest > risks > drama > MM > community > esports > watch, so the
"primary" chip is always first.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional

from sqlalchemy import text as _sqltext
from sqlmodel import Session

from app.services.reports import iso_week_bounds


# Section IDs used in URLs (?section=...) + the human-readable labels for
# dropdowns. The order here is also the priority order for tagging
# (first-wins on conflicts).
SECTION_OPTIONS = [
    ("",                "All sections"),
    ("biggest",         "Biggest"),
    ("market_momentum", "Market momentum"),
    ("risks",           "Risks"),
    ("community",       "Community sentiment"),
    ("esports",         "Esports & streaming"),
    ("drama",           "Controversy"),
    ("watch",           "Watch next week"),
    ("not_surfaced",    "Not surfaced"),
]


def load_synthesis_section_map(session: Session, week_ids: list[str]) -> dict[int, list[dict]]:
    """Map cluster_id → list of {section, label, week_id} entries for every
    section the cluster appears in. Multiple chips per cluster are kept and
    ordered by priority (biggest > risks > drama > MM > community > esports >
    watch) so the first chip is always the most editorially weighty.

    Clusters never referenced by any synthesis are absent (= "not surfaced").
    """
    if not week_ids:
        return {}
    out: dict[int, list[dict]] = defaultdict(list)

    def add(cid: int, payload: dict) -> None:
        # Don't duplicate the exact same (section, label) for the same cluster.
        for existing in out[cid]:
            if existing["section"] == payload["section"] and existing["label"] == payload["label"]:
                return
        out[cid].append(payload)

    for wid in week_ids:
        try:
            week_start, _ = iso_week_bounds(wid)
        except (ValueError, IndexError):
            continue
        row = session.exec(_sqltext(
            "SELECT synthesis_json FROM weekly_reports WHERE week_start = :s"
        ).bindparams(s=week_start)).first()
        if not row or not row[0]:
            continue
        try:
            payload = json.loads(row[0])
        except (TypeError, ValueError):
            continue

        # Priority order (highest first). All entries are kept; first added
        # ends up first in the per-cluster list so the primary chip renders
        # leftmost.
        for idx, b in enumerate(payload.get("biggest", []) or [], start=1):
            try:
                cid = int(b["cluster_id"])
            except (KeyError, TypeError, ValueError):
                continue
            add(cid, {"section": "biggest", "label": f"Biggest #{idx}", "week_id": wid})

        for r in payload.get("risks", []) or []:
            try:
                cid = int(r["cluster_id"])
            except (KeyError, TypeError, ValueError):
                continue
            sev = r.get("severity", "")
            add(cid, {"section": "risks",
                      "label": f"Risk · {sev}" if sev else "Risk",
                      "week_id": wid})

        for d in payload.get("drama", []) or []:
            try:
                cid = int(d["cluster_id"])
            except (KeyError, TypeError, ValueError):
                continue
            sev = d.get("severity", "")
            add(cid, {"section": "drama",
                      "label": f"Controversy · {sev}" if sev else "Controversy",
                      "week_id": wid})

        for m in payload.get("market_momentum", []) or []:
            try:
                cid = int(m["cluster_id"])
            except (KeyError, TypeError, ValueError):
                continue
            cat = m.get("category", "")
            add(cid, {"section": "market_momentum",
                      "label": f"MM · {cat}" if cat else "Market momentum",
                      "week_id": wid})

        cs = payload.get("community_sentiment") or {}
        for c in (cs.get("heated_about") or []):
            try:
                cid = int(c["cluster_id"])
            except (KeyError, TypeError, ValueError):
                continue
            add(cid, {"section": "community", "label": "Community · heated", "week_id": wid})
        for c in (cs.get("celebrating") or []):
            try:
                cid = int(c["cluster_id"])
            except (KeyError, TypeError, ValueError):
                continue
            add(cid, {"section": "community", "label": "Community · celebrating", "week_id": wid})

        for e in payload.get("esports", []) or []:
            try:
                cid = int(e["cluster_id"])
            except (KeyError, TypeError, ValueError):
                continue
            add(cid, {"section": "esports", "label": "Esports", "week_id": wid})

        for w in payload.get("watch", []) or []:
            cid_raw = w.get("cluster_id") if isinstance(w, dict) else None
            if cid_raw is None:
                continue
            try:
                cid = int(cid_raw)
            except (TypeError, ValueError):
                continue
            day = w.get("day", "")
            add(cid, {"section": "watch",
                      "label": f"Watch · {day}" if day else "Watch next week",
                      "week_id": wid})

    return dict(out)


def section_label_for(section: str) -> str:
    """Human-readable label for a section ID (used in header meta lines)."""
    return next((lbl for val, lbl in SECTION_OPTIONS if val == section), "")


def items_in_section(
    session: Session,
    week_ids: list[str],
    section: str,
) -> Optional[set[int]]:
    """Return item IDs whose cluster belongs to the given editorial section.

    `week_ids`: scope the lookup (pass available weeks).
    `section`: section key from SECTION_OPTIONS.

    Returns:
      - None when `section` is empty (= "no filter, show everything")
      - a set of int item IDs that match (may be empty)

    Special-cased: `section == 'not_surfaced'` returns members of clusters in
    `week_ids` that are NOT in any editorial section.
    """
    if not section:
        return None

    section_map = load_synthesis_section_map(session, week_ids)

    if section == "not_surfaced":
        # Members of clusters in scope that aren't tagged in any section.
        if not week_ids:
            return set()
        wid_placeholders = ",".join(f"'{w}'" for w in week_ids if "'" not in w)
        if not wid_placeholders:
            return set()
        rows = session.exec(_sqltext(
            f"SELECT id, member_item_ids FROM clusters WHERE week_id IN ({wid_placeholders})"
        )).all()
        out: set[int] = set()
        for cid, mids_json in rows:
            if section_map.get(int(cid)):
                continue  # surfaced in at least one section — skip
            try:
                ids = json.loads(mids_json or "[]")
                out.update(int(i) for i in ids)
            except (TypeError, ValueError):
                pass
        return out

    # Specific section: collect clusters whose section list contains the target.
    matching_cids = [
        cid for cid, sections_list in section_map.items()
        if any(s["section"] == section for s in sections_list)
    ]
    if not matching_cids:
        return set()
    placeholders = ",".join(str(int(c)) for c in matching_cids)
    rows = session.exec(_sqltext(
        f"SELECT member_item_ids FROM clusters WHERE id IN ({placeholders})"
    )).all()
    out = set()
    for (mids_json,) in rows:
        try:
            ids = json.loads(mids_json or "[]")
            out.update(int(i) for i in ids)
        except (TypeError, ValueError):
            pass
    return out
