# Kronos Signal

Прогнозирование цен MOEX-акций с помощью Kronos Foundation Model.
Сигналы BUY/SELL/HOLD с текстовой интерпретацией для трейдера.

## Возможности

- **Два режима:** внутридневной (5-min, прогноз на 2ч) и дневной (1h, прогноз на 24ч)
- **MOEX ISS API** — бесплатно, без регистрации, без лимитов
- **Kronos-mini** (4M params) — предобученная модель для K-line (OHLCV), принята в AAAI 2026
- **Модель локально** — интернет не нужен при запуске, только для обновления
- **Интерпретация сигналов** — понятный текстовый разбор, не просто BUY/SELL
- **Работает на CPU** — даже на старом железе (GeForce 940MX, ~4 сек/шаг)

## Быстрый старт

```bash
# 1. Клонировать
git clone <repo-url>
cd kronos-signal

# 2. Установить зависимости
uv venv .venv
source .venv/Scripts/activate   # Windows
# source .venv/bin/activate     # Linux/macOS
uv pip install -r requirements.txt

# 3. Запустить
python scripts/run.py
```

## Ярлыки (Windows)

Ярлыки на рабочем столе запускают анализ двойным кликом:
- **Kronos Signal** — 5-min версия (~2 мин)
- **Kronos Signal Hourly** — 1h версия с MC=3 (~4 мин)

## Результат

```
Ticker     Current   Forecast Signal     Chg%   Up%
SBERP       324.83     325.11 HOLD      +0.1%  100%

SBERP: 324.83 -> 325.11 rub
[HOLD] Сильный уклон в рост. Держать.
Уверенность в рост: 100% - почти все 2ч цена выше
=> Действие: держать позицию, продавать рано
```

## Структура проекта

- `scripts/run.py` — основной конвейер
- `config.yaml` / `config-hourly.yaml` — конфиги
- `models/` — Kronos-mini + Tokenizer (32 MB)
- `kronos-source/model/` — исходный код Kronos
- `references/trader-guide.md` — инструкция по сигналам

## Требования

- Python 3.11+
- 4 GB RAM
- 500 MB диска (с моделями)

## Лицензия

MIT
