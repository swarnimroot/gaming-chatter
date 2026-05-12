"""Clustering: cosine similarity on TLDR embeddings, persisted to clusters table.

Algorithm: connected-components on a thresholded similarity graph.
Threshold + min-size locked in DECISIONS.md (2026-05-07).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

import numpy as np
from sqlmodel import Session, col, delete, select

from app.config import CLUSTER_LABEL_SAMPLE, CLUSTER_MIN_SIZE, CLUSTER_THRESHOLD
from app.db.models import Cluster, Enrichment, Item, RunLog
from app.db.session import engine
from app.services.ollama import label_cluster

log = logging.getLogger(__name__)


def _normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def _connected_components(sim: np.ndarray, threshold: float) -> list[list[int]]:
    n = sim.shape[0]
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    iu = np.triu_indices(n, k=1)
    mask = sim[iu] >= threshold
    for i, j in zip(iu[0][mask], iu[1][mask]):
        union(int(i), int(j))

    groups = defaultdict(list)
    for idx in range(n):
        groups[find(idx)].append(idx)
    return list(groups.values())


def cluster_window(
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    week_id: str = "all",
) -> dict:
    """Cluster ok-enrichments whose item.published_at falls within [start, end).

    Replaces any existing rows for `week_id` (idempotent re-runs).
    Returns a counts dict.
    """
    started = datetime.utcnow()
    totals = {"items": 0, "groups": 0, "labelled": 0, "label_failed": 0}

    with Session(engine) as session:
        run = RunLog(job_type="cluster", status="running", started_at=started)
        session.add(run)
        session.commit()
        session.refresh(run)

        # Wipe any prior clusters for this week_id so re-runs replace cleanly.
        session.exec(delete(Cluster).where(Cluster.week_id == week_id))
        session.commit()

        stmt = (
            select(Enrichment, Item)
            .join(Item, Item.id == Enrichment.item_id)
            .where(Enrichment.status == "ok")
            .where(col(Enrichment.embedding).is_not(None))
        )
        if start is not None:
            stmt = stmt.where(Item.published_at >= start)
        if end is not None:
            stmt = stmt.where(Item.published_at < end)
        rows = session.exec(stmt).all()
        totals["items"] = len(rows)
        if not rows:
            run.status = "ok"
            run.items_processed = 0
            run.completed_at = datetime.utcnow()
            session.add(run)
            session.commit()
            log.info("cluster_window: no rows for window %s..%s; skipped", start, end)
            return totals

        vectors = np.vstack([
            np.frombuffer(enr.embedding, dtype=np.float32) for enr, _ in rows
        ]).astype(np.float32)
        normed = _normalize(vectors)
        sim = normed @ normed.T
        components = _connected_components(sim, CLUSTER_THRESHOLD)
        groups = [c for c in components if len(c) >= CLUSTER_MIN_SIZE]
        groups.sort(key=len, reverse=True)
        totals["groups"] = len(groups)

        scoring_now = datetime.utcnow()
        for rank, group_indices in enumerate(groups, start=1):
            sample = group_indices[:CLUSTER_LABEL_SAMPLE]
            titles = [rows[i][1].title for i in sample]
            tldrs = [rows[i][0].tldr or "" for i in sample]
            try:
                label = label_cluster(titles, tldrs)
                totals["labelled"] += 1
                log.info("cluster %d/%d (size=%d): %s", rank, len(groups), len(group_indices), label)
            except Exception as e:  # noqa: BLE001
                label = f"(unlabelled cluster of {len(group_indices)} items)"
                totals["label_failed"] += 1
                log.warning("cluster %d/%d (size=%d) label_cluster failed: %s", rank, len(groups), len(group_indices), e)

            centroid = normed[group_indices].mean(axis=0)
            cnorm = float(np.linalg.norm(centroid))
            if cnorm > 0:
                centroid = centroid / cnorm
            centroid_bytes = centroid.astype(np.float32).tobytes()

            member_items = [rows[i][1] for i in group_indices]
            member_ids = [int(it.id) for it in member_items]
            source_count = len({it.source_id for it in member_items})
            published_dates = [it.published_at for it in member_items if it.published_at is not None]
            latest_published_at = max(published_dates) if published_dates else None
            if latest_published_at is not None:
                days_since = max(0.0, (scoring_now - latest_published_at).total_seconds() / 86400.0)
            else:
                days_since = 0.0
            score = source_count * len(member_ids) / (1.0 + days_since)

            session.add(Cluster(
                week_id=week_id,
                label=label,
                centroid=centroid_bytes,
                member_item_ids=json.dumps(member_ids),
                member_count=len(member_ids),
                source_count=source_count,
                latest_published_at=latest_published_at,
                score=score,
            ))
            session.commit()

        run.status = "ok"
        run.items_processed = totals["groups"]
        run.completed_at = datetime.utcnow()
        if totals["label_failed"]:
            run.error = f"{totals['label_failed']} label calls failed"
        session.add(run)
        session.commit()

    log.info("cluster_window done: %s", totals)
    return totals
