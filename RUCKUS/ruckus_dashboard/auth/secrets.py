"""Encrypt/decrypt small secrets (profile passwords) with a persisted Fernet key.

On Windows the master key is wrapped with DPAPI (CRYPTPROTECT_LOCAL_MACHINE) so
the on-disk file is unusable when copied to another machine. On other platforms
the key is written with 0600 permissions (best-effort).

Ported verbatim from RUCKUS/ruckus_dashboard.py lines 2563-2692.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - profile secrets degrade to disabled.
    Fernet = None
    InvalidToken = Exception


LOG = logging.getLogger("ruckus_dashboard")

DPAPI_MARKER = b"DPAPI1\n"
_CRYPTPROTECT_LOCAL_MACHINE = 0x4


def _dpapi_available() -> bool:
    return sys.platform == "win32"


if sys.platform == "win32":
    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint), ("pbData", ctypes.c_void_p)]


def _dpapi_protect(data: bytes) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
    blob_out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(blob_out.pbData))


def _dpapi_unprotect(blob: bytes) -> bytes:
    buf = ctypes.create_string_buffer(blob, len(blob))
    blob_in = _DATA_BLOB(len(blob), ctypes.cast(buf, ctypes.c_void_p))
    blob_out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(blob_out.pbData))


def _key_file_is_wrapped(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(len(DPAPI_MARKER)) == DPAPI_MARKER
    except OSError:
        return False


def _write_protected_key(path: Path, key: bytes) -> None:
    payload = key
    if _dpapi_available():
        try:
            payload = DPAPI_MARKER + _dpapi_protect(key)
        except OSError as exc:
            LOG.warning(f"DPAPI protect failed; storing key unwrapped: {exc}")
            payload = key
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / (path.name + ".tmp")
        tmp.write_bytes(payload)
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except OSError as exc:
        LOG.warning(f"Could not persist secret key {path.name}: {exc}")


def _read_protected_key(path: Path) -> bytes | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if raw.startswith(DPAPI_MARKER):
        try:
            return _dpapi_unprotect(raw[len(DPAPI_MARKER):])
        except OSError as exc:
            LOG.warning(f"DPAPI unprotect failed for {path.name}: {exc}")
            return None
    return raw


class SecretsManager:
    """Encrypt/decrypt small secrets (profile passwords) with a persisted Fernet key."""

    def __init__(self, instance_path: str) -> None:
        self.key_file = Path(instance_path) / ".secret_master"
        self._fernet = None
        if Fernet is not None:
            key = self._load_or_create_key()
            if key:
                self._fernet = Fernet(key)

    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        if not plaintext or self._fernet is None:
            return ""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, blob: str) -> str:
        if not blob or self._fernet is None:
            return ""
        try:
            return self._fernet.decrypt(blob.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return ""

    def _load_or_create_key(self) -> bytes:
        raw = _read_protected_key(self.key_file)
        if raw is not None:
            candidate = raw.strip()
            try:
                Fernet(candidate)  # validate
                if _dpapi_available() and not _key_file_is_wrapped(self.key_file):
                    _write_protected_key(self.key_file, candidate)  # migrate to wrapped
                return candidate
            except Exception:
                pass
        key = Fernet.generate_key()
        _write_protected_key(self.key_file, key)
        return key
