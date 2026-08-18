from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from licensing import LicenseManager


def test_licensing_defaults_to_live_whmcs_mode(monkeypatch):
    monkeypatch.delenv("PIMATRIX_LICENSE_MODE", raising=False)
    with TemporaryDirectory() as td:
        manager = LicenseManager(td, "0.6.15")
    assert manager.mode == "whmcs"


def test_invalid_licensing_mode_fails_closed_to_whmcs(monkeypatch):
    monkeypatch.setenv("PIMATRIX_LICENSE_MODE", "unexpected")
    with TemporaryDirectory() as td:
        manager = LicenseManager(td, "0.6.15")
    assert manager.mode == "whmcs"


def test_installer_creates_live_config_and_migrates_development_mode():
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "PIMATRIX_LICENSE_MODE=whmcs" in installer
    assert "grep -q '^PIMATRIX_LICENSE_MODE=development" in installer
    assert "Enabling live WHMCS licence enforcement" in installer
    assert "sed -i 's/^PIMATRIX_LICENSE_MODE=development" in installer


def test_live_mode_documentation_and_service_environment_are_packaged():
    guide = (ROOT / "WHMCS-LICENSING.md").read_text(encoding="utf-8")
    service = (ROOT / "systemd" / "pi-matrix-signage.service").read_text(encoding="utf-8")
    assert "PIMATRIX_LICENSE_MODE=whmcs" in guide
    assert "EnvironmentFile=-/home/fpp/media/pi-matrix-signage-data/license.env" in service


def test_release_version_is_v0615_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 6, 15)
