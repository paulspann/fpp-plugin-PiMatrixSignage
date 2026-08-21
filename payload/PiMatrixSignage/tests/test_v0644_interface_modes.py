from pathlib import Path
from types import SimpleNamespace

import controller_platform as cp

ROOT = Path(__file__).resolve().parents[1]


def test_interface_ui_offers_fpp_first_as_recommended_default_and_appliance_option():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "Controller &amp; FPP</button>" in html
    assert "Controller interface" in html
    assert "FPP + Pi Matrix Signage add-on" in html
    assert "Recommended default" in html
    assert "Pi Matrix Signage appliance" in html
    assert 'name="controllerInterfaceMode" value="fpp"' in html
    assert 'name="controllerInterfaceMode" value="appliance"' in html
    assert "loadInterfaceMode" in js
    assert "saveInterfaceMode" in js
    assert "/api/interface-mode" in js
    assert "openFppInterface" in js


def test_fresh_install_defaults_to_fpp_but_migrates_existing_v0643_appliance():
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'interface_mode="fpp"' in install
    assert '/etc/apache2/conf-enabled/pi-matrix-signage-appliance.conf' in install
    assert 'interface_mode="appliance"' in install
    assert "Preserving existing Pi Matrix Signage appliance mode" in install
    assert "Defaulting controller interface to FPP-first add-on mode" in install
    assert 'a2disconf pi-matrix-signage-appliance' in install
    assert 'a2enconf pi-matrix-signage-appliance' in install
    assert 'MODE_FILE="$PERSIST/interface-mode"' in install


def test_platform_helper_switches_interface_mode_with_apache_validation():
    helper = (ROOT / "systemd" / "pi-matrix-signage-platform").read_text(encoding="utf-8")
    assert "--interface-mode" in helper
    assert "set_interface_mode" in helper
    assert "a2enconf pi-matrix-signage-appliance" in helper
    assert "a2disconf pi-matrix-signage-appliance" in helper
    assert "apache2ctl configtest" in helper
    assert "systemctl reload apache2" in helper
    assert "interface-mode" in helper


def test_interface_mode_status_defaults_to_fpp_and_detects_legacy_appliance(monkeypatch, tmp_path):
    mode_file = tmp_path / "interface-mode"
    enabled = tmp_path / "enabled.conf"
    monkeypatch.setattr(cp, "INTERFACE_MODE_FILE", mode_file)
    monkeypatch.setattr(cp, "APPLIANCE_ENABLED_CONF", enabled)
    monkeypatch.setattr(cp, "PLATFORM_UPDATE_HELPER", tmp_path / "helper")

    status = cp.interface_mode_status()
    assert status["mode"] == "fpp"
    assert status["actual_mode"] == "fpp"
    assert status["in_sync"] is True

    enabled.write_text("enabled", encoding="utf-8")
    status = cp.interface_mode_status()
    assert status["mode"] == "appliance"
    assert status["actual_mode"] == "appliance"

    mode_file.write_text("fpp\n", encoding="utf-8")
    status = cp.interface_mode_status()
    assert status["mode"] == "fpp"
    assert status["actual_mode"] == "appliance"
    assert status["in_sync"] is False


def test_set_interface_mode_uses_narrow_privileged_helper(monkeypatch, tmp_path):
    helper = tmp_path / "helper"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(cp, "PLATFORM_UPDATE_HELPER", helper)
    monkeypatch.setattr(cp, "interface_mode_status", lambda: {"mode": "appliance", "actual_mode": "appliance", "in_sync": True})
    seen = {}

    def fake_run(cmd, capture_output, text, timeout):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="appliance enabled\n", stderr="")

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    result = cp.set_interface_mode("appliance")
    assert seen["cmd"] == ["sudo", "-n", str(helper), "--interface-mode", "appliance"]
    assert result["ok"] is True


def test_interface_mode_routes_require_users_permission_for_changes():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '@app.get("/api/interface-mode")' in app
    assert '@app.put("/api/interface-mode")' in app
    route = app.split('@app.put("/api/interface-mode")', 1)[1].split('@app.get("/api/controller-output")', 1)[0]
    assert '@permission_required("display_setup")' in route
    assert 'g.current_user.get("can_users")' in route
    assert "set_interface_mode(mode)" in route


def test_help_explains_both_interface_modes_and_upgrade_persistence():
    help_html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    assert "FPP + Pi Matrix Signage add-on" in help_html
    assert "Pi Matrix Signage appliance" in help_html
    assert "Fresh installs start" in help_html
    assert "Existing appliance installations retain their chosen mode" in help_html
    assert "safe default for new installs" in install
    assert "v0.6.43 appliance installation remains in appliance mode" in install


def test_release_version_is_v0644_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 44)
