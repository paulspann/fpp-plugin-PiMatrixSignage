from pathlib import Path
from unittest.mock import Mock

import pytest

from gpio_controls import GPIOControlManager

ROOT = Path(__file__).resolve().parents[1]


def test_adafruit_outputs_are_first_class_display_choices():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert '"adafruit_hat": "Adafruit RGB Matrix HAT / Bonnet"' in app
    assert '"adafruit_triple": "Adafruit Triple Matrix Bonnet"' in app
    assert 'value="adafruit_hat"' in html
    assert 'value="adafruit_triple"' in html
    assert 'id="adafruitSettings"' in html
    assert "adafruit_hat" in js and "adafruit_triple" in js


def test_fpp_setup_uses_documented_adafruit_mappings():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "hardware mapping adafruit-hat" in app
    assert "Regular wiring pinout (hardware mapping regular)" in app
    assert "Configure 3 parallel outputs for the Triple Matrix Bonnet / Active3 wiring" in app
    assert "adafruit-hat-pwm" in app
    assert "Raspberry Pi 5" in app


def test_adafruit_starter_profiles_are_packaged():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "Starter · Adafruit RGB Matrix HAT/Bonnet · P5 64×32 · 1 panel" in app
    assert "Starter · Adafruit Triple Matrix Bonnet · P5 64×32 · 3 panels" in app
    assert '"panel_output_type": "adafruit_hat"' in app
    assert '"panel_output_type": "adafruit_triple"' in app


def test_adafruit_scan_rates_and_certificate_labels_are_supported():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'elif output_type in ("adafruit_hat", "adafruit_triple")' in app
    assert '("1/4", "1/8", "1/16", "1/32")' in app
    assert "PANEL_OUTPUT_LABELS.get(output_type" in app


def test_gpio_controls_are_blocked_for_both_adafruit_outputs():
    engine = Mock()
    log = Mock()
    db = Mock()
    manager = GPIOControlManager(db, engine, log)

    for output in ("adafruit_hat", "adafruit_triple"):
        db.get_settings.return_value = {
            "panel_output_type": output,
            "gpio_controls_enabled": True,
            "gpio_inputs": [{"id": "A", "enabled": True, "action": "emergency"}],
        }
        status = manager.status()
        assert status["enabled"] is False
        assert status["available_for_output"] is False
        assert "Unavailable" in status["profile"]
        with pytest.raises(ValueError, match="unavailable"):
            manager.test_action("A")


def test_ui_explains_gpio_conflict_and_manual_detection_boundary():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    help_html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")

    assert "Reserved by HUB75 output" in js
    assert "the Adafruit RGB Matrix mappings use GPIO6, GPIO13 and GPIO26" in js
    assert "cannot be reliably auto-detected across all revisions" in js
    assert "Physical GPIO controls are unavailable with either Adafruit direct-HUB75 adapter" in help_html
    assert "3 parallel outputs" in help_html
    assert "Adafruit direct-HUB75 outputs" in install


def test_release_version_is_v0637_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 37)
