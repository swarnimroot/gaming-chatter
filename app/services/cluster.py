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
from app.services.anthropic import label_cluster

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


def cluster_window_incremental(
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    week_id: str = "all",
) -> dict:
    """Incremental version of `cluster_window`: append new items to existing
    clusters (cosine ≥ threshold) and only create new clusters for items that
    don't fit. Existing cluster IDs + labels are preserved, so any synthesis_json
    referencing them stays valid.

    Phase 3c.11 — replaces destructive rebuild for pipeline runs.

    Returns counts:
      items_processed: candidate items in window not previously clustered
      items_appended_existing: of those, how many got attached to an existing cluster
      items_in_new_clusters: how many formed brand-new clusters
      items_orphaned: how many couldn't find any home (no group ≥ min_size)
      clusters_existing_touched: existing clusters that gained members
      clusters_new_created: brand-new cluster rows
      labels_called: Sonnet 4.6 calls (only for new clusters — old keep their labels)
      label_failed: subset of labels_called
    """
    started = datetime.utcnow()
    totals = {
        "items_processed": 0,
        "items_appended_existing": 0,
        "items_in_new_clusters": 0,
        "items_orphaned": 0,
        "clusters_existing_touched": 0,
        "clusters_new_created": 0,
        "labels_called": 0,
        "label_failed": 0,
    }

    with Session(engine) as session:
        run = RunLog(job_type="cluster", status="running", started_at=started)
        session.add(run)
        session.commit()
        session.refresh(run)

        # 1. Load existing clusters for this week. Their centroids are already
        # L2-normalized from prior runs of cluster_window (or this function).
        existing = session.exec(select(Cluster).where(Cluster.week_id == week_id)).all()
        already_clustered: set[int] = set()
        for c in existing:
            try:
                already_clustered.update(json.loads(c.member_item_ids or "[]"))
            except (TypeError, ValueError):
                pass

        # 2. Load candidate items in window (same query shape as cluster_window).
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
        all_rows = session.exec(stmt).all()

        # 3. Filter to NEW items only.
        new_rows = [(e, it) for (e, it) in all_rows if it.id not in already_clustered]
        totals["items_processed"] = len(new_rows)

        if not new_rows:
            run.status = "ok"
            run.items_processed = 0
            run.completed_at = datetime.utcnow()
            session.add(run)
            session.commit()
            log.info("cluster_window_incremental: no new items in week=%s; nothing to do", week_id)
            return totals

        new_vectors = np.vstack([
            np.frombuffer(e.embedding, dtype=np.float32) for (e, _) in new_rows
        ]).astype(np.float32)
        new_normed = _normalize(new_vectors)

        # 4. Match each new item to its best existing cluster (if any clear above threshold).
        appended_per_cluster: dict[int, list[int]] = defaultdict(list)
        orphan_indices: list[int] = []
        if existing:
            existing_centroids = np.vstack([
                np.frombuffer(c.centroid, dtype=np.float32) for c in existing
            ]).astype(np.float32)
            # Centroids stored normalized; new_normed is normalized → dot product = cosine.
            sim_to_existing = new_normed @ existing_centroids.T
            best_idx = sim_to_existing.argmax(axis=1)
            best_sim = sim_to_existing.max(axis=1)
            for i, (j, s) in enumerate(zip(best_idx, best_sim)):
                if float(s) >= CLUSTER_THRESHOLD:
                    appended_per_cluster[int(existing[int(j)].id)].append(i)
                else:
                    orphan_indices.append(i)
        else:
            orphan_indices = list(range(len(new_rows)))

        # 5. Append new items into matched existing clusters.
        scoring_now = datetime.utcnow()
        existing_by_id = {c.id: c for c in existing}
        for cluster_id, idx_list in appended_per_cluster.items():
            c = existing_by_id[cluster_id]
            try:
                old_members = json.loads(c.member_item_ids or "[]")
            except (TypeError, ValueError):
                old_members = []
            new_ids = [int(new_rows[i][1].id) for i in idx_list]
            updated_members = list(old_members) + new_ids

            # Re-query distinct source_ids across the full updated member list.
            src_rows = session.exec(
                select(Item.source_id).where(col(Item.id).in_(updated_members))
            ).all()
            source_count = len(set(src_rows))

            # Latest published_at across old (already on cluster) + new members.
            candidate_dates = [c.latest_published_at] if c.latest_published_at else []
            for i in idx_list:
                pa = new_rows[i][1].published_at
                if pa is not None:
                    candidate_dates.append(pa)
            latest = max(candidate_dates) if candidate_dates else None

            # Weighted-mean centroid update. The stored centroid is L2-normalized,
            # so this is an approximation of the true sample mean — but it's stable
            # and the cosine threshold (0.85) gives plenty of margin against drift.
            old_count = c.member_count
            new_count = len(idx_list)
            total_count = old_count + new_count
            old_centroid = np.frombuffer(c.centroid, dtype=np.float32)
            new_sum = new_normed[idx_list].sum(axis=0)
            mixed = (old_centroid * old_count + new_sum) / total_count
            cnorm = float(np.linalg.norm(mixed))
            if cnorm > 0:
                mixed = mixed / cnorm

            if latest is not None:
                days_since = max(0.0, (scoring_now - latest).total_seconds() / 86400.0)
            else:
                days_since = 0.0
            score = source_count * total_count / (1.0 + days_since)

            c.member_item_ids = json.dumps(updated_members)
            c.member_count = total_count
            c.source_count = source_count
            c.latest_published_at = latest
            c.centroid = mixed.astype(np.float32).tobytes()
            c.score = score
            # NOTE: label NOT updated — existing cluster identity preserved.
            session.add(c)

            totals["items_appended_existing"] += new_count
        totals["clusters_existing_touched"] = len(appended_per_cluster)

        # 6. Form brand-new clusters from orphan items.
        if orphan_indices:
            orphan_normed = new_normed[orphan_indices]
            sim_orphan = orphan_normed @ orphan_normed.T
            components = _connected_components(sim_orphan, CLUSTER_THRESHOLD)
            new_groups = [grp for grp in components if len(grp) >= CLUSTER_MIN_SIZE]
            new_groups.sort(key=len, reverse=True)

            for rank, group in enumerate(new_groups, start=1):
                full_idx = [orphan_indices[i] for i in group]
                sample = full_idx[:CLUSTER_LABEL_SAMPLE]
                titles = [new_rows[i][1].title for i in sample]
                tldrs = [new_rows[i][0].tldr or "" for i in sample]
                try:
                    label = label_cluster(titles, tldrs)
                    totals["labels_called"] += 1
                    log.info("new cluster %d/%d (size=%d): %s", rank, len(new_groups), len(group), label)
                except Exception as e:  # noqa: BLE001
                    label = f"(unlabelled cluster of {len(group)} items)"
                    totals["label_failed"] += 1
                    log.warning("new cluster %d/%d label_cluster failed: %s", rank, len(new_groups), e)

                centroid = new_normed[full_idx].mean(axis=0)
                cnorm = float(np.linalg.norm(centroid))
                if cnorm > 0:
                    centroid = centroid / cnorm

                member_items = [new_rows[i][1] for i in full_idx]
                member_ids = [int(it.id) for it in member_items]
                source_count = len({it.source_id for it in member_items})
                published_dates = [it.published_at for it in member_items if it.published_at is not None]
                latest = max(published_dates) if published_dates else None
                if latest is not None:
                    days_since = max(0.0, (scoring_now - latest).total_seconds() / 86400.0)
                else:
                    days_since = 0.0
                score = source_count * len(member_ids) / (1.0 + days_since)

                session.add(Cluster(
                    week_id=week_id,
                    label=label,
                    centroid=centroid.astype(np.float32).tobytes(),
                    member_item_ids=json.dumps(member_ids),
                    member_count=len(member_ids),
                    source_count=source_count,
                    latest_published_at=latest,
                    score=score,
                ))
                totals["clusters_new_created"] += 1
                totals["items_in_new_clusters"] += len(group)

            in_groups = sum(len(g) for g in new_groups)
            totals["items_orphaned"] = len(orphan_indices) - in_groups

        session.commit()

        run.status = "ok"
        run.items_processed = totals["items_processed"]
        run.completed_at = datetime.utcnow()
        if totals["label_failed"]:
            run.error = f"{totals['label_failed']} label calls failed"
        session.add(run)
        session.commit()

    log.info("cluster_window_incremental done: %s", totals)
    return totals
