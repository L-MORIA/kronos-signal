# Kronos Signal

AI-агент для прогнозирования цен MOEX-акций с помощью Kronos Foundation Model.
Генерирует сигналы BUY/SELL/HOLD на основе forecast нейросети.

## Для кого этот проект

Приватный. Трейдер использует для анализа SBERP (Сбербанк преф) на MOEX.
Два режима:
- **5-min** — внутридневной прогноз на 2 часа (~2 мин на запуск)
- **Hourly** — дневной прогноз на 24 часа, Monte Carlo усреднение (~4 мин на запуск)

## Быстрый старт

```bash
git clone <repo-url>
cd kronos-signal
uv venv .venv && source .venv/Scripts/activate && uv pip install -r requirements.txt
python scripts/run.py
```

## Структура проекта

```
kronos-signal/
├── AGENTS.md                 # этот файл — описание для AI-агентов
├── README.md
├── LICENSE                   # MIT
├── .gitignore
├── requirements.txt
├── config.yaml               # 5-min версия (SBERP, 1min→5min, MC=1, T=1.0)
├── config-hourly.yaml        # Hourly версия (SBERP, 1h→1h, MC=3, T=0.85)
├── launch.bat                # ярлык для 5-min (Windows)
├── launch2.bat               # ярлык для Hourly (Windows)
├── models/
│   ├── Kronos-mini/          # 4M params, 16 MB
│   │   ├── config.json
│   │   └── model.safetensors
│   └── Kronos-Tokenizer-2k/  # BSQ tokenizer, 15 MB
│       ├── config.json
│       └── model.safetensors
├── kronos-source/
│   └── model/                # исходный код Kronos
│       ├── __init__.py
│       ├── kronos.py
│       └── module.py
├── scripts/
│   ├── run.py                # основной конвейер (fetch→predict→signal→interpret)
│   └── md_to_docx.py         # конвертер .md → .docx
├── references/
│   ├── trader-guide.md       # инструкция для трейдера
│   ├── trader-guide.docx     # DOCX-версия
│   └── architecture.html     # архитектурная схема (открыть в браузере)
└── update_models/
    ├── update_models.py       # проверка обновлений на HuggingFace Hub
    └── update_models.bat
```

## Конвейер run.py

1. `fetch_moex()` — MOEX ISS API (бесплатно, без регистрации), 1-min или 1h свечи
2. `resample()` — агрегация в нужный таймфрейм (5min или оставить 1h)
3. `KronosPredictor.predict()` — авторегрессивный forecast 24 шага
4. `signal()` — сравнение forecast close с последней ценой, порог 2%
5. `interpret()` — текстовый разбор для трейдера

## Команды

```bash
# 5-min версия (SBERP)
python scripts/run.py

# Hourly версия
python scripts/run.py --config config-hourly.yaml

# Обновить модели с HuggingFace Hub
python update_models/update_models.py
```

## Параметры config.yaml

| Параметр | Описание | Дефолт |
|----------|----------|--------|
| tickers | список тикеров MOEX | [SBERP] |
| interval | исходные свечи из MOEX (1=1мин, 60=1ч) | 1 |
| resample_to | таймфрейм агрегации | 5 |
| lookback_candles | сколько свечей подаём в модель | 150 |
| pred_len | сколько свечей прогнозируем | 24 |
| threshold_pct | порог сигнала BUY/SELL | 2.0 |
| sample_count | Monte Carlo семплов | 1 |
| temperature | температура predict | 1.0 |
| top_p | nucleus sampling | 0.9 |
| top_k | top-k фильтр | 0 |
