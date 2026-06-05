"""Self-signed TLS certificate generation for the local HTTPS server.

Generates a development-grade RSA cert/key pair under the instance directory
(or override paths via the RUCKUS_CERT_FILE / RUCKUS_KEY_FILE environment
variables). Idempotent: if both files already exist they are reused as-is.
"""

import os
import socket
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path


def ensure_self_signed_cert(instance_path: str) -> tuple[Path, Path]:
    cert_file = Path(os.getenv("RUCKUS_CERT_FILE", Path(instance_path) / "cert.pem"))
    key_file = Path(os.getenv("RUCKUS_KEY_FILE", Path(instance_path) / "key.pem"))

    if cert_file.exists() and key_file.exists():
        return cert_file, key_file

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:  # pragma: no cover
        raise SystemExit(
            "The 'cryptography' package is required to generate the HTTPS "
            "certificate. Install with: pip install cryptography"
        )

    cert_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.parent.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "AE"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Internal"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )
    now = datetime.now(timezone.utc)
    alt_names = [
        x509.DNSName("localhost"),
        x509.DNSName(socket.gethostname()),
        x509.IPAddress(ip_address("127.0.0.1")),
        x509.IPAddress(ip_address("::1")),
    ]
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return cert_file, key_file
