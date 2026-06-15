#!/usr/bin/env python3
"""Kronos Signal — fetch MOEX candles, predict with Kronos, output BUY/SELL/HOLD."""

import sys
import os
import json
import yaml
import requests
import datetime
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── CLI args ──────────────────────────────────────────────────────────
import argparse
_parser = argparse.ArgumentParser()
_parser.add_argument("--config", default="config.yaml",
                    help="config file name (relative to D:/kronos-signal/)")
_args, _ = _parser.parse_known_args()

# ── Kronos source ─────────────────────────────────────────────────────
KRONOS_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kronos-source")
if KRONOS_SRC not in sys.path:
    sys.path.insert(0, KRONOS_SRC)

from model import Kronos, KronosTokenizer, KronosPredictor

# ── Config ────────────────────────────────────────────────────────────
CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", _args.config)
with open(CFG_PATH, "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

TICKERS = CFG["tickers"]
INTERVAL_SRC = CFG.get("interval", 1)       # 1 = 1 минута из MOEX
RESAMPLE_TO = CFG.get("resample_to", 5)     # агрегируем в 5 мин
LOOKBACK = CFG.get("lookback_candles", 200)
PRED_LEN = CFG.get("pred_len", 100)
THRESHOLD = CFG.get("threshold_pct", 2.0)
MODEL_NAME = CFG["model_name"]
TOKENIZER_NAME = CFG["tokenizer_name"]
LOG_FILE = CFG["log_file"]
BOARDS = CFG.get("boards", {})
SAMPLE_COUNT = CFG.get("sample_count", 1)
TEMPERATURE = CFG.get("temperature", 1.0)
TOP_K = CFG.get("top_k", 0)
TOP_P = CFG.get("top_p", 0.9)

MOEX_BASE = "https://iss.moex.com/iss/engines/stock/markets/shares"

# ── Tools ─────────────────────────────────────────────────────────────

def moex_url(ticker):
    board = BOARDS.get(ticker, "TQBR")
    return f"{MOEX_BASE}/boards/{board}/securities/{ticker}/candles.json"


def fetch_day_candles(ticker, date_str):
    """Fetch up to 500 1-min candles for a given date."""
    url = moex_url(ticker)
    params = {"interval": INTERVAL_SRC, "limit": 500, "from": date_str}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()["candles"]["data"]
        if not data:
            return None
        cols = r.json()["candles"]["columns"]
        # cols: open, close, high, low, value, volume, begin, end
        df = pd.DataFrame(data, columns=cols)
        df = df.rename(columns={
            "OPEN": "open", "CLOSE": "close", "HIGH": "high",
            "LOW": "low", "VOLUME": "volume", "BEGIN": "begin"
        })
        df["begin"] = pd.to_datetime(df["begin"])
        df = df.sort_values("begin").reset_index(drop=True)
        return df[["begin", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        print(f"  ⚠ {ticker} {date_str}: {e}", file=sys.stderr)
        return None


def fetch_multi_day(ticker, min_candles=600):
    """Fetch 1-min candles by iterating dates with from+till."""
    dfs = []
    today = datetime.date.today()
    for offset in range(14):
        day = today - datetime.timedelta(days=offset)
        day_str = day.strftime("%Y-%m-%d")
        next_day = (day + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        # from=day, till=next_day — получаем только свечи за этот день
        url = moex_url(ticker)
        params = {"interval": INTERVAL_SRC, "limit": 500, 
                   "from": day_str, "till": next_day}
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()["candles"]["data"]
            if data:
                cols = r.json()["candles"]["columns"]
                df = pd.DataFrame(data, columns=cols)
                df = df.rename(columns={"OPEN": "open", "CLOSE": "close",
                    "HIGH": "high", "LOW": "low", "VOLUME": "volume", "BEGIN": "begin"})
                df["begin"] = pd.to_datetime(df["begin"])
                dfs.append(df)
                print(f"    {day_str}: {len(df)} candles", file=sys.stderr)
        except Exception as e:
            pass  # empty day
        total = sum(len(d) for d in dfs)
        if total >= min_candles:
            break
    if not dfs:
        return None
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=["begin"]).sort_values("begin").reset_index(drop=True)
    return combined


def resample_to_5min(df_1min):
    """Aggregate 1-min OHLCV to 5-min candles."""
    if df_1min is None or len(df_1min) < 2:
        return None
    df = df_1min.set_index("begin")
    ohlc = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    df5 = df.resample("5min", closed="left", label="left").agg(ohlc)
    df5 = df5.dropna(subset=["open"]).reset_index()
    df5 = df5.rename(columns={"index": "begin"})
    df5["begin"] = pd.to_datetime(df5["begin"])
    return df5


def calc_time_stamps(ts_series):
    """Extract time features for Kronos: minute, hour, weekday, day, month."""
    ts = pd.to_datetime(ts_series)
    df = pd.DataFrame({
        "minute": ts.dt.minute,
        "hour": ts.dt.hour,
        "weekday": ts.dt.weekday,
        "day": ts.dt.day,
        "month": ts.dt.month,
    })
    return df


def generate_future_timestamps(last_ts, pred_len, freq="5min"):
    """Generate future timestamps for prediction horizon."""
    ts = pd.to_datetime(last_ts)
    future = pd.date_range(start=ts, periods=pred_len + 1, freq=freq)[1:]
    return pd.Series(future)


def compute_signal(forecast_close, last_close, threshold):
    change_pct = (forecast_close - last_close) / last_close * 100
    if change_pct >= threshold:
        return "BUY", change_pct
    elif change_pct <= -threshold:
        return "SELL", change_pct
    return "HOLD", change_pct


def load_model():
    print("  Loading Kronos-mini (4M params)...", file=sys.stderr)
    tok = KronosTokenizer.from_pretrained(TOKENIZER_NAME)
    model = Kronos.from_pretrained(MODEL_NAME)
    predictor = KronosPredictor(model, tok, device="cpu", max_context=2048)
    print(f"  Model loaded (device={predictor.device})", file=sys.stderr)
    return predictor


def fill_gaps_5min(df_5min):
    """Fill gaps (non-trading hours) by carrying last close forward."""
    if df_5min is None or len(df_5min) < 2:
        return df_5min
    full_range = pd.date_range(
        df_5min["begin"].min(), df_5min["begin"].max(), freq="5min"
    )
    df = df_5min.set_index("begin").reindex(full_range)
    # Forward-fill price columns
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].ffill()
    df["volume"] = df["volume"].fillna(0)
    df = df.reset_index().rename(columns={"index": "begin"})
    return df


# ── Interpret signal for trader ──────────────────────────────────────

def interpret(ticker, cur, fcast, signal, chg, up):
    """Return human-readable interpretation of a single ticker result."""
    lines = []
    lines.append(f"  {ticker}: {cur:.2f} -> {fcast:.2f} rub")
    abs_chg = abs(chg)

    # Signal
    if signal == "BUY":
        lines.append(f"  [BUY] Сигнал к покупке. Модель ждёт рост >{THRESHOLD}%.")
    elif signal == "SELL":
        lines.append(f"  [SELL] Сигнал к продаже. Модель ждёт снижение >{THRESHOLD}%.")
    else:  # HOLD
        if up >= 80:
            lines.append(f"  [HOLD] Сильный уклон в рост. Держать.")
        elif up <= 20:
            lines.append(f"  [HOLD] Уклон в снижение. Присмотреться к продаже.")
        else:
            lines.append(f"  [HOLD] Боковик. Ничего не делать.")

    # Chg
    if abs_chg < 0.3:
        lines.append(f"  Изменение {chg:+.1f}% - микро-движение, в пределах шума")
    elif abs_chg < 1.0:
        lines.append(f"  Изменение {chg:+.1f}% - слабое движение")
    elif abs_chg < THRESHOLD:
        lines.append(f"  Изменение {chg:+.1f}% - заметно, но ниже порога {THRESHOLD}%")
    else:
        lines.append(f"  Изменение {chg:+.1f}% - сильное движение (выше порога!)")

    # Up
    if up >= 80:
        lines.append(f"  Уверенность в рост: {up:.0f}% - почти все 2ч цена выше")
    elif up <= 20:
        lines.append(f"  Уверенность в падение: {up:.0f}% - почти все 2ч цена ниже")
    else:
        lines.append(f"  Уверенность: {up:.0f}% - рынок не определился")

    # Recommendation
    if signal == "BUY" and up >= 80:
        lines.append(f"  => Действие: рассмотреть покупку, стоп на {max(0.5, abs_chg*0.5):.1f}%")
    elif signal == "BUY":
        lines.append(f"  => Действие: присмотреться, ждать подтверждения")
    elif signal == "SELL" and up <= 30:
        lines.append(f"  => Действие: рассмотреть фиксацию / шорт")
    elif signal == "SELL":
        lines.append(f"  => Действие: присмотреться к продаже, стоп")
    elif up >= 80:
        lines.append(f"  => Действие: держать позицию, продавать рано")
    elif up <= 20:
        lines.append(f"  => Действие: присмотреться к продаже / хеджу")
    else:
        lines.append(f"  => Действие: ничего не делать, рынок без сигнала")

    return "\n".join(lines)

# ──── Main ────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M MSK")
    print(f"  Kronos Signal — {now_str}")
    print("=" * 70)
    print(file=sys.stderr)

    # Load model once
    predictor = load_model()

    results = []

    for ticker in TICKERS:
        print(f"\n  [{ticker}]", file=sys.stderr)
        print(file=sys.stderr)
        pass # timer placeholder

        # 1. Fetch 1-min candles
        df_1min = fetch_multi_day(ticker, min_candles=LOOKBACK + 500)
        if df_1min is None or len(df_1min) < 100:
            print(f"  ⚠ {ticker}: not enough data, skip", file=sys.stderr)
            results.append((ticker, 0, 0, "NODATA", 0, 0))
            continue

        # 2. Resample to 5-min
        df_5min = resample_to_5min(df_1min)
        if df_5min is None or len(df_5min) < 50:
            print(f"  ⚠ {ticker}: no 5min candles, skip", file=sys.stderr)
            results.append((ticker, 0, 0, "NODATA", 0, 0))
            continue

        # 3. Fill gaps — non-trading hours
        df_5min = fill_gaps_5min(df_5min)

        # 4. Take last LOOKBACK candles
        df_5min = df_5min.tail(min(LOOKBACK, len(df_5min))).reset_index(drop=True)
        n_candles = len(df_5min)
        last_candle = df_5min.iloc[-1]
        last_close = last_candle["close"]
        last_ts = last_candle["begin"]

        # 5. Use KronosPredictor.predict — handles norm/denorm internally
        x_ts = pd.Series(df_5min["begin"])
        y_ts_future = generate_future_timestamps(last_ts, PRED_LEN)
        pass  # predicting

        # prep timing removed
        try:
            pred_df = predictor.predict(
                df=df_5min[["open", "high", "low", "close", "volume"]],
                x_timestamp=x_ts,
                y_timestamp=y_ts_future,
                pred_len=PRED_LEN,
                T=TEMPERATURE, top_k=TOP_K, top_p=TOP_P,
                sample_count=SAMPLE_COUNT, verbose=False
            )
        except Exception as e:
            print(f"  ⚠ {ticker}: predict error: {e}", file=sys.stderr)
            results.append((ticker, last_close, 0, "ERROR", 0, 0))
            continue

        # predict timing removed
        # pred_df columns: open, high, low, close, volume, amount
        pred_close_avg = float(pred_df["close"].mean())

        # 6. Compute signal
        signal, change_pct = compute_signal(pred_close_avg, float(last_close), THRESHOLD)

        # Upside probability: how many forecast candles end above last close
        up_count = int((pred_df["close"] > last_close).sum())
        up_prob = float(up_count / len(pred_df) * 100)

        results.append((ticker, float(last_close), round(pred_close_avg, 2),
                        signal, round(change_pct, 1), round(up_prob, 0)))

        print(f"  ✓ {ticker}: {n_candles} candles, "
              f"last={last_close:.2f} → forecast={pred_close_avg:.2f}, "
              f"signal={signal} ({change_pct:+.1f}%), up={up_prob:.0f}%",
              file=sys.stderr)

    # ── Output table ────────────────────────────────────────────────
    header = (
        f"{'Ticker':<7} {'Current':>10} {'Forecast':>10} {'Signal':<7} "
        f"{'Chg%':>7} {'Up%':>5}"
    )
    sep = "-" * len(header)
    lines = [sep, header, sep]
    for ticker, cur, fcast, sig, chg, up in results:
        lines.append(
            f"{ticker:<7} {cur:>10.2f} {fcast:>10.2f} {sig:<7} "
            f"{chg:>+6.1f}% {up:>4.0f}%"
        )
    lines.append(sep)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"  Updated: {ts} MSK  |  pred_len={PRED_LEN} ({PRED_LEN*5}min)  |  threshold={THRESHOLD}%")
    lines.append("")

    output = "\n".join(lines)

    # ── Interpretation ──────────────────────────────────────────────
    interp_lines = []
    for ticker, cur, fcast, sig, chg, up in results:
        if sig in ("ERROR", "NODATA"):
            interp_lines.append(f"  {ticker}: нет данных или ошибка — пропущен")
        else:
            interp_lines.append(interpret(ticker, cur, fcast, sig, chg, up))
        interp_lines.append("")

    output += "\n".join(interp_lines)

    # Print to stdout (cronjob captures this)
    print(output)

    # Write log
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n--- {ts} ---\n")
        f.write(output)
        f.write("\n")


if __name__ == "__main__":
    main()
