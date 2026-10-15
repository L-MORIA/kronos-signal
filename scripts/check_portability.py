# -*- coding: utf-8 -*-
"""
Pre-flight проверка portability проекта kronos-signal.

Запуск из корня проекта (или передай корень первым аргументом):
    python scripts/check_portability.py [path/to/kronos-signal]
    python scripts/check_portability.py --allow-absolute   # не падать на абсолютных путях (фиксированная машина)

Проверяет:
  - launch.bat / launch2.bat — нет ли абсолютных путей вида C:\\kronos-signal (должен быть %~dp0)
  - config.yaml / config-hourly.yaml — log_file и model_name относительные
Выводит OK/WARNING/CRITICAL для каждого пункта, exit 0 = готово, exit 1 = есть CRITICAL.
Скрипт только читает файлы — ничего не модифицирует.
"""
import os
import re
import sys
import pathlib

ALLOW_ABSOLUTE = "--allow-absolute" in sys.argv[1:]


def find_base() -> pathlib.Path:
    """Корень проекта: аргумент → cwd → cwd/kronos-signal → parent.parent от скрипта."""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cands = []
    if args:
        cands.append(pathlib.Path(args[0]).resolve())
    cwd = pathlib.Path.cwd()
    cands += [cwd, cwd / "kronos-signal", pathlib.Path(__file__).resolve().parent.parent]
    for c in cands:
        if (c / "config.yaml").exists() or (c / "launch.bat").exists():
            return c
    return cwd


BASE = find_base()
BAT_FILES = ["launch.bat", "launch2.bat"]
CONFIG_FILES = ["config.yaml", "config-hourly.yaml"]


def check_bat_no_absolute() -> bool:
    """launch.bat / launch2.bat не должны содержать абсолютные пути к kronos-signal."""
    ok = True
    for name in BAT_FILES:
        p = BASE / name
        if not p.exists():
            print(f"[WARNING] {name} не найден")
            continue
        text = p.read_text(encoding="cp1251", errors="replace")
        # Ищем hardcoded C:\kronos-signal или D:\kronos-signal (и кавычные варианты)
        if re.search(r'[A-Za-z]:\\+kronos-signal', text):
            msg = f"[CRITICAL] {name}: найден абсолютный путь к kronos-signal. Замените на %~dp0"
            if ALLOW_ABSOLUTE:
                msg = f"[WARNING] {name}: абсолютный путь (игнорируется из-за --allow-absolute)"
            else:
                ok = False
            print(msg)
        else:
            print(f"[OK] {name}: относительные пути")
    return ok


def check_config_relative_log() -> bool:
    """config.yaml/config-hourly.yaml: log_file и model_name должны быть относительными."""
    ok = True
    for name in CONFIG_FILES:
        p = BASE / name
        if not p.exists():
            print(f"[WARNING] {name} не найден")
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        problems = []
        if re.search(r'log_file:\s*[A-Za-z]:[\\/]', text):
            problems.append("log_file использует абсолютный путь — замените на logs/log.txt")
        if re.search(r'model_name:\s*[A-Za-z]:[\\/]', text):
            problems.append("model_name использует абсолютный путь — замените на models/Kronos-mini")
        if problems:
            for pr in problems:
                msg = f"[CRITICAL] {name}: {pr}"
                if ALLOW_ABSOLUTE:
                    msg = f"[WARNING] {name}: {pr} (игнорируется из-за --allow-absolute)"
                else:
                    ok = False
                print(msg)
        else:
            print(f"[OK] {name}: пути относительные")
    return ok


if __name__ == "__main__":
    print(f"Корень проекта: {BASE}")
    ok = check_bat_no_absolute()
    ok &= check_config_relative_log()
    if ok:
        print("\nOK: всё готово к запуску. Hardcoded пути не найдены.")
        sys.exit(0)
    else:
        print("\nFAIL: найдены проблемы. Исправьте и запустите снова.")
        sys.exit(1)
