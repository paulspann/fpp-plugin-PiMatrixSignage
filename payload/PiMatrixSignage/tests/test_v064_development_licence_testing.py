from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from licensing import LicenseManager

ROOT = Path(__file__).resolve().parents[1]


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, _limit=-1):
        return self.payload


def _signed_response(private_key, entitlement: dict) -> bytes:
    payload = json.dumps(entitlement, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    return json.dumps({
        "entitlement_b64": base64.b64encode(payload).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
    }).encode("utf-8")


def test_development_mode_can_activate_real_whmcs_licence_without_enforcement(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pub = td / "license-public.pem"
        pub.write_bytes(public_pem)
        monkeypatch.setenv("PIMATRIX_LICENSE_MODE", "development")
        monkeypatch.setenv("PIMATRIX_LICENSE_ENDPOINT", "https://licensing.example.test/api.php")
        monkeypatch.setenv("PIMATRIX_LICENSE_PUBLIC_KEY", str(pub))
        lm = LicenseManager(td, "0.6.4")
        key = "PMS-TEST-1234-5678"
        now = datetime.now(timezone.utc)
        entitlement = {
            "schema": 1,
            "product": "Pi Matrix Signage",
            "product_name": "Pi Matrix Sign",
            "customer": "Test Customer",
            "status": "Active",
            "license_key_hash": hashlib.sha256(key.encode()).hexdigest(),
            "device_id": lm.identity["device_id"],
            "issued_at": now.isoformat(),
            "valid_until": (now + timedelta(days=7)).isoformat(),
            "grace_until": (now + timedelta(days=30)).isoformat(),
            "features": {},
            "whmcs_local_key": "LOCAL",
        }
        with patch("urllib.request.urlopen", return_value=_Response(_signed_response(private, entitlement))):
            info = lm.activate(key)
        assert lm.is_licensed() is True  # development still never blocks output
        assert info["mode"] == "development"
        assert info["test_licensed"] is True
        assert info["status"] == "Active (development mode)"
        assert info["license_key_masked"]
        assert info["customer"] == "Test Customer"


def test_development_mode_ui_keeps_activation_controls_available():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "if($('licenceKey'))$('licenceKey').disabled=false" in js
    assert "if($('activateLicence'))$('activateLicence').disabled=false" in js
    assert "test_licensed" in js
    assert "disabled=!whmcs" not in js


def test_release_version_includes_v064_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 6, 4)


def test_rejected_development_activation_does_not_install_invalid_key(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pub = td / "license-public.pem"
        pub.write_bytes(public_pem)
        monkeypatch.setenv("PIMATRIX_LICENSE_MODE", "development")
        monkeypatch.setenv("PIMATRIX_LICENSE_ENDPOINT", "https://licensing.example.test/api.php")
        monkeypatch.setenv("PIMATRIX_LICENSE_PUBLIC_KEY", str(pub))
        lm = LicenseManager(td, "0.6.5")
        key = "PMS-REJECTED-1234"
        now = datetime.now(timezone.utc)
        entitlement = {
            "schema": 1,
            "product": "Pi Matrix Signage",
            "status": "Invalid",
            "license_key_hash": hashlib.sha256(key.encode()).hexdigest(),
            "device_id": lm.identity["device_id"],
            "issued_at": now.isoformat(),
            "valid_until": (now + timedelta(days=7)).isoformat(),
            "grace_until": (now + timedelta(days=30)).isoformat(),
            "features": {},
            "whmcs_local_key": "",
        }
        with patch("urllib.request.urlopen", return_value=_Response(_signed_response(private, entitlement))):
            try:
                lm.activate(key)
            except Exception as exc:
                assert "Invalid" in str(exc)
            else:
                raise AssertionError("rejected licence should fail activation")
        info = lm.info()
        assert info["license_key_masked"] == ""
        assert "Last WHMCS activation attempt failed" in info["message"]
        assert "Invalid" in info["message"]


def test_release_version_includes_v065_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 6, 5)
