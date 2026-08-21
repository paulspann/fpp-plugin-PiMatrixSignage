from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_colorlight_settings_and_display_controls_are_packaged():
    database = (ROOT / "database.py").read_text(encoding="utf-8")
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert '"panel_output_type": "rpi_mfc"' in database
    assert '"colorlight_receiver_model": "5a-75b"' in database
    assert '"colorlight_interface": "eth1"' in database
    assert 'id="panelOutputType"' in html
    assert 'id="colorlightReceiverModel"' in html
    assert 'id="colorlightInterface"' in html
    assert "function updateOutputHardware()" in js
    assert "$('gpioControlsCard').classList.toggle('hidden',colorlight)" not in js
    assert "These controls are wired to the Pi, not to the Colorlight receiver card." in js


def test_colorlight_validation_and_fpp_setup_are_hardware_specific():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'output_type not in PANEL_OUTPUT_LABELS' in app
    assert '("5a-75b", "5a-75e")' in app
    assert 'Path("/sys/class/net") / interface' in app
    assert '@app.get("/api/controller-output")' in app
    assert 'f"Colorlight {receiver_model}" if output_type == "colorlight" else PANEL_OUTPUT_LABELS.get(output_type, output_type)' in app
    platform = (ROOT / "controller_platform.py").read_text(encoding="utf-8")
    assert '"subType": "ColorLight5a75"' in platform
    assert '"interface": str(settings.get("colorlight_interface") or "eth1")' in platform


def test_help_explains_colorlight_receiver_programming_boundary():
    manual = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    assert "Colorlight 5A-75B / 5A-75E" in manual
    assert "does not replace Colorlight's receiver-card programming tool" in manual


def test_release_version_is_v0624_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 24)
