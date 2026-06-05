from ruckus_dashboard.auth.secrets import SecretsManager
from ruckus_dashboard.auth.profiles import ProfileStore


def test_save_list_delete(tmp_instance):
    secrets_mgr = SecretsManager(tmp_instance)
    store = ProfileStore(tmp_instance, secrets_mgr)
    form = {"platform": "smartzone", "smartzone_host": "sz.example",
            "smartzone_username": "admin", "smartzone_password": "hunter2"}
    store.save("lab", form)
    items = store.list_masked()
    assert any(item["name"] == "lab" for item in items)
    pw = store.resolve_secret("lab", "smartzone_password")
    if secrets_mgr.available():
        assert pw == "hunter2"
    store.delete("lab")
    assert not any(item["name"] == "lab" for item in store.list_masked())


def test_save_requires_profile_name(tmp_instance):
    import pytest
    mgr = SecretsManager(tmp_instance)
    store = ProfileStore(tmp_instance, mgr)
    with pytest.raises(ValueError):
        store.save("", {"platform": "smartzone"})
