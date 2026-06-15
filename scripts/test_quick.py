"""Quick Kronos test — 1 ticker, 10 steps, debug timing."""
import sys, os, json, time, requests
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "kronos-source"))
from model import Kronos, KronosTokenizer, KronosPredictor

t0 = time.time()
print("Loading model...", flush=True)
tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-2k")
model = Kronos.from_pretrained("NeoQuasar/Kronos-mini")
pred = KronosPredictor(model, tok, device="cpu", max_context=2048)
print(f"Model loaded: {time.time()-t0:.1f}s", flush=True)

# Fetch one day of 1min candles
url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/SBER/candles.json"
r = requests.get(url, params={"interval": 1, "limit": 500, "from": "2026-06-11"}, timeout=20)
d = r.json()["candles"]["data"]
cols = r.json()["candles"]["columns"]
df = pd.DataFrame(d, columns=cols)
df = df.rename(columns={"OPEN": "open", "CLOSE": "close", "HIGH": "high",
                        "LOW": "low", "VOLUME": "volume", "BEGIN": "begin"})
df["begin"] = pd.to_datetime(df["begin"])
df = df.sort_values("begin")
print(f"Got {len(df)} 1min candles", flush=True)

# Resample to 5min
df5 = df.set_index("begin").resample("5min", closed="left", label="left").agg({
    "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
}).dropna(subset=["open"]).reset_index()
print(f"Resampled to {len(df5)} 5min candles", flush=True)
print(f"Last close: {df5['close'].iloc[-1]}", flush=True)

# Predict 10 steps
t1 = time.time()
freq = "5min"
last_ts = df5["begin"].iloc[-1]
future = pd.date_range(start=last_ts, periods=11, freq=freq)[1:]
result = pred.predict(
    df=df5[["open", "high", "low", "close", "volume"]],
    x_timestamp=pd.Series(df5["begin"]),
    y_timestamp=pd.Series(future),
    pred_len=10,
    T=1.0, top_p=0.9, sample_count=1, verbose=True
)
print(f"Predict done: {time.time()-t1:.1f}s", flush=True)
print("Forecast close:", result["close"].values, flush=True)
