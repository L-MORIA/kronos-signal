"""Tests for rss_market_news.py fixes."""
import datetime
import io
from pathlib import Path

from conftest import PROJECT_ROOT


# ── cache location ────────────────────────────────────────────────────

def test_cache_dir_inside_project(rss_mod):
    """Regression: CACHE_DIR used to point one level ABOVE the project root
    (`dirname(__file__)/../news_cache`), littering outside the repo."""
    expected = PROJECT_ROOT / "news_cache"
    assert Path(rss_mod.CACHE_DIR).resolve() == expected.resolve()


# ── ticker matching ───────────────────────────────────────────────────

def test_match_known_ticker(rss_mod):
    assert rss_mod.match("Сбербанк отчитался", ["SBER"]) == "SBER"


def test_match_unknown_ticker_no_keyerror(rss_mod):
    """Regression: match() did TICKER_KW[ticker] and raised KeyError for any
    ticker without keyword mapping (e.g. MTSS from --tickers)."""
    assert rss_mod.match("лукойл новость", ["MTSS"]) is None
    assert rss_mod.match("сбер новость", ["MTSS", "SBER"]) == "SBER"


# ── date parsing ──────────────────────────────────────────────────────

def test_parse_dt_with_timezone(rss_mod):
    dt = rss_mod.parse_dt("Thu, 22 Oct 2026 12:34:56 +0300")
    assert dt != datetime.datetime.min
    assert dt.hour == 12 and dt.minute == 34


def test_parse_dt_without_timezone(rss_mod):
    """Regression: the old rsplit-based parser failed on dates without a
    timezone suffix (it stripped the seconds instead)."""
    dt = rss_mod.parse_dt("Thu, 22 Oct 2026 12:34:56")
    assert dt == datetime.datetime(2026, 10, 22, 12, 34, 56)


def test_parse_dt_garbage(rss_mod):
    assert rss_mod.parse_dt("") == datetime.datetime.min
    assert rss_mod.parse_dt("not a date at all") == datetime.datetime.min


# ── XML hardening ─────────────────────────────────────────────────────

GOOD_RSS = """<?xml version="1.0"?>
<rss><channel>
<item><title>Сбербанк news</title><link>https://ex/1</link>
<description>desc</description><pubDate>Thu, 22 Oct 2026 12:34:56 +0300</pubDate></item>
</channel></rss>"""

ENTITY_BOMB = """<?xml version="1.0"?>
<!DOCTYPE rss [<!ENTITY a "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">]>
<rss><channel>
<item><title>&a;&a;&a;</title><link>https://ex/2</link></item>
</channel></rss>"""


class FakeUrlopen:
    def __init__(self, raw):
        self._raw = raw

    def read(self):
        return self._raw


def test_fetch_rejects_dtd_payload(rss_mod, monkeypatch):
    """DOCTYPE/ENTITY payloads must be refused (XML bomb / XXE shield)."""
    monkeypatch.setattr(rss_mod, "urlopen", lambda req, timeout=15: FakeUrlopen(ENTITY_BOMB.encode()))
    assert rss_mod.fetch("https://example.com/rss") == []


def test_fetch_parses_good_payload(rss_mod, monkeypatch):
    monkeypatch.setattr(rss_mod, "urlopen", lambda req, timeout=15: FakeUrlopen(GOOD_RSS.encode()))
    items = rss_mod.fetch("https://example.com/rss")
    assert len(items) == 1
    assert items[0]["title"] == "Сбербанк news"
    assert items[0]["pub"] == "Thu, 22 Oct 2026 12:34:56 +0300"
