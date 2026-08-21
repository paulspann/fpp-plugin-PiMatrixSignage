from pathlib import Path

import controller_platform as cp

ROOT = Path(__file__).resolve().parents[1]


def _settings(output_type="colorlight"):
    return {
        "panel_output_type": output_type,
        "panel_width": 64,
        "panel_height": 32,
        "panel_scan": "1/16",
        "panels_across": 4,
        "panels_down": 2,
        "color_order": "RGB",
        "brightness": 60,
        "colorlight_interface": "eth1",
        "ddp_port": 4048,
    }


def test_customer_ui_uses_controller_appliance_language():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    help_html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")

    assert 'Controller &amp; FPP</button>' in html
    assert "Panel controller configuration" in html
    assert "Controller software" in html
    assert "Engineering access" in html
    assert "FPP setup helper" not in html
    assert "Controller &amp; FPP" in html
    assert "configure FPP" not in js
    assert "FPP-first mode" in help_html and "appliance mode" in help_html


def test_bare_root_appliance_entry_preserves_explicit_platform_urls():
    conf = (ROOT / "systemd" / "pi-matrix-signage-appliance.conf").read_text(encoding="utf-8")
    entry = (ROOT / "systemd" / "pimatrix-appliance.php").read_text(encoding="utf-8")
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    uninstall = (ROOT / "uninstall.sh").read_text(encoding="utf-8")

    assert "DirectoryIndex pimatrix-appliance.php index.php index.html" in conf
    assert "Location: http://" in entry and ":8090/" in entry
    assert "a2enconf pi-matrix-signage-appliance" in install
    assert "apache2ctl configtest" in install
    assert "a2disconf pi-matrix-signage-appliance" in uninstall
    assert "/opt/fpp/www/pimatrix-appliance.php" in uninstall


def test_managed_output_builds_colorlight_and_adafruit_configs(monkeypatch):
    monkeypatch.setattr(cp, "_load_current_channel_outputs", lambda: {"channelOutputs": []})
    monkeypatch.setattr(cp, "_cape_panel_profile", lambda: {})

    colorlight, _ = cp.build_managed_output_config(_settings("colorlight"), {})
    matrix = colorlight["channelOutputs"][-1]
    assert matrix["type"] == "LEDPanelMatrix"
    assert matrix["subType"] == "ColorLight5a75"
    assert matrix["interface"] == "eth1"
    assert matrix["channelCount"] == 256 * 64 * 3

    hat, _ = cp.build_managed_output_config(_settings("adafruit_hat"), {})
    assert hat["channelOutputs"][-1]["wiringPinout"] == "adafruit-hat"
    assert hat["channelOutputs"][-1]["ledPanelsOutputs"] == 1

    triple_settings = _settings("adafruit_triple")
    triple_settings["panels_across"] = 3
    triple, _ = cp.build_managed_output_config(triple_settings, {})
    assert triple["channelOutputs"][-1]["wiringPinout"] == "regular"
    assert triple["channelOutputs"][-1]["ledPanelsOutputs"] == 3
    assert {p["outputNumber"] for p in triple["channelOutputs"][-1]["panels"]} == {0, 1, 2}


def test_hanson_managed_output_uses_physical_cape_profile_not_guessed_mapping(monkeypatch):
    monkeypatch.setattr(cp, "_load_current_channel_outputs", lambda: {"channelOutputs": []})
    monkeypatch.setattr(cp, "_cape_panel_profile", lambda: {"driver": "RGBMatrix", "name": "rPi-MFC", "_key": "rPi-MFC"})
    config, engineering = cp.build_managed_output_config(_settings("rpi_mfc"), {"rpi_mfc_detected": True})
    matrix = config["channelOutputs"][-1]
    assert matrix["subType"] == "RGBMatrix"
    assert matrix["configName"] == "rPi-MFC"
    assert "wiringPinout" not in matrix
    assert engineering["cape_panel_profile"] == "rPi-MFC"


def test_apply_output_writes_panel_output_and_enables_local_frame_input(monkeypatch):
    writes = []
    monkeypatch.setattr(cp, "build_managed_output_config", lambda settings, detection: ({"channelOutputs": [{"type": "LEDPanelMatrix"}]}, {}))
    monkeypatch.setattr(cp, "_request_raw_json_file", lambda path, payload, timeout=8: writes.append((path, payload)))
    monkeypatch.setattr(cp, "_request_json", lambda path, method="GET", payload=None, timeout=5: writes.append((path, payload)) or {})
    monkeypatch.setattr(cp, "output_status", lambda settings, detection, ddp_port: {"output_ready": True, "engineering": {}})
    monkeypatch.setattr(cp.time, "sleep", lambda _: None)

    result = cp.apply_output(_settings(), {}, 4048)
    assert writes[0][0] == "/api/configfile/channeloutputs.json"
    assert writes[1][0] == "/api/channel/output/universeInputs"
    input_cfg = writes[1][1]["channelInputs"][0]
    assert input_cfg["type"] == "universes"
    assert input_cfg["enabled"] == 1
    assert input_cfg["universes"] == []
    assert result["message"] == "Panel controller configuration applied"


def test_controller_update_and_engineering_routes_are_gated_and_packaged():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    helper = (ROOT / "systemd" / "pi-matrix-signage-platform").read_text(encoding="utf-8")
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    for route in (
        '@app.get("/api/controller-output")',
        '@app.post("/api/controller-output/apply")',
        '@app.get("/api/controller-update")',
        '@app.post("/api/controller-update/install")',
        '@app.post("/api/engineering-access")',
    ):
        assert route in app
    assert 'if not bool(g.current_user.get("can_users"))' in app
    assert '_verify_password' in app
    assert "/opt/fpp/scripts/upgrade_plugin" in helper
    assert 'PLUGIN="fpp-plugin-PiMatrixSignage"' in helper
    assert "systemd-run --quiet --collect" in helper
    assert "pi-matrix-signage-platform" in install
    assert "applyControllerOutputConfig" in js
    assert "loadControllerUpdate" in js
    assert "openEngineeringAccess" in js


def test_display_save_and_profile_apply_manage_controller_automatically():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    save = js.split("async function saveSettings()", 1)[1].split("function controllerHealthClass", 1)[0]
    profile = js.split("async function applyHardwareProfile", 1)[1].split("async function deleteHardwareProfile", 1)[0]
    assert "applyControllerOutputConfig({confirmFirst:false,quiet:true})" in save
    assert "applyControllerOutputConfig({confirmFirst:false,quiet:true})" in profile
    assert "panel controller needs attention" in save


def test_release_version_is_v0643_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 43)
