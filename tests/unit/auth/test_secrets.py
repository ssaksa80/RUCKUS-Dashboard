import sys
import pytest
from ruckus_dashboard.auth.secrets import SecretsManager


def test_round_trip(tmp_instance):
    mgr = SecretsManager(tmp_instance)
    if not mgr.available():
        pytest.skip("cryptography not installed")
    blob = mgr.encrypt("hunter2")
    assert blob and blob != "hunter2"
    assert mgr.decrypt(blob) == "hunter2"


def test_decrypt_garbage_returns_empty(tmp_instance):
    mgr = SecretsManager(tmp_instance)
    if not mgr.available():
        pytest.skip()
    assert mgr.decrypt("not-a-valid-token") == ""


def test_key_persists_across_instances(tmp_instance):
    mgr1 = SecretsManager(tmp_instance)
    if not mgr1.available():
        pytest.skip()
    blob = mgr1.encrypt("secret")
    mgr2 = SecretsManager(tmp_instance)
    assert mgr2.decrypt(blob) == "secret"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_wrapping_used_on_windows(tmp_instance):
    from ruckus_dashboard.auth.secrets import _dpapi_available
    if not _dpapi_available():
        pytest.skip("DPAPI not loadable in this Windows env")
    mgr = SecretsManager(tmp_instance)
    blob = mgr.encrypt("x")
    assert mgr.decrypt(blob) == "x"
