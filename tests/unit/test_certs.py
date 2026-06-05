from pathlib import Path

from ruckus_dashboard.certs import ensure_self_signed_cert


def test_generates_cert_and_key(tmp_instance):
    cert, key = ensure_self_signed_cert(tmp_instance)
    assert Path(cert).exists()
    assert Path(key).exists()
    assert Path(cert).read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    assert b"PRIVATE KEY" in Path(key).read_bytes()


def test_idempotent(tmp_instance):
    cert1, key1 = ensure_self_signed_cert(tmp_instance)
    bytes1 = Path(cert1).read_bytes()
    cert2, key2 = ensure_self_signed_cert(tmp_instance)
    assert Path(cert2).read_bytes() == bytes1
