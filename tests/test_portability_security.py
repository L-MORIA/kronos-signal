"""Тесты гигиены безопасности (второй проход аудита):

- .gitignore закрывает секреты (.env, ключи, креды)
- исходники проекта не содержат eval/exec и unsafe yaml load
- вендоренная модель kronos.py доступна для импорта (kronos-source в sys.path)
"""
import re
from pathlib import Path

from conftest import PROJECT_ROOT


def test_gitignore_covers_secrets():
    gi = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", ".key", ".pem", "credentials"):
        assert pattern in gi, f".gitignore не содержит {pattern}"


ROOT_PY_FILES = (
    list(PROJECT_ROOT.glob("*.py"))
    + list((PROJECT_ROOT / "scripts").glob("*.py"))
    + [PROJECT_ROOT / "update_models" / "update_models.py"]
)


def test_no_eval_exec_in_project_sources():
    for f in ROOT_PY_FILES:
        if not f.exists():
            continue
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"\beval\s*\(", src), f"eval() найден в {f.name}"
        assert not re.search(r"\bexec\s*\(", src), f"exec() найден в {f.name}"


def test_no_unsafe_yaml_load():
    for f in ROOT_PY_FILES:
        if not f.exists():
            continue
        src = f.read_text(encoding="utf-8")
        assert "yaml.load(" not in src, f"небезопасный yaml.load в {f.name} (нужен safe_load)"


def test_kronos_source_importable():
    """conftest кладёт kronos-source в sys.path — модель доступна по import."""
    import model.kronos  # noqa: F401
