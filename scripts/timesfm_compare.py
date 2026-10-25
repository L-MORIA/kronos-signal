#!/usr/bin/env python3
"""TimesFM 2.5 vs Kronos-mini cross-comparison on MOEX tickers.

Runs TimesFM 2.5 inference over the same hourly candles that
Kronos-mini (config-hourly.yaml) already processed, then writes
a side-by-side comparison table + JSON to forecasts/timesfm/.

Usage:
    .venv-timesfm/Scripts/python.exe scripts/timesfm_compare.py
"""
import json, os, requests, datetime, sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from timesfm import TimesFM_2p5_200M_torch as TimesFM
except Exception as e:
    print(f"❌ timesfm import failed: {e}", file=sys.stderr)
    sys.exit(1)

MOEX_BASE = "https://iss.moex.com/iss/engines/stock/markets/shares"
BOARDS = {
    "SBER":  "TQBR", "SBERP": "TQBR", "GAZP": "TQBR", "LKOH": "TQBR",
    "VTBR":  "TQBR", "FEES":  "TQBR", "MOEX": "TQBR", "ROSN": "TQBR",
    "TRNFP": "TQBR", "YDEX":  "TQBR", "GMKN": "TQBR", "SNGSP": "TQBR",
    "MTSS":  "TQBR", "AFKS":  "TQBR",
}
TICKERS = list(BOARDS.keys())
LOOKBACK_DAYS = 85          # mirror Kronos hourly context (~500 candles)
PRED_LEN = 24               # 24h horizon, matches Kronos hourly
HORIZON = PRED_LEN

FORECAST_DIR = Path("forecasts")
TIMESFM_DIR = FORECAST_DIR / "timesfm"
TIMESFM_DIR.mkdir(parents=True, exist_ok=True)


def fmt_num(v, spec=".2f", width=12):
    """Format a float for the table; None/NaN -> dash placeholder."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—".rjust(width)
    return f"{v:{spec}}".rjust(width)


def fetch_hourly(ticker, days=LOOKBACK_DAYS):
    """Fetch hourly candles from MOEX ISS, resilient to daily gaps."""
    dfs = []
    today = datetime.date.today()
    for offset in range(days):
        day = today - datetime.timedelta(days=offset)
        url = f"{MOEX_BASE}/boards/{BOARDS[ticker]}/securities/{ticker}/candles.json"
        params = {"interval": 60, "limit": 500,
                  "from": day.strftime("%Y-%m-%d"),
                  "till": (day + datetime.timedelta(days=1)).strftime("%Y-%m-%d")}
        try:
            r = requests.get(url, params=params, timeout=12)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            print(f"  ⚠️ {day} {ticker}: skipped ({type(e).__name__})", file=sys.stderr)
            continue
        data = payload.get("candles", {}).get("data")
        if data:
            cols = payload["candles"]["columns"]
            df = pd.DataFrame(data, columns=cols)
            df["begin"] = pd.to_datetime(df["begin"])
            df = df[["begin", "open", "close", "high", "low", "volume"]].rename(
                columns={"begin": "ds"})
            dfs.append(df)
    if not dfs:
        return None
    combined = pd.concat(dfs).drop_duplicates(subset=["ds"]).sort_values("ds")
    return combined.reset_index(drop=True)


def main():
    print("Loading TimesFM 2.5 …")
    model = TimesFM()
    print("Model loaded.")

    rows = []

    for ticker in TICKERS:
        print(f"\n[{ticker}] fetching candles…", flush=True)
        df = fetch_hourly(ticker)
        if df is None or df.empty:
            print(f"  ❌ no candles for {ticker}")
            continue

        close = df["close"].astype(float).values
        last_close = float(close[-1])

        # TimesFM wants list-of-lists
        pred = None
        pred_series = None
        try:
            forecasts = model.forecast(
                horizon=HORIZON,
                inputs=[close.tolist()],
                temperature=0.85,
                top_k=0,
                top_p=0.85,
                n_samples=3,
            )
            # forecasts: (n_samples, horizon) or (horizon,) depending on version
            if forecasts.ndim == 2:
                pred_series = forecasts.mean(axis=0)
                pred = float(pred_series[-1])
            else:
                pred_series = forecasts
                pred = float(forecasts[-1])
        except Exception as e:
            print(f"  ❌ inference failed: {e}")

        # Load Kronos hourly forecast for comparison
        kronos_files = sorted(FORECAST_DIR.glob(f"*hourly_{ticker}.json"),
                             reverse=True)
        kronos_last = kronos_forecast = kronos_signal = None
        if kronos_files:
            try:
                with open(kronos_files[0], encoding="utf-8") as f:
                    kj = json.load(f)
                kronos_last = kj.get("last_close")
                kronos_forecast = kj.get("forecast_close")
                kronos_signal = kj.get("signal")
            except (OSError, json.JSONDecodeError) as e:
                print(f"  ⚠️ kronos forecast unreadable: {e}")

        chg = ((pred - last_close) / last_close * 100) if pred is not None else None

        rows.append({
            "ticker": ticker,
            "last_close": last_close,
            "timesfm_forecast": pred,
            "timesfm_chg_pct": round(chg, 2) if chg is not None else None,
            "kronos_last": kronos_last,
            "kronos_forecast": kronos_forecast,
            "kronos_signal": kronos_signal,
        })

        # Save timesfm JSON
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        out = {
            "ticker": ticker,
            "last_close": last_close,
            "pred_prices": [round(float(p), 4) for p in pred_series.tolist()]
                           if pred_series is not None else [],
            "forecast_close": pred,
            "chg_pct": round(chg, 2) if chg is not None else None,
            "source": "timesfm-2.5-200m",
            "horizon": HORIZON,
            "timestamp": ts,
        }
        with open(TIMESFM_DIR / f"{ts}_timesfm_{ticker}.json", "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        if pred is not None:
            print(f"  ✅ {ticker}: last={last_close:.2f} → timesfm={pred:.2f} "
                  f"(chg={chg:+.2f}%)")
        else:
            print(f"  ⚠️ {ticker}: pred=NA")

    # Print comparison table
    print("\n" + "=" * 90)
    print(f"TimesFM 2.5 vs Kronos-mini  |  Horizon={HORIZON}h  |  {datetime.datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 90)
    print(f"{'Ticker':<8} {'Kronos Last':>12} {'Kronos FC':>12} {'Signal':>8} "
          f"{'TFM Last':>12} {'TFM FC':>12} {'Chg%':>8}  Diff(K-T)")
    print("-" * 90)
    for r in rows:
        kl, kf, sig = r["kronos_last"], r["kronos_forecast"], r["kronos_signal"] or "—"
        tl, tf, chg = r["last_close"], r["timesfm_forecast"], r["timesfm_chg_pct"]
        diff = None
        if kf and tf:
            diff = round((tf - kf) / kf * 100, 2)
        chg_txt = f"{chg:+.2f}%" if chg is not None else "—"
        diff_txt = f"{diff:+.2f}%" if diff is not None else "—"
        print(f"{r['ticker']:<8} "
              f"{fmt_num(kl)} {fmt_num(kf)} {sig:>8} "
              f"{fmt_num(tl)} {fmt_num(tf)} {chg_txt:>8}  "
              f"{diff_txt}")
    print("=" * 90)

    # JSON summary
    with open(TIMESFM_DIR / "comparison_summary.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved {len(rows)} forecasts + summary to {TIMESFM_DIR}/")


if __name__ == "__main__":
    main()
