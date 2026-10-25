#!/usr/bin/env python3
"""RSS сборщик новостей по тикерам MOEX.
Подключается к 4 RSS-фидам, фильтрует по тикеру, сохраняет seen_urls.

Usage:
  python rss_market_news.py --hours 24 --tickers SBER,GAZP,LKOH,SBERP,VTBR
  python rss_market_news.py --hours 48 --cron
  python rss_market_news.py --json
"""
import argparse, datetime, json, os, re, sys
from email.utils import parsedate_to_datetime
from defusedxml import ElementTree
from urllib.request import Request, urlopen

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
SEEN_FILE = os.path.join(CACHE_DIR, "seen_urls.txt")

RSS_FEEDS = {
    "SmartLab": "https://smart-lab.ru/rss/",
    "Investing.com": "https://ru.investing.com/rss/news.rss",
    "ПРАЙМ": "https://1prime.ru/export/rss2/index.xml",
    "Интерфакс": "https://www.interfax.ru/rss",
}

TICKER_KW = {
    "SBER": ["сбер","sber","сбербанк","sberbank"],
    "GAZP": ["газпром","gazp","gazprom"],
    "LKOH": ["лукойл","lukoil","lkoh"],
    "SBERP": ["сбер.?преф","sberp","сбербанк.?п"],
    "VTBR": ["втб","vtbr","vtb"],
}


def load_seen():
    if not os.path.isfile(SEEN_FILE): return set()
    with open(SEEN_FILE, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}

def save_seen(urls):
    with open(SEEN_FILE, "a", encoding="utf-8") as f:
        for u in urls: f.write(u + "\n")

def fetch(url):
    if not url.lower().startswith("https://"):
        print(f"  ⚠️  {url}: разрешён только https", file=sys.stderr)
        return []
    try:
        # схема проверена выше, url — из захардкоженного RSS_FEEDS
        resp = urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15)  # nosec B310
        raw = resp.read()
        # Отсекаем DTD/ENTITY — защита от XML-бомб (billion laughs / XXE)
        head = raw[:2048]
        if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
            print(f"  ⚠️  {url}: DTD в XML отклонён", file=sys.stderr)
            return []
        root = ElementTree.fromstring(raw)
        items = []
        for item in root.iter("item"):
            items.append({
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "desc": re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip()[:300],
                "pub": (item.findtext("pubDate") or "").strip(),
            })
        return items
    except Exception as e:
        print(f"  ⚠️  {url}: {e}", file=sys.stderr)
        return []

def match(text, tickers):
    """Вернуть тикер с самым специфичным (длинным) совпавшим паттерном.

    kw — regex-паттерны (например "сбер.?преф"): substring-поиск их убивал,
    а порядок тикеров решал исход — «сбербанк преф» доставался SBER (его
    короткое «сбер» проверялось первым). Теперь совпадения ищутся regex'ом
    и побеждает самый длинный паттерн.
    """
    t = text.lower()
    best_ticker, best_len = None, 0
    for ticker in tickers:
        for kw in TICKER_KW.get(ticker, []):
            if re.search(kw, t) and len(kw) > best_len:
                best_ticker, best_len = ticker, len(kw)
    return best_ticker

def parse_dt(s):
    """RFC-822 pubDate -> naive local datetime (datetime.min если не парсится)."""
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except (TypeError, ValueError):
        return datetime.datetime.min

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--tickers", default="SBER,GAZP,LKOH,SBERP,VTBR")
    ap.add_argument("--cron", action="store_true", help="Только новые")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    unknown = [t for t in tickers if t not in TICKER_KW]
    if unknown:
        print(f"  ⚠️  Нет ключевых слов для тикеров: {', '.join(unknown)} (пропущены)", file=sys.stderr)
        tickers = [t for t in tickers if t in TICKER_KW]
    if not tickers:
        print("Нет известных тикеров для фильтрации.", file=sys.stderr)
        return
    seen = load_seen()
    new_urls, articles = set(), []
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=args.hours)

    for src, url in RSS_FEEDS.items():
        for item in fetch(url):
            if not item["link"]: continue
            dt = parse_dt(item["pub"])
            if dt < cutoff: continue
            if args.cron and item["link"] in seen: continue
            text = f"{item['title']} {item['desc']}"
            m = match(text, tickers)
            if m:
                item["src"] = src; item["ticker"] = m
                item["date"] = dt.strftime("%d.%m %H:%M") if dt > datetime.datetime.min else ""
                articles.append(item)
                new_urls.add(item["link"])

    if new_urls: save_seen(new_urls)

    if args.json:
        print(json.dumps(articles, ensure_ascii=False, indent=2))
        return

    if not articles:
        print("Нет новостей за последние {}ч.".format(args.hours))
        return

    for t in tickers:
        group = [a for a in articles if a["ticker"] == t]
        if not group: continue
        print(f"\n{'='*55}")
        print(f"  {t}")
        print(f"{'='*55}")
        for a in group[:5]:
            print(f"  [{a['src']}] {a['date']}")
            print(f"  {a['title'][:90]}")
            print(f"  {a['link']}")
            if a['desc']: print(f"  {a['desc'][:140]}")
            print()

    print(f"Всего: {len(articles)}, новых: {len(new_urls)}")

if __name__ == "__main__":
    main()
