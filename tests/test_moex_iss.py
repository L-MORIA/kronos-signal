"""Тесты scripts/moex_iss.py — CLI из SKILL.md (все запросы мокаются)."""
import json
import sys
import types

import pytest

from conftest import _load_module


@pytest.fixture(scope="module")
def moex():
    return _load_module("moex_iss_mod", "scripts/moex_iss.py")


class FakeResponse:
    def __init__(self, payload, text=None):
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def patch_get(monkeypatch, moex, routes):
    """routes: callable(url, params) -> payload (или None для сетевой ошибки)."""

    def fake_get(url, params=None, timeout=None):
        result = routes(url, params or {})
        if result is None:
            raise moex.requests.ConnectionError("network down")
        return FakeResponse(result)

    monkeypatch.setattr(moex.requests, "get", fake_get)


def iss_block(name, columns, data):
    return {name: {"columns": columns, "data": data}}


# ── block(): колонки в любом регистре ─────────────────────────────────

def test_block_uppercases_columns(moex):
    payload = iss_block("candles", ["open", "close"], [[1.0, 2.0]])
    rows = moex.block(payload, "candles")
    assert rows[0]["OPEN"] == 1.0 and rows[0]["CLOSE"] == 2.0


def test_block_missing_is_safe(moex):
    assert moex.block(None, "x") == []
    assert moex.block({}, "x") == []


# ── is_valid_ticker ───────────────────────────────────────────────────

def test_is_valid_ticker(moex):
    assert moex.is_valid_ticker("SBER")
    assert moex.is_valid_ticker("YDEX")
    assert not moex.is_valid_ticker("../evil")
    assert not moex.is_valid_ticker("")
    assert not moex.is_valid_ticker("..")
    assert not moex.is_valid_ticker("SBER SBER")


# ── quote ─────────────────────────────────────────────────────────────

def test_quote_formats_price_change_volume(moex, monkeypatch, capsys):
    def routes(url, params):
        if url.endswith("/securities/SBER/boards.json"):
            return iss_block("boards", ["secid", "boardid", "is_traded", "is_primary"],
                             [["SBER", "TQBR", 1, 1]])
        assert url.endswith("/SBER/marketdata.json"), url
        return iss_block("marketdata",
                         ["SECID", "LAST", "LASTCHANGE", "LASTCHANGEPRCNT", "VOLTODAY", "VALTODAY"],
                         [["SBER", 300.76, -0.43, -0.14, 1357409, 408275326]])

    patch_get(monkeypatch, moex, routes)
    moex.main(["quote", "SBER"])
    out = capsys.readouterr().out
    assert "SBER @ 300.76 rub" in out
    assert "-0.43" in out and "-0.14%" in out
    assert "vol=" in out and "val=" in out


def test_quote_invalid_ticker_rejected(moex):
    with pytest.raises(SystemExit):
        moex.main(["quote", "../evil"])


def test_quote_no_data_on_weekend(moex, monkeypatch, capsys):
    """Выходной: бумага найдена, но LAST нет — сообщение, а не крэш
    (по формату ответа из SKILL.md)."""

    def routes(url, params):
        if url.endswith("/boards.json"):
            return iss_block("boards", ["secid", "boardid", "is_traded", "is_primary"],
                             [["XXX", "TQBR", 1, 1]])
        return iss_block("marketdata", ["SECID", "LAST"], [["XXX", None]])

    patch_get(monkeypatch, moex, routes)
    moex.main(["quote", "XXX"])
    assert "нет данных" in capsys.readouterr().out


def test_quote_unknown_security_exits(moex, monkeypatch):
    def routes(url, params):
        if url.endswith("/boards.json"):
            return iss_block("boards", ["secid", "boardid", "is_traded", "is_primary"],
                             [["QQQ", "TQBR", 1, 1]])
        return iss_block("marketdata", ["SECID", "LAST"], [])

    patch_get(monkeypatch, moex, routes)
    with pytest.raises(SystemExit):
        moex.main(["quote", "QQQ"])


# ── portfolio ─────────────────────────────────────────────────────────

def test_portfolio_table_and_total(moex, monkeypatch, capsys):
    prices = {"SBER": (300.0, +1.5, +0.5, 1000, 300000),
              "GAZP": (120.0, -0.5, -0.4, 2000, 240000)}

    def routes(url, params):
        if url.endswith("/boards.json"):
            return iss_block("boards", ["secid", "boardid", "is_traded", "is_primary"],
                             [["SBER", "TQBR", 1, 1]])
        for t in prices:
            if url.endswith(f"/{t}/marketdata.json"):
                v = prices[t]
                return iss_block("marketdata",
                                 ["SECID", "LAST", "LASTCHANGE", "LASTCHANGEPRCNT", "VOLTODAY", "VALTODAY"],
                                 [[t, v[0], v[1], v[2], v[3], v[4]]])
        raise AssertionError(url)

    patch_get(monkeypatch, moex, routes)
    moex.main(["portfolio", "SBER,GAZP"])
    out = capsys.readouterr().out
    assert "SBER" in out and "GAZP" in out and "300.00" in out and "120.00" in out
    assert "540 000" in out  # суммарный объём


# ── candles: пагинация по start + форматы вывода ──────────────────────

def candle_page(n, start_no):
    return iss_block("candles",
                     ["open", "close", "high", "low", "volume", "begin", "end"],
                     [[100 + start_no + i, 101 + start_no + i, 102, 99, 500,
                       f"2026-10-2{i % 3} 10:{(start_no + i) % 60:02d}:00",
                       f"2026-10-2{i % 3} 10:{(start_no + i) % 60:02d}:59"]
                      for i in range(n)])


def test_candles_paginates_until_short_page(moex, monkeypatch, capsys):
    calls = []

    def routes(url, params):
        if url.endswith("/boards.json"):
            return iss_block("boards", ["secid", "boardid", "is_traded", "is_primary"],
                             [["SBER", "TQBR", 1, 1]])
        calls.append(params["start"])
        # первая страница полная (500), вторая короткая (13) -> стоп
        return candle_page(moex.CANDLE_PAGE, params["start"]) if params["start"] == 0 \
            else candle_page(13, params["start"])

    patch_get(monkeypatch, moex, routes)
    moex.main(["candles", "SBER", "--interval", "60", "--days", "5"])
    out = capsys.readouterr().out
    assert calls == [0, moex.CANDLE_PAGE]
    assert "свечей=513" in out


def test_candles_json_output(moex, monkeypatch, capsys):
    def routes(url, params):
        if url.endswith("/boards.json"):
            return iss_block("boards", ["secid", "boardid", "is_traded", "is_primary"],
                             [["SBER", "TQBR", 1, 1]])
        return candle_page(3, 0)

    patch_get(monkeypatch, moex, routes)
    moex.main(["--output", "json", "candles", "SBER", "--interval", "60"])
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 3 and "OPEN" in data[0]


def test_candles_csv_output(moex, monkeypatch, capsys):
    def routes(url, params):
        if url.endswith("/boards.json"):
            return iss_block("boards", ["secid", "boardid", "is_traded", "is_primary"],
                             [["SBER", "TQBR", 1, 1]])
        return candle_page(2, 0)

    patch_get(monkeypatch, moex, routes)
    moex.main(["--output", "csv", "candles", "SBER", "--interval", "60"])
    out = capsys.readouterr().out
    assert out.startswith("begin,open,high,low,close,volume")
    assert out.count("\n") == 3  # заголовок + 2 строки


def test_candles_empty_means_weekend(moex, monkeypatch):
    def routes(url, params):
        if url.endswith("/boards.json"):
            return iss_block("boards", ["secid", "boardid", "is_traded", "is_primary"],
                             [["SBER", "TQBR", 1, 1]])
        return iss_block("candles", ["open"], [])

    patch_get(monkeypatch, moex, routes)
    with pytest.raises(SystemExit, match="выходные"):
        moex.main(["candles", "SBER", "--interval", "24"])


def test_candles_rejects_bad_interval(moex):
    with pytest.raises(SystemExit):
        moex.main(["candles", "SBER", "--interval", "5"])  # 5-min нет в ISS


# ── news ──────────────────────────────────────────────────────────────

def test_news_filters_by_days_and_unescapes_html(moex, monkeypatch, capsys):
    import datetime as dt
    fresh = dt.datetime.now() - dt.timedelta(hours=2)
    stale = dt.datetime.now() - dt.timedelta(days=10)

    def routes(url, params):
        assert "sitenews" in url
        assert params.get("q") == "SBERP"
        return iss_block("sitenews", ["id", "title", "published_at"],
                         [[1, 'Итоги дня &quot;Сбербанк&quot; преф',
                           fresh.strftime("%Y-%m-%d %H:%M:%S")],
                          [2, "старая новость", stale.strftime("%Y-%m-%d %H:%M:%S")]])

    patch_get(monkeypatch, moex, routes)
    moex.main(["news", "SBERP", "--days", "3"])
    out = capsys.readouterr().out
    assert '"Сбербанк"' in out      # html.unescape сработал
    assert "старая новость" not in out
    assert "Всего: 1" in out


# ── security / board ──────────────────────────────────────────────────

def test_security_info(moex, monkeypatch, capsys):
    def routes(url, params):
        return iss_block("securities",
                         ["secid", "name", "isin", "type", "group", "is_traded", "primary_boardid"],
                         [["FIXSBER", "Фиксинг", None, None, None, 1, None],
                          ["SBER", "Сбербанк России ПАО ао", "RU0009029540",
                           "common_share", "stock_shares", 1, "TQBR"]])

    patch_get(monkeypatch, moex, routes)
    moex.main(["security", "SBER"])
    out = capsys.readouterr().out
    assert "RU0009029540" in out and "TQBR" in out
    assert "Фиксинг" not in out    # отфильтровали по точному SECID


def test_board_marks_primary(moex, monkeypatch, capsys):
    def routes(url, params):
        return iss_block("boards",
                         ["secid", "boardid", "title", "is_traded", "is_primary", "currencyid"],
                         [["SBER", "TQBR", "Т+: основной", 1, 1, "RUB"],
                          ["SBER", "SMAL", "неполные лоты", 0, 0, "RUB"]])

    patch_get(monkeypatch, moex, routes)
    moex.main(["board", "SBER"])
    out = capsys.readouterr().out
    assert "* TQBR" in out          # основная доска помечена
    assert "SMAL" in out and "закрыта" in out


# ── indices ───────────────────────────────────────────────────────────

def test_indices_shows_requested(moex, monkeypatch, capsys):
    def routes(url, params):
        assert "index" in url
        payload = {}
        payload.update(iss_block("securities", ["SECID", "SHORTNAME"],
                                 [["IMOEX", "Индекс МосБиржи"], ["RTSI", "RTS Index"]]))
        payload.update(iss_block("marketdata",
                                 ["SECID", "CURRENTVALUE", "LASTCHANGEPRC"],
                                 [["IMOEX", 2469.36, 1.64], ["RTSI", 1080.55, 1.71]]))
        return payload

    patch_get(monkeypatch, moex, routes)
    moex.main(["indices", "IMOEX,RTSI"])
    out = capsys.readouterr().out
    assert "2469.36" in out and "+1.64%" in out
    assert "RTSI" in out and "1080.55" in out


def test_indices_skips_missing(moex, monkeypatch, capsys):
    def routes(url, params):
        payload = iss_block("securities", ["SECID", "SHORTNAME"], [["IMOEX", "ИМ"]])
        payload["marketdata"] = {"columns": ["SECID", "CURRENTVALUE", "LASTCHANGEPRC"],
                                 "data": [["IMOEX", 2469.36, 1.64]]}
        return payload

    patch_get(monkeypatch, moex, routes)
    moex.main(["indices", "IMOEX,NOINDEX"])
    out = capsys.readouterr().out
    assert "IMOEX" in out and "NOINDEX" not in out


# ── network resilience ────────────────────────────────────────────────

def test_iss_get_returns_none_on_network_error(moex, monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise moex.requests.ConnectionError("down")

    monkeypatch.setattr(moex.requests, "get", fake_get)
    monkeypatch.setattr(moex.time, "sleep", lambda s: None)
    assert moex.iss_get("https://iss.moex.com/iss/x.json") is None


# ── interpret() опечатка (фикс этого прохода) ─────────────────────────

def test_interpret_no_typo_padenie(run_mod):
    text = run_mod.interpret("SBERP", 300.0, 295.0, "HOLD", -1.7, 10)
    assert "Уверенность в падении" in text
    assert "в падение" not in text


# ── dividends: ISS-блок удалён, фолбэк на smart-lab ──────────────────

SMARTLAB_HTML = """
<html><body><table>
<tr><th>Компания</th><th>Тикер</th><th>Период</th><th>Дивиденд, руб</th>
<th>Доходность</th><th></th><th>Дата закр. реестра</th><th>Посл. день с див.</th>
<th>Дата выплаты</th><th>Цена закр.</th></tr>
<tr><td>ЛУКОЙЛ</td><td>LKOH</td><td>3кв 2026</td><td>535</td><td>8,7%</td><td></td>
<td>08.12.2026</td><td>09.12.2026</td><td>19.12.2026</td><td>6147</td></tr>
<tr><td>Сбербанк-п</td><td>SBERP</td><td>2кв 2026</td><td>45,60</td><td>15,2%</td><td></td>
<td>10.07.2026</td><td>09.07.2026</td><td>25.07.2026</td><td>299</td></tr>
<tr><td>мусорная строка без ячеек</td></tr>
<tr><td>Плохая сумма</td><td>XXX</td><td>1кв</td><td>n/a</td><td></td><td></td>
<td>01.01.2026</td><td>02.01.2026</td><td>03.01.2026</td><td>1</td></tr>
</table></body></html>
"""


def test_parse_smartlab_dividends(moex):
    rows = moex.parse_smartlab_dividends(SMARTLAB_HTML)
    assert {r["ticker"] for r in rows} == {"LKOH", "SBERP"}
    lkoh = next(r for r in rows if r["ticker"] == "LKOH")
    assert lkoh["amount"] == 535.0
    assert lkoh["registry_date"] == "08.12.2026"
    assert lkoh["pay_date"] == "19.12.2026"
    sberp = next(r for r in rows if r["ticker"] == "SBERP")
    assert sberp["amount"] == 45.60  # запятая как десятичный разделитель
    assert sberp["name"] == "Сбербанк-п"


def test_dividends_falls_back_to_smartlab(moex, monkeypatch, capsys):
    def fake_get(url, params=None, timeout=None, headers=None):
        if "smart-lab" in url:
            return FakeResponse(None, text=SMARTLAB_HTML)
        # ISS отдаёт descriptor без блока dividends
        return FakeResponse({"description": {"columns": [], "data": []}})

    monkeypatch.setattr(moex.requests, "get", fake_get)
    moex.main(["dividends", "LKOH"])
    out = capsys.readouterr().out
    assert "smart-lab" in out and "535.00" in out and "08.12.2026" in out


def test_dividends_no_declared_exits(moex, monkeypatch):
    def routes(url, params=None, timeout=None, headers=None):
        if "iss.moex" in url:
            return FakeResponse({"description": {"columns": [], "data": []}})
        return FakeResponse(None, text=SMARTLAB_HTML)

    monkeypatch.setattr(moex.requests, "get", routes)
    with pytest.raises(SystemExit, match="объявлений нет"):
        moex.main(["dividends", "VTBR"])


def test_dividends_uses_iss_block_if_returned(moex, monkeypatch, capsys):
    """Если MOEX вернёт блок dividends — приоритет у официального ISS."""

    def routes(url, params=None, timeout=None):
        if url.endswith("/SBER/dividends.json"):
            return FakeResponse(iss_block("dividends",
                                          ["registryclosedate", "dividendsum"],
                                          [["2026-07-10", 45.6]]))
        raise AssertionError("smart-lab не должен запрашиваться: " + url)

    monkeypatch.setattr(moex.requests, "get", routes)
    moex.main(["dividends", "SBER"])
    out = capsys.readouterr().out
    assert "2026-07-10" in out and "45.60" in out
    assert "smart-lab" not in out
