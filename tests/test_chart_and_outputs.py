"""Chart rendering, forecast JSON persistence and interpretation text."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from conftest import PROJECT_ROOT, _load_module


@pytest.fixture(scope="session")
def run_chart_mod(tmp_path_factory):
    """Import scripts/run.py with --chart so plot_chart exists; charts go to tmp."""
    chart_dir = tmp_path_factory.mktemp("charts")
    old_argv = __import__("sys").argv
    __import__("sys").argv = ["run.py", "--chart", "--chart-dir", str(chart_dir)]
    try:
        mod = _load_module("run_chart_mod", "scripts/run.py")
    finally:
        __import__("sys").argv = old_argv
    return mod


def _synthetic(n=100, freq="5min"):
    idx = pd.date_range("2026-10-23 10:00", periods=n, freq=freq)
    trend = 292.0 + np.linspace(0, 1, n)
    df = pd.DataFrame({
        "begin": idx, "open": trend, "high": trend + 0.4,
        "low": trend - 0.4, "close": trend, "volume": np.full(n, 900.0),
    })
    fut_idx = pd.date_range(idx[-1], periods=25, freq=freq)[1:]
    pred = pd.DataFrame({
        "open": trend[-1] + 0.1, "high": trend[-1] + 0.5, "low": trend[-1] - 0.3,
        "close": trend[-1] + 0.2, "volume": 800.0, "amount": 800.0 * trend[-1],
    }, index=fut_idx)
    return df, pred


# ── plot_chart ────────────────────────────────────────────────────────

def test_plot_chart_5min_writes_png(run_chart_mod, tmp_path):
    df, pred = _synthetic()
    out = tmp_path / "SBERP-chart.png"
    run_chart_mod.plot_chart("SBERP", df, pred, str(out), "5min", "5-min")
    assert out.exists() and out.stat().st_size > 10_000


def test_plot_chart_hourly_writes_png(run_chart_mod, tmp_path):
    df, pred = _synthetic(freq="60min")
    out = tmp_path / "SBERP-hourly.png"
    run_chart_mod.plot_chart("SBERP", df, pred, str(out), "60min", "1h")
    assert out.exists() and out.stat().st_size > 10_000


def test_plot_chart_without_forecast(run_chart_mod, tmp_path):
    df, _ = _synthetic()
    out = tmp_path / "no-fcast.png"
    run_chart_mod.plot_chart("SBERP", df, None, str(out), "5min", "5-min")
    assert out.exists() and out.stat().st_size > 10_000


# ── save_forecast ─────────────────────────────────────────────────────

def _pred_df(n=24):
    fut = pd.date_range("2026-10-23 18:00", periods=n, freq="5min")
    return pd.DataFrame({
        "open": 100.0, "high": 101.0, "low": 99.0,
        "close": np.linspace(103.0, 105.0, n),  # mean 104 vs 100 => +4% => BUY
        "volume": 10.0, "amount": 1000.0,
    }, index=fut)


def test_save_forecast_json_structure(run_mod, monkeypatch, tmp_path):
    monkeypatch.setattr(run_mod, "PROJECT_ROOT", str(tmp_path))
    y_ts = pd.Series(pd.date_range("2026-10-23 18:00", periods=24, freq="5min"))
    run_mod.save_forecast("TEST", 100.0, _pred_df(), y_ts, "5min")

    files = list(Path(tmp_path, "forecasts").glob("*_5min_TEST.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["ticker"] == "TEST"
    assert data["last_close"] == 100.0
    assert len(data["pred_prices"]) == 24 and len(data["pred_high"]) == 24
    assert data["signal"] == "BUY"
    assert data["config"]["pred_len"] == run_mod.PRED_LEN
    # everything must be plain JSON types (no numpy leftovers)
    json.dumps(data)  # already parsed; re-dump ensures serializable round-trip


def test_save_forecast_timestamps_match_pred_len(run_mod, monkeypatch, tmp_path):
    monkeypatch.setattr(run_mod, "PROJECT_ROOT", str(tmp_path))
    y_ts = pd.Series(pd.date_range("2026-10-23 18:00", periods=24, freq="5min"))
    run_mod.save_forecast("TEST", 100.0, _pred_df(24), y_ts, "hourly")
    data = json.loads(next(Path(tmp_path, "forecasts").glob("*_hourly_TEST.json"))
                      .read_text(encoding="utf-8"))
    assert len(data["pred_timestamps"]) == len(data["pred_prices"]) == 24


# ── interpret text branches ───────────────────────────────────────────

@pytest.mark.parametrize("sig,up,expected", [
    ("BUY", 90, "Сигнал к покупке"),
    ("SELL", 10, "Сигнал к продаже"),
    ("HOLD", 85, "Сильный уклон в рост"),
    ("HOLD", 10, "Уклон в снижение"),
    ("HOLD", 50, "Боковик"),
])
def test_interpret_branches(run_mod, sig, up, expected):
    text = run_mod.interpret("SBER", 100.0, 101.0, sig, 1.0, up)
    assert expected in text
    assert "Действие:" in text


def test_interpret_stop_recommendation_for_strong_buy(run_mod):
    text = run_mod.interpret("SBER", 100.0, 103.0, "BUY", 3.0, 90)
    assert "стоп" in text


def test_interpret_zero_change_is_noise(run_mod):
    text = run_mod.interpret("SBER", 100.0, 100.05, "HOLD", 0.05, 50)
    assert "микро-движение" in text
