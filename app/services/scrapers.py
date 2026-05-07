"""Thin wrappers around scrapers-lib tier1.

Phase 1 path is RSS-only. YouTube handles are resolved to channel-feed URLs
and ingested as RSS; transcript fetching is a Phase 2 concern.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from scrapers_lib.tier1 import rss as _rss

log = logging.getLogger(__name__)

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
        return _rss.fetch_rss_feed(url=url_or_handle, source_slug=source_slug)
    if source_type == "youtube":
        feed_url = resolve_youtube_feed(url_or_handle)
        return _rss.fetch_rss_feed(url=feed_url, source_slug=source_slug)
    raise ValueError(f"unknown source type: {source_type}")
