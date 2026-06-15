"""Desktop launcher for Kronos Signal — Hourly config.
Запускается по двойному клику. Использует конфиг config-hourly.yaml.
"""
import os
import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
SCRIPT = BASE_DIR / "scripts" / "run.py"
LOG = BASE_DIR / "log-hourly.txt"

print("Запуск Kronos Signal (Hourly)...")
print("(1h свечи, MC=3, контекст ~85 дней)\n")

result = subprocess.run(
    [str(VENV_PYTHON), str(SCRIPT), "--config", "config-hourly.yaml"],
    cwd=str(BASE_DIR),
    capture_output=True,
    text=True,
    timeout=600
)

if result.stdout:
    print(result.stdout)
if result.stderr:
    # фильтруем технический вывод — он дублирует stdout
    for line in result.stderr.split("\n"):
        if "Warning:" in line or "Loading" in line or "[SBERP]" in line \
           or "candles" in line or "Model loaded" in line or "✓" in line:
            print(line)

print(f"\nГотово! Результат записан в {LOG.name}")
input("\nНажми Enter для закрытия...")
