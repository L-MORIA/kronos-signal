"""Проверка и обновление моделей Kronos с HuggingFace Hub.

Запуск: python C:/kronos-models/update_models.py
Сравнивает локальную версию с последней на HF Hub.
Если есть новая - скачивает в C:/kronos-models/.
"""
import os
import json
import requests
import hashlib
from pathlib import Path

MODELS_DIR = Path("C:/kronos-signal/models").resolve()
VERSION_FILE = Path("C:/kronos-signal/.version")

REPOS = {
    "Kronos-mini": "NeoQuasar/Kronos-mini",
    "Kronos-Tokenizer-2k": "NeoQuasar/Kronos-Tokenizer-2k",
}

def get_local_version():
    """Прочитать сохранённую дату последнего обновления."""
    if not VERSION_FILE.exists():
        return None
    try:
        return VERSION_FILE.read_text().strip()
    except:
        return None

def save_local_version(date_str):
    VERSION_FILE.write_text(f"{date_str}\n")

def get_remote_info(repo_id):
    """Получить lastModified дату модели с HF Hub."""
    url = f"https://huggingface.co/api/models/{repo_id}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("lastModified", None)
    except Exception as e:
        print(f"  Ошибка запроса к HF Hub: {e}")
        return None

def check_snapshot_integrity(local_dir):
    """Проверить, что в локальной директории есть model.safetensors и config.json."""
    return (local_dir / "model.safetensors").exists() and (local_dir / "config.json").exists()

def main():
    print("=" * 60)
    print("  Проверка обновлений моделей Kronos")
    print("=" * 60)
    print()

    # Проверка интернета
    try:
        requests.get("https://huggingface.co", timeout=5)
    except:
        print("  Нет доступа к HuggingFace Hub. Интернет не доступен.")
        print("  Локальные модели актуальны (проверка невозможна).")
        return

    # Текущая локальная версия
    local_ver = get_local_version()
    if local_ver:
        print(f"  Локальная версия: {local_ver}")
    else:
        print(f"  Локальная версия: неизвестна (первая проверка)")
    print()

    updated = False
    for folder, repo_id in REPOS.items():
        local_dir = MODELS_DIR / folder
        if not local_dir.exists():
            print(f"  ⚠ {folder}: директория не найдена")
            continue
        
        if not check_snapshot_integrity(local_dir):
            print(f"  ⚠ {folder}: повреждена (нет model.safetensors)")
            continue

        print(f"  {folder} ({repo_id})...")
        remote_date = get_remote_info(repo_id)
        if not remote_date:
            print(f"    Не удалось получить информацию с HF Hub")
            continue

        print(f"    Последнее изменение на сервере: {remote_date}")

        # Сравнение
        if local_ver and remote_date <= local_ver:
            print(f"    ✓ Актуальна")
        else:
            print(f"    → Есть обновление! Скачиваю...")
            from huggingface_hub import snapshot_download
            try:
                snapshot_download(
                    repo_id=repo_id,
                    local_dir=str(local_dir),
                    local_dir_use_symlinks=False,
                    resume_download=True,
                )
                print(f"    ✓ Обновлено: {local_dir}")
                updated = True
            except Exception as e:
                print(f"    ⚠ Ошибка скачивания: {e}")

        print()

    # Обновить версию, если что-то поменялось
    if updated or not local_ver:
        # Берём самую свежую дату из удалённых репозиториев
        dates = []
        for repo_id in REPOS.values():
            d = get_remote_info(repo_id)
            if d:
                dates.append(d)
        if dates:
            latest = max(dates)
            save_local_version(latest)
            print(f"  Версия сохранена: {latest}")
        else:
            print("  ⚠ Не удалось сохранить версию")
    else:
        print("  Всё актуально, обновлений нет.")

    print()
    print("  Готово!")

if __name__ == "__main__":
    main()
