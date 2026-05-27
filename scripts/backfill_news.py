"""Backfill news articles from the 15 news RSS sources into items + enrichments.

Native RSS exposes only ~15-100 recent entries per site; sitemaps reach back
much further. This script enumerates each site's sitemap (or sitemap index),
filters URLs to a date window, then routes each new URL through the SAME
persistence + enrichment helpers used by the daily ingest path.

Usage:
    python scripts/backfill_news.py --start 2026-05-04 --end 2026-05-17
    python scripts/backfill_news.py --start 2026-05-04 --end 2026-05-04 \\
        --source "PC Gamer" --limit-per-source 3
    python scripts/backfill_news.py --start 2026-05-04 --end 2026-05-17 --dry-run

Design notes:
- Sibling of scripts/backfill_youtube.py — mirrors the _Mention / _persist_item
  / _enrich_one pattern exactly. We synthesize one RawMention per in-range
  article URL and persist inline.
- Body extraction reuses scrapers_lib.tier1.article.fetch_article (trafilatura,
  uses warmed Chrome-impersonated curl session under the hood — same code path
  as app.services.article_fetch.fetch_skipped_bodies, so we share the same
  Cloudflare-handling behavior).
- Sitemaps are fetched directly via httpx for vanilla sites and via the
  warmed curl session for Cloudflare-fronted ones (GameSpot, GamesBeat).
- Per-site sitemap recipes (SOURCE_RECIPES) were derived from a manual
  reconnaissance pass on 2026-05-22; each entry encodes the exact sitemap
  URL pattern + extraction strategy. Sites with rolling Google News
  sitemaps (~48hr window) are NOT useful here — we use monthly/yearly
  archive sitemaps instead. The recon notes per site are in the inline
  comments next to each recipe entry.
- Date extraction priority: <news:publication_date> if present, else <lastmod>.
  When lastmod is the only date, we cross-check with article:published_time
  meta tag from the article HTML before commit (lastmod ≠ publish date for
  many evergreen-refreshed guides).
- Rate-limiting: 1 req/sec per domain via scrapers_lib.core.rate_limiter.
- robots.txt: respected via scrapers_lib.core.robots.RobotsChecker.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)

import httpx  # noqa: E402

from scrapers_lib._version import __version__ as _SL_VERSION  # noqa: E402
from scrapers_lib.core.attribution import rss_article_id  # noqa: E402
from scrapers_lib.core.curl_session import warmed_curl_session  # noqa: E402
from scrapers_lib.core.rate_limiter import RateLimiter  # noqa: E402
from scrapers_lib.core.robots import RobotsChecker  # noqa: E402
from scrapers_lib.tier1.article import fetch_article as _fetch_article  # noqa: E402
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

log = logging.getLogger("backfill_news")

# Same UA family as the rest of scrapers-lib so target sites see a coherent
# identity across sitemap fetches, robots.txt fetches, and article fetches.
_DEFAULT_UA = (
    f"Mozilla/5.0 (compatible; scrapers-lib/{_SL_VERSION}; +https://github.com/)"
)
# Some sitemaps return empty body to the scrapers-lib UA but work with a
# Chrome string (Polygon, TheGamer, Game Rant). We promote a browser-shaped UA
# for sitemap fetches; the underlying article body fetcher still uses the
# warmed curl_cffi session, which has Chrome TLS impersonation built in.
_SITEMAP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# Sitemap XML namespaces — declared at the root of every sitemap.
_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


# ─────────────────────────────────────────────────────────────────────────────
# Per-source sitemap recipes
# ─────────────────────────────────────────────────────────────────────────────
#
# Each recipe encodes how to enumerate URLs+dates in a date window for ONE site.
# Recipes were derived from a manual robots.txt + sitemap reconnaissance on
# 2026-05-22. Re-check if any site changes its sitemap layout.
#
# kind = strategy for selecting which child-sitemap shards to descend:
#   "monthly_archive"   = one shard per YYYY-MM. url_template uses {year}/{month_2d}.
#   "monthly_archive_named" = one shard per YYYY/monthname (Game Developer).
#   "monthly_parts"     = one or more "...YYYY-MM-partN-articles.xml" shards.
#                         We discover N by reading the index.
#   "yearly_archive"    = one shard per year. lastmod is the only date.
#   "ign_year"          = IGN's "sitemap-articles-YYYY.xml" — yearly with lastmod.
#   "gamespot_numbered" = GameSpot's "articles-sitemapN.xml" sequential shards;
#                         we discover the highest-N shard from the root index
#                         (Cloudflare requires warmed session).
#   "gamesbeat_yoast"   = Yoast WP "post-sitemap.xml" is always the active
#                         (latest 1000) shard; descend it directly.
#                         (Cloudflare requires warmed session.)
#   "gameinformer_paged" = paginated sitemap.xml?page=N with no per-page date
#                         hint. We scan pages newest-first (page=1 has newest
#                         entries) until we drop below the date window.
#
# warmed = True when the site requires the curl_cffi Chrome-TLS-impersonating
#          session (Cloudflare challenge); False when plain httpx works.
@dataclass
class _Recipe:
    name: str                   # matches sources.yaml `name` exactly
    base_url: str               # for robots.txt + relative resolution
    kind: str
    index_url: Optional[str]    # the sitemap-index to descend (None for direct shard)
    shard_url_template: Optional[str]  # used by monthly/yearly kinds; supports {year}/{month_2d}
    warmed: bool = False
    notes: str = ""


SOURCE_RECIPES: list[_Recipe] = [
    _Recipe(
        name="IGN",
        base_url="https://www.ign.com",
        kind="ign_year",
        index_url=None,
        # IGN's robots.txt advertises both sitemap-articles-{year}.xml (year bucket,
        # lastmod-only) and rss/news/sitemap (rolling ~30 URLs with news:publication_date).
        # The year bucket is the right choice for a 14-day backfill: ~5k entries
        # for 2026 covering Jan-now, filtered down to the window via lastmod.
        shard_url_template="https://www.ign.com/rss/sitemap-articles-{year}.xml",
        warmed=False,
        notes="year bucket, lastmod-only (lastmod ~= publish for recent posts)",
    ),
    _Recipe(
        name="GameSpot",
        base_url="https://www.gamespot.com",
        kind="gamespot_numbered",
        # Behind Cloudflare; warmed_curl_session needed even for the index.
        index_url="https://www.gamespot.com/sitemap_index.xml",
        shard_url_template=None,  # discovered from index
        warmed=True,
        notes="numbered shards (1..N), highest-N is newest",
    ),
    _Recipe(
        name="Polygon",
        base_url="https://www.polygon.com",
        kind="monthly_parts",
        index_url="https://www.polygon.com/sitemap.xml",
        # Valnet shape: sitemap-{YYYY-MM}-part{N}-articles.xml.
        shard_url_template="https://www.polygon.com/sitemap-{year}-{month_2d}-part{part}-articles.xml",
        warmed=False,
        notes="Valnet monthly parts, lastmod-only",
    ),
    _Recipe(
        name="PC Gamer",
        base_url="https://www.pcgamer.com",
        kind="monthly_archive",
        index_url="https://www.pcgamer.com/sitemap.xml",
        shard_url_template="https://www.pcgamer.com/sitemap-{year}-{month_2d}.xml",
        warmed=False,
        notes="monthly archive, lastmod-only",
    ),
    _Recipe(
        name="Kotaku",
        base_url="https://kotaku.com",
        kind="monthly_archive",
        index_url="https://kotaku.com/sitemap_index.xml",
        shard_url_template="https://kotaku.com/post-sitemap-{year}-{month_2d}.xml",
        warmed=False,
        notes="WP keleops-sitemaps monthly post archive, lastmod-only",
    ),
    _Recipe(
        name="Eurogamer",
        base_url="https://www.eurogamer.net",
        kind="yearly_archive",
        index_url="https://www.eurogamer.net/sitemap.xml",
        shard_url_template="https://www.eurogamer.net/sitemap-{year}.xml",
        warmed=False,
        notes="year bucket, lastmod-only; evergreen guides may have refreshed lastmod",
    ),
    _Recipe(
        name="Game Informer",
        base_url="https://gameinformer.com",
        # No Sitemap directive in robots.txt. The site has paginated
        # sitemap.xml?page=N (Drupal simple_sitemap module). All pages have
        # the same root lastmod, so we have to scan pages newest-first.
        kind="gameinformer_paged",
        index_url="https://gameinformer.com/sitemap.xml",
        shard_url_template="https://gameinformer.com/sitemap.xml?page={page}",
        warmed=False,
        notes="Drupal paginated sitemap; page=1 has newest items",
    ),
    _Recipe(
        name="GamesBeat",
        base_url="https://gamesbeat.com",
        # Yoast WP. The "live" shard is post-sitemap.xml (unnumbered);
        # post-sitemap2..N are historical and we don't need them for 14-day
        # backfill. Cloudflare requires warmed session.
        kind="gamesbeat_yoast",
        index_url=None,
        shard_url_template="https://gamesbeat.com/post-sitemap.xml",
        warmed=True,
        notes="Yoast WP, latest shard is post-sitemap.xml (unnumbered)",
    ),
    _Recipe(
        name="GamesIndustry.biz",
        base_url="https://www.gamesindustry.biz",
        kind="yearly_archive",
        index_url="https://www.gamesindustry.biz/sitemap.xml",
        shard_url_template="https://www.gamesindustry.biz/sitemap-{year}.xml",
        warmed=False,
        notes="Ziff Davis year bucket, lastmod-only",
    ),
    _Recipe(
        name="Game Developer",
        base_url="https://www.gamedeveloper.com",
        # Informa platform with named monthly sitemaps.
        kind="monthly_archive_named",
        index_url="https://www.gamedeveloper.com/news-archive-index.xml",
        shard_url_template="https://www.gamedeveloper.com/news/archive/{year}/{month_name}.xml",
        warmed=False,
        notes="Informa news archive, /news/archive/YYYY/monthname.xml, lastmod-only",
    ),
    _Recipe(
        name="Rock Paper Shotgun",
        base_url="https://www.rockpapershotgun.com",
        kind="yearly_archive",
        index_url="https://www.rockpapershotgun.com/sitemap.xml",
        shard_url_template="https://www.rockpapershotgun.com/sitemap-{year}.xml",
        warmed=False,
        notes="Ziff Davis year bucket, lastmod-only",
    ),
    _Recipe(
        name="VG247",
        base_url="https://www.vg247.com",
        kind="yearly_archive",
        index_url="https://www.vg247.com/sitemap.xml",
        shard_url_template="https://www.vg247.com/sitemap-{year}.xml",
        warmed=False,
        notes="Ziff Davis year bucket, lastmod-only",
    ),
    _Recipe(
        name="TheGamer",
        base_url="https://www.thegamer.com",
        kind="monthly_parts",
        index_url="https://www.thegamer.com/sitemap.xml",
        shard_url_template="https://www.thegamer.com/sitemap-{year}-{month_2d}-part{part}-articles.xml",
        warmed=False,
        notes="Valnet monthly parts, lastmod-only",
    ),
    _Recipe(
        name="GamingBible",
        base_url="https://www.gamingbible.com",
        kind="monthly_archive",
        index_url="https://www.gamingbible.com/sitemap/sitemap.xml",
        shard_url_template="https://www.gamingbible.com/sitemap/includes/articles-{year}-{month_2d}.xml",
        warmed=False,
        notes="LADbible-platform monthly archive, lastmod-only",
    ),
    _Recipe(
        name="Game Rant",
        base_url="https://gamerant.com",
        kind="monthly_parts",
        index_url="https://gamerant.com/sitemap.xml",
        shard_url_template="https://gamerant.com/sitemap-{year}-{month_2d}-part{part}-articles.xml",
        warmed=False,
        notes="Valnet monthly parts, lastmod-only",
    ),
]

# Month-name lookup for "monthly_archive_named" (Game Developer).
_MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


# ─────────────────────────────────────────────────────────────────────────────
# Mention container (mirror of backfill_youtube._Mention)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class _Mention:
    mention_id: str
    source_title: str
    source_url: str
    raw_text: str
    author: Optional[str]
    published_at: Optional[datetime]
    source: str
    source_type: str = "article"
    raw: Optional[dict] = None


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers (sitemap + meta-tag fetch)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_sitemap(url: str, warmed: bool, rl: RateLimiter, timeout: float = 30.0) -> Optional[str]:
    """Fetch sitemap XML, honoring per-domain rate limit. Returns text or None on error."""
    domain = urlparse(url).netloc
    # Block synchronously on the bucket. Sitemaps are few + slow polite, no need
    # to gate-skip — sleep until a token is available.
    while not rl.try_acquire(domain):
        time.sleep(min(rl.wait_seconds(domain), 1.0))

    try:
        if warmed:
            with warmed_curl_session(f"{urlparse(url).scheme}://{domain}/", timeout=timeout) as s:
                r = s.get(
                    url,
                    headers={
                        "User-Agent": _SITEMAP_UA,
                        "Accept": "application/xml, text/xml, */*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    timeout=timeout,
                )
            status = getattr(r, "status_code", 0)
            text = getattr(r, "text", "")
        else:
            r = httpx.get(
                url,
                headers={
                    "User-Agent": _SITEMAP_UA,
                    "Accept": "application/xml, text/xml, */*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    # Some Ziff Davis sites only serve gzipped robots.txt/sitemaps
                    # without an explicit Accept-Encoding hint. httpx auto-handles
                    # gzip + deflate; we intentionally OMIT 'br' here because
                    # httpx requires the optional 'brotli'/'brotlicffi' package
                    # to decode brotli responses (Polygon, PC Gamer, TheGamer
                    # default to brotli for browser-UA clients).
                    "Accept-Encoding": "gzip, deflate",
                },
                follow_redirects=True,
                timeout=timeout,
            )
            status = r.status_code
            text = r.text
    except Exception as e:  # noqa: BLE001
        log.warning("sitemap fetch error %s: %s: %s", url, type(e).__name__, e)
        return None

    if status >= 400:
        log.warning("sitemap fetch %s returned HTTP %d", url, status)
        return None
    if not text or len(text) < 50:
        log.warning("sitemap fetch %s returned empty/short body (%d chars)", url, len(text or ""))
        return None
    return text


_META_PUB_RE = re.compile(
    r'<meta\s+(?:property|name)=["\']article:published_time["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _fetch_article_published_meta(url: str, rl: RateLimiter, timeout: float = 20.0) -> Optional[datetime]:
    """Pull <meta property="article:published_time"> from a URL's HTML head.

    Used to cross-check lastmod-only dates. Returns None on any failure.
    Uses warmed curl session (article-fetch path) for parity with the actual
    body fetch — same Cloudflare-handling behavior.
    """
    domain = urlparse(url).netloc
    while not rl.try_acquire(domain):
        time.sleep(min(rl.wait_seconds(domain), 1.0))
    try:
        with warmed_curl_session(
            f"{urlparse(url).scheme}://{domain}/", timeout=timeout
        ) as s:
            r = s.get(
                url,
                headers={
                    "User-Agent": _DEFAULT_UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    # We don't need the full body; many sites still send it all.
                    # 4MB cap inside curl_cffi default is fine.
                },
                timeout=timeout,
            )
        if getattr(r, "status_code", 0) >= 400:
            return None
        html = getattr(r, "text", "") or ""
    except Exception:  # noqa: BLE001
        return None
    # Scan only the first 20KB — the meta tag is in <head>.
    m = _META_PUB_RE.search(html[:20000])
    if not m:
        return None
    return _parse_iso8601(m.group(1))


# ─────────────────────────────────────────────────────────────────────────────
# XML helpers
# ─────────────────────────────────────────────────────────────────────────────
def _parse_iso8601(s: str) -> Optional[datetime]:
    """Parse a sitemap date string ('YYYY-MM-DDTHH:MM:SS[.fff][Z|+00:00]') to UTC.

    Handles fractional seconds (IGN, GamingBible) and trailing 'Z'.
    Returns None for unparseable input.
    """
    if not s:
        return None
    s = s.strip()
    # Trim fractional seconds (Python's fromisoformat supported them only from 3.11)
    s = re.sub(r"\.\d+", "", s)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class _UrlEntry:
    """One <url> entry from a sitemap, normalized."""
    loc: str
    published_at: Optional[datetime]
    date_source: str  # "news_pub_date" | "lastmod" | "unknown"


def _parse_urlset(xml_text: str) -> list[_UrlEntry]:
    """Parse a <urlset> XML and return one _UrlEntry per <url>."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.warning("XML parse error: %s", e)
        return []
    out: list[_UrlEntry] = []
    # Iterate every <url> child of the root. ET strips namespaces into
    # {ns}tag form; we look for the sitemap-schema namespace explicitly.
    for url_el in root.findall("sm:url", _NS):
        loc_el = url_el.find("sm:loc", _NS)
        if loc_el is None or not (loc_el.text or "").strip():
            continue
        loc = loc_el.text.strip()
        # Prefer news:publication_date when present.
        pub_dt = None
        date_src = "unknown"
        news_el = url_el.find("news:news/news:publication_date", _NS)
        if news_el is not None and news_el.text:
            pub_dt = _parse_iso8601(news_el.text)
            if pub_dt:
                date_src = "news_pub_date"
        if pub_dt is None:
            lm_el = url_el.find("sm:lastmod", _NS)
            if lm_el is not None and lm_el.text:
                pub_dt = _parse_iso8601(lm_el.text)
                if pub_dt:
                    date_src = "lastmod"
        out.append(_UrlEntry(loc=loc, published_at=pub_dt, date_source=date_src))
    return out


def _parse_sitemapindex(xml_text: str) -> list[tuple[str, Optional[datetime]]]:
    """Parse a <sitemapindex> XML; returns list of (loc, lastmod) tuples."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[tuple[str, Optional[datetime]]] = []
    for sm in root.findall("sm:sitemap", _NS):
        loc_el = sm.find("sm:loc", _NS)
        if loc_el is None or not (loc_el.text or "").strip():
            continue
        loc = loc_el.text.strip()
        lm_el = sm.find("sm:lastmod", _NS)
        lm = _parse_iso8601(lm_el.text) if (lm_el is not None and lm_el.text) else None
        out.append((loc, lm))
    return out


def _is_index(xml_text: str) -> bool:
    """Cheap pre-check: is this a <sitemapindex> or a <urlset>?"""
    head = xml_text[:1024].lower()
    return "<sitemapindex" in head


# ─────────────────────────────────────────────────────────────────────────────
# Per-recipe enumerator: shard URLs covering the date window
# ─────────────────────────────────────────────────────────────────────────────
def _months_in_window(start: datetime, end: datetime) -> list[tuple[int, int]]:
    """Return list of (year, month) tuples covering [start, end] inclusive.

    For our 14-day windows this is usually 1 month (sometimes 2 when the window
    straddles a month boundary).
    """
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y < end.year) or (y == end.year and m <= end.month):
        out.append((y, m))
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def _years_in_window(start: datetime, end: datetime) -> list[int]:
    """Years covered by [start, end]. Usually 1, occasionally 2."""
    return list(range(start.year, end.year + 1))


def _enumerate_shards(
    recipe: _Recipe,
    start: datetime,
    end: datetime,
    rl: RateLimiter,
) -> list[str]:
    """Return the list of urlset (leaf) sitemap URLs that contain in-range entries.

    For yearly/monthly recipes this is computed directly from the templates.
    For numbered/paged recipes we may need to fetch the index first.
    """
    if recipe.kind == "monthly_archive":
        urls = [
            recipe.shard_url_template.format(year=y, month_2d=f"{m:02d}")
            for (y, m) in _months_in_window(start, end)
        ]
        return urls
    if recipe.kind == "monthly_archive_named":
        return [
            recipe.shard_url_template.format(year=y, month_name=_MONTH_NAMES[m - 1])
            for (y, m) in _months_in_window(start, end)
        ]
    if recipe.kind == "yearly_archive" or recipe.kind == "ign_year":
        return [recipe.shard_url_template.format(year=y) for y in _years_in_window(start, end)]
    if recipe.kind == "monthly_parts":
        # Read the index to discover which part-N shards exist for the
        # months in our window.
        if not recipe.index_url:
            return []
        idx_text = _fetch_sitemap(recipe.index_url, recipe.warmed, rl)
        if not idx_text:
            return []
        idx_locs = [loc for (loc, _) in _parse_sitemapindex(idx_text)]
        wanted_prefixes = [
            recipe.shard_url_template.format(year=y, month_2d=f"{m:02d}", part="").rstrip(".xml").rstrip("part")
            for (y, m) in _months_in_window(start, end)
        ]
        # Cleaner: match every index loc whose YYYY-MM stem is in our window.
        out: list[str] = []
        for (y, m) in _months_in_window(start, end):
            stem = f"-{y}-{m:02d}-part"
            for loc in idx_locs:
                if stem in loc and loc.endswith("-articles.xml"):
                    out.append(loc)
        return sorted(set(out))
    if recipe.kind == "gamespot_numbered":
        # Newest GameSpot articles live in the highest-numbered articles-sitemapN.xml.
        # The unnumbered articles-sitemap.xml is OLDEST (sequential, 1k per shard).
        # For 14-day backfill we just need the latest shard.
        if not recipe.index_url:
            return []
        idx_text = _fetch_sitemap(recipe.index_url, recipe.warmed, rl)
        if not idx_text:
            return []
        idx_locs = [loc for (loc, _) in _parse_sitemapindex(idx_text)]
        article_shards = []
        for loc in idx_locs:
            m = re.search(r"articles-sitemap(\d+)\.xml", loc)
            if m:
                article_shards.append((int(m.group(1)), loc))
        if not article_shards:
            return []
        article_shards.sort(reverse=True)
        # Take top 2 shards in case window straddles a shard rollover.
        return [loc for _, loc in article_shards[:2]]
    if recipe.kind == "gamesbeat_yoast":
        # Direct shard — Yoast WP keeps the live 1000 in post-sitemap.xml.
        return [recipe.shard_url_template]
    if recipe.kind == "gameinformer_paged":
        # Pages are numbered; page=1 has newest items, monotonically older as page
        # number increases. We probe newest-first and stop when a whole page falls
        # below the window. Returning all candidate page URLs here would be
        # wasteful, so we return page=1..20 and let the caller short-circuit
        # via the date-window check on each page's contents.
        return [recipe.shard_url_template.format(page=p) for p in range(1, 21)]
    log.warning("unknown recipe kind: %s", recipe.kind)
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Top-level enumeration: per-source URL list within date window
# ─────────────────────────────────────────────────────────────────────────────
def _enumerate_urls_in_window(
    recipe: _Recipe,
    start: datetime,
    end: datetime,
    rl: RateLimiter,
) -> list[_UrlEntry]:
    """For one recipe, return all in-window _UrlEntry objects."""
    shards = _enumerate_shards(recipe, start, end, rl)
    if not shards:
        log.warning("[%s] no shards resolved", recipe.name)
        return []
    log.info("[%s] enumerating %d shard(s): %s", recipe.name, len(shards), shards[:5])

    start_d = start.date()
    end_d = end.date()
    out: list[_UrlEntry] = []
    consecutive_below_window = 0

    for shard_url in shards:
        xml_text = _fetch_sitemap(shard_url, recipe.warmed, rl)
        if not xml_text:
            log.warning("[%s] shard fetch failed: %s", recipe.name, shard_url)
            continue
        if _is_index(xml_text):
            # One level of recursion — descend index entries whose lastmod is
            # in window (when present).
            children = _parse_sitemapindex(xml_text)
            shard_xml = []
            for (child_loc, child_lm) in children:
                if child_lm and child_lm.date() < start_d:
                    continue
                child_text = _fetch_sitemap(child_loc, recipe.warmed, rl)
                if child_text and not _is_index(child_text):
                    shard_xml.append((child_loc, child_text))
            # In-window entries from each leaf.
            for (_, child_text) in shard_xml:
                for ent in _parse_urlset(child_text):
                    if ent.published_at is None:
                        continue
                    if start_d <= ent.published_at.date() <= end_d:
                        out.append(ent)
            continue

        entries = _parse_urlset(xml_text)
        if not entries:
            log.info("[%s] shard %s had 0 <url> entries", recipe.name, shard_url)
            continue

        page_in_window = 0
        page_above = 0  # newer than end
        page_below = 0  # older than start
        for ent in entries:
            if ent.published_at is None:
                continue
            d = ent.published_at.date()
            if d < start_d:
                page_below += 1
                continue
            if d > end_d:
                page_above += 1
                continue
            page_in_window += 1
            out.append(ent)
        log.info(
            "[%s] shard %s: in_window=%d above=%d below=%d (%d total entries)",
            recipe.name, shard_url, page_in_window, page_above, page_below, len(entries),
        )

        # gameinformer_paged: short-circuit when an entire page is below window.
        if recipe.kind == "gameinformer_paged":
            if page_in_window == 0 and page_below > 0 and page_above == 0:
                consecutive_below_window += 1
                if consecutive_below_window >= 2:
                    log.info("[%s] two consecutive pages below window — stop paging", recipe.name)
                    break
            else:
                consecutive_below_window = 0

    # Dedup on loc.
    seen: set[str] = set()
    dedup: list[_UrlEntry] = []
    for ent in out:
        if ent.loc in seen:
            continue
        seen.add(ent.loc)
        dedup.append(ent)
    return dedup


# ─────────────────────────────────────────────────────────────────────────────
# Persist + enrich (mirror of backfill_youtube)
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_source(session: Session, name: str) -> Optional[Source]:
    """Find the Source row by exact name match."""
    return session.exec(select(Source).where(Source.name == name)).first()


def _build_mention(source: Source, ent: _UrlEntry, body: str, title: str, author: Optional[str]) -> _Mention:
    slug = _slugify(source.name)
    # article_mention_id uses the canonical URL for stable de-dup across refetches.
    # We use rss_article_id with the URL as guid, matching tier1.rss's behavior
    # for "article" mentions inside RSS feeds — keeps mention_id semantics
    # consistent with daily ingest.
    mention_id = rss_article_id(slug, ent.loc)
    raw_text = body
    return _Mention(
        mention_id=mention_id,
        source_title=title or "(untitled)",
        source_url=ent.loc,
        raw_text=raw_text,
        author=author,
        published_at=ent.published_at,
        source=slug,
        raw={
            "sitemap_date_source": ent.date_source,
            "backfill": "news_sitemap",
        },
    )


def _persist_item(session: Session, source: Source, m: _Mention) -> Optional[int]:
    """Mirror of backfill_youtube._persist_item. Returns item.id or None on dedup."""
    existing_item = session.exec(select(Item).where(Item.url == m.source_url)).first()
    if existing_item:
        return None
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
    """Run the per-item enrich branch (non-YT — body comes from item.body_text)."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────
def backfill(
    start: datetime,
    end: datetime,
    source_filter: Optional[str],
    dry_run: bool,
    limit_per_source: Optional[int],
) -> dict:
    """Top-level driver. Mirrors backfill_youtube.backfill structure."""
    if source_filter:
        targets = [r for r in SOURCE_RECIPES if r.name == source_filter]
        if not targets:
            log.error(
                "unknown source name: %s; known=%s",
                source_filter, [r.name for r in SOURCE_RECIPES],
            )
            return {"error": "unknown source"}
    else:
        targets = list(SOURCE_RECIPES)

    rl = RateLimiter(default_rps=1.0, default_burst=1)
    robots = RobotsChecker(user_agent=_DEFAULT_UA)

    grand = {
        "sources": 0,
        "enumerated": 0,
        "in_range": 0,
        "deduped": 0,
        "ingested": 0,
        "enriched_ok": 0,
        "enriched_skipped": 0,
        "enriched_failed": 0,
        "robots_blocked": 0,
        "fetch_failed": 0,
        "errors": 0,
    }

    started = datetime.utcnow()
    with Session(engine) as outer_session:
        run = RunLog(job_type="backfill_news", status="running", started_at=started)
        outer_session.add(run)
        outer_session.commit()
        outer_session.refresh(run)
        run_id = run.id

    for recipe in targets:
        grand["sources"] += 1
        log.info("=== source %s (%s) ===", recipe.name, recipe.kind)

        try:
            entries = _enumerate_urls_in_window(recipe, start, end, rl)
        except Exception as e:  # noqa: BLE001
            log.error("enumerate failed for %s: %s: %s", recipe.name, type(e).__name__, e)
            grand["errors"] += 1
            continue

        grand["enumerated"] += len(entries)
        if limit_per_source:
            entries = entries[:limit_per_source]
        grand["in_range"] += len(entries)
        log.info("[%s] in-window entries: %d (capped to %s)", recipe.name, len(entries), limit_per_source or "no-cap")

        with Session(engine) as session:
            source = _resolve_source(session, recipe.name)
            if source is None:
                log.error("no Source row for %s; skipping", recipe.name)
                grand["errors"] += 1
                continue

            src_dedup = 0
            src_ingested = 0
            src_enr_ok = 0
            src_enr_skip = 0
            src_enr_fail = 0
            src_robots = 0
            src_fetch_fail = 0

            for ent in entries:
                # URL-level dedup BEFORE doing any work (coexists with the
                # parallel YT backfill: both insert into the same items table,
                # and items.url is the dedup key).
                existing = session.exec(select(Item).where(Item.url == ent.loc)).first()
                if existing:
                    src_dedup += 1
                    log.info("  [dedup] %s (item_id=%d)", ent.loc, existing.id)
                    continue

                # robots.txt gate.
                if not robots.allowed(ent.loc):
                    src_robots += 1
                    log.info("  [robots-blocked] %s", ent.loc)
                    continue

                log.info("  [%s] %s  %s", ent.published_at.date() if ent.published_at else "?", ent.date_source, ent.loc)

                if dry_run:
                    continue

                # Rate-limit the article fetch per-domain (same rate limiter
                # so sitemap + article share the bucket).
                domain = urlparse(ent.loc).netloc
                while not rl.try_acquire(domain):
                    time.sleep(min(rl.wait_seconds(domain), 1.0))

                try:
                    mentions = _fetch_article(ent.loc)
                except Exception as e:  # noqa: BLE001
                    src_fetch_fail += 1
                    log.warning("    article fetch failed (%s): %s", type(e).__name__, e)
                    continue

                if not mentions:
                    src_fetch_fail += 1
                    log.info("    no body extracted (trafilatura returned empty)")
                    continue

                rm = mentions[0]
                body = rm.raw_text or ""
                if len(body) < ENRICH_BODY_CHAR_MIN:
                    src_fetch_fail += 1
                    log.info("    body too short (%d chars)", len(body))
                    continue

                # Cross-check lastmod-only dates against article:published_time
                # meta tag. If the meta tag says the article is OUTSIDE our
                # window, skip — the lastmod was an evergreen refresh, not
                # a real publish.
                final_pub = ent.published_at
                if ent.date_source == "lastmod":
                    # trafilatura's Document.date is also available — we
                    # already have it via rm.published_at.
                    if rm.published_at is not None:
                        meta_dt = rm.published_at
                    else:
                        meta_dt = _fetch_article_published_meta(ent.loc, rl)
                    if meta_dt is not None:
                        if not (start.date() <= meta_dt.date() <= end.date()):
                            log.info(
                                "    [out-of-window] meta:published_time=%s outside [%s..%s]; skipping",
                                meta_dt.date(), start.date(), end.date(),
                            )
                            continue
                        final_pub = meta_dt

                title = rm.source_title or ent.loc
                author = rm.author

                # Build mention with the (possibly meta-corrected) date.
                ent_for_build = _UrlEntry(loc=ent.loc, published_at=final_pub, date_source=ent.date_source)
                m = _build_mention(source, ent_for_build, body, title, author)

                try:
                    item_id = _persist_item(session, source, m)
                except Exception as e:  # noqa: BLE001
                    log.warning("    persist failed: %s: %s", type(e).__name__, e)
                    grand["errors"] += 1
                    session.rollback()
                    continue
                if item_id is None:
                    src_dedup += 1
                    log.info("    -> deduped at persist (race)")
                    continue
                src_ingested += 1

                try:
                    status, info = _enrich_one(session, item_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("    enrich orchestration error item=%d: %s: %s",
                                item_id, type(e).__name__, e)
                    grand["errors"] += 1
                    continue
                if status == "ok":
                    src_enr_ok += 1
                    log.info("    -> item_id=%d enrich=ok", item_id)
                elif status == "skipped":
                    src_enr_skip += 1
                    log.info("    -> item_id=%d enrich=skipped (%s)", item_id, info)
                else:
                    src_enr_fail += 1
                    log.warning("    -> item_id=%d enrich=failed (%s)", item_id, info)

            grand["deduped"] += src_dedup
            grand["ingested"] += src_ingested
            grand["enriched_ok"] += src_enr_ok
            grand["enriched_skipped"] += src_enr_skip
            grand["enriched_failed"] += src_enr_fail
            grand["robots_blocked"] += src_robots
            grand["fetch_failed"] += src_fetch_fail

            log.info(
                "[%s] summary: in_range=%d dedup=%d ingested=%d "
                "enriched ok/skip/fail=%d/%d/%d robots=%d fetch_fail=%d",
                recipe.name, len(entries), src_dedup, src_ingested,
                src_enr_ok, src_enr_skip, src_enr_fail, src_robots, src_fetch_fail,
            )

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
                run.error = f"{grand['errors']} source/item-level errors"
            session.add(run)
            session.commit()

    return grand


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--source", default=None,
                    help='Restrict to one source (exact sources.yaml name, e.g. "PC Gamer")')
    ap.add_argument("--dry-run", action="store_true",
                    help="Enumerate + print; no body fetch, no DB writes")
    ap.add_argument("--limit-per-source", type=int, default=None,
                    help="Cap entries per source after date filter")
    args = ap.parse_args()

    try:
        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as e:
        log.error("bad date: %s", e)
        return 2
    if end < start:
        log.error("--end %s < --start %s", args.end, args.start)
        return 2

    log.info("=== backfill_news start ===")
    log.info(
        "  window=%s..%s source=%s dry_run=%s limit_per_source=%s",
        args.start, args.end, args.source or "ALL",
        args.dry_run, args.limit_per_source,
    )
    t0 = time.time()
    totals = backfill(
        start=start,
        end=end,
        source_filter=args.source,
        dry_run=args.dry_run,
        limit_per_source=args.limit_per_source,
    )
    elapsed = time.time() - t0
    log.info("=== backfill_news done in %.1fs ===", elapsed)
    log.info("TOTALS: %s", json.dumps(totals, indent=2))
    return 0 if totals.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
