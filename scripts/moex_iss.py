#!/usr/bin/env python3
"""MOEX ISS CLI — котировки, свечи, новости, справочники Московской Биржи.

Публичный API ISS: без регистрации, бесплатно. Описание команд — SKILL.md.

Usage:
    python scripts/moex_iss.py quote SBER
    python scripts/moex_iss.py portfolio SBER,GAZP,LKOH,SBERP,VTBR
    python scripts/moex_iss.py candles SBER --interval 24 --days 7
    python scripts/moex_iss.py --output plot candles FEES --interval 1 --days 30
    python scripts/moex_iss.py news SBERP --days 7
    python scripts/moex_iss.py indices
"""
import argparse
import csv
import io
import json
import sys
import time
import datetime

import requests

ISS = "https://iss.moex.com/iss"
SHARES = f"{ISS}/engines/stock/markets/shares"
BOARDS_FALLBACK = "TQBR"  # основной стакан акций (SBERP — TQBR, не TQBD)

# /candles.json отдаёт максимум 500 строк на страницу независимо от limit
CANDLE_PAGE = 500
PAGE_PAUSE = 0.3  # пауза между страницами, чтобы не долбить ISS

INTERVALS = {1: "1min", 10: "10min", 60: "1h", 24: "1d", 7: "1w", 31: "1M"}


def iss_get(url, params=None, retries=2):
    params = dict(params or {})
    params.setdefault("iss.meta", "off")
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries:
                print(f"ошибка запроса {url}: {e}", file=sys.stderr)
                return None
            time.sleep(0.5)


def block(payload, name):
    """Блок ISS -> список dict (колонки могут быть и lower-, и UPPER-case)."""
    b = (payload or {}).get(name) or {}
    cols = [c.upper() for c in b.get("columns", [])]
    return [dict(zip(cols, row)) for row in b.get("data", [])]


def is_valid_ticker(ticker):
    import re
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,11}", ticker or ""))


def board_for(ticker):
    """Основная доска тикера (is_primary=1) с fallback на TQBR."""
    rows = block(iss_get(f"{ISS}/securities/{ticker}/boards.json"), "boards")
    for r in rows:
        if str(r.get("IS_PRIMARY")) == "1" and str(r.get("IS_TRADED")) == "1":
            return r.get("BOARDID", BOARDS_FALLBACK)
    for r in rows:
        if str(r.get("IS_PRIMARY")) == "1":
            return r.get("BOARDID", BOARDS_FALLBACK)
    return BOARDS_FALLBACK


# ── quote / portfolio ──────────────────────────────────────────────────

def marketdata(ticker):
    board = board_for(ticker)
    url = f"{SHARES}/boards/{board}/securities/{ticker}/marketdata.json"
    rows = block(iss_get(url), "marketdata")
    return rows[0] if rows else None


def fmt_quote(ticker, md):
    last = md.get("LAST") or md.get("MARKETPRICE") or md.get("LASTTOPREVPRICE")
    if last is None:
        return f"{ticker}: нет данных (сегодня торгов нет?)"
    chg = md.get("LASTCHANGE")
    pct = md.get("LASTCHANGEPRCNT")
    move = ""
    if chg is not None:
        sign = "+" if (chg or 0) >= 0 else "-"
        pct_txt = f", {sign}{abs(pct):.2f}%" if pct is not None else ""
        move = f"  ({sign}{abs(chg):.2f}{pct_txt})"
    vol = md.get("VOLTODAY")
    val = md.get("VALTODAY")
    parts = [f"{ticker} @ {last:.2f} rub{move}"]
    if vol:
        parts.append(f"vol={int(vol):,}")
    if val:
        parts.append(f"val={int(val):,} rub")
    return "  ".join(parts).replace(",", " ")  # ascii-формат чисел по SKILL.md


def cmd_quote(args):
    ticker = args.ticker.upper()
    if not is_valid_ticker(ticker):
        sys.exit(f"некорректный тикер: {ticker!r}")
    md = marketdata(ticker)
    if not md:
        sys.exit(f"{ticker}: не найден на MOEX")
    print(fmt_quote(ticker, md))


def cmd_portfolio(args):
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    bad = [t for t in tickers if not is_valid_ticker(t)]
    if bad:
        sys.exit(f"некорректные тикеры: {', '.join(bad)}")
    rows, total_val = [], 0.0
    for t in tickers:
        md = marketdata(t)
        if not md:
            rows.append((t, None, None, None, None))
            continue
        last = md.get("LAST") or md.get("MARKETPRICE")
        chg = md.get("LASTCHANGE")
        pct = md.get("LASTCHANGEPRCNT")
        val = md.get("VALTODAY") or 0
        total_val += float(val or 0)
        rows.append((t, last, chg, pct, md.get("VOLTODAY")))
    w = (7, 10, 9, 8, 12)
    print(f"{'Ticker':<{w[0]}} {'Price':>{w[1]}} {'Change':>{w[2]}} {'Chg%':>{w[3]}} {'Volume':>{w[4]}}")
    print("-" * (sum(w) + 4))
    for t, last, chg, pct, vol in rows:
        if last is None:
            print(f"{t:<{w[0]}} {'нет данных':>{w[1] + w[2] + w[3] + w[4] + 3}}")
            continue
        chg_s = f"{chg:+.2f}" if chg is not None else "-"
        pct_s = f"{pct:+.2f}" if pct is not None else "-"
        vol_s = f"{int(vol):,}".replace(",", " ") if vol else "-"
        print(f"{t:<{w[0]}} {last:>{w[1]}.2f} {chg_s:>{w[2]}} {pct_s:>{w[3]}} {vol_s:>{w[4]}}")
    print("-" * (sum(w) + 4))
    print(f"Суммарный объём торгов: {int(total_val):,} rub".replace(",", " "))


# ── candles ────────────────────────────────────────────────────────────

def fetch_candles(ticker, interval, days):
    """Свечи за последние `days` дней с пагинацией по start (500/страница)."""
    board = board_for(ticker)
    url = f"{SHARES}/boards/{board}/securities/{ticker}/candles.json"
    date_from = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    dfs, start = [], 0
    while True:
        payload = iss_get(url, {"interval": interval, "from": date_from,
                                "limit": CANDLE_PAGE, "start": start})
        rows = block(payload, "candles")
        if not rows:
            break
        dfs.extend(rows)
        if len(rows) < CANDLE_PAGE:
            break
        start += len(rows)
        time.sleep(PAGE_PAUSE)
    return dfs


def cmd_candles(args):
    ticker = args.ticker.upper()
    if not is_valid_ticker(ticker):
        sys.exit(f"некорректный тикер: {ticker!r}")
    if args.interval not in INTERVALS:
        sys.exit(f"интервал {args.interval} не поддерживается: {sorted(INTERVALS)}")
    rows = fetch_candles(ticker, args.interval, args.days)
    if not rows:
        sys.exit("нет свечей за период (выходные/праздник?)")

    if args.output == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return
    if args.output == "csv":
        buf = io.StringIO()
        wr = csv.writer(buf)
        wr.writerow(["begin", "open", "high", "low", "close", "volume"])
        for r in rows:
            wr.writerow([r.get("BEGIN"), r.get("OPEN"), r.get("HIGH"),
                         r.get("LOW"), r.get("CLOSE"), r.get("VOLUME")])
        print(buf.getvalue(), end="")
        return
    if args.output == "plot":
        plot_candles(ticker, rows, args.interval)
        return

    # таблица + резюме
    print(f"{'begin':<19} {'open':>9} {'high':>9} {'low':>9} {'close':>9} {'volume':>12}")
    tail = rows[-30:]
    for r in tail:
        print(f"{str(r.get('BEGIN')):<19} {r.get('OPEN'):>9.2f} {r.get('HIGH'):>9.2f} "
              f"{r.get('LOW'):>9.2f} {r.get('CLOSE'):>9.2f} {int(r.get('VOLUME') or 0):>12,}".replace(",", " "))
    if len(rows) > len(tail):
        print(f"... показаны последние {len(tail)} из {len(rows)} свечей")
    closes = [r["CLOSE"] for r in rows]
    hi, lo = max(r["HIGH"] for r in rows), min(r["LOW"] for r in rows)
    trend = closes[-1] - closes[0]
    sign = "+" if trend >= 0 else "-"
    print(f"свечей={len(rows)}  max={hi:.2f}  min={lo:.2f}  "
          f"тренд={sign}{abs(trend):.2f} ({sign}{abs(trend / closes[0] * 100):.2f}%)")


def plot_candles(ticker, rows, interval):
    """Свечной график PNG (тела зелёный/красный, тени, панель объёма)."""
    import os
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.DataFrame(rows)
    df["begin"] = pd.to_datetime(df["BEGIN"])
    df = df.sort_values("begin").reset_index(drop=True)

    # не более 800 свечей на графике: ресемплим 1-min крупнее
    if len(df) > 800:
        rule = "15min" if interval == 1 else "1h"
        df = (df.set_index("begin")
                .resample(rule, closed="left", label="left")
                .agg({"OPEN": "first", "HIGH": "max", "LOW": "min",
                      "CLOSE": "last", "VOLUME": "sum"})
                .dropna(subset=["OPEN"]).reset_index())

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    x, w = range(len(df)), max(len(df) / 60.0, 0.6)
    for i, r in df.iterrows():
        color = "#26a69a" if r["CLOSE"] >= r["OPEN"] else "#ef5350"
        ax1.plot([i, i], [r["LOW"], r["HIGH"]], color=color, linewidth=0.7)
        ax1.bar(i, abs(r["CLOSE"] - r["OPEN"]) or (r["HIGH"] - r["LOW"]) * 0.01,
                bottom=min(r["OPEN"], r["CLOSE"]), width=w, color=color)
        ax2.bar(i, r["VOLUME"] or 0, width=w, color=color, alpha=0.8)

    closes = df["CLOSE"]
    stats = (f"{ticker}  {INTERVALS.get(interval, '')}\n"
             f"last={closes.iloc[-1]:.2f}\n"
             f"min={df['LOW'].min():.2f}  max={df['HIGH'].max():.2f}\n"
             f"avg={closes.mean():.2f}  n={len(df)}")
    ax1.text(0.99, 0.97, stats, transform=ax1.transAxes, ha="right", va="top",
             family="monospace", fontsize=9,
             bbox=dict(boxstyle="round", facecolor="#f0f0f0", alpha=0.85))

    step = max(1, len(df) // 20)  # не более 20 меток по X
    ticks = list(x[::step])
    ax2.set_xticks(ticks)
    ax2.set_xticklabels([df["begin"].iloc[i].strftime("%m-%d %H:%M") for i in ticks],
                        rotation=30, ha="right", fontsize=8)
    ax1.set_title(f"{ticker} — MOEX ISS", fontsize=12)
    ax1.set_ylabel("Price, rub")
    ax2.set_ylabel("Volume")
    for ax in (ax1, ax2):
        ax.grid(True, alpha=0.25)
    plt.tight_layout()

    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    out_dir = desktop if os.path.isdir(desktop) else os.getcwd()
    out = os.path.join(out_dir, f"{ticker}-candles.png")
    plt.savefig(out, dpi=130)
    plt.close(fig)
    print(f"CHART_PATH:{out}")


# ── news ───────────────────────────────────────────────────────────────

def cmd_news(args):
    params = {"start": 0, "limit": 100}
    if args.ticker:
        ticker = args.ticker.upper()
        if not is_valid_ticker(ticker):
            sys.exit(f"некорректный тикер: {ticker!r}")
        params["q"] = ticker
    if args.days:
        params["limit"] = max(params["limit"], args.days * 40)
    rows = block(iss_get(f"{ISS}/sitenews.json", params), "sitenews")
    cutoff = datetime.datetime.now() - datetime.timedelta(days=args.days)
    kept, out = [], []
    import html
    for r in rows:
        pub = str(r.get("PUBLISHED_AT") or "")
        try:
            dt = datetime.datetime.strptime(pub, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if dt < cutoff:
            continue
        kept.append((dt, html.unescape(str(r.get("TITLE", "")))))
    if not kept:
        sys.exit("новостей за период нет")
    if args.output == "json":
        print(json.dumps([{"published_at": dt.isoformat(), "title": t} for dt, t in kept],
                         ensure_ascii=False, indent=2))
        return
    for dt, title in kept:
        print(f"{dt:%Y-%m-%d %H:%M}  {title}")
    print(f"\nВсего: {len(kept)} за последние {args.days} дн.")


# ── справочные команды ────────────────────────────────────────────────

def cmd_security(args):
    ticker = args.ticker.upper()
    if not is_valid_ticker(ticker):
        sys.exit(f"некорректный тикер: {ticker!r}")
    rows = block(iss_get(f"{ISS}/securities.json",
                         {"q": ticker, "iss.only": "securities"}), "securities")
    for r in rows:
        if r.get("SECID") == ticker:
            print(f"{ticker}: {r.get('NAME')}")
            print(f"  ISIN: {r.get('ISIN')}  тип: {r.get('TYPE')}  "
                  f"группа: {r.get('GROUP')}")
            print(f"  основная доска: {r.get('PRIMARY_BOARDID')}  "
                  f"торгуется: {'да' if str(r.get('IS_TRADED')) == '1' else 'нет'}")
            return
    sys.exit(f"{ticker}: не найден")


def cmd_board(args):
    ticker = args.ticker.upper()
    if not is_valid_ticker(ticker):
        sys.exit(f"некорректный тикер: {ticker!r}")
    boards = block(iss_get(f"{ISS}/securities/{ticker}/boards.json"), "boards")
    if not boards:
        sys.exit(f"{ticker}: не найден")
    for r in boards:
        mark = "*" if str(r.get("IS_PRIMARY")) == "1" else " "
        traded = "торгуется" if str(r.get("IS_TRADED")) == "1" else "закрыта"
        print(f"{mark} {r.get('BOARDID'):<6} {r.get('TITLE')}  [{traded}]")
    print(f"\n* — основная доска. Валюта: {boards[0].get('CURRENCYID')}")


def cmd_orderbook(args):
    ticker = args.ticker.upper()
    if not is_valid_ticker(ticker):
        sys.exit(f"некорректный тикер: {ticker!r}")
    board = board_for(ticker)
    url = f"{SHARES}/boards/{board}/securities/{ticker}/orderbook.json"
    rows = block(iss_get(url), "orderbook")
    if not rows:
        sys.exit("стакан пуст (вне торговой сессии)")
    bids = sorted([r for r in rows if r.get("BID")], key=lambda r: -r["BID"])[:10]
    asks = sorted([r for r in rows if r.get("OFFER")], key=lambda r: r["OFFER"])[:10]
    print(f"{ticker}: стакан (топ-10)")
    print(f"{'BID':>10} {'BIDSIZE':>10}   |   {'OFFER':<10} {'OFFERSIZE':<10}")
    for i in range(max(len(bids), len(asks))):
        b = bids[i] if i < len(bids) else {}
        a = asks[i] if i < len(asks) else {}
        bid_s = f"{b.get('BID', 0):.2f}" if b.get("BID") else "-"
        bidsz_s = f"{int(b.get('BIDDEPTH') or 0):,}".replace(",", " ") if b.get("BIDDEPTH") else "-"
        ask_s = f"{a.get('OFFER', 0):.2f}" if a.get("OFFER") else "-"
        asksz_s = f"{int(a.get('OFFERDEPTH') or 0):,}".replace(",", " ") if a.get("OFFERDEPTH") else "-"
        print(f"{bid_s:>10} {bidsz_s:>10}   |   {ask_s:<10} {asksz_s:<10}")


SMARTLAB_DIV_URL = "https://smart-lab.ru/dividends/index/order_by_pay_date_asc/"


def parse_smartlab_dividends(html_text):
    """Таблица дивидендов smart-lab → [{ticker, name, period, amount, yield_pct,
    registry_date, last_buy_date, pay_date, close_price}].

    Колонки: компания, тикер, период, дивиденд руб, доходность, бейдж,
    дата закрытия реестра, последний день с дивидендом, дата выплаты, цена.
    """
    import html as html_mod
    import re

    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(cells) < 9:
            continue
        clean = [html_mod.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in cells]
        ticker = clean[1].upper()
        if not is_valid_ticker(ticker) or not clean[3]:
            continue
        try:
            rows.append({
                "ticker": ticker, "name": clean[0], "period": clean[2],
                "amount": float(clean[3].replace(" ", "").replace(",", ".")),
                "yield_pct": clean[4], "registry_date": clean[6],
                "last_buy_date": clean[7], "pay_date": clean[8],
                "close_price": clean[9],
            })
        except ValueError:
            continue
    return rows


def dividends_from_smartlab(ticker):
    """Объявленные дивиденды с smart-lab.ru — неофициальный источник:
    ISS больше не отдаёт блок dividends, smart-lab агрегирует объявления эмитентов."""
    try:
        r = requests.get(SMARTLAB_DIV_URL, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    except Exception as e:
        print(f"ошибка запроса smart-lab: {e}", file=sys.stderr)
        return []
    return [d for d in parse_smartlab_dividends(r.text) if d["ticker"] == ticker]


def cmd_dividends(args):
    ticker = args.ticker.upper()
    if not is_valid_ticker(ticker):
        sys.exit(f"некорректный тикер: {ticker!r}")
    # ISS раньше отдавал /securities/{T}/dividends.json — пробуем на случай возврата
    rows = block(iss_get(f"{ISS}/securities/{ticker}/dividends.json",
                         {"iss.only": "dividends"}), "dividends")
    if rows:
        print(f"{'дата реестра':<12} {'выплата':>10}")
        for r in rows:
            print(f"{r.get('REGISTRYCLOSEDDATE') or r.get('REGISTRYCLOSEDATE') or '-':<12} "
                  f"{(r.get('DIVIDENDSUM') or 0):>10.2f}")
        return
    # фолбэк: объявления с smart-lab.ru
    divs = dividends_from_smartlab(ticker)
    if not divs:
        sys.exit(f"{ticker}: дивиденды недоступны (ISS не отдаёт блок, "
                 f"на smart-lab объявлений нет)")
    print(f"{ticker}: объявленные дивиденды (источник: smart-lab.ru, неофициально)")
    print(f"{'период':<12} {'руб/акц':>8} {'доходн.':>8} {'реестр':>11} {'выплата':>11}")
    for d in divs:
        print(f"{d['period']:<12} {d['amount']:>8.2f} {d['yield_pct']:>8} "
              f"{d['registry_date']:>11} {d['pay_date']:>11}")
    total = sum(d["amount"] for d in divs)
    print(f"\nВсего объявлено: {total:.2f} руб/акц за {len(divs)} выплат(ы)")


def cmd_indices(args):
    codes = [c.strip().upper() for c in args.codes.split(",") if c.strip()]
    payload = iss_get(f"{ISS}/engines/stock/markets/index/boards/SNDX/securities.json",
                      {"iss.only": "securities,marketdata"})
    names = {r["SECID"]: r.get("SHORTNAME") for r in block(payload, "securities")}
    mds = {r["SECID"]: r for r in block(payload, "marketdata")}
    shown = 0
    for code in codes:
        md = mds.get(code)
        if not md:
            continue
        val = md.get("CURRENTVALUE") or md.get("LASTVALUE")
        pct = md.get("LASTCHANGEPRC")
        if val is None:
            print(f"{code:<8} нет данных за сегодня")
            continue
        sign = "+" if (pct or 0) >= 0 else "-"
        print(f"{code:<8} {val:>12.2f}  {sign}{abs(pct):.2f}%   {names.get(code, '')}")
        shown += 1
    if not shown:
        sys.exit("индексы недоступны")


def cmd_securities(args):
    board = args.board or BOARDS_FALLBACK
    url = f"{SHARES}/boards/{board}/securities.json"
    rows, start = [], 0
    while True:
        page = block(iss_get(url, {"limit": 100, "start": start}), "securities")
        if not page:
            break
        rows.extend(page)
        if len(page) < 100 or len(rows) >= args.limit:
            break
        start += len(page)
        time.sleep(PAGE_PAUSE)
    rows = rows[:args.limit]
    if not rows:
        sys.exit(f"доска {board}: пусто")
    print(f"{'Ticker':<8} {'Name':<24} {'PrevClose':>10} {'Lot':>5} {'List':>5}")
    print("-" * 56)
    for r in rows:
        print(f"{r.get('SECID') or '-':<8} {str(r.get('SHORTNAME') or '-')[:24]:<24} "
              f"{(r.get('PREVPRICE') or 0):>10.2f} {(r.get('LOTSIZE') or 0):>5} "
              f"{(r.get('LISTLEVEL') or 0):>5}")
    print(f"\nДоска {board}: {len(rows)} бумаг")


def cmd_marketdata(args):
    payload = iss_get(f"{ISS}/engines/stock/markets/index/boards/SNDX/securities.json",
                      {"iss.only": "securities,marketdata"})
    mds = {r["SECID"]: r for r in block(payload, "marketdata")}
    imoex = mds.get("IMOEX")
    if imoex:
        val = imoex.get("CURRENTVALUE") or imoex.get("LASTVALUE")
        pct = imoex.get("LASTCHANGEPRC")
        valtod = imoex.get("VALTODAY")
        sign = "+" if (pct or 0) >= 0 else "-"
        print(f"IMOEX: {val:.2f} ({sign}{abs(pct):.2f}%)  "
              f"объём рынка: {int(valtod or 0):,} rub".replace(",", " "))
    for code in ("MOEXBC", "RGBI"):
        md = mds.get(code)
        if md:
            val = md.get("CURRENTVALUE") or md.get("LASTVALUE")
            pct = md.get("LASTCHANGEPRC")
            sign = "+" if (pct or 0) >= 0 else "-"
            print(f"{code}: {val:.2f} ({sign}{abs(pct):.2f}%)")


# ── CLI ────────────────────────────────────────────────────────────────

def build_parser():
    # --output ДО подкоманды (особенность argparse с subparsers, см. SKILL.md)
    p = argparse.ArgumentParser(description="MOEX ISS CLI")
    p.add_argument("--output", default="table",
                   choices=["table", "json", "csv", "plot"],
                   help="формат вывода (для candles/news); ставить ДО подкоманды")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("quote", help="котировка одной бумаги")
    q.add_argument("ticker")

    pf = sub.add_parser("portfolio", help="сводка по нескольким бумагам")
    pf.add_argument("tickers")

    c = sub.add_parser("candles", help="OHLCV свечи (+ график)")
    c.add_argument("ticker")
    c.add_argument("--interval", type=int, default=24, choices=sorted(INTERVALS))
    c.add_argument("--days", type=int, default=7)

    n = sub.add_parser("news", help="новости биржи (sitenews)")
    n.add_argument("ticker", nargs="?", default="")
    n.add_argument("--days", type=int, default=1)

    for name, help_txt in (("security", "ISIN, название, тип"),
                           ("board", "режим торгов, доски"),
                           ("orderbook", "стакан (в сессию)"),
                           ("dividends", "дивиденды")):
        s = sub.add_parser(name, help=help_txt)
        s.add_argument("ticker")

    i = sub.add_parser("indices", help="IMOEX, RTSI и др.")
    i.add_argument("codes", nargs="?", default="IMOEX,RTSI,MOEXBC,RGBI")

    sec = sub.add_parser("securities", help="все бумаги доски")
    sec.add_argument("--board", default=BOARDS_FALLBACK)
    sec.add_argument("--limit", type=int, default=50)

    sub.add_parser("marketdata", help="сводка по рынку")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {
        "quote": cmd_quote, "portfolio": cmd_portfolio, "candles": cmd_candles,
        "news": cmd_news, "security": cmd_security, "board": cmd_board,
        "orderbook": cmd_orderbook, "dividends": cmd_dividends,
        "indices": cmd_indices, "securities": cmd_securities,
        "marketdata": cmd_marketdata,
    }
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()
