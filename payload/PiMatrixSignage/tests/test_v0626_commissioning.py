import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import Database  # noqa: E402


def test_hardware_profiles_round_trip_complete_configuration(tmp_path):
    db = Database(str(tmp_path / "data" / "signage.db"))
    config = {
        "panel_model": "P5 outdoor 64x32",
        "panel_width": 64,
        "panel_height": 32,
        "panel_scan": "1/8",
        "panel_output_type": "colorlight",
        "colorlight_receiver_model": "5a-75b",
        "colorlight_interface": "eth1",
        "panels_across": 2,
        "panels_down": 2,
        "display_rotation": 0,
        "color_order": "RGB",
        "brightness": 70,
    }
    profile_id = db.save_hardware_profile("Outdoor 2x2", config)
    assert db.get_hardware_profile(profile_id)["config"] == config
    assert db.list_hardware_profiles()[0]["name"] == "Outdoor 2x2"
    db.delete_hardware_profile(profile_id)
    assert db.list_hardware_profiles() == []


def test_commissioning_wizard_and_support_package_are_packaged():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for route in ("/api/hardware/network-interfaces", "/api/hardware/colorlight-test", "/api/hardware/colorlight-commission", "/api/hardware-profiles", "/api/support-package"):
        assert route in app
    for control in ("colorlightWizardCard", "detectedColorlightInterface", "completeCommissioning", "hardwareProfileList", "createSupportPackage"):
        assert f'id="{control}"' in html
    assert "function detectColorlightInterfaces" in js
    assert "function renderHardwareProfiles" in js
    assert "function createSupportPackage" in js


def test_support_package_redacts_secrets_and_can_include_preview():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "_SENSITIVE_SUPPORT_KEYS" in app
    assert "_redact_support_text" in app
    assert '"[redacted]"' in app
    assert 'zf.writestr("display-preview.png"' in app
    assert '"license_key"' not in app[app.index('def support_package_api():'):app.index('@app.get("/api/backups")')]


def test_release_version_is_v0626():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.26"
