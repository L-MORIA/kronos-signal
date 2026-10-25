"""End-to-end orchestration test for run.main(): fetch -> predict -> signal ->
table -> interpretation -> forecast JSON -> log append. Network and the real
model are replaced by deterministic fakes."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def synthetic_1min(n=600, start="2026-10-23 10:00", base=100.0):
    idx = pd.date_range(start, periods=n, freq="1min")
    trend = base + np.linspace(0, 1.0, n)
    return pd.DataFrame({
        "begin": idx,
        "open": trend,
        "high": trend + 0.3,
        "low": trend - 0.3,
        "close": trend + 0.05,
        "volume": np.full(n, 500.0),
    })


class FakePredictor:
    """Returns a deterministic rising forecast (+2.5% => BUY)."""

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def predict(self, df, x_timestamp, y_timestamp, pred_len, T, top_k, top_p,
                sample_count, verbose):
        self.calls.append(dict(rows=len(df), pred_len=pred_len, T=T,
                               sample_count=sample_count))
        if self.fail:
            raise RuntimeError("boom")
        n = len(y_timestamp)
        fut = np.full(n, 105.0)  # last close ~101.05 => +3.9% => BUY
        return pd.DataFrame({
            "open": fut, "high": fut + 0.2, "low": fut - 0.2,
            "close": fut, "volume": np.full(n, 300.0),
            "amount": fut * 300.0,
        }, index=pd.Series(y_timestamp).reset_index(drop=True))


@pytest.fixture
def isolated_run(run_mod, monkeypatch, tmp_path):
    """Point PROJECT_ROOT/LOG_FILE at a temp dir so main() writes nothing real."""
    monkeypatch.setattr(run_mod, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(run_mod, "LOG_FILE", str(tmp_path / "logs" / "log.txt"))
    monkeypatch.setattr(run_mod, "TICKERS", ["FAKE"])
    return run_mod


def test_main_happy_path_produces_table_log_and_forecast(
        isolated_run, monkeypatch, capsys):
    run_mod = isolated_run
    fake = FakePredictor()
    monkeypatch.setattr(run_mod, "fetch_multi_day",
                        lambda t, min_candles=0: synthetic_1min())
    monkeypatch.setattr(run_mod, "load_model", lambda: fake)

    run_mod.main()

    out = capsys.readouterr().out
    assert "FAKE" in out and "BUY" in out
    assert "Updated:" in out and "threshold=2.0%" in out
    assert "Сигнал к покупке" in out              # interpretation branch
    assert "pred_len=24 (120min)" in out          # footer reflects config

    # predictor got the resampled 5-min context, MC and T from config
    assert fake.calls[0]["rows"] == 120           # 600 1-min -> 120 5-min
    assert fake.calls[0]["pred_len"] == run_mod.PRED_LEN
    assert fake.calls[0]["sample_count"] == run_mod.SAMPLE_COUNT

    # forecast JSON written under the isolated project root
    fjson = list(Path(run_mod.PROJECT_ROOT, "forecasts").glob("*_FAKE.json"))
    assert len(fjson) == 1
    data = json.loads(fjson[0].read_text(encoding="utf-8"))
    assert data["ticker"] == "FAKE" and data["signal"] == "BUY"
    assert len(data["pred_prices"]) == run_mod.PRED_LEN
    assert len(data["pred_timestamps"]) == run_mod.PRED_LEN
    # timestamps are 5-min steps into the future
    t0 = pd.Timestamp(data["pred_timestamps"][0])
    t1 = pd.Timestamp(data["pred_timestamps"][1])
    assert t1 - t0 == pd.Timedelta("5min")

    # log file appended with a session separator
    log = Path(run_mod.LOG_FILE).read_text(encoding="utf-8")
    assert "--- " in log and "BUY" in log


def test_main_nodata_ticker_is_skipped_gracefully(isolated_run, monkeypatch, capsys):
    run_mod = isolated_run
    monkeypatch.setattr(run_mod, "fetch_multi_day", lambda t, min_candles=0: None)
    monkeypatch.setattr(run_mod, "load_model", lambda: FakePredictor())
    run_mod.main()
    out = capsys.readouterr().out
    assert "NODATA" in out
    assert "нет данных или ошибка" in out


def test_main_predict_error_reports_error_row(isolated_run, monkeypatch, capsys):
    run_mod = isolated_run
    monkeypatch.setattr(run_mod, "fetch_multi_day",
                        lambda t, min_candles=0: synthetic_1min())
    monkeypatch.setattr(run_mod, "load_model", lambda: FakePredictor(fail=True))
    run_mod.main()  # must not raise
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "нет данных или ошибка" in out


def test_main_thin_data_falls_back_to_nodata(isolated_run, monkeypatch, capsys):
    """<100 source candles -> NODATA, not a crash inside resample/predict."""
    run_mod = isolated_run
    monkeypatch.setattr(run_mod, "fetch_multi_day",
                        lambda t, min_candles=0: synthetic_1min(n=42))
    monkeypatch.setattr(run_mod, "load_model", lambda: FakePredictor())
    run_mod.main()
    assert "NODATA" in capsys.readouterr().out
