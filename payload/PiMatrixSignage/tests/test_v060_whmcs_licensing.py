from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from licensing import LicenseManager, device_identity
from renderer import RendererEngine
from database import Database

ROOT = Path(__file__).resolve().parents[1]


def _signed_response(private_key, entitlement: dict) -> bytes:
    payload = json.dumps(entitlement, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    return json.dumps({
        "entitlement_b64": base64.b64encode(payload).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
    }).encode("utf-8")


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, _limit=-1):
        return self.payload


def test_device_identity_is_stable_and_privacy_minimised():
    a = device_identity()
    b = device_identity()
    assert a["device_id"] == b["device_id"]
    assert a["device_id"].startswith("PMS-")
    # Public ID must be a digest-style identifier, not a raw serial/machine-id dump.
    assert len(a["device_id"].split("-")) == 5


def test_development_mode_remains_licensed_without_server_configuration(monkeypatch):
    monkeypatch.setenv("PIMATRIX_LICENSE_MODE", "development")
    with tempfile.TemporaryDirectory() as td:
        lm = LicenseManager(td, "0.6.2")
        info = lm.info()
        assert lm.is_licensed() is True
        assert info["status"] == "Development mode"


def test_whmcs_signed_entitlement_binds_to_device_and_key(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pub = td / "license-public.pem"
        pub.write_bytes(public_pem)
        monkeypatch.setenv("PIMATRIX_LICENSE_MODE", "whmcs")
        monkeypatch.setenv("PIMATRIX_LICENSE_ENDPOINT", "https://licensing.example.test/pimatrix-license.php")
        monkeypatch.setenv("PIMATRIX_LICENSE_PUBLIC_KEY", str(pub))
        monkeypatch.setenv("PIMATRIX_LICENSE_PREFIX", "PMS-")
        lm = LicenseManager(td, "0.6.2")
        key = "PMS-TEST-1234-5678"
        now = datetime.now(timezone.utc)
        entitlement = {
            "schema": 1,
            "product": "Pi Matrix Signage",
            "status": "Active",
            "license_key_hash": hashlib.sha256(key.encode()).hexdigest(),
            "device_id": lm.identity["device_id"],
            "issued_at": now.isoformat(),
            "valid_until": (now + timedelta(days=7)).isoformat(),
            "grace_until": (now + timedelta(days=30)).isoformat(),
            "features": {},
            "whmcs_local_key": "LOCAL",
        }
        response = _signed_response(private, entitlement)
        with patch("urllib.request.urlopen", return_value=_Response(response)):
            info = lm.activate(key)
        assert info["licensed"] is True
        assert lm.is_licensed() is True
        assert "TEST" not in info["license_key_masked"] or info["license_key_masked"] != key

        wrong = dict(entitlement)
        wrong["device_id"] = "PMS-00000000-00000000-00000000-00000000"
        signed = _signed_response(private, wrong)
        with patch("urllib.request.urlopen", return_value=_Response(signed)):
            try:
                lm.activate(key)
            except Exception as exc:
                assert "different controller" in str(exc)
            else:
                raise AssertionError("device mismatch should be rejected")


def test_renderer_target_resolution_is_blocked_when_commercial_licence_is_invalid():
    with tempfile.TemporaryDirectory() as td:
        db = Database(str(Path(td) / "signage.db"))
        mid = db.save_message({"name": "Licensed content", "text": "HELLO", "enabled": True})
        db.update_settings({"default_message_id": mid})
        engine = RendererEngine(db, td, td, license_checker=lambda: False)
        engine.reload_settings()
        assert engine._resolve_target(datetime.now(timezone.utc)) is None


def test_v060_packaging_includes_licensing_module_and_ui():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    service = (ROOT / "systemd" / "pi-matrix-signage.service").read_text(encoding="utf-8")
    updater = (ROOT / "systemd" / "pi-matrix-signage-upgrade").read_text(encoding="utf-8")
    assert (ROOT / "licensing.py").is_file()
    assert '"PiMatrixSignage/licensing.py"' in app_py
    assert 'id="licenceCard"' in html
    assert "/api/license/activate" in app_py
    assert "renderLicence" in js
    assert "license.env" in service
    assert '"PiMatrixSignage/licensing.py"' in updater
    assert (ROOT / "WHMCS-LICENSING.md").is_file()


def test_release_version_is_v062_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 6, 2)


def test_v062_defaults_to_native_whmcs_addon_endpoints(monkeypatch):
    monkeypatch.delenv("PIMATRIX_LICENSE_ENDPOINT", raising=False)
    monkeypatch.setenv("PIMATRIX_LICENSE_MODE", "development")
    with tempfile.TemporaryDirectory() as td:
        lm = LicenseManager(td, "0.6.2")
        assert lm.endpoint == "https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/api.php"
        assert lm.public_key_url == "https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/public-key.php"


def test_v062_public_key_is_downloaded_automatically(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        monkeypatch.setenv("PIMATRIX_LICENSE_MODE", "whmcs")
        monkeypatch.setenv("PIMATRIX_LICENSE_ENDPOINT", "https://licensing.example.test/api.php")
        monkeypatch.setenv("PIMATRIX_LICENSE_PUBLIC_KEY_URL", "https://licensing.example.test/public-key.php")
        monkeypatch.setenv("PIMATRIX_LICENSE_PUBLIC_KEY", str(td / "downloaded-public.pem"))
        lm = LicenseManager(td, "0.6.2")
        key = "PMS-TEST-1234-5678"
        now = datetime.now(timezone.utc)
        entitlement = {
            "schema": 1, "product": "Pi Matrix Signage", "status": "Active",
            "license_key_hash": hashlib.sha256(key.encode()).hexdigest(),
            "device_id": lm.identity["device_id"], "issued_at": now.isoformat(),
            "valid_until": (now + timedelta(days=7)).isoformat(),
            "grace_until": (now + timedelta(days=30)).isoformat(),
            "features": {}, "whmcs_local_key": "LOCAL",
        }
        signed = _signed_response(private, entitlement)
        calls = []
        def fake_urlopen(req, timeout=0):
            calls.append(req.full_url)
            if req.full_url.endswith("public-key.php"):
                return _Response(public_pem)
            return _Response(signed)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            info = lm.activate(key)
        assert info["licensed"] is True
        assert (td / "downloaded-public.pem").read_bytes() == public_pem
        assert calls[0].endswith("api.php")
        assert any(x.endswith("public-key.php") for x in calls)
