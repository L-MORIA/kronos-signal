"""SBERP 5-min chart — fetch from MOEX ISS, plot today."""
import sys, os, requests, datetime, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
warnings.filterwarnings("ignore")

# ── Config ──
TICKER = "SBERP"
BOARD = "TQBR"
BASE = "https://iss.moex.com/iss/engines/stock/markets/shares"
URL = f"{BASE}/boards/{BOARD}/securities/{TICKER}/candles.json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sberp-5min-chart.png")

today = datetime.date.today()
today_str = today.strftime("%Y-%m-%d")
print(f"Fetching SBERP 1-min candles for {today_str}...", file=sys.stderr)

# Fetch today's 1-min candles
params = {"interval": 1, "limit": 500, "from": today_str, "till": (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")}
r = requests.get(URL, params=params, timeout=10)
r.raise_for_status()
data = r.json()["candles"]
if not data["data"]:
    print("No data for today (maybe weekend/holiday). Trying last trading day...", file=sys.stderr)
    # Try yesterday
    yesterday = today - datetime.timedelta(days=1)
    params["from"] = yesterday.strftime("%Y-%m-%d")
    params["till"] = today_str
    r = requests.get(URL, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()["candles"]

rows = data["data"]
cols = data["columns"]

df = pd.DataFrame(rows, columns=cols)
df = df.rename(columns={"OPEN": "open", "CLOSE": "close", "HIGH": "high", "LOW": "low", "VOLUME": "volume", "BEGIN": "begin"})
df["begin"] = pd.to_datetime(df["begin"])
df = df.sort_values("begin").reset_index(drop=True)
print(f"Fetched {len(df)} 1-min candles", file=sys.stderr)

# Resample to 5-min
df5 = df.set_index("begin")
ohlc = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
df5 = df5.resample("5min", closed="left", label="left").agg(ohlc)
df5 = df5.dropna(subset=["open"])
print(f"Resampled to {len(df5)} 5-min candles", file=sys.stderr)

# ── Plot ──
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 7), gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
fig.patch.set_facecolor("#1a1a2e")

# Candlestick-like plot
for ax in [ax1, ax2]:
    ax.set_facecolor("#16213e")

times = df5.index
opens = df5["open"].values
highs = df5["high"].values
lows = df5["low"].values
closes = df5["close"].values
volumes = df5["volume"].values

# Price line with fill
ax1.plot(times, closes, color="#00d2ff", linewidth=1.5, label=f"{TICKER} Close")
ax1.fill_between(times, closes, closes.min(), alpha=0.08, color="#00d2ff")

# Candlestick bodies
for i in range(len(times)):
    t = times[i]
    o, h, l, c = opens[i], highs[i], lows[i], closes[i]
    color = "#00ff88" if c >= o else "#ff4757"
    # Wick
    ax1.plot([t, t], [l, h], color=color, linewidth=0.8, alpha=0.6)
    # Body
    body_w = pd.Timedelta("2min")
    ax1.bar(t, abs(c - o) or 0.01, bottom=min(o, c), width=body_w, color=color, alpha=0.9)

# Volume bars
ax2.bar(times, volumes, width=pd.Timedelta("4min"), color="#00d2ff", alpha=0.3)
ax2.set_ylabel("Volume", color="#8899aa")

# Formatting
ax1.set_title(f"{TICKER} — 5-min Chart ({today_str})", color="white", fontsize=14, pad=15)
ax1.set_ylabel("Price (RUB)", color="#8899aa")
ax1.tick_params(colors="#8899aa")
ax2.tick_params(colors="#8899aa")
ax1.legend(loc="upper left", facecolor="#1a1a2e", edgecolor="none", labelcolor="white")

ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
ax1.xaxis.set_major_locator(mdates.HourLocator(interval=1))
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
ax2.xaxis.set_major_locator(mdates.HourLocator(interval=1))
plt.xticks(rotation=45)

# Grid
for ax in [ax1, ax2]:
    ax.grid(True, alpha=0.1, color="white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#333")
    ax.spines["bottom"].set_color("#333")

plt.tight_layout()
plt.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="#1a1a2e")
print(f"\nChart saved: {OUT}", file=sys.stderr)

# Print summary
last = df5.iloc[-1]
print(f"\nLast 5-min candle: {last.name.strftime('%H:%M')} | O={last['open']:.2f} H={last['high']:.2f} L={last['low']:.2f} C={last['close']:.2f} V={int(last['volume'])}", file=sys.stderr)

# Return the path for the agent
print(f"CHART_PATH:{OUT}")
