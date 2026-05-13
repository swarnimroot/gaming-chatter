"""Shared shell chrome — nav items + path-aware is_active flag.

Phase 3c.7: routes that render the `.gc-shell` layout (Home/`/`, Dashboard,
Clusters, Sources) all need the same sidebar nav. Centralizing the nav
definition here keeps a single source of truth.
"""
from __future__ import annotations

NAV_ITEMS_BASE = [
    {"id": "weekly",    "label": "Weekly read-out", "icon": "newspaper", "href": "/"},
    {"id": "dashboard", "label": "Dashboard",       "icon": "gauge",     "href": "/dashboard"},
    {"id": "clusters",  "label": "Clusters",        "icon": "shapes",    "href": "/clusters"},
    {"id": "sources",   "label": "Sources",         "icon": "rss",       "href": "/sources"},
]


def nav_items_for(active_id: str) -> list[dict]:
    """Return the nav list with is_active set on the matching item."""
    return [
        {**n, "is_active": n["id"] == active_id}
        for n in NAV_ITEMS_BASE
    ]
