"""Debug predict speed on SBER data."""
import sys, os, time, json, requests
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "kronos-source"))
from model import Kronos, KronosTokenizer, KronosPredictor

# Fetch 2 days of data (1000 1min candles)
url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/SBER/candles.json"
dfs = []
for day_offset in [0, 1]:
    day_str = (pd.Timestamp.now() - pd.Timedelta(days=day_offset)).strftime("%Y-%m-%d")
    next_str = (pd.Timestamp.now() - pd.Timedelta(days=day_offset-1)).strftime("%Y-%m-%d")
    r = requests.get(url, params={"interval": 1, "limit": 500, "from": day_str, "till": next_str}, timeout=10)
    data = r.json()["candles"]["data"]
    if data:
        cols = r.json()["candles"]["columns"]
        df = pd.DataFrame(data, columns=cols)
        df = df.rename(columns={"OPEN":"open","CLOSE":"close","HIGH":"high","LOW":"low","VOLUME":"volume","BEGIN":"begin"})
        df["begin"] = pd.to_datetime(df["begin"])
        dfs.append(df)

combined = pd.concat(dfs, ignore_index=True)
combined = combined.drop_duplicates(subset=["begin"]).sort_values("begin").reset_index(drop=True)
print(f"Fetched {len(combined)} 1min candles: {combined['begin'].iloc[0]} to {combined['begin'].iloc[-1]}")

# Resample to 5min
df5 = combined.set_index("begin").resample("5min", closed="left", label="left").agg({
    "open":"first","high":"max","low":"min","close":"last","volume":"sum"
}).dropna(subset=["open"]).reset_index()
print(f"Resampled to {len(df5)} 5min candles")
df5 = df5.tail(200).reset_index(drop=True)  # LOOKBACK=200
print(f"After tail(200): {len(df5)} candles, last close={df5['close'].iloc[-1]}")

# Load model
print("Loading model...", flush=True)
t0 = time.time()
tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-2k")
model = Kronos.from_pretrained("NeoQuasar/Kronos-mini")
pred = KronosPredictor(model, tok, device="cpu", max_context=2048)
print(f"Model loaded: {time.time()-t0:.1f}s", flush=True)

# Predict 10 steps first
future = pd.date_range(start=df5["begin"].iloc[-1], periods=11, freq="5min")[1:]
print(f"Predicting 10 steps...", flush=True)
t1 = time.time()
result = pred.predict(
    df=df5[["open","high","low","close","volume"]],
    x_timestamp=pd.Series(df5["begin"]),
    y_timestamp=pd.Series(future),
    pred_len=10, T=1.0, top_p=0.9, sample_count=1, verbose=True
)
print(f"10 steps done: {time.time()-t1:.1f}s", flush=True)
print(f"Forecast[0]: {result['close'].values[0]:.2f}", flush=True)
