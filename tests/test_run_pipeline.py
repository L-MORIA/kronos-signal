"""Regression tests for the run.py data pipeline (both 5-min and hourly modes)."""
import datetime
import json
import types

import numpy as np
import pandas as pd
import pytest


def make_1min_df(start="2026-10-23 10:00", periods=120, freq="1min"):
    idx = pd.date_range(start, periods=periods, freq=freq)
    base = 100.0 + np.arange(periods, dtype=float) * 0.01
    return pd.DataFrame({
        "begin": idx,
        "open": base,
        "high": base + 0.5,
        "low": base - 0.5,
        "close": base + 0.2,
        "volume": np.full(periods, 100.0),
    })


# ── resample_ohlcv ────────────────────────────────────────────────────

def test_resample_5min_aggregates_ohlcv(run_mod):
    df = make_1min_df()
    out = run_mod.resample_ohlcv(df, "5min")
    assert len(out) == 24  # 120 1-min candles -> 24 5-min candles
    first = out.iloc[0]
    assert first["open"] == df["open"].iloc[0]
    assert first["high"] == df["high"].iloc[:5].max()
    assert first["low"] == df["low"].iloc[:5].min()
    assert first["close"] == df["close"].iloc[4]
    assert first["volume"] == 500.0


def test_resample_hourly_candles_stay_hourly(run_mod):
    """Regression: hourly source candles must not be blown up by a 5-min rule.

    Old code hardcoded resample('5min') — with 1h input it dropped 11/12
    empty bins (accidentally harmless) but fill_gaps then re-inflated the
    series. The pipeline rule must follow the config.
    """
    idx = pd.date_range("2026-10-23 07:00", periods=100, freq="1h")
    df = pd.DataFrame({
        "begin": idx, "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 100.5, "volume": 10.0,
    })
    out = run_mod.resample_ohlcv(df, "60min")
    assert len(out) == 100
    assert (out["begin"].diff().dropna() == pd.Timedelta("1h")).all()


def test_resample_noop_for_1min(run_mod):
    df = make_1min_df()
    out = run_mod.resample_ohlcv(df, "1min")
    assert len(out) == len(df)


# ── fill_gaps ─────────────────────────────────────────────────────────

def test_fill_gaps_hourly_does_not_inflate(run_mod):
    """Regression: fill_gaps hardcoded a 5-min grid, turning N hourly candles
    into ~12*N fake 5-min candles and destroying the hourly context window."""
    idx = pd.date_range("2026-10-23 07:00", periods=200, freq="1h")
    df = pd.DataFrame({
        "begin": idx, "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 100.5, "volume": 10.0,
    })
    out = run_mod.fill_gaps(df, "60min")
    assert len(out) == 200  # no gaps inside a continuous hourly range


def test_fill_gaps_closes_inner_gap(run_mod):
    a = make_1min_df("2026-10-23 10:00", periods=5)   # 10:00-10:04
    b = make_1min_df("2026-10-23 10:10", periods=5)   # 10:10-10:14
    df = pd.concat([a, b], ignore_index=True)
    out = run_mod.fill_gaps(df, "5min")
    # 5-min grid: 10:00, 10:05 (gap), 10:10 -> gap candle ffilled
    assert list(out["begin"]) == [
        pd.Timestamp("2026-10-23 10:00"),
        pd.Timestamp("2026-10-23 10:05"),
        pd.Timestamp("2026-10-23 10:10"),
    ]
    assert out.iloc[1]["close"] == out.iloc[0]["close"]  # carried forward
    assert out.iloc[1]["volume"] == 0


# ── future timestamps ─────────────────────────────────────────────────

def test_future_timestamps_follow_configured_freq(run_mod):
    """Regression: forecast horizon must be 24h in hourly mode, not 2h."""
    last = pd.Timestamp("2026-10-23 18:00")
    fut = run_mod.generate_future_timestamps(last, 24, "60min")
    assert len(fut) == 24
    assert fut.iloc[0] == last + pd.Timedelta("1h")
    assert fut.iloc[-1] - fut.iloc[0] == pd.Timedelta("23h")


def test_future_timestamps_5min(run_mod):
    fut = run_mod.generate_future_timestamps(pd.Timestamp("2026-10-23 18:00"), 24, "5min")
    assert fut.iloc[-1] - fut.iloc[0] == pd.Timedelta("1h55min")


def test_hourly_pipeline_horizon_matches_interpret_claim(run_mod, monkeypatch):
    """The footer/interpret text says PRED_LEN*RESAMPLE_TO minutes — the actual
    y_timestamps passed to the model must span the same horizon."""
    monkeypatch.setattr(run_mod, "PRED_LEN", 24)
    monkeypatch.setattr(run_mod, "RESAMPLE_TO", 60)
    idx = pd.date_range("2026-10-23 07:00", periods=100, freq="1h")
    df = pd.DataFrame({
        "begin": idx, "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 100.5, "volume": 10.0,
    })
    df = run_mod.fill_gaps(run_mod.resample_ohlcv(df, "60min"), "60min")
    fut = run_mod.generate_future_timestamps(df["begin"].iloc[-1], 24, "60min")
    actual_span = fut.iloc[-1] - fut.iloc[0] + pd.Timedelta("60min")
    claimed = pd.Timedelta(minutes=run_mod.PRED_LEN * run_mod.RESAMPLE_TO)
    assert actual_span == claimed

    text = run_mod.interpret("SBER", 100.0, 101.0, "BUY", 1.0, 85)
    assert "24ч" in text  # not "2ч" — the old mismatch


# ── signal ────────────────────────────────────────────────────────────

def test_compute_signal_thresholds(run_mod):
    assert run_mod.compute_signal(102.0, 100.0, 2.0)[0] == "BUY"    # exactly +2%
    assert run_mod.compute_signal(98.0, 100.0, 2.0)[0] == "SELL"    # exactly -2%
    assert run_mod.compute_signal(101.9, 100.0, 2.0)[0] == "HOLD"
    sig, chg = run_mod.compute_signal(101.0, 100.0, 2.0)
    assert sig == "HOLD" and chg == pytest.approx(1.0)


# ── ticker / URL safety ───────────────────────────────────────────────

def test_moex_url_accepts_valid_tickers(run_mod):
    assert "/SBER/candles.json" in run_mod.moex_url("SBER")
    assert "/boards/TQBR/" in run_mod.moex_url("YDEX")


def test_moex_url_rejects_path_injection(run_mod):
    for bad in ["../etc", "SBER/../../x", "a b", "", "x" * 25, "SB ER"]:
        with pytest.raises(ValueError):
            run_mod.moex_url(bad)


# ── fetch pagination (mocked MOEX ISS) ────────────────────────────────

class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_payload(rows):
    return {"candles": {
        "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
        "data": rows,
    }}


def row(ts, price=100.0):
    return [price, price, price + 0.5, price - 0.5, 1e6, 10, ts, ts]


def test_fetch_candles_range_paginates(run_mod, monkeypatch):
    """Regression: MOEX caps a response at 500 rows; old code lost the tail
    of every trading day (limit=500, no `start` pagination)."""
    calls = []
    t0 = pd.Timestamp("2026-10-23 06:00")

    def fake_get(url, params=None, timeout=10):
        calls.append(params["start"])
        start = params["start"]
        count = 500 if start == 0 else 300
        rows = [row((t0 + pd.Timedelta(minutes=i)).isoformat())
                for i in range(start, start + count)]
        return FakeResponse(make_payload(rows))

    monkeypatch.setattr(run_mod, "requests", types.SimpleNamespace(get=fake_get))
    df = run_mod.fetch_candles_range("SBER", "2026-10-23", "2026-10-24")
    assert len(df) == 800          # both pages concatenated, nothing truncated
    assert calls == [0, 500]       # followed the `start` cursor
    assert df["begin"].is_monotonic_increasing


def test_fetch_candles_range_stops_on_short_page(run_mod, monkeypatch):
    def fake_get(url, params=None, timeout=10):
        rows = [row(f"2026-10-23 10:{i:02d}:00") for i in range(50)]
        return FakeResponse(make_payload(rows))

    monkeypatch.setattr(run_mod, "requests", types.SimpleNamespace(get=fake_get))
    df = run_mod.fetch_candles_range("SBER", "2026-10-23", "2026-10-24")
    assert len(df) == 50


def test_fetch_multi_day_hourly_reaches_lookback(run_mod, monkeypatch):
    """Regression: hourly config needs ~500 candles; the old fixed 14-day scan
    could only ever collect ~180 hourly candles."""
    monkeypatch.setattr(run_mod, "INTERVAL_SRC", 60)

    def fake_get(url, params=None, timeout=10):
        d_from = datetime.date.fromisoformat(params["from"])
        d_till = datetime.date.fromisoformat(params["till"])
        rows = []
        day = d_from
        while day < d_till:
            # weekdays only, 16 hourly candles per trading day
            if day.weekday() < 5:
                for h in range(7, 23):
                    rows.append(row(f"{day} {h:02d}:00:00"))
            day += datetime.timedelta(days=1)
        return FakeResponse(make_payload(rows))

    monkeypatch.setattr(run_mod, "requests", types.SimpleNamespace(get=fake_get))
    df = run_mod.fetch_multi_day("SBER", min_candles=1000)
    assert df is not None and len(df) >= 1000
    assert (df["begin"].diff().dropna() >= pd.Timedelta("1h")).all()


def test_fetch_multi_day_deduplicates(run_mod, monkeypatch):
    monkeypatch.setattr(run_mod, "INTERVAL_SRC", 60)

    def fake_get(url, params=None, timeout=10):
        # same candles returned for every chunk -> must be deduped
        rows = [row(f"2026-10-2{d} {h:02d}:00:00") for d in range(0, 3) for h in range(7, 10)]
        return FakeResponse(make_payload(rows))

    monkeypatch.setattr(run_mod, "requests", types.SimpleNamespace(get=fake_get))
    df = run_mod.fetch_multi_day("SBER", min_candles=50)
    assert len(df) == len(df.drop_duplicates(subset=["begin"]))


# ═══════════════════════════════════════════════════════════════════════
# Дополнения второго прохода аудита: гэпы ночь/выходные, валидация
# тикеров, save_forecast, устойчивость fetch к ошибкам сети.
# ═══════════════════════════════════════════════════════════════════════

def test_fill_gaps_does_not_fill_overnight(run_mod):
    """Ночь/выходные не заполняются плоскими фейковыми свечами:
    ранее каждая ночь в hourly-режиме превращалась в ~15 фиктивных свечей."""
    fri = make_1min_df("2026-01-08 17:00", periods=20, freq="5min")
    mon = make_1min_df("2026-01-11 10:00", periods=10, freq="5min")
    mon[["open", "high", "low", "close"]] += 2.0
    df = pd.concat([fri, mon], ignore_index=True)
    out = run_mod.fill_gaps(df, "5min", max_gap_bars=3)
    fri_last = fri["begin"].iloc[-1]
    tail_allowed = fri_last + pd.Timedelta(minutes=15)  # ≤3 баров хвостом
    assert (out["begin"] <= fri_last).sum() == 20      # реальные свечи целы
    assert (out["begin"] >= pd.Timestamp("2026-01-11 10:00")).sum() == 10
    night = out[(out["begin"] > tail_allowed)
                & (out["begin"] < pd.Timestamp("2026-01-11 10:00"))]
    assert len(night) == 0
    assert len(out) <= len(df) + 6


def test_fill_gaps_hourly_night_not_filled(run_mod):
    """Часовые свечи через ночь: между днями не появляются плоские свечи."""
    day1 = make_1min_df("2026-01-05 10:00", periods=8, freq="1h")
    day2 = make_1min_df("2026-01-06 10:00", periods=8, freq="1h")
    day2[["open", "high", "low", "close"]] += 1.0
    df = pd.concat([day1, day2], ignore_index=True)
    out = run_mod.fill_gaps(df, "60min", max_gap_bars=3)
    night = out[(out["begin"] > pd.Timestamp("2026-01-05 20:00"))
                & (out["begin"] < pd.Timestamp("2026-01-06 10:00"))]
    assert len(night) == 0
    assert len(out) <= len(df) + 2 * 3


@pytest.mark.parametrize("ticker,expected", [
    ("SBERP", True), ("GAZP", True), ("YDEX", True), ("A", True),
    ("..", False), ("...", False),
    ("..\evil", False), ("../evil", False), ("../../etc/passwd", False),
    ("SB ER", False), ("", False),
    ("VERYLONGTICKER99", False),   # > 12 символов
    ("SBER;rm -rf", False),
    ("-SBER", False),              # не начинается с буквы/цифры
])
def test_is_valid_ticker(run_mod, ticker, expected):
    assert run_mod.is_valid_ticker(ticker) is expected


def test_save_forecast_writes_json(run_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(run_mod, "PROJECT_ROOT", str(tmp_path))
    idx = pd.date_range("2026-01-05 10:05", periods=24, freq="5min")
    pred_df = pd.DataFrame({
        "open": 300.0, "high": 301.0, "low": 299.0, "close": 300.5,
        "volume": 1000.0, "amount": 300500.0,
    }, index=idx)
    y_ts = run_mod.generate_future_timestamps(idx[0], 24, "5min")
    run_mod.save_forecast("SBERP", 299.0, pred_df, y_ts, "5min")
    files = list((tmp_path / "forecasts").glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["ticker"] == "SBERP" and data["mode"] == "5min"
    assert len(data["pred_prices"]) == 24
    assert data["signal"] in ("BUY", "SELL", "HOLD")


def test_fetch_candles_range_empty_page_returns_none(run_mod, monkeypatch):
    def fake_get(url, params=None, timeout=10):
        return FakeResponse(make_payload([]))
    monkeypatch.setattr(run_mod, "requests", types.SimpleNamespace(get=fake_get))
    assert run_mod.fetch_candles_range("SBER", "2026-10-23", "2026-10-24") is None


def test_fetch_candles_range_network_error_returns_none(run_mod, monkeypatch):
    def fake_get(url, params=None, timeout=10):
        raise ConnectionError("boom")
    monkeypatch.setattr(run_mod, "requests", types.SimpleNamespace(get=fake_get))
    assert run_mod.fetch_candles_range("SBER", "2026-10-23", "2026-10-24") is None
