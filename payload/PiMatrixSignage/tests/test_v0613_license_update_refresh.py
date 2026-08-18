from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from licensing import LicenseManager


def test_new_software_version_requires_refresh_when_key_is_installed(monkeypatch):
    monkeypatch.setenv("PIMATRIX_LICENSE_MODE", "development")
    with TemporaryDirectory() as td:
        manager = LicenseManager(td, "0.6.13")
        manager._state = {"license_key": "PMS-TEST", "reported_app_version": "0.6.12"}
        assert manager._version_refresh_due() is True
        manager._state["reported_app_version"] = "0.6.13"
        assert manager._version_refresh_due() is False
        manager._state.pop("license_key")
        assert manager._version_refresh_due() is False


def test_successful_post_update_check_records_reported_version(monkeypatch):
    monkeypatch.setenv("PIMATRIX_LICENSE_MODE", "development")
    with TemporaryDirectory() as td:
        manager = LicenseManager(td, "0.6.13")
        manager._state = {"license_key": "PMS-TEST", "reported_app_version": "0.6.12"}
        response = {"ok": True, "reason": "", "signed_entitlement": {"entitlement_b64": "", "signature": ""}}
        with patch.object(manager, "_remote", return_value=response) as remote:
            manager.check_now(silent=True)
        assert remote.call_args.args == ("PMS-TEST",)
        assert manager._state["reported_app_version"] == "0.6.13"
        assert manager._load_state()["reported_app_version"] == "0.6.13"


def test_failed_post_update_check_keeps_refresh_due_for_retry(monkeypatch):
    monkeypatch.setenv("PIMATRIX_LICENSE_MODE", "development")
    with TemporaryDirectory() as td:
        manager = LicenseManager(td, "0.6.13")
        manager._state = {"license_key": "PMS-TEST", "reported_app_version": "0.6.12"}
        with patch.object(manager, "_remote", side_effect=RuntimeError("offline")):
            manager.check_now(silent=True)
        assert manager._state["reported_app_version"] == "0.6.12"
        assert manager._version_refresh_due() is True


def test_release_version_is_v0613_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 6, 13)
