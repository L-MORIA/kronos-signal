"""Shared fixtures: import project modules that live outside a package."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# kronos-source в sys.path для тестов модели (from model.kronos import ...)
KRONOS_SRC = PROJECT_ROOT / "kronos-source"
if str(KRONOS_SRC) not in sys.path:
    sys.path.insert(0, str(KRONOS_SRC))


def _load_module(name, rel_path):
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def run_mod():
    """Import scripts/run.py (default config.yaml, no model loading at import)."""
    return _load_module("run_mod", "scripts/run.py")


@pytest.fixture(scope="session")
def rss_mod():
    return _load_module("rss_mod", "rss_market_news.py")


@pytest.fixture(scope="session")
def timesfm_mod():
    # stub the heavy `timesfm` dependency so the module imports without the lib
    stub = types.ModuleType("timesfm")
    stub.TimesFM_2p5_200M_torch = object
    sys.modules.setdefault("timesfm", stub)
    return _load_module("timesfm_mod", "scripts/timesfm_compare.py")
