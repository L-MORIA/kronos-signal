---
name: kronos-signal
description: "Kronos foundation model forecast for MOEX tickers — fetch candles from MOEX ISS, predict with Kronos-mini, output BUY/SELL/HOLD signal"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [finance, trading, moex, kronos, forecast, signal]
prerequisites:
  commands: [python]
  pip_packages: [requests, pyyaml, einops, safetensors, huggingface_hub]
---

# Kronos Signal

Скилл для прогнозирования цен MOEX-акций через Kronos Foundation Model.

**Источник данных:** MOEX ISS API (бесплатно, без регистрации)
**Модель:** Kronos-mini (4M параметров) на CPU

## Workflow

```
Каждый час (cronjob):
  1. fetch_moex.py → 1-min свечи из MOEX ISS
  2. resample → 5-min свечи
  3. Kronos-mini.predict(pred_len=100) → forecast ~500 мин
  4. Сравнить forecast close с текущей ценой → BUY/SELL/HOLD
  5. Вывод в чат + лог C:\kronos-signal\log.txt
```

## Настройка

### 1. Установка зависимостей

```bash
pip install requests pyyaml einops safetensors huggingface_hub
```

### 2. Структура

```
C:\kronos-signal\
├── config.yaml              # тикеры, пороги, модель
├── log.txt                  # лог сигналов
├── kronos-source/           # клон репозитория Kronos
│   └── model/
├── kronos-signal.ico        # иконка ярлыка
└── scripts/
    └── run.py               # entry point
```

### 3. Запуск вручную

```bash
cd C:\kronos-signal && .venv\Scripts\python scripts\run.py
```

### 4. Cronjob (раз в час)

```bash
hermes cron every 1h --name kronos-signal --skills kronos-signal
```

## Config

См. `C:\kronos-signal\config.yaml`:

```yaml
tickers:
  - SBER
  - GAZP
  - LKOH
  - SBERP
  - VTBR
interval: 1        # 1 = 1 минута из MOEX
resample_to: 5     # агрегация в 5-минутные свечи
lookback_candles: 2100   # ~7 торговых дней
pred_len: 100      # прогноз на ~500 мин (~8 часов)
threshold_pct: 2.0 # порог BUY/SELL в %
model_name: NeoQuasar/Kronos-mini
tokenizer_name: NeoQuasar/Kronos-Tokenizer-2k
```

## Сигналы

| Signal | Условие |
|--------|---------|
| **BUY**  | forecast close > last close + 2% |
| **SELL** | forecast close < last close - 2% |
| **HOLD** | между -2% и +2% |

Дополнительно: Upside Probability — доля спрогнозированных свечей, где цена выше последней известной.

## Питфоллы

1. **MOEX ISS лимит 500 свечей/запрос** — делаем несколько запросов на разные дни
2. **5-min candles не поддерживаются напрямую** — получаем 1-min свечи, агрегируем в 5-min
3. **Гэпы (ночь/выходные)** — заполняем последней ценой (ffill)
4. **Торговая сессия MOEX 10:00–18:45 MSK** — вне сессии данных нет
5. **Модель обучена на крипто-биржах** — на MOEX точность может отличаться
6. **Kronos не учитывает корпоративные события** — дивиденды, сплиты, отсечки
