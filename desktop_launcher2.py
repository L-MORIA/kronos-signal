"""Desktop launcher for Kronos Signal — Hourly config.
Запускается по двойному клику — показывает прогресс в реальном времени."""
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
SCRIPT = BASE_DIR / "scripts" / "run.py"

print("Запуск Kronos Signal (Hourly)...")
print("(1h свечи, MC=3, контекст ~85 дней)\n")

try:
    subprocess.run(
        [str(VENV_PYTHON), str(SCRIPT), "--config", "config-hourly.yaml"],
        cwd=str(BASE_DIR),
        check=True,
    )
except subprocess.CalledProcessError as e:
    print(f"\nОшибка: {e}", file=sys.stderr)
except FileNotFoundError as e:
    print(f"\nОшибка: {e}", file=sys.stderr)
    print("Запустите установку: cd kronos-signal && uv venv .venv && uv pip install -r requirements.txt")

print("\nГотово! Результат записан в logs/log.txt")
print("Нажми Enter для закрытия...", end="", flush=True)
input()
