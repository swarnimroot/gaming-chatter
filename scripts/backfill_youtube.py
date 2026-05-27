"""Backfill YouTube videos from the 6 hardcoded YT channels into items + enrichments.

RSS exposes only ~15 recent entries per channel; yt-dlp can enumerate full channel
history. This script uses yt-dlp in flat-extract mode (metadata only, no download)
to list channel uploads, filters to a date window, then routes each new video
through the SAME persistence + enrichment helpers used by the daily ingest path.

Usage:
    python scripts/backfill_youtube.py --start 2026-05-04 --end 2026-05-17
    python scripts/backfill_youtube.py --start 2026-05-04 --end 2026-05-04 \\
        --channel UCgaPRP68bbyHnfkPhWWBrNw --limit-per-channel 3
    python scripts/backfill_youtube.py --start 2026-05-04 --end 2026-05-17 --dry-run

Design notes:
- Reuses the existing item-persist contract from app.services.ingest
  (RawItem -> Item; external_id + url dedup; fingerprint via title MD5).
  We do not call ingest_source() directly because that re-fetches the live
  RSS feed; instead we synthesize one RawMention per yt-dlp entry and persist
  inline with the same field semantics.
- Enrichment is delegated to the helpers from app.services.enrich
  (_body_for_enrichment + _persist_ok/_persist_failed/_persist_skipped) so the
  Haiku pre-screen, whisper-CPU transcript fallback, and Anthropic enrich call
  paths are identical to the daily pipeline.
- Embeddings are picked up by a post-pass call to embed_pending(), which
  naturally scopes itself to 'ok' enrichments lacking an embedding.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)

from scrapers_lib.core.attribution import rss_article_id  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.config import ENRICH_BODY_CHAR_MIN  # noqa: E402
from app.db.models import Item, RawItem, RunLog, Source  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.services.anthropic import enrich_item as anthropic_enrich_item  # noqa: E402
from app.services.enrich import (  # noqa: E402
    _body_for_enrichment,
    _persist_failed,
    _persist_ok,
    _persist_skipped,
    embed_pending,
)
from app.services.ingest import _fingerprint, _slugify, _to_payload  # noqa: E402

log = logging.getLogger("backfill_yt")

# The 6 hardcoded channels (mirror of sources.yaml; channel_ids verified 2026-05-21).
# Listed here so --channel filtering can short-circuit on unknown IDs without
# touching the DB; the actual Source row is resolved by channel_id substring
# match against url_or_handle.
CHANNELS: list[tuple[str, str]] = [
    ("UCKy1dAqELo0zrOtPkf0eTMw", "IGN (YouTube)"),
    ("UCbu2SsF-Or3Rsn3NxqODImw", "GameSpot (YouTube)"),
    ("UCK-65DO2oOxxMwphl2tYtcw", "Game Informer (YouTube)"),
    ("UCT6iAerLNE-0J1S_E97UAuQ", "YongYea (YouTube)"),
    ("UCgaPRP68bbyHnfkPhWWBrNw", "PC Gamer (YouTube)"),
    ("UCNvzD7Z-g64bPXxGzaQaa4g", "Gameranx (YouTube)"),
]


@dataclass
class _Mention:
    """Minimal RawMention-shaped object matching what ingest_source consumes.

    ingest_source reads these attributes via getattr():
      mention_id, source_title, source_url, raw_text, author, published_at
    plus dataclasses.asdict() to serialize raw_payload. Keeping this a plain
    dataclass (not RawMention) avoids pulling in pydantic validators we don't
    need and keeps the JSON payload small.
    """
    mention_id: str
    source_title: str
    source_url: str
    raw_text: str
    author: Optional[str]
    published_at: Optional[datetime]
    source: str
    source_type: str = "video"
    raw: Optional[dict] = None


def _enumerate_channel(channel_id: str, playlist_cap: int) -> list[dict]:
    """List uploads on a channel via yt-dlp flat extraction.

    extract_flat returns metadata-only entries (no per-video page fetch).
    Returns the raw entries list from yt-dlp.
    """
    import yt_dlp

    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "playlist_items": f"1-{playlist_cap}",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = info.get("entries") or []
    return [e for e in entries if e]


def _parse_upload_date(entry: dict) -> Optional[datetime]:
    """yt-dlp returns upload_date as 'YYYYMMDD' string in flat mode.

    In flat extraction with /videos endpoint, upload_date is often missing
    (it's only populated by the per-video info pass). When absent we have to
    fall back to a per-video lookup OR rely on 'timestamp' if present. Returns
    None when neither field is usable; caller will treat as out-of-window.
    """
    upload_date = entry.get("upload_date")
    if upload_date:
        try:
            return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    ts = entry.get("timestamp")
    if ts:
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except (ValueError, OSError):
            pass
    return None


def _fetch_per_video_date(video_id: str) -> Optional[datetime]:
    """When flat-extract didn't give us a date, fall back to a per-video metadata
    fetch. Slower (one HTTP roundtrip per video) but required for accurate
    windowing on channels where the listing endpoint omits upload_date."""
    import yt_dlp

    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        log.warning("per-video metadata fetch failed for %s: %s", video_id, e)
        return None
    if not info:
        return None
    upload_date = info.get("upload_date")
    if upload_date:
        try:
            return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    ts = info.get("timestamp")
    if ts:
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except (ValueError, OSError):
            return None
    return None


def _resolve_source(session: Session, channel_id: str) -> Optional[Source]:
    """Find the Source row whose url_or_handle contains this channel_id.

    sources.yaml stores YT 'handle' as the full Atom feed URL with channel_id=...
    so a substring match is unambiguous.
    """
    rows = session.exec(select(Source).where(Source.type == "youtube")).all()
    for s in rows:
        if channel_id in (s.url_or_handle or ""):
            return s
    return None


def _build_mention(channel_id: str, source: Source, entry: dict, upload_dt: datetime) -> _Mention:
    """Construct a RawMention-equivalent for one yt-dlp entry."""
    video_id = entry["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    title = (entry.get("title") or "").strip() or "(untitled)"
    description = entry.get("description") or ""
    # Body composition mirrors tier1.rss._compose_entry_text behavior:
    # title \n description, with HTML already absent for yt-dlp output.
    parts = [title]
    if description:
        parts.append(description.strip())
    raw_text = "\n".join(p for p in parts if p)

    author = entry.get("uploader") or entry.get("channel") or source.name
    slug = _slugify(source.name)
    guid = f"yt:video:{video_id}"  # stable per-video GUID
    mention_id = rss_article_id(slug, guid)

    return _Mention(
        mention_id=mention_id,
        source_title=title,
        source_url=video_url,
        raw_text=raw_text,
        author=author,
        published_at=upload_dt,
        source=slug,
        raw={"video_id": video_id, "channel_id": channel_id, "yt_dlp_flat": True},
    )


def _persist_item(session: Session, source: Source, m: _Mention) -> Optional[int]:
    """Mirror of ingest._persist loop body. Returns the new item.id or None
    if dedup'd. Commits on success.

    Dedup is layered:
      1) items.url == video_url  (the user's explicit dedup contract)
      2) raw_items.external_id   (matches the live ingest pipeline's own check)
    """
    # url dedup
    existing_item = session.exec(
        select(Item).where(Item.url == m.source_url)
    ).first()
    if existing_item:
        return None

    # external_id dedup (per-source)
    existing_raw = session.exec(
        select(RawItem).where(
            RawItem.source_id == source.id,
            RawItem.external_id == m.mention_id,
        )
    ).first()
    if existing_raw:
        return None

    raw = RawItem(
        source_id=source.id,
        external_id=m.mention_id,
        raw_payload=_to_payload(m),
    )
    session.add(raw)
    session.flush()

    item = Item(
        source_id=source.id,
        raw_item_id=raw.id,
        title=m.source_title,
        url=m.source_url,
        body_text=m.raw_text,
        author=m.author,
        published_at=m.published_at,
        fingerprint=_fingerprint(m.source_title),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item.id


def _enrich_one(session: Session, item_id: int) -> tuple[str, Optional[str]]:
    """Run the enrichment pipeline for one freshly-inserted item.

    Returns (status, error_or_reason) where status is one of:
      'ok', 'skipped', 'failed'
    Mirrors the per-item branch in enrich_pending() exactly: prescreen +
    transcript fetch via _body_for_enrichment, then Haiku call, then persist.
    """
    item = session.get(Item, item_id)
    if item is None:
        return "failed", "item disappeared after insert"
    body, label, prescreen_skip = _body_for_enrichment(session, item)
    if prescreen_skip:
        _persist_skipped(session, item_id, prescreen_skip)
        session.commit()
        return "skipped", prescreen_skip
    if len(body or "") < ENRICH_BODY_CHAR_MIN:
        reason = f"body too short ({len(body or '')} chars)"
        _persist_skipped(session, item_id, reason)
        session.commit()
        return "skipped", reason
    try:
        data = anthropic_enrich_item(item.title, body, label)
        _persist_ok(session, item_id, data)
        session.commit()
        return "ok", None
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        _persist_failed(session, item_id, msg)
        session.commit()
        return "failed", msg


def backfill(
    start: datetime,
    end: datetime,
    channel_filter: Optional[str],
    dry_run: bool,
    limit_per_channel: Optional[int],
    playlist_cap: int,
) -> dict:
    """Top-level driver. Returns aggregate totals."""
    if channel_filter:
        targets = [(cid, name) for cid, name in CHANNELS if cid == channel_filter]
        if not targets:
            log.error("unknown channel_id: %s; known=%s", channel_filter,
                      [c for c, _ in CHANNELS])
            return {"error": "unknown channel"}
    else:
        targets = list(CHANNELS)

    start_date = start.date()
    end_date = end.date()

    grand = {
        "channels": 0,
        "enumerated": 0,
        "in_range": 0,
        "deduped": 0,
        "ingested": 0,
        "enriched_ok": 0,
        "enriched_skipped": 0,
        "enriched_failed": 0,
        "errors": 0,
    }

    started = datetime.utcnow()
    with Session(engine) as outer_session:
        run = RunLog(job_type="backfill_yt", status="running", started_at=started)
        outer_session.add(run)
        outer_session.commit()
        outer_session.refresh(run)
        run_id = run.id

    for channel_id, expected_name in targets:
        grand["channels"] += 1
        log.info("=== channel %s (%s) ===", channel_id, expected_name)

        with Session(engine) as session:
            source = _resolve_source(session, channel_id)
            if source is None:
                log.error("no Source row for channel_id=%s; skipping", channel_id)
                grand["errors"] += 1
                continue

            try:
                entries = _enumerate_channel(channel_id, playlist_cap)
            except Exception as e:  # noqa: BLE001
                log.error("yt-dlp enumerate failed for %s: %s", channel_id, e)
                grand["errors"] += 1
                continue

            ch_enum = len(entries)
            grand["enumerated"] += ch_enum

            in_range: list[tuple[dict, datetime]] = []
            for entry in entries:
                dt = _parse_upload_date(entry)
                if dt is None:
                    # Fall back to per-video metadata to recover the date.
                    vid = entry.get("id")
                    if vid:
                        dt = _fetch_per_video_date(vid)
                if dt is None:
                    continue
                if not (start_date <= dt.date() <= end_date):
                    continue
                in_range.append((entry, dt))

            if limit_per_channel:
                in_range = in_range[:limit_per_channel]

            ch_in_range = len(in_range)
            grand["in_range"] += ch_in_range
            log.info(
                "  enumerated=%d in_range=%d (window %s..%s)",
                ch_enum, ch_in_range, start_date, end_date,
            )

            ch_dedup = 0
            ch_ingested = 0
            ch_enr_ok = 0
            ch_enr_skip = 0
            ch_enr_fail = 0

            for entry, upload_dt in in_range:
                video_id = entry.get("id") or "<no-id>"
                video_url = f"https://www.youtube.com/watch?v={video_id}"

                # Dedup probe (also done inside _persist_item, but we want a
                # clean log line BEFORE doing any work).
                existing_item = session.exec(
                    select(Item).where(Item.url == video_url)
                ).first()
                if existing_item:
                    ch_dedup += 1
                    log.info("  [dedup] %s (item_id=%d)", video_id, existing_item.id)
                    continue

                m = _build_mention(channel_id, source, entry, upload_dt)
                title_preview = (m.source_title or "")[:70]
                log.info("  [%s] %s  %s", upload_dt.date(), video_id, title_preview)

                if dry_run:
                    continue

                try:
                    item_id = _persist_item(session, source, m)
                except Exception as e:  # noqa: BLE001
                    log.warning("  persist failed for %s: %s: %s",
                                video_id, type(e).__name__, e)
                    grand["errors"] += 1
                    session.rollback()
                    continue
                if item_id is None:
                    ch_dedup += 1
                    log.info("    -> deduped at persist (race)")
                    continue
                ch_ingested += 1

                # Enrich inline so smoke output shows end-to-end result.
                try:
                    status, info = _enrich_one(session, item_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("  enrich orchestration error for item=%d: %s: %s",
                                item_id, type(e).__name__, e)
                    grand["errors"] += 1
                    continue

                if status == "ok":
                    ch_enr_ok += 1
                    log.info("    -> item_id=%d enrich=ok", item_id)
                elif status == "skipped":
                    ch_enr_skip += 1
                    log.info("    -> item_id=%d enrich=skipped (%s)", item_id, info)
                else:
                    ch_enr_fail += 1
                    log.warning("    -> item_id=%d enrich=failed (%s)", item_id, info)

            grand["deduped"] += ch_dedup
            grand["ingested"] += ch_ingested
            grand["enriched_ok"] += ch_enr_ok
            grand["enriched_skipped"] += ch_enr_skip
            grand["enriched_failed"] += ch_enr_fail

            log.info(
                "  channel summary: enum=%d in_range=%d dedup=%d ingested=%d "
                "enriched ok/skip/fail=%d/%d/%d",
                ch_enum, ch_in_range, ch_dedup, ch_ingested,
                ch_enr_ok, ch_enr_skip, ch_enr_fail,
            )

    # Run embeddings post-pass for any newly enriched-ok items.
    if not dry_run and grand["enriched_ok"] > 0:
        log.info("=== embedding new items ===")
        emb = embed_pending()
        log.info("embed totals: %s", emb)

    # Finalize run log.
    with Session(engine) as session:
        run = session.get(RunLog, run_id)
        if run:
            run.status = "ok" if grand["errors"] == 0 else "ok_with_errors"
            run.items_processed = grand["ingested"]
            run.completed_at = datetime.utcnow()
            if grand["errors"]:
                run.error = f"{grand['errors']} channel/item-level errors"
            session.add(run)
            session.commit()

    return grand


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--channel", default=None,
                    help="Restrict to one channel_id (default = all 6)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Enumerate + print; no DB writes")
    ap.add_argument("--limit-per-channel", type=int, default=None,
                    help="Cap entries per channel after date filter")
    ap.add_argument("--playlist-cap", type=int, default=200,
                    help="Max entries to ask yt-dlp for per channel (default 200)")
    args = ap.parse_args()

    try:
        start = datetime.strptime(args.start, "%Y-%m-%d")
        end = datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError as e:
        log.error("bad date: %s", e)
        return 2
    if end < start:
        log.error("--end %s < --start %s", args.end, args.start)
        return 2

    log.info("=== backfill_youtube start ===")
    log.info(
        "  window=%s..%s channel=%s dry_run=%s limit_per_channel=%s playlist_cap=%d",
        args.start, args.end, args.channel or "ALL",
        args.dry_run, args.limit_per_channel, args.playlist_cap,
    )
    t0 = time.time()
    totals = backfill(
        start=start,
        end=end,
        channel_filter=args.channel,
        dry_run=args.dry_run,
        limit_per_channel=args.limit_per_channel,
        playlist_cap=args.playlist_cap,
    )
    elapsed = time.time() - t0
    log.info("=== backfill_youtube done in %.1fs ===", elapsed)
    log.info("TOTALS: %s", json.dumps(totals, indent=2))
    return 0 if totals.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
