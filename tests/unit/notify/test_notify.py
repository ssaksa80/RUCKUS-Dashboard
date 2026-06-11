"""Unit tests for notification config, rules, mailer, scheduler due-logic,
and the Excel report builder."""
import json
import time

import pytest

from ruckus_dashboard.notify import config as cfg_mod
from ruckus_dashboard.notify.rules import evaluate
from ruckus_dashboard.notify.scheduler import NotifyScheduler, state_from_data
from ruckus_dashboard.reports.excel import build_report


class FakeSecrets:
    def encrypt(self, s):
        return f"enc:{s}"

    def decrypt(self, s):
        assert s.startswith("enc:")
        return s[4:]


# ── config ───────────────────────────────────────────────────────────────

def test_config_password_encrypted_masked_and_preserved(tmp_path):
    secrets = FakeSecrets()
    saved = cfg_mod.save_config(str(tmp_path), {
        "smtp": {"host": "mail.x", "password": "hunter2"},
        "alerts": {"enabled": True, "recipients": ["a@x"]},
    }, secrets)
    # encrypted at rest, never plaintext
    raw = json.loads((tmp_path / "notifications.json").read_text())
    assert raw["smtp"]["password_enc"] == "enc:hunter2"
    assert "hunter2" not in json.dumps(raw["smtp"].get("password", ""))
    # masked for display
    disp = cfg_mod.display_config(saved)
    assert disp["smtp"]["password"] == cfg_mod.PASSWORD_MASK
    # posting the mask back preserves the stored secret
    saved2 = cfg_mod.save_config(str(tmp_path), {
        "smtp": {"host": "mail.x", "password": cfg_mod.PASSWORD_MASK},
    }, secrets)
    assert cfg_mod.smtp_password(saved2, secrets) == "hunter2"


def test_config_defaults_when_missing(tmp_path):
    cfg = cfg_mod.load_config(str(tmp_path))
    assert cfg["smtp"]["port"] == 587
    assert cfg["alerts"]["rules"]["critical_alarm"] is True
    assert cfg["report"]["time"] == "07:00"


# ── rules ────────────────────────────────────────────────────────────────

def test_rules_fire_on_transition_only():
    rules = {"ap_offline": True, "switch_offline": True, "critical_alarm": True}
    first = evaluate(None, {"aps_offline": 2}, rules, 1)
    assert len(first) == 1 and "2" in first[0]
    # unchanged level → silence
    again = evaluate({"aps_offline": 2}, {"aps_offline": 2}, rules, 1)
    assert again == []
    # rises again → fires
    more = evaluate({"aps_offline": 2}, {"aps_offline": 5}, rules, 1)
    assert len(more) == 1


def test_rules_threshold_and_toggles():
    rules = {"ap_offline": True, "switch_offline": False, "critical_alarm": True}
    assert evaluate({}, {"aps_offline": 1}, rules, 3) == []     # below threshold
    assert evaluate({}, {"switches_offline": 9}, rules, 1) == []  # rule off
    crit = evaluate({}, {"critical_alarms": 1}, rules, 1)
    assert len(crit) == 1


# ── scheduler due-logic ──────────────────────────────────────────────────

def _sched(tmp_path):
    return NotifyScheduler(str(tmp_path), {}, FakeSecrets())


def test_alerts_due_respects_interval(tmp_path):
    s = _sched(tmp_path)
    cfg = cfg_mod.load_config(str(tmp_path))
    cfg["alerts"]["enabled"] = True
    cfg["alerts"]["check_seconds"] = 300
    assert s._alerts_due(cfg, time.time()) is True
    s._last_alert_check = time.time()
    assert s._alerts_due(cfg, time.time()) is False
    cfg["alerts"]["enabled"] = False
    assert s._alerts_due(cfg, time.time() + 9999) is False


def test_report_due_once_per_day_after_time(tmp_path):
    s = _sched(tmp_path)
    cfg = cfg_mod.load_config(str(tmp_path))
    cfg["report"]["enabled"] = True
    cfg["report"]["time"] = "07:00"
    before = time.strptime("2026-06-10 06:59", "%Y-%m-%d %H:%M")
    after = time.strptime("2026-06-10 07:01", "%Y-%m-%d %H:%M")
    assert s._report_due(cfg, before) is False
    assert s._report_due(cfg, after) is True
    s._last_report_day = "2026-06-10"
    assert s._report_due(cfg, after) is False      # once per day
    next_day = time.strptime("2026-06-11 07:01", "%Y-%m-%d %H:%M")
    assert s._report_due(cfg, next_day) is True


def test_state_from_data_counts():
    data = {"aps": [{"status": "offline"}, {"status": "online"}],
            "switches": [{"status": "offline"}],
            "alarms": [{"severity": "critical", "count": 3},
                       {"severity": "major", "count": 1}]}
    s = state_from_data(data)
    assert s["aps_offline"] == 1
    assert s["switches_offline"] == 1
    assert s["critical_alarms"] == 3
    assert s["poor_aps"] == []


def test_poor_quality_aps_threshold():
    from ruckus_dashboard.notify.scheduler import poor_quality_aps
    clients = ([{"ap": "AP-BAD", "quality": "poor"}] * 4 +
               [{"ap": "AP-BAD", "quality": "good"}] +     # 4/5 poor = 80%
               [{"ap": "AP-OK", "quality": "poor"}] +      # only 1 client -> skip
               [{"ap": "AP-FINE", "quality": "good"}] * 5)
    flagged = poor_quality_aps(clients)
    assert flagged == ["AP-BAD (4/5 poor)"]


def test_poor_ap_rule_fires_for_new_aps_only():
    rules = {"poor_client_ap": True}
    first = evaluate(None, {"poor_aps": ["AP-1 (4/5 poor)"]}, rules, 1)
    assert len(first) == 1 and "AP-1" in first[0]
    same = evaluate({"poor_aps": ["AP-1 (4/5 poor)"]},
                    {"poor_aps": ["AP-1 (5/6 poor)"]}, rules, 1)
    assert same == []                       # same AP still degraded -> silent
    new = evaluate({"poor_aps": ["AP-1 (4/5 poor)"]},
                   {"poor_aps": ["AP-1 (4/5 poor)", "AP-2 (3/3 poor)"]}, rules, 1)
    assert len(new) == 1 and "AP-2" in new[0]


# ── excel report ─────────────────────────────────────────────────────────

def test_build_report_loads_and_has_sheets_and_charts():
    import openpyxl, io
    data = {
        "aps": [{"name": "AP1", "zone": "HQ", "status": "online", "mac": "a"},
                {"name": "AP2", "zone": "HQ", "status": "offline", "mac": "b"}],
        "clients": [{"hostname": "h1", "mac": "m", "ssid": "S", "ap": "AP1",
                     "band": "5 GHz", "quality": "good",
                     "rx_bytes": 10, "tx_bytes": 20}],
        "alarms": [{"severity": "critical", "category": "AP", "source": "AP2",
                    "message": "down", "count": 1}],
        "switches": [{"name": "SW1", "ip": "10.0.0.1", "model": "ICX",
                      "fw": "x", "status": "online", "ports_online": 10,
                      "ports_total": 24, "group": "Core", "mac": "c"}],
    }
    blob = build_report(data)
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    assert set(wb.sheetnames) == {"Overview", "APs by Zone", "Clients",
                                  "Alarms", "Switches", "Offline Devices"}
    assert len(wb["APs by Zone"]._charts) == 1   # bar
    assert len(wb["Clients"]._charts) == 1       # pie
    assert len(wb["Alarms"]._charts) == 1        # pie
    # offline AP listed
    assert any(c.value == "AP2" for row in wb["Offline Devices"].iter_rows()
               for c in row)


# ── mailer (monkeypatched smtplib) ───────────────────────────────────────

def test_send_email_via_monkeypatched_smtp(monkeypatch):
    from ruckus_dashboard.notify import mailer
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=0):
            sent["host"], sent["port"] = host, port

        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): sent["ehlo"] = sent.get("ehlo", 0) + 1
        def starttls(self): sent["tls"] = True
        def login(self, u, p): sent["login"] = (u, p)
        def send_message(self, msg): sent["subject"] = msg["Subject"]

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    cfg = {"smtp": {"host": "mail.x", "port": 587, "use_tls": True,
                    "username": "u", "from_addr": "dso@x"}}
    mailer.send_email(cfg, "pw", ["a@x"], "Subject!", "body")
    assert sent["host"] == "mail.x" and sent["tls"] is True
    assert sent["ehlo"] == 2   # before and after STARTTLS (networker pattern)
    assert sent["login"] == ("u", "pw")
    assert sent["subject"] == "Subject!"


def test_send_email_requires_host_and_recipients():
    from ruckus_dashboard.notify.mailer import send_email
    with pytest.raises(ValueError):
        send_email({"smtp": {"host": ""}}, "", ["a@x"], "s", "b")
    with pytest.raises(ValueError):
        send_email({"smtp": {"host": "mail.x"}}, "", [], "s", "b")


def test_send_email_ssl_mode_uses_smtp_ssl(monkeypatch):
    from ruckus_dashboard.notify import mailer
    used = {}

    class FakeSSL:
        def __init__(self, host, port, timeout=0): used["ssl"] = (host, port)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, u, p): used["login"] = (u, p)
        def send_message(self, msg): used["sent"] = True

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSSL)
    cfg = {"smtp": {"host": "mail.x", "port": 465, "security": "ssl",
                    "username": "u", "from_addr": "dso@x"}}
    out = mailer.send_email(cfg, "pw", ["a@x"], "s", "b")
    assert used["ssl"] == ("mail.x", 465) and used["sent"]
    assert out["stage"] == "sent" and out["security"] == "ssl"


def test_send_email_reports_failing_stage(monkeypatch):
    import smtplib as real_smtplib
    from ruckus_dashboard.notify import mailer

    class FakeSMTP:
        def __init__(self, host, port, timeout=0): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): pass
        def starttls(self): pass
        def login(self, u, p):
            raise real_smtplib.SMTPAuthenticationError(535, b"5.7.8 Bad creds")
        def send_message(self, msg): pass

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    cfg = {"smtp": {"host": "mail.x", "port": 587, "security": "starttls",
                    "username": "u"}}
    with pytest.raises(mailer.SmtpDeliveryError) as ei:
        mailer.send_email(cfg, "wrong", ["a@x"], "s", "b")
    assert ei.value.stage == "login"
    assert "authentication rejected" in ei.value.detail
    assert "5.7.8" in ei.value.detail
