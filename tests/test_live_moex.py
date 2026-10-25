"""Opt-in live tests against the real MOEX ISS API (deselected by default).

Run with: python -m pytest tests/ -m live
"""
import datetime

import pytest

pytestmark = pytest.mark.live


def test_live_fetch_full_trading_day_not_truncated(run_mod):
    """A trading day holds ~1000 1-min candles; pagination must return more
    than the 500-row API cap."""
    # pick the last weekday <= yesterday (market data lags today's session)
    day = datetime.date.today() - datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    df = run_mod.fetch_candles_range(
        "SBER", day.strftime("%Y-%m-%d"),
        (day + datetime.timedelta(days=1)).strftime("%Y-%m-%d"))
    assert df is not None
    assert len(df) > 500, f"day {day} truncated: {len(df)} rows"
    assert df["begin"].is_monotonic_increasing


def test_live_fetch_multi_day_hourly_enough_context(run_mod, monkeypatch):
    monkeypatch.setattr(run_mod, "INTERVAL_SRC", 60)
    df = run_mod.fetch_multi_day("SBER", min_candles=500)
    assert df is not None and len(df) >= 500
    assert (df["begin"].diff().dropna() >= pd_timedelta("1h")).all()


def pd_timedelta(s):
    import pandas as pd
    return pd.Timedelta(s)


def test_live_hourly_pipeline_end_to_end_shape(run_mod, monkeypatch):
    """Resample->fill_gaps->future timestamps on real hourly data yield an
    hourly grid and a true 24h horizon."""
    monkeypatch.setattr(run_mod, "INTERVAL_SRC", 60)
    df = run_mod.fetch_multi_day("SBERP", min_candles=600)
    if df is None or len(df) < 100:
        pytest.skip("MOEX returned thin data")
    df_tf = run_mod.fill_gaps(run_mod.resample_ohlcv(df, "60min"), "60min")
    diffs = df_tf["begin"].diff().dropna().unique()
    assert all(d == pd_timedelta("1h") for d in diffs)
    fut = run_mod.generate_future_timestamps(df_tf["begin"].iloc[-1], 24, "60min")
    assert fut.iloc[-1] - fut.iloc[0] == pd_timedelta("23h")
