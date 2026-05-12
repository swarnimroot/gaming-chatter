"""Exploratory: try several similarity thresholds, print the resulting groups.

Loads every 'ok' enrichment with an embedding, builds a cosine-similarity matrix,
and forms clusters via connected-components on a thresholded graph. For each
threshold we print summary stats plus the largest groups, so we can pick the
threshold that produces editorially-cohesive clusters.

No DB writes. Run: python scripts/explore_clustering.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db.models import Enrichment, Item, Source  # noqa: E402
from app.db.session import engine  # noqa: E402

THRESHOLDS = [0.78, 0.80, 0.82, 0.85, 0.88]
MIN_CLUSTER_SIZE = 2
TOP_N_LARGEST = 10
TITLES_PER_GROUP = 5


def load_corpus():
    """Return (vectors fp32 N x D, items list aligned with vectors)."""
    with Session(engine) as session:
        rows = session.exec(
            select(Enrichment, Item, Source)
            .join(Item, Item.id == Enrichment.item_id)
            .join(Source, Source.id == Item.source_id)
            .where(Enrichment.status == "ok")
            .where(Enrichment.embedding.is_not(None))
        ).all()

    vectors = []
    meta = []
    for enr, item, source in rows:
        vec = np.frombuffer(enr.embedding, dtype=np.float32)
        vectors.append(vec)
        meta.append({
            "item_id": item.id,
            "title": item.title,
            "source": source.name,
            "tldr": enr.tldr or "",
        })
    arr = np.vstack(vectors).astype(np.float32)
    return arr, meta


def normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def cluster_connected_components(sim: np.ndarray, threshold: float) -> list[list[int]]:
    """Union-find over the thresholded similarity graph."""
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

    # iterate upper triangle only
    iu = np.triu_indices(n, k=1)
    mask = sim[iu] >= threshold
    pairs_i = iu[0][mask]
    pairs_j = iu[1][mask]
    for i, j in zip(pairs_i, pairs_j):
        union(int(i), int(j))

    groups = defaultdict(list)
    for idx in range(n):
        groups[find(idx)].append(idx)
    return list(groups.values())


def report(threshold: float, clusters: list[list[int]], meta: list[dict], n_total: int) -> None:
    multi = [c for c in clusters if len(c) >= MIN_CLUSTER_SIZE]
    multi.sort(key=len, reverse=True)
    items_in_multi = sum(len(c) for c in multi)
    pct = 100.0 * items_in_multi / n_total if n_total else 0.0

    print(f"\n{'=' * 78}")
    print(f"threshold={threshold:.2f}   min_size={MIN_CLUSTER_SIZE}")
    print(f"{'=' * 78}")
    print(f"  total items:           {n_total}")
    print(f"  multi-item groups:     {len(multi)}")
    print(f"  items in such groups:  {items_in_multi}  ({pct:.1f}% of corpus)")
    print(f"  singletons:            {n_total - items_in_multi}")
    if multi:
        print(f"  largest group size:    {len(multi[0])}")
        sizes = [len(c) for c in multi]
        print(f"  size distribution:     mean={np.mean(sizes):.1f}  median={int(np.median(sizes))}")
    print()
    print(f"  Top {min(TOP_N_LARGEST, len(multi))} largest groups:")
    print(f"  {'-' * 74}")
    for rank, cluster in enumerate(multi[:TOP_N_LARGEST], start=1):
        sources = sorted({meta[i]["source"] for i in cluster})
        print(f"  #{rank}  size={len(cluster)}  sources={len(sources)}")
        for i in cluster[:TITLES_PER_GROUP]:
            m = meta[i]
            title = m["title"][:90]
            print(f"      [{m['source'][:25]:25s}] {title}")
        if len(cluster) > TITLES_PER_GROUP:
            print(f"      ... and {len(cluster) - TITLES_PER_GROUP} more")
        print()


def main() -> int:
    print("loading corpus...", flush=True)
    vectors, meta = load_corpus()
    n = len(meta)
    print(f"loaded {n} items with {vectors.shape[1]}-dim embeddings")

    print("normalizing + computing similarity matrix...", flush=True)
    normed = normalize(vectors)
    sim = normed @ normed.T

    for threshold in THRESHOLDS:
        clusters = cluster_connected_components(sim, threshold)
        report(threshold, clusters, meta, n)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
