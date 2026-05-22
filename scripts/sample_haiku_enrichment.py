"""Sample 10 items via Haiku 4.5 and write a side-by-side diff vs current
DB enrichments for user review. Does NOT persist anything.

Run:    python scripts/sample_haiku_enrichment.py
Output: docs/SAMPLE_HAIKU_<date>.md
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from app.db.models import Enrichment, Item, Source
from app.db.session import engine
from app.services.anthropic import enrich_item
from app.services.enrich import _body_for_enrichment

SAMPLE_COUNT = 10
OUTPUT = Path("docs") / f"SAMPLE_HAIKU_{datetime.utcnow():%Y-%m-%d}.md"


def _pick_sample(session: Session, n: int) -> list[Item]:
    """Pick a diverse mix of n items:
      Pass 1 — known-bad cases (Minions title, Reddit-handle leak in people).
      Pass 2 — one per category where possible (diversity).
      Pass 3 — fill remaining slots with newest items.
    """
    rows = session.exec(
        select(Item, Enrichment)
        .join(Enrichment, Item.id == Enrichment.item_id)
        .where(Enrichment.status == "ok")
        .order_by(Item.published_at.desc().nullslast())
    ).all()

    picked: list[Item] = []
    picked_ids: set[int] = set()
    seen_categories: set[str] = set()

    def _add(item: Item, cat: str | None) -> None:
        if item.id in picked_ids:
            return
        picked.append(item)
        picked_ids.add(item.id)
        if cat:
            seen_categories.add(cat)

    # Pass 1: known-bad cases.
    for item, enr in rows:
        if len(picked) >= n:
            break
        if "Minions" in (item.title or ""):
            _add(item, enr.category)
            continue
        if enr.entities and "Responsible_Box" in enr.entities:
            _add(item, enr.category)

    # Pass 2: diversify by category.
    for item, enr in rows:
        if len(picked) >= n:
            break
        if item.id in picked_ids:
            continue
        cat = enr.category or ""
        if cat in seen_categories:
            continue
        _add(item, cat)

    # Pass 3: fill with newest.
    for item, enr in rows:
        if len(picked) >= n:
            break
        _add(item, enr.category)

    return picked


def _format(d: dict | None) -> str:
    if d is None:
        return "_(no enrichment row)_"
    ent = d.get("entities") or {}
    return "\n".join([
        f"- **tldr:** {d.get('tldr', '')}",
        f"- **games:** {ent.get('games', [])}",
        f"- **companies:** {ent.get('companies', [])}",
        f"- **people:** {ent.get('people', [])}",
        f"- **category:** {d.get('category', '')}",
        f"- **sentiment:** {d.get('sentiment_score', '')} — {d.get('sentiment_summary', '')}",
        f"- **genres:** {d.get('genres') or []}",
        f"- **platforms:** {d.get('platforms') or []}",
        f"- **event:** {d.get('event') or 'null'}",
    ])


def _old_from_db(enr: Enrichment) -> dict:
    return {
        "tldr": enr.tldr,
        "entities": json.loads(enr.entities) if enr.entities else {},
        "category": enr.category,
        "sentiment_score": enr.sentiment_score,
        "sentiment_summary": enr.sentiment_summary,
        "genres": json.loads(enr.genres) if enr.genres else [],
        "platforms": json.loads(enr.platforms) if enr.platforms else [],
        "event": enr.event,
    }


def _new_from_haiku(data) -> dict:
    return {
        "tldr": data.tldr,
        "entities": data.entities.model_dump(),
        "category": data.category,
        "sentiment_score": data.sentiment_score,
        "sentiment_summary": data.sentiment_summary,
        "genres": data.genres,
        "platforms": data.platforms,
        "event": data.event,
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("sample_haiku")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    out = [
        f"# Haiku 4.5 10-item sample — {datetime.utcnow():%Y-%m-%d %H:%M UTC}",
        "",
        "Side-by-side: current DB enrichment (qwen2.5:7b) vs fresh Haiku 4.5 call.",
        "**No DB writes.** Eyeball the diff and tell me whether to proceed with the 988-item backfill.",
        "",
        "What to check:",
        "- `people` contains no underscored Reddit handles (e.g. `Responsible_Box_2422`)",
        "- Non-game items (movies, hardware-only, pure industry) have empty `genres`",
        "- Only the locked 12-genre / 6-platform / 13-event values appear",
        "- tldr is neutral + accurate; sentiment_score is plausible",
        "",
    ]

    with Session(engine) as session:
        items = _pick_sample(session, SAMPLE_COUNT)
        log.info("picked %d items", len(items))

        for idx, item in enumerate(items, start=1):
            enr = session.exec(
                select(Enrichment).where(Enrichment.item_id == item.id)
            ).first()
            source = session.get(Source, item.source_id)
            src_name = source.name if source else "?"

            log.info("[%d/%d] %s — %s", idx, len(items), src_name, (item.title or "")[:80])
            body, label, _prescreen_skip = _body_for_enrichment(session, item)

            try:
                data = enrich_item(item.title, body, label)
                new_dict = _new_from_haiku(data)
                new_err = None
            except Exception as e:  # noqa: BLE001
                new_dict = None
                new_err = f"{type(e).__name__}: {e}"
                log.warning("haiku failed: %s", new_err)

            old_dict = _old_from_db(enr) if enr else None

            out.append(f"## {idx}. {item.title}")
            out.append("")
            out.append(f"`{src_name}` · published {item.published_at} · item id {item.id}")
            out.append(f"<{item.url}>")
            out.append("")
            out.append("### Current (qwen2.5:7b, in DB)")
            out.append("")
            out.append(_format(old_dict))
            out.append("")
            out.append("### New (Haiku 4.5)")
            out.append("")
            out.append(f"_ERROR: {new_err}_" if new_err else _format(new_dict))
            out.append("")
            out.append("---")
            out.append("")

    OUTPUT.write_text("\n".join(out), encoding="utf-8")
    log.info("wrote %s", OUTPUT)
    print(f"\nDone. Review: {OUTPUT}")


if __name__ == "__main__":
    main()
