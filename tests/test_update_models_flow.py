"""Hermetic tests for update_models.py main() flow (HF Hub mocked)."""
import importlib.util
import sys

import pytest

from conftest import PROJECT_ROOT

spec = importlib.util.spec_from_file_location(
    "update_models_flow_mod", PROJECT_ROOT / "update_models" / "update_models.py")
um = importlib.util.module_from_spec(spec)
sys.modules["update_models_flow_mod"] = um
spec.loader.exec_module(um)


class FakeResp:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fake models dir + version file + HF Hub, recording downloads."""
    models_dir = tmp_path / "models"
    for repo in um.REPOS:
        (models_dir / repo).mkdir(parents=True)
        (models_dir / repo / "model.safetensors").write_bytes(b"x")
        (models_dir / repo / "config.json").write_text("{}")
    downloads = []

    def fake_get(url, timeout=10):
        if "/api/models/" in url:
            return FakeResp({"lastModified": "2026-10-01T00:00:00.000Z"})
        return FakeResp()  # connectivity probe

    monkeypatch.setattr(um, "MODELS_DIR", models_dir)
    monkeypatch.setattr(um, "VERSION_FILE", tmp_path / ".version")
    monkeypatch.setattr(um.requests, "get", fake_get)

    import huggingface_hub
    monkeypatch.setattr(
        huggingface_hub, "snapshot_download",
        lambda **kw: downloads.append(kw["repo_id"]), raising=True)
    return downloads


def test_first_run_downloads_and_saves_version(env, capsys):
    um.main()
    out = capsys.readouterr().out
    assert len(env) == len(um.REPOS)          # both repos fetched
    assert um.VERSION_FILE.exists()
    assert "2026-10-01" in um.VERSION_FILE.read_text(encoding="utf-8")
    assert "Версия сохранена" in out


def test_second_run_up_to_date_no_download(env, capsys):
    um.main()          # first run downloads + saves version
    env.clear()
    um.main()          # remote date <= local version -> no re-download
    assert env == []
    out = capsys.readouterr().out
    assert "актуальны" in out or "Актуальна" in out


def test_new_remote_date_triggers_download(env, monkeypatch, capsys):
    um.main()
    env.clear()
    # server now has a newer model
    def newer_get(url, timeout=10):
        if "/api/models/" in url:
            return FakeResp({"lastModified": "2026-10-20T00:00:00.000Z"})
        return FakeResp()
    monkeypatch.setattr(um.requests, "get", newer_get)
    um.main()
    assert len(env) == len(um.REPOS)


def test_missing_model_dir_skipped(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(um, "MODELS_DIR", tmp_path / "nope")
    monkeypatch.setattr(um, "VERSION_FILE", tmp_path / ".version")
    um.main()
    assert "директория не найдена" in capsys.readouterr().out
