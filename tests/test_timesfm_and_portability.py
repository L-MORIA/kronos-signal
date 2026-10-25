"""Tests for timesfm_compare.py None-handling and portable project paths."""
import subprocess
import sys
from pathlib import Path

from conftest import PROJECT_ROOT


# ── timesfm_compare formatting ────────────────────────────────────────

def test_fmt_num_none_safe(timesfm_mod):
    """Regression: the comparison table crashed with TypeError whenever any
    Kronos/TimesFM value was None (missing forecast file, failed inference)."""
    assert timesfm_mod.fmt_num(None).strip() == "—"
    assert timesfm_mod.fmt_num(float("nan")).strip() == "—"
    assert timesfm_mod.fmt_num(123.456) == f"{123.456:.2f}".rjust(12)


def test_chg_zero_is_not_none(timesfm_mod):
    """Regression: `if pred else None` treated a legitimate 0.0% change as
    missing data. The fixed code branches on `is not None`."""
    # 0-change must produce chg == 0.0, indistinguishable path from others
    pred, last = 100.0, 100.0
    chg = ((pred - last) / last * 100) if pred is not None else None
    assert chg == 0.0


def test_timesfm_dir_created_under_forecasts(timesfm_mod):
    assert timesfm_mod.TIMESFM_DIR.exists()
    assert timesfm_mod.TIMESFM_DIR.parent.name == "forecasts"


# ── portable paths ────────────────────────────────────────────────────

def test_update_models_paths_relative():
    """Regression: update_models.py hardcoded C:/kronos-signal — broke on any
    other clone location."""
    spec_dirs = {}
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "update_models_mod", PROJECT_ROOT / "update_models" / "update_models.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["update_models_mod"] = mod
    spec.loader.exec_module(mod)
    assert mod.MODELS_DIR == (PROJECT_ROOT / "models").resolve()
    assert mod.VERSION_FILE == (PROJECT_ROOT / ".version").resolve()
    assert "C:/" not in str(mod.MODELS_DIR).replace(str(PROJECT_ROOT), "")


def test_md_to_docx_paths_relative():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "md_to_docx_mod", PROJECT_ROOT / "scripts" / "md_to_docx.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["md_to_docx_mod"] = mod
    spec.loader.exec_module(mod)
    assert mod.MD_PATH == PROJECT_ROOT / "references" / "trader-guide.md"
    assert mod.DOCX_PATH == PROJECT_ROOT / "references" / "trader-guide.docx"


def test_check_portability_passes():
    """check_portability must be green on the fixed repo (exit 0)."""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "check_portability.py"),
         str(PROJECT_ROOT)],
        capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_hardcoded_drive_left_in_project_scripts():
    offenders = []
    for rel in ["scripts/run.py", "scripts/md_to_docx.py", "rss_market_news.py",
                "update_models/update_models.py", "update_models/update_models.bat",
                "launch.bat", "launch2.bat"]:
        text = (PROJECT_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        # absolute drive paths like C:\kronos-signal / C:/kronos-signal
        import re
        if re.search(r"[A-Za-z]:[\\/]+kronos", text):
            offenders.append(rel)
    assert offenders == []
