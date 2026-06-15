"""Unit tests for the Reddit rate-gate in app/services/scrapers.py.

Reddit's unauthenticated RSS endpoint allows ~1 request / 60s per IP (measured
2026-06-15). These tests cover the host detection, the proactive spacing gate,
and the 429 backstop that honors x-ratelimit-reset. No network — scrapers-lib's
fetch_rss_feed and time.sleep are monkeypatched."""

import httpx
import pytest

import app.services.scrapers as scrapers


@pytest.mark.parametrize("url,expected", [
    ("https://www.reddit.com/r/Games/.rss", True),
    ("https://reddit.com/r/Games/.rss", True),
    ("https://old.reddit.com/r/Games/.rss", True),
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UC123", False),
    ("https://www.eurogamer.net/feed", False),
    ("https://notreddit.com.evil.com/x", False),
])
def test_is_reddit_url(url, expected):
    assert scrapers._is_reddit_url(url) is expected


@pytest.fixture()
def fake_clock(monkeypatch):
    state = {"now": 1000.0, "slept": []}
    monkeypatch.setattr(scrapers.time, "monotonic", lambda: state["now"])

    def fake_sleep(s):
        state["slept"].append(s)
        state["now"] += s  # advance the clock by the slept amount

    monkeypatch.setattr(scrapers.time, "sleep", fake_sleep)
    monkeypatch.setattr(scrapers, "_reddit_last_request", 0.0)
    return state


def test_gate_first_call_does_not_sleep(fake_clock):
    scrapers._reddit_rate_gate()
    assert fake_clock["slept"] == []


def test_gate_second_immediate_call_sleeps_full_interval(fake_clock):
    scrapers._reddit_rate_gate()
    scrapers._reddit_rate_gate()
    assert fake_clock["slept"] == [pytest.approx(scrapers._REDDIT_MIN_INTERVAL_S)]


def test_gate_partial_elapsed_sleeps_remainder(fake_clock):
    scrapers._reddit_rate_gate()           # claims slot at t=1000
    fake_clock["now"] += 20.0              # 20s pass externally
    scrapers._reddit_rate_gate()           # must sleep 65-20 = 45s
    assert fake_clock["slept"] == [pytest.approx(scrapers._REDDIT_MIN_INTERVAL_S - 20.0)]


def _resp_429(reset="30"):
    headers = {"x-ratelimit-reset": reset} if reset is not None else {}
    return httpx.Response(429, headers=headers, request=httpx.Request("GET", "https://www.reddit.com/r/X/.rss"))


def test_fetch_reddit_retries_on_429_honoring_reset(fake_clock, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(url, source_slug=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.HTTPStatusError("429", request=_resp_429().request, response=_resp_429("30"))
        return ["item"]

    monkeypatch.setattr(scrapers._rss, "fetch_rss_feed", fake_fetch)
    out = scrapers._fetch_reddit_rss("https://www.reddit.com/r/X/.rss", "x")
    assert out == ["item"]
    assert calls["n"] == 2
    # gate (no initial wait) + the 429 backstop sleep of reset+2 = 32s
    assert 32.0 in [pytest.approx(s) for s in fake_clock["slept"]]


def test_fetch_reddit_429_without_reset_falls_back_to_interval(fake_clock, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(url, source_slug=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.HTTPStatusError("429", request=_resp_429(None).request, response=_resp_429(None))
        return ["ok"]

    monkeypatch.setattr(scrapers._rss, "fetch_rss_feed", fake_fetch)
    out = scrapers._fetch_reddit_rss("https://www.reddit.com/r/X/.rss", "x")
    assert out == ["ok"]
    assert scrapers._REDDIT_MIN_INTERVAL_S in [pytest.approx(s) for s in fake_clock["slept"]]


def test_fetch_reddit_non_429_error_propagates(fake_clock, monkeypatch):
    def fake_fetch(url, source_slug=None):
        resp = httpx.Response(500, request=httpx.Request("GET", "https://www.reddit.com/r/X/.rss"))
        raise httpx.HTTPStatusError("500", request=resp.request, response=resp)

    monkeypatch.setattr(scrapers._rss, "fetch_rss_feed", fake_fetch)
    with pytest.raises(httpx.HTTPStatusError):
        scrapers._fetch_reddit_rss("https://www.reddit.com/r/X/.rss", "x")
