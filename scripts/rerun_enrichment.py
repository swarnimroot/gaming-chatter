"""Re-run enrichment on existing items with force=True.

Used for Phase 3c.0 backlog re-enrichment (extends prompt with
genres/platforms/event taxonomy). Does NOT re-embed.

Usage:
    python scripts/rerun_enrichment.py --limit 10 --sample
    python scripts/rerun_enrichment.py            # all items, no diff
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)

from sqlmodel import Session, col, select  # noqa: E402

from app.config import ENRICH_BODY_CHAR_MIN  # noqa: E402
from app.db.models import Enrichment, Item  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.services import enrich as enrich_module  # noqa: E402
from app.services.enrich import _body_for_enrichment, _persist_ok, enrich_pending  # noqa: E402
from app.services.ollama import enrich_item as ollama_enrich_item  # noqa: E402

log = logging.getLogger("rerun")

SNAPSHOT_FIELDS = (
    "tldr", "entities", "category", "sentiment_score", "sentiment_summary",
    "genres", "platforms", "event", "status",
)


def _snapshot_for_items(item_ids: list[int]) -> dict[int, dict]:
    snap: dict[int, dict] = {}
    if not item_ids:
        return snap
    with Session(engine) as session:
        rows = session.exec(
            select(Enrichment).where(Enrichment.item_id.in_(item_ids))
        ).all()
        for r in rows:
            snap[r.item_id] = {f: getattr(r, f) for f in SNAPSHOT_FIELDS}
    return snap


def _pick_sample_item_ids(limit: int) -> list[tuple[int, str]]:
    """Replicate enrich_pending(force=True) ordering+filtering, return (id, title)."""
    with Session(engine) as session:
        items = session.exec(
            select(Item).order_by(Item.published_at.desc().nullslast())
        ).all()
        # force=True => no skip_ids; ordering matches enrich_pending
        if limit:
            items = items[:limit]
        return [(it.id, it.title) for it in items]


def _fmt(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, str) and len(v) > 80:
        return repr(v[:77] + "...")
    return repr(v)


def _print_diff(item_id: int, title: str, before: dict | None, after: dict | None) -> None:
    print(f"=== Item {item_id}: {title!r} ===")
    if before is None and after is None:
        print("  [no enrichment row before or after]")
        return
    if before is None:
        before = {f: None for f in SNAPSHOT_FIELDS}
    if after is None:
        after = {f: None for f in SNAPSHOT_FIELDS}

    new_marker_fields = {"genres", "platforms", "event"}
    # Field display order matching the spec example
    display_order = (
        "category", "sentiment_score", "sentiment_summary", "tldr",
        "entities", "genres", "platforms", "event", "status",
    )
    for f in display_order:
        b = before.get(f)
        a = after.get(f)
        marker = "  *NEW*" if f in new_marker_fields else ""
        if b == a:
            print(f"  {f}: [SAME] {_fmt(a)}")
        else:
            print(f"  {f}: {_fmt(b)} -> {_fmt(a)}{marker}")
    print()


def _rerun_targeted_ids(item_ids: list[int]) -> dict:
    """Re-enrich an explicit list of item_ids in place.

    Bypasses enrich_pending's queueing/skip logic. For each id, fetches the
    item, builds the body, calls Ollama directly, and persists via _persist_ok.
    Mirrors enrich_pending's failure handling (preserves existing ok row on
    re-enrich failure) but only touches the specified ids.
    """
    totals = {"attempted": 0, "ok": 0, "failed": 0, "skipped": 0, "missing": 0, "preserved": 0}
    with Session(engine) as session:
        existing_status: dict[int, str] = {
            iid: status for iid, status in session.exec(
                select(Enrichment.item_id, Enrichment.status)
            ).all() if iid in set(item_ids)
        }
        for iid in item_ids:
            totals["attempted"] += 1
            item = session.get(Item, iid)
            if item is None:
                log.warning("item id=%s not found; skipping", iid)
                totals["missing"] += 1
                continue
            body, label = _body_for_enrichment(session, item)
            if len(body or "") < ENRICH_BODY_CHAR_MIN:
                log.info("item=%s body too short (%d chars); skipping", iid, len(body or ""))
                totals["skipped"] += 1
                continue
            try:
                data = ollama_enrich_item(item.title, body, label)
                _persist_ok(session, iid, data)
                totals["ok"] += 1
                session.commit()
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                if existing_status.get(iid) == "ok":
                    totals["preserved"] += 1
                    log.warning("re-enrich failed for item=%s; preserving existing ok row: %s", iid, msg)
                else:
                    totals["failed"] += 1
                    log.warning("enrich failed for item=%s: %s", iid, msg)
                session.rollback()
    return totals


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="Max items to process")
    ap.add_argument("--sample", action="store_true", help="Print before/after diff per item")
    ap.add_argument(
        "--ids",
        type=str,
        default=None,
        help="Comma-separated item_ids to target directly (overrides selection; implies --sample)",
    )
    args = ap.parse_args()

    t0 = time.time()

    targeted_ids: list[int] = []
    if args.ids:
        targeted_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        args.sample = True  # always diff when targeting
        log.info("targeted-id mode: %d ids = %s", len(targeted_ids), targeted_ids)

    sample_pairs: list[tuple[int, str]] = []
    before_snap: dict[int, dict] = {}
    if args.sample:
        if targeted_ids:
            with Session(engine) as session:
                rows = session.exec(
                    select(Item).where(col(Item.id).in_(targeted_ids))
                ).all()
                by_id = {it.id: it.title for it in rows}
            sample_pairs = [(iid, by_id.get(iid, "<not found>")) for iid in targeted_ids]
        else:
            if not args.limit:
                log.warning("--sample without --limit will diff ALL items; this is verbose")
            sample_pairs = _pick_sample_item_ids(args.limit or 0)
        sample_ids = [iid for iid, _ in sample_pairs]
        log.info("sample: snapshotting %d items before re-enrich", len(sample_ids))
        before_snap = _snapshot_for_items(sample_ids)

    # Progress bar (non-sample mode). In sample mode the run is short and
    # the diff output is what matters; skip the bar to avoid mingled output.
    pbar = None
    if not args.sample:
        try:
            from tqdm import tqdm
            # Best-effort total: count items that would be processed.
            with Session(engine) as session:
                items = session.exec(
                    select(Item).order_by(Item.published_at.desc().nullslast())
                ).all()
                total = len(items) if not args.limit else min(len(items), args.limit)
            pbar = tqdm(total=total, desc="re-enrich", unit="item")

            orig_enrich_item = enrich_module.enrich_item

            def _wrapped(*a, **kw):
                try:
                    return orig_enrich_item(*a, **kw)
                finally:
                    if pbar is not None:
                        pbar.update(1)
            enrich_module.enrich_item = _wrapped  # type: ignore[assignment]
        except ImportError:
            log.warning("tqdm not installed; running without progress bar")

    if targeted_ids:
        log.info("=== rerun_enrichment start (targeted ids, n=%d) ===", len(targeted_ids))
        totals = _rerun_targeted_ids(targeted_ids)
    else:
        log.info("=== rerun_enrichment start (limit=%s, force=True) ===", args.limit)
        totals = enrich_pending(force=True, limit=args.limit)

    if pbar is not None:
        pbar.close()
        # restore
        enrich_module.enrich_item = orig_enrich_item  # type: ignore[assignment]

    log.info("totals: %s", totals)

    if args.sample:
        after_snap = _snapshot_for_items([iid for iid, _ in sample_pairs])
        print()
        print("=" * 72)
        print(f"BEFORE/AFTER DIFF for {len(sample_pairs)} sampled items")
        print("=" * 72)
        print()
        for iid, title in sample_pairs:
            _print_diff(iid, title, before_snap.get(iid), after_snap.get(iid))

    elapsed = time.time() - t0
    log.info("=== rerun_enrichment done; elapsed %.1fs ===", elapsed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
