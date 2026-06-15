"""Desktop launcher for Kronos Signal.
Запускается по двойному клику — всегда, без ограничений.
"""
import os
import sys
import time
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
SCRIPT = BASE_DIR / "scripts" / "run.py"

print("Запуск Kronos Signal...\n")

result = subprocess.run(
    [str(VENV_PYTHON), str(SCRIPT)],
    cwd=str(BASE_DIR),
    capture_output=True,
    text=True,
    timeout=600
)

if result.stdout:
    print(result.stdout)
if result.stderr:
    print(result.stderr, file=sys.stderr)

print("\nГотово! Результат записан в log.txt")
input("\nНажми Enter для закрытия...")
