"""Thin wrappers around scrapers-lib tier1.

Phase 1 path is RSS-only. YouTube handles are resolved to channel-feed URLs
and ingested as RSS; transcript fetching is a Phase 2 concern.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from scrapers_lib.tier1 import rss as _rss

log = logging.getLogger(__name__)

# Reddit serves unauthenticated RSS at ~1 request per 60s per IP. Measured
# 2026-06-15 from the response headers: a single request returns
# x-ratelimit-used=1 / x-ratelimit-remaining=0.0 / x-ratelimit-reset=59, and a
# burst (or even 6s spacing) 429s everything after the first. The whole of
# www.reddit.com shares one per-IP bucket, so every subreddit feed draws from
# the same budget. We can't authenticate our way to a higher limit (the Reddit
# API application was rejected — see OPEN_QUESTIONS), so we serialize reddit
# fetches to stay under the limit. 65s = 60s window + 5s safety margin. With 10
# subreddits this adds ~10 min of (idle) wall-clock to ingest; it's unattended
# and costs no CPU/$. See DECISIONS 2026-06-15.
_REDDIT_MIN_INTERVAL_S = 65.0
_reddit_gate_lock = threading.Lock()
_reddit_last_request = 0.0  # time.monotonic() at the last reddit request


def _is_reddit_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "reddit.com" or host.endswith(".reddit.com")


def _reddit_rate_gate() -> None:
    """Block until >= _REDDIT_MIN_INTERVAL_S has elapsed since the last reddit
    request, then claim the slot. Serializes every reddit.com fetch in the
    process so the per-IP 1-req/60s budget is never exceeded."""
    global _reddit_last_request
    with _reddit_gate_lock:
        wait = _REDDIT_MIN_INTERVAL_S - (time.monotonic() - _reddit_last_request)
        if wait > 0:
            log.info("reddit rate gate: sleeping %.0fs before next reddit fetch", wait)
            time.sleep(wait)
        _reddit_last_request = time.monotonic()


def _fetch_reddit_rss(url: str, source_slug: str | None) -> list[Any]:
    """Reddit RSS fetch: proactive rate-gate + one 429 backstop that honors the
    x-ratelimit-reset header (Reddit does not send Retry-After)."""
    global _reddit_last_request
    _reddit_rate_gate()
    try:
        return _rss.fetch_rss_feed(url=url, source_slug=source_slug)
    except httpx.HTTPStatusError as e:
        resp = e.response
        if resp is None or resp.status_code != 429:
            raise
        reset = resp.headers.get("x-ratelimit-reset")
        try:
            sleep_s = float(reset) + 2.0
        except (TypeError, ValueError):
            sleep_s = _REDDIT_MIN_INTERVAL_S
        log.warning(
            "reddit 429 on %s; honoring x-ratelimit-reset=%s, sleeping %.0fs then retrying once",
            url, reset, sleep_s,
        )
        time.sleep(sleep_s)
        with _reddit_gate_lock:
            _reddit_last_request = time.monotonic()
        return _rss.fetch_rss_feed(url=url, source_slug=source_slug)

# YouTube's feeds/videos.xml endpoint intermittently soft-blocks by IP
# reputation, returning 404 (NOT 429) to feed traffic it deems bot-like. When
# it triggers, all of our channels go dark together for multi-day streaks
# (observed 06-16 onward: ~45% of nights fully dark, in runs of 1-4 days), then
# recover on their own. The channel IDs stay valid throughout (they return 200
# on recovery and when hit from a browser). Unlike Reddit there's no published
# rate to gate around, but the scrapers-lib default UA identifies as a bot
# ("scrapers-lib/1.7.0"); sending a full browser User-Agent lowers how often
# YouTube flags us, and a single retry on 404 absorbs transient hits. This is a
# mitigation, not a guarantee — persistent IP-reputation blocks may still cause
# dark streaks. See DECISIONS 2026-07-13.
_YT_FEED_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_YT_FEED_HEADERS = {
    "User-Agent": _YT_FEED_BROWSER_UA,
    "Accept": (
        "application/rss+xml, application/atom+xml, application/xml, "
        "text/xml, */*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_YT_404_RETRY_DELAY_S = 3.0


def _fetch_youtube_rss(feed_url: str, source_slug: str | None) -> list[Any]:
    """Fetch a YouTube channel feed with a browser User-Agent, retrying once on
    404. Mirrors _rss.fetch_rss_feed (fetch bytes -> parse_rss_feed) but swaps
    the bot-flavored default UA for a browser one to reduce YouTube soft-blocks.
    Non-404 errors, and a 404 that survives the retry, propagate unchanged."""
    last_exc: httpx.HTTPStatusError | None = None
    for attempt in (1, 2):
        try:
            r = httpx.get(
                feed_url,
                headers=_YT_FEED_HEADERS,
                follow_redirects=True,
                timeout=30.0,
            )
            r.raise_for_status()
            return _rss.parse_rss_feed(r.content, feed_url, source_slug=source_slug)
        except httpx.HTTPStatusError as e:
            last_exc = e
            resp = e.response
            if resp is not None and resp.status_code == 404 and attempt == 1:
                log.warning(
                    "youtube feed 404 on %s; retrying once in %.0fs",
                    feed_url, _YT_404_RETRY_DELAY_S,
                )
                time.sleep(_YT_404_RETRY_DELAY_S)
                continue
            raise
    raise last_exc  # pragma: no cover - loop always returns or raises above


# In-process cache: handle/url → resolved channel-feed URL.
_youtube_feed_cache: dict[str, str] = {}

_CHANNEL_ID_RE = re.compile(r'"channelId":"(UC[\w-]+)"')
_CHANNEL_PATH_RE = re.compile(r"channel/(UC[\w-]+)")
_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) gaming-chatter/0.1"


def resolve_youtube_feed(handle_or_url: str) -> str:
    """Resolve an @handle or channel URL to its videos.xml feed URL.

    Already-resolved feed URLs pass through unchanged.
    """
    if handle_or_url in _youtube_feed_cache:
        return _youtube_feed_cache[handle_or_url]
    if "feeds/videos.xml" in handle_or_url:
        return handle_or_url

    page = handle_or_url
    if page.startswith("@"):
        page = f"https://www.youtube.com/{page}"
    elif not page.startswith("http"):
        page = f"https://www.youtube.com/{page}"

    r = httpx.get(
        page,
        follow_redirects=True,
        timeout=15.0,
        headers={"User-Agent": _BROWSER_UA, "Accept-Language": "en"},
    )
    r.raise_for_status()
    m = _CHANNEL_ID_RE.search(r.text) or _CHANNEL_PATH_RE.search(r.text)
    if not m:
        raise ValueError(f"could not resolve youtube channel id for: {handle_or_url}")
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
    _youtube_feed_cache[handle_or_url] = feed_url
    log.info("resolved youtube %s -> %s", handle_or_url, feed_url)
    return feed_url


def fetch_source(source_type: str, url_or_handle: str, source_slug: str) -> list[Any]:
    """Type-agnostic fetch returning a list of RawMention.

    Both rss and youtube go through tier1.rss; youtube handles are resolved
    to a channel feed URL first.
    """
    if source_type == "rss":
        if _is_reddit_url(url_or_handle):
            return _fetch_reddit_rss(url_or_handle, source_slug)
        return _rss.fetch_rss_feed(url=url_or_handle, source_slug=source_slug)
    if source_type == "youtube":
        feed_url = resolve_youtube_feed(url_or_handle)
        return _fetch_youtube_rss(feed_url, source_slug)
    raise ValueError(f"unknown source type: {source_type}")
