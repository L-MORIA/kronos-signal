---
name: moex-iss
description: "MOEX ISS API — котировки, свечи, стакан, индексы, дивиденды и справочные данные Московской Биржи. Использовать когда пользователь спрашивает про цены акций MOEX (SBER, GAZP, LKOH, VTBR, SBERP и др.), хочет получить сводку по портфелю, посмотреть свечи/график, узнать дивиденды, проверить режим торгов или получить любую информацию по российским акциям через MOEX ISS. НЕ использовать для прогнозов/сигналов — это делает kronos-signal."
version: 1.1.0
author: L-MORIA
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [moex, trading, finance, stocks, russia, market-data]
    related_skills: [kronos-signal, polymarket]
prerequisites:
  commands: [python3]
  pip_packages: [requests]
  optional_pip_packages: [matplotlib]
---

# MOEX ISS Skill

Прямой доступ к данным **Московской Биржи** через публичный API ISS (без регистрации, бесплатно).

## Когда срабатывает

- Пользователь спрашивает цену любой акции MOEX: SBER, GAZP, LKOH, VTBR, SBERP и т.д.
- Пользователь хочет сводку по портфелю из нескольких бумаг
- Пользователь просит свечи/график/OHLCV по бумаге
- Пользователь спрашивает про дивиденды, режим торгов, справочную информацию
- Пользователь хочет узнать текущие индексы (IMOEX, RTSI)
- Пользователь говорит "что там по рынку сегодня"
- Пользователь спрашивает про новости биржи, остановки торгов, дискретные аукционы, расширение коридоров

## Быстрый старт

```bash
python scripts/moex_iss.py quote SBER
python scripts/moex_iss.py portfolio SBER,GAZP,LKOH,SBERP,VTBR
python scripts/moex_iss.py --output plot candles FEES --interval 1 --days 30
```

## Команды

### quote

```bash
moex_iss.py quote SBER
# SBER @ 300.76 rub  (-0.43, -0.14%)  vol=1,357,409  val=408,275,326 rub
```

### portfolio

```bash
moex_iss.py portfolio SBER,GAZP,LKOH,SBERP,VTBR
# Таблица: Ticker, Price, Change, Change%, Volume
```

### candles -- OHLCV candles (+ chart)

```bash
# Daily candles for 1 week
moex_iss.py candles SBER --interval 24 --days 7

# 10-min intraday for 1 day
moex_iss.py candles SBER --interval 10 --days 1

# Hourly for 1 month
moex_iss.py candles GAZP --interval 60 --days 30

# JSON output
moex_iss.py candles SBER --interval 24 --days 5 --output json

# CSV output
moex_iss.py candles SBER --interval 10 --days 1 --output csv

# CANDLESTICK CHART as PNG on Desktop
# NOTE: --output plot MUST come BEFORE the subcommand (argparse quirk)
moex_iss.py --output plot candles FEES --interval 1 --days 30
```

**Интервалы:** 1=1min, 10=10min, 60=1h, 24=1d, 7=1w, 31=1M.

**5-min нет в MOEX ISS.** Использовать interval=1 (1-min) и resample. `scripts/plot.py` делает это автоматически для больших диапазонов.

**Лимит 500 свечей на запрос.** Для 1-min это ~1 день. Для месяца — итерация по дням (c 0.3s паузой). `scripts/plot.py` делает это. `moex_iss.py` без `--output plot` — один запрос, 500 свечей.

**Выходные:** MOEX закрыт Сб-Вс/праздники. Не показывать пустые строки или нули.

### news — новости биржи

```bash
# Все новости за сегодня
moex_iss.py news

# Новости за последние 3 дня
moex_iss.py news --days 3

# Новости по тикеру (SBERP, GAZP и т.д.)
moex_iss.py news SBERP --days 7

# JSON
moex_iss.py news SBERP --days 7 --output json
```

**~20-30 сообщений в день.** Публикуются в реальном времени в течение торговой сессии.
Включают: остановки/начало торгов, дискретные аукционы, расширение ценовых коридоров, меры дестабилизации, изменения в списках, итоги размещений.

Поиск по тикеру (параметр `q` MOEX) возвращает новости, где упоминается бумага — как правило, это меры дестабилизации и коридоры.

### rss-news — сбор новостей из внешних RSS-источников

MOEX news даёт только биржевые уведомления. Для аналитики и обзоров используется скрипт `rss_market_news.py` (лежит в `~/.hermes/scripts/rss_market_news.py`):

**Подключённые RSS-источники:**
| Источник | URL | Тип контента |
|----------|-----|-------------|
| **SmartLab** | `smart-lab.ru/rss/` | Аналитика рынка РФ, дивиденды, обсуждения эмитентов |
| **Investing.com Россия** | `ru.investing.com/rss/news.rss` | Глобальные финансы на русском |
| **ПРАЙМ** | `1prime.ru/export/rss2/index.xml` | Экономика, макростатистика |
| **Интерфакс** | `interfax.ru/rss` | Деловые новости |

**Фильтрация по тикерам:** автоматически ищет ключевые слова (SBER→сбер/sberbank, GAZP→газпром/gazprom, LKOH→лукойл/lukoil, SBERP→сбер преф/sberp, VTBR→втб/vtb)

```bash
# Сбор новостей по всем 5 тикерам за 48ч
python ~/.hermes/scripts/rss_market_news.py --hours 48

# Только по SBER и GAZP
python ~/.hermes/scripts/rss_market_news.py --tickers SBER,GAZP

# JSON для скриптов
python ~/.hermes/scripts/rss_market_news.py --json

# Режим cron: только новые (непросмотренные)
python ~/.hermes/scripts/rss_market_news.py --hours 24 --cron
```

**Cron:** настроен `0 9 * * 1-5` — будни в 9:00, сбор + анализ через LLM.
**Трекер просмотренных:** `~/.hermes/cache/rss-news/seen_urls.txt`

### Прочие команды

```bash
moex_iss.py security SBER      # ISIN, название, тип, листинг
moex_iss.py board SBER          # режим торгов, лот, шаг цены
moex_iss.py orderbook SBER     # стакан (только в сессию)
moex_iss.py dividends SBER     # дивиденды
moex_iss.py indices             # IMOEX, RTSI, MOEXBC и др.
moex_iss.py securities --board TQBR  # все бумаги на доске
moex_iss.py marketdata          # сводка по рынку
```

## Формат ответа

- **Цена:** `TICKER @ X.XX rub (+/-Y.YY, +/-Z.ZZ%)` + объём
- **Свечи:** таблица + резюме (макс/мин/тренд)
- **Портфель:** таблица + суммарный объём
- **Индексы:** построчно с процентами
- Только ASCII (без стрелок/эмодзи)
- Если сегодня выходной — "сегодня торгов нет", не выводить нули/пустые строки
- Не добавлять оговорок про точность (источник — официальный API биржи)

## Pitfalls

1. **SBERP — TQBR, не TQBD.** Все префы Сбербанка торгуются в основном стакане.
2. **Выходные = пустой ответ.** Не выводить нули/графики за Сб-Вс.
3. **from+till обязательны.** Без till — некорректные данные.
4. **Регистр колонок разный.** candles — lower case, marketdata — UPPER CASE. Всегда читать columns из ответа.
5. **CHANGEPCT нет в marketdata.** Вычислять: change / last * 100.
6. **Лимит 500 свечей** на запрос. Для больших диапазонов — итерация по дням.
7. **`--output plot` ставить ДО подкоманды.** argparse с subparsers: `moex_iss.py --output plot candles TICKER`, не после.
8. **График — только свечной.** Не линейный. Традиционные японские свечи: зелёное тело (bullish), красное (bearish), тени high-low. Нижняя панель — объём с цветом по свече. Стат-блок в правом верхнем углу.
9. **`--output plot` с interval=1 и days>3:** авто-ресемпл до крупного таймфрейма (чтобы не >800 свечей). Не показывать более 20 меток на оси X.

## RSS-мониторинг новостей по тикерам

Скрипт `scripts/rss_market_news.py` собирает новости из 4 RSS-финасовых источников и фильтрует по 5 тикерам (SBER, GAZP, LKOH, SBERP, VTBR).

**Источники:**

| Источник | RSS URL |
|----------|---------|
| SmartLab | `https://smart-lab.ru/rss/` |
| Investing.com Россия | `https://ru.investing.com/rss/news.rss` |
| ПРАЙМ | `https://1prime.ru/export/rss2/index.xml` |
| Интерфакс | `https://www.interfax.ru/rss` |

**Фильтрация:** по ключевым словам (сбер/sber/sberbank, газпром/gazprom, лукойл/lukoil, втб/vtb и т.д.)

**Использование:**

```bash
python scripts/rss_market_news.py --hours 48
python scripts/rss_market_news.py --hours 24 --cron          # только новые
python scripts/rss_market_news.py --hours 24 --tickers SBER  # по одному тикеру
python scripts/rss_market_news.py --hours 48 --json          # JSON
```

**Cron:** создана задача `Новости по 5 фишкам` (будни 9:00):
- Собирает свежие новости за 24ч → анализирует через LLM → сводка
- `cronjob action='list'` — просмотр статуса
- `cronjob action='run' job_id=...` — ручной запуск

**Кэш:** `news_cache/seen_urls.txt` — чтобы не дублировать прочитанные новости.

## Reference files

- `scripts/moex_api.py` — чистый клиент MOEX ISS (можно импортировать)
- `scripts/moex_iss.py` — CLI-обёртка (все команды, `--output plot`)
- `scripts/moex_plot.py` — matplotlib-функция для `--output plot`
- `scripts/plot.py` — standalone скрипт: 5-min график за месяц (с итерацией по дням)
- `scripts/rss_market_news.py` — RSS-сборщик новостей по 5 тикерам
- `references/moex-boards.md` — engine/market/board архитектура MOEX
- `references/moex-endpoints.md` — API endpoint reference, quirks
