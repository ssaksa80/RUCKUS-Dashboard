import os
from ruckus_dashboard.config import build_config, _bool_env, _int_env


def test_bool_env_true_values(monkeypatch):
    for value in ["1", "true", "yes", "on", "TRUE", "Yes"]:
        monkeypatch.setenv("X", value)
        assert _bool_env("X", False) is True


def test_bool_env_default(monkeypatch):
    monkeypatch.delenv("X", raising=False)
    assert _bool_env("X", True) is True
    assert _bool_env("X", False) is False


def test_int_env_invalid_returns_default(monkeypatch):
    monkeypatch.setenv("X", "not-a-number")
    assert _int_env("X", 42) == 42


def test_build_config_defaults(tmp_path):
    cfg = build_config(str(tmp_path))
    assert cfg["APP_HOST"] == "127.0.0.1"
    assert cfg["APP_PORT"] == 8444
    assert cfg["RUCKUS_SMARTZONE_PORT"] == 8443
    assert cfg["SESSION_COOKIE_SAMESITE"] == "Strict"
    assert cfg["RUCKUS_ENABLE_NEW_UI"] is False  # new — defaults off


def test_build_config_new_ui_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("RUCKUS_ENABLE_NEW_UI", "1")
    cfg = build_config(str(tmp_path))
    assert cfg["RUCKUS_ENABLE_NEW_UI"] is True
