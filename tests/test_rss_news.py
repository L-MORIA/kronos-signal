"""Тесты RSS-матчинга rss_market_news.py (второй проход аудита):

- match(): паттерны с regex-метасимволами ("сбер.?преф") работают через
  re.search — substring-поиск их убивал
- match(): специфичность вместо порядка — «сбербанк преф» больше не
  приписывается SBER, чьё короткое «сбер» проверялось первым
- main(): неизвестные тикеры фильтруются с предупреждением, скрипт не падает
"""
import sys


def test_match_sberp_regex_pattern(rss_mod):
    """"сбер.?преф" содержит regex-метасимволы: substring-поиск его убивал."""
    assert rss_mod.match("Котировки сбер-преф обновили максимум", ["SBERP"]) == "SBERP"
    assert rss_mod.match("Дивиденды сбер преф утвердили", ["SBERP"]) == "SBERP"
    assert rss_mod.match("куплю sberp дёшево", ["SBERP"]) == "SBERP"


def test_match_sberp_not_shadowed_by_sber(rss_mod):
    """Новость про префы не должна приписываться SBER, даже если SBER
    идёт первым в списке (раньше решал порядок, а не специфичность)."""
    text = "Дивиденды сбербанк преф утвердили"
    assert rss_mod.match(text, ["SBER", "SBERP"]) == "SBERP"
    assert rss_mod.match(text, ["SBERP", "SBER"]) == "SBERP"


def test_match_plain_sber_news_still_sber(rss_mod):
    assert rss_mod.match("Сбербанк запустил новый сервис", ["SBER", "SBERP"]) == "SBER"


def test_match_no_hit(rss_mod):
    assert rss_mod.match("Погода в Москве завтра", ["GAZP"]) is None


# ── интеграция: main() с неизвестным тикером не падает ────────────────

def test_main_unknown_ticker_filtered(rss_mod, monkeypatch):
    """--tickers MOEX раньше ронял скрипт KeyError в match(); теперь
    тикер отфильтровывается с предупреждением, цикл по фидам не запускается."""
    called = []
    monkeypatch.setattr(rss_mod, "fetch", lambda url: called.append(url) or [])
    monkeypatch.setattr(rss_mod, "load_seen", lambda: set())
    monkeypatch.setattr(rss_mod, "save_seen", lambda urls: None)
    monkeypatch.setattr(sys, "argv", ["rss_market_news.py", "--tickers", "MOEX"])
    rss_mod.main()
    assert called == []  # фиды даже не опрашивались — нет известных тикеров
