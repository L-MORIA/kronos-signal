"""Hermetic tests for rss_market_news.main(): grouping, dedup via --cron, JSON."""
import datetime
import json
import sys
from email.utils import format_datetime

import pytest


def recent_pub(hours_ago):
    """RFC-822 date `hours_ago` before the real clock (no tz -> machine-local)."""
    return format_datetime(datetime.datetime.now() - datetime.timedelta(hours=hours_ago))


ITEMS_SBER = {
    "title": "Сбербанк улучшил прогноз",
    "link": "https://example.com/sber-1",
    "desc": "Сбербанк news body",
    "pub": recent_pub(2),
}
ITEMS_LKOH = {
    "title": "Лукойл отчитался",
    "link": "https://example.com/lkoh-1",
    "desc": "Лукойл news body",
    "pub": recent_pub(1),
}


@pytest.fixture
def isolated_rss(rss_mod, monkeypatch, tmp_path):
    seen_file = tmp_path / "seen_urls.txt"
    monkeypatch.setattr(rss_mod, "SEEN_FILE", str(seen_file))
    return rss_mod, seen_file


def run_rss(rss_mod, monkeypatch, argv, items):
    monkeypatch.setattr(rss_mod, "fetch", lambda url: items if "example" in url else [])
    monkeypatch.setattr(rss_mod, "RSS_FEEDS", {"Test": "https://example.com/rss"})
    monkeypatch.setattr(sys, "argv", argv)
    rss_mod.main()


def test_main_groups_by_ticker_and_records_seen(isolated_rss, monkeypatch, capsys):
    rss_mod, seen_file = isolated_rss
    run_rss(rss_mod, monkeypatch,
            ["rss", "--hours", "24", "--tickers", "SBER,LKOH"],
            [ITEMS_SBER, ITEMS_LKOH])
    out = capsys.readouterr().out
    assert "SBER" in out          # group headers use ticker names
    assert "LKOH" in out
    assert "Всего: 2, новых: 2" in out
    saved = seen_file.read_text(encoding="utf-8").split()
    assert "https://example.com/sber-1" in saved
    assert "https://example.com/lkoh-1" in saved


def test_main_cron_deduplicates_seen_links(isolated_rss, monkeypatch, capsys):
    rss_mod, seen_file = isolated_rss
    argv = ["rss", "--hours", "24", "--tickers", "SBER,LKOH"]
    run_rss(rss_mod, monkeypatch, argv, [ITEMS_SBER, ITEMS_LKOH])
    capsys.readouterr()
    # second run in cron mode: everything already seen
    run_rss(rss_mod, monkeypatch, argv + ["--cron"], [ITEMS_SBER, ITEMS_LKOH])
    out = capsys.readouterr().out
    assert "Нет новостей" in out


def test_main_json_output(isolated_rss, monkeypatch, capsys):
    rss_mod, _ = isolated_rss
    run_rss(rss_mod, monkeypatch,
            ["rss", "--json", "--hours", "24", "--tickers", "SBER"],
            [ITEMS_SBER])
    data = json.loads(capsys.readouterr().out)
    assert data[0]["ticker"] == "SBER"
    assert data[0]["src"] == "Test"
