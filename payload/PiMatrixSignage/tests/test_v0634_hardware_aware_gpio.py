from pathlib import Path
from unittest.mock import Mock

from gpio_controls import GPIOControlManager

ROOT = Path(__file__).resolve().parents[1]


def test_gpio_panel_has_hardware_specific_wiring_targets():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="gpioControlsIntro"' in html
    assert 'id="gpioWiringHelp"' in html
    assert 'data-gpio-wiring="A"' in html
    assert 'data-gpio-wiring="B"' in html
    assert 'data-gpio-wiring="C"' in html

    assert "$('gpioControlsCard').classList.toggle('hidden',colorlight)" not in js
    assert "These controls are wired to the Pi, not to the Colorlight receiver card." in js
    assert "A = GPIO6 / physical pin 31" in js
    assert "B = GPIO13 / physical pin 33" in js
    assert "C = GPIO26 / physical pin 37" in js
    assert "never apply 5V/12V or any external voltage" in js
    assert "CN2 · GPIO6 · Pin 31" in js


def test_gpio_status_profile_follows_output_hardware():
    engine = Mock()
    log = Mock()

    db = Mock()
    db.get_settings.return_value = {"panel_output_type": "colorlight", "gpio_controls_enabled": False, "gpio_inputs": []}
    manager = GPIOControlManager(db, engine, log)
    assert manager.status()["profile"] == "Raspberry Pi GPIO (Colorlight mode)"

    db.get_settings.return_value = {"panel_output_type": "rpi_mfc", "gpio_controls_enabled": False, "gpio_inputs": []}
    assert manager.status()["profile"] == "Hanson rPi-MFC inputs"


def test_help_explains_both_hanson_and_colorlight_physical_control_wiring():
    manual = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    assert "CN2/CN3/CN4" in manual
    assert "Raspberry Pi physical pins 31/33/37" in manual
    assert "Do not connect the switches to the Colorlight receiver" in manual
