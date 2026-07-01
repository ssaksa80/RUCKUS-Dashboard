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


def test_build_config_auth_required_defaults_on(monkeypatch, tmp_path):
    monkeypatch.delenv("RUCKUS_AUTH_REQUIRED", raising=False)
    cfg = build_config(str(tmp_path))
    assert cfg["RUCKUS_AUTH_REQUIRED"] is True  # PhaseB default: enforce app-login


def test_build_config_auth_required_off_switch(monkeypatch, tmp_path):
    monkeypatch.setenv("RUCKUS_AUTH_REQUIRED", "0")
    cfg = build_config(str(tmp_path))
    assert cfg["RUCKUS_AUTH_REQUIRED"] is False


def test_build_config_database_url_and_admin_pw_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("RUCKUS_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("RUCKUS_ADMIN_PASSWORD", "seed-pw")
    cfg = build_config(str(tmp_path))
    assert cfg["RUCKUS_DATABASE_URL"] == "sqlite:///:memory:"
    assert cfg["RUCKUS_ADMIN_PASSWORD"] == "seed-pw"


def test_build_config_database_url_defaults_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("RUCKUS_DATABASE_URL", raising=False)
    cfg = build_config(str(tmp_path))
    assert cfg["RUCKUS_DATABASE_URL"] == ""  # resolved by db.init_db
