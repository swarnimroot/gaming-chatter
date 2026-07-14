"""Unit tests for the YouTube feed fetch in app/services/scrapers.py.

YouTube's feeds/videos.xml endpoint intermittently soft-blocks by IP reputation
with a 404 (observed 06-16 onward: all channels dark for multi-day streaks,
then self-recover). _fetch_youtube_rss sends a browser User-Agent instead of
the scrapers-lib bot UA and retries once on 404. These tests cover the browser
UA, the single 404 retry, retry exhaustion, and non-404 pass-through. No
network — httpx.get, time.sleep, and parse_rss_feed are monkeypatched."""

import httpx
import pytest

import app.services.scrapers as scrapers

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UC123"


@pytest.fixture()
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(scrapers.time, "sleep", lambda s: slept.append(s))
    return slept


def _ok_response():
    return httpx.Response(200, content=b"<feed/>", request=httpx.Request("GET", FEED))


def _err_response(code):
    return httpx.Response(code, request=httpx.Request("GET", FEED))


def test_success_first_try_no_retry(no_sleep, monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, follow_redirects=None, timeout=None):
        calls["n"] += 1
        return _ok_response()

    monkeypatch.setattr(scrapers.httpx, "get", fake_get)
    monkeypatch.setattr(scrapers._rss, "parse_rss_feed", lambda body, url, source_slug=None: ["item"])

    assert scrapers._fetch_youtube_rss(FEED, "gameranx") == ["item"]
    assert calls["n"] == 1
    assert no_sleep == []


def test_sends_browser_user_agent(no_sleep, monkeypatch):
    seen = {}

    def fake_get(url, headers=None, follow_redirects=None, timeout=None):
        seen["headers"] = headers
        return _ok_response()

    monkeypatch.setattr(scrapers.httpx, "get", fake_get)
    monkeypatch.setattr(scrapers._rss, "parse_rss_feed", lambda *a, **k: [])

    scrapers._fetch_youtube_rss(FEED, "x")
    ua = seen["headers"]["User-Agent"]
    assert "Chrome" in ua and "Mozilla" in ua
    assert "scrapers-lib" not in ua  # not the bot UA


def test_404_retries_once_then_succeeds(no_sleep, monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, follow_redirects=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _err_response(404)
        return _ok_response()

    monkeypatch.setattr(scrapers.httpx, "get", fake_get)
    monkeypatch.setattr(scrapers._rss, "parse_rss_feed", lambda *a, **k: ["ok"])

    assert scrapers._fetch_youtube_rss(FEED, "x") == ["ok"]
    assert calls["n"] == 2
    assert no_sleep == [pytest.approx(scrapers._YT_404_RETRY_DELAY_S)]


def test_404_twice_raises(no_sleep, monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, follow_redirects=None, timeout=None):
        calls["n"] += 1
        return _err_response(404)

    monkeypatch.setattr(scrapers.httpx, "get", fake_get)
    monkeypatch.setattr(scrapers._rss, "parse_rss_feed", lambda *a, **k: [])

    with pytest.raises(httpx.HTTPStatusError):
        scrapers._fetch_youtube_rss(FEED, "x")
    assert calls["n"] == 2  # initial + one retry, then give up
    assert no_sleep == [pytest.approx(scrapers._YT_404_RETRY_DELAY_S)]


def test_non_404_error_propagates_without_retry(no_sleep, monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, follow_redirects=None, timeout=None):
        calls["n"] += 1
        return _err_response(500)

    monkeypatch.setattr(scrapers.httpx, "get", fake_get)
    monkeypatch.setattr(scrapers._rss, "parse_rss_feed", lambda *a, **k: [])

    with pytest.raises(httpx.HTTPStatusError):
        scrapers._fetch_youtube_rss(FEED, "x")
    assert calls["n"] == 1  # no retry on non-404
    assert no_sleep == []
