"""Debug MOEX ISS from+till pagination."""
import requests
import json

url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/SBER/candles.json"

tests = [
    ("Jun14 alone", {"interval": 1, "limit": 5, "from": "2026-06-14", "till": "2026-06-15"}),
    ("Jun13 alone", {"interval": 1, "limit": 5, "from": "2026-06-13", "till": "2026-06-14"}),
    ("Jun11 alone", {"interval": 1, "limit": 5, "from": "2026-06-11", "till": "2026-06-12"}),
    ("Jun10 alone", {"interval": 1, "limit": 5, "from": "2026-06-10", "till": "2026-06-11"}),
    ("Jun09 alone", {"interval": 1, "limit": 5, "from": "2026-06-09", "till": "2026-06-10"}),
    ("No till",    {"interval": 1, "limit": 5, "from": "2026-06-14"}),
    ("Jun05 alone", {"interval": 1, "limit": 5, "from": "2026-06-05", "till": "2026-06-06"}),
]

for label, params in tests:
    r = requests.get(url, params=params, timeout=10)
    data = r.json()["candles"]["data"]
    dates = set(d[6][:10] for d in data) if data else {"empty"}
    print(f"  {label}: {len(data)} candles, dates: {dates}")
    for d in data[:2]:
        print(f"    {d[6]} close={d[1]}")
