"""Desktop launcher for Kronos Signal.
Запускается по двойному клику — показывает прогресс в реальном времени."""
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
SCRIPT = BASE_DIR / "scripts" / "run.py"

print("Запуск Kronos Signal...\n")

proc = subprocess.Popen(
    [str(VENV_PYTHON), str(SCRIPT)],
    cwd=str(BASE_DIR),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1,
)

# Live stdout
for line in iter(proc.stdout.readline, ""):
    print(line, end="", flush=True)

# Live stderr
for line in iter(proc.stderr.readline, ""):
    print(line, end="", flush=True, file=sys.stderr)

proc.wait()

print("\nГотово! Результат записан в log.txt")
input("\nНажми Enter для закрытия...")
