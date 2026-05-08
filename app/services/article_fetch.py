"""Phase 2.5 — fetch full article bodies for items whose enrichment skipped.

News-site RSS feeds (PC Gamer, Kotaku, Game Developer, GamesIndustry.biz)
carry only short teasers, so the on-ingest body falls below
ENRICH_BODY_CHAR_MIN and the enrichment row is persisted with status='skipped'.
This module re-fetches the full article body via scrapers_lib.tier1.article
and updates Item.body_text so a subsequent enrich_pending(retry_failed=True)
can promote the row to 'ok'.

Excluded from this pass:
  - YouTube items — article extractor doesn't help; their content path is
    the transcript fetch in app.services.ollama.
  - Reddit URLs — link-post pages have no extractable article body
    (trafilatura returns nothing). Reddit link-posts duplicate articles
    captured directly from news-site feeds, per DECISIONS 2026-05-07.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from scrapers_lib.tier1.article import fetch_article as _fetch_article
from sqlmodel import Session, select

from app.config import ENRICH_BODY_CHAR_MIN
from app.db.models import Enrichment, Item, RunLog, Source
from app.db.session import engine

log = logging.getLogger(__name__)


def _is_reddit_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("reddit.com")


def fetch_skipped_bodies(
    *,
    limit: Optional[int] = None,
    delay_s: float = 1.0,
) -> dict:
    """Re-fetch article bodies for items whose enrichment is currently 'skipped'.

    For each non-YouTube skipped item: call tier1.article on item.url. If a body
    of at least ENRICH_BODY_CHAR_MIN chars comes back, overwrite item.body_text.
    Otherwise leave the item alone (it will remain skipped on re-enrichment).
    """
    started = datetime.utcnow()
    totals = {
        "attempted": 0,
        "fetched": 0,
        "no_body": 0,
        "too_short": 0,
        "errored": 0,
        "yt_excluded": 0,
        "reddit_excluded": 0,
    }

    with Session(engine) as session:
        run = RunLog(job_type="article_fetch", status="running", started_at=started)
        session.add(run)
        session.commit()
        session.refresh(run)

        rows = session.exec(
            select(Item, Enrichment, Source)
            .join(Enrichment, Enrichment.item_id == Item.id)
            .join(Source, Source.id == Item.source_id)
            .where(Enrichment.status == "skipped")
        ).all()
        if limit:
            rows = rows[:limit]

        for item, _enr, source in rows:
            if source.type == "youtube":
                totals["yt_excluded"] += 1
                continue
            if _is_reddit_url(item.url):
                totals["reddit_excluded"] += 1
                continue

            totals["attempted"] += 1
            try:
                mentions = _fetch_article(item.url)
            except Exception as e:  # noqa: BLE001
                totals["errored"] += 1
                log.warning("article fetch failed for item=%s url=%s: %s", item.id, item.url, e)
                time.sleep(delay_s)
                continue

            if not mentions:
                totals["no_body"] += 1
                log.info("no body extracted for item=%s url=%s", item.id, item.url)
                time.sleep(delay_s)
                continue

            body = mentions[0].raw_text or ""
            if len(body) < ENRICH_BODY_CHAR_MIN:
                totals["too_short"] += 1
                log.info(
                    "extracted body too short (%d chars) for item=%s url=%s",
                    len(body), item.id, item.url,
                )
                time.sleep(delay_s)
                continue

            item.body_text = body
            session.add(item)
            session.commit()
            totals["fetched"] += 1
            log.info("fetched %d chars for item=%s", len(body), item.id)
            time.sleep(delay_s)

        run.status = "ok"
        run.items_processed = totals["fetched"]
        run.completed_at = datetime.utcnow()
        if totals["errored"] or totals["no_body"] or totals["too_short"]:
            run.error = (
                f"{totals['errored']} errored, "
                f"{totals['no_body']} no_body, "
                f"{totals['too_short']} too_short"
            )
        session.add(run)
        session.commit()

    log.info("fetch_skipped_bodies done: %s", totals)
    return totals
