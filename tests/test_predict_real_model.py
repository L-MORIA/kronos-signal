"""Main functionality: real Kronos-mini prediction with local weights.

Skipped automatically when torch or the local model files are unavailable,
so the suite still runs on a bare checkout.
"""
import sys

import numpy as np
import pandas as pd
import pytest

from conftest import PROJECT_ROOT

torch = pytest.importorskip("torch")

requires_weights = pytest.mark.skipif(
    not (PROJECT_ROOT / "models" / "Kronos-mini" / "model.safetensors").exists()
    or not (PROJECT_ROOT / "models" / "Kronos-Tokenizer-2k" / "model.safetensors").exists(),
    reason="local model weights (models/) not present")


def synthetic_ohlcv(n=160, start="2026-10-23 10:00", freq="5min", base=292.0):
    idx = pd.date_range(start, periods=n, freq=freq)
    trend = base + np.cumsum(np.random.default_rng(7).normal(0, 0.15, n))
    df = pd.DataFrame({
        "open": trend, "high": trend + 0.4, "low": trend - 0.4,
        "close": trend, "volume": np.full(n, 1000.0),
    })
    return df, pd.Series(idx)


@pytest.fixture(scope="module")
def predictor():
    kronos_src = str(PROJECT_ROOT / "kronos-source")
    if kronos_src not in sys.path:
        sys.path.insert(0, kronos_src)
    from model import Kronos, KronosTokenizer, KronosPredictor
    tok = KronosTokenizer.from_pretrained(str(PROJECT_ROOT / "models" / "Kronos-Tokenizer-2k"))
    model = Kronos.from_pretrained(str(PROJECT_ROOT / "models" / "Kronos-mini"))
    return KronosPredictor(model, tok, device="cpu", max_context=2048)


@requires_weights
def test_predict_returns_wellformed_ohlcv_forecast(predictor):
    torch.manual_seed(42)
    df, x_ts = synthetic_ohlcv()
    y_ts = pd.Series(pd.date_range(x_ts.iloc[-1], periods=25, freq="5min")[1:])
    pred = predictor.predict(
        df=df, x_timestamp=x_ts, y_timestamp=y_ts,
        pred_len=24, T=1.0, top_k=0, top_p=0.9, sample_count=1, verbose=False)

    assert list(pred.columns) == ["open", "high", "low", "close", "volume", "amount"]
    assert len(pred) == 24
    assert list(pred.index) == list(y_ts)                 # index is y_timestamp
    vals = pred[["open", "high", "low", "close"]].values
    assert np.isfinite(vals).all()                        # no NaN/inf after denorm
    # prices stay in a sane band around the input scale (no normalization blow-up)
    assert (pred["close"] > 100).all() and (pred["close"] < 700).all()


@requires_weights
def test_predict_monte_carlo_sample_count_3(predictor):
    """config-hourly uses sample_count=3 — the MC averaging path must not
    corrupt shapes or produce NaNs."""
    torch.manual_seed(43)
    df, x_ts = synthetic_ohlcv(n=200)
    y_ts = pd.Series(pd.date_range(x_ts.iloc[-1], periods=25, freq="60min")[1:])
    pred = predictor.predict(
        df=df, x_timestamp=x_ts, y_timestamp=y_ts,
        pred_len=24, T=0.85, top_k=0, top_p=0.85, sample_count=3, verbose=False)
    assert pred.shape == (24, 6)
    assert np.isfinite(pred.values).all()


@requires_weights
def test_predict_rejects_nan_input(predictor):
    df, x_ts = synthetic_ohlcv(n=60)
    df.loc[3, "close"] = np.nan
    y_ts = pd.Series(pd.date_range(x_ts.iloc[-1], periods=25, freq="5min")[1:])
    with pytest.raises(ValueError):
        predictor.predict(df=df, x_timestamp=x_ts, y_timestamp=y_ts,
                          pred_len=24, T=1.0, top_k=0, top_p=0.9,
                          sample_count=1, verbose=False)


@requires_weights
def test_predict_long_context_uses_full_lookback(predictor):
    """config-hourly supplies 500 candles — predict must handle a 500-row
    context without trimming or crashing."""
    torch.manual_seed(44)
    df, x_ts = synthetic_ohlcv(n=500, freq="60min")
    y_ts = pd.Series(pd.date_range(x_ts.iloc[-1], periods=25, freq="60min")[1:])
    pred = predictor.predict(
        df=df, x_timestamp=x_ts, y_timestamp=y_ts,
        pred_len=24, T=0.85, top_k=0, top_p=0.85, sample_count=1, verbose=False)
    assert pred.shape == (24, 6)
    assert np.isfinite(pred.values).all()
