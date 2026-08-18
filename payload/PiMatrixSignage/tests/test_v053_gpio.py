import tempfile
from pathlib import Path
from unittest.mock import Mock

from database import Database
from gpio_controls import GPIOControlManager, RPI_MFC_INPUTS, normalise_gpio_inputs
from renderer import RendererEngine

ROOT = Path(__file__).resolve().parents[1]


def test_rpimfc_dedicated_input_mapping_and_sanitisation():
    rows = normalise_gpio_inputs([
        {"id":"A","enabled":True,"action":"emergency","gpio":99,"header_pin":1,"connector":"BAD","contact_type":"normally_closed","debounce_ms":1},
        {"id":"B","enabled":True,"action":"nonsense","debounce_ms":9999},
    ])
    by = {r["id"]: r for r in rows}
    assert (by["A"]["connector"], by["A"]["gpio"], by["A"]["header_pin"]) == ("CN2", 6, 31)
    assert (by["B"]["connector"], by["B"]["gpio"], by["B"]["header_pin"]) == ("CN3", 13, 33)
    assert (by["C"]["connector"], by["C"]["gpio"], by["C"]["header_pin"]) == ("CN4", 26, 37)
    assert by["A"]["contact_type"] == "normally_closed"
    assert by["A"]["debounce_ms"] == 20
    assert by["B"]["action"] == "none" and by["B"]["debounce_ms"] == 2000
    assert all(r["pull"] == "pull-up" for r in rows)


def test_gpio_event_parsing_supports_gpiod_v1_and_v2():
    f = GPIOControlManager._event_level
    assert f("0") == 0
    assert f("1") == 1
    assert f("2") == 0
    assert f("rising") == 1
    assert f("falling") == 0
    assert f("junk") is None


def test_no_and_nc_contacts_have_fail_safe_semantics():
    assert GPIOControlManager._is_active({"contact_type":"normally_open"}, 0) is True
    assert GPIOControlManager._is_active({"contact_type":"normally_open"}, 1) is False
    assert GPIOControlManager._is_active({"contact_type":"normally_closed"}, 1) is True
    assert GPIOControlManager._is_active({"contact_type":"normally_closed"}, 0) is False


def test_gpio_action_dispatch_and_source_aware_emergency():
    db = Mock(); db.get_settings.return_value = {"gpio_controls_enabled":True,"gpio_inputs":[]}
    eng = Mock(); log = Mock()
    mgr = GPIOControlManager(db, eng, log)
    item={"id":"A","action":"emergency","emergency_behaviour":"while_active"}
    mgr._perform_action(item, True)
    eng.activate_emergency.assert_called_once_with(source="gpio:A")
    mgr._perform_action(item, False)
    eng.clear_emergency.assert_called_once_with(source="gpio:A")


def test_engine_only_clears_emergency_when_gpio_source_matches():
    with tempfile.TemporaryDirectory() as td:
        db=Database(str(Path(td)/"data"/"signage.db"))
        mid=db.list_message_options()[0]["id"]
        db.update_settings({"emergency_message_id":mid})
        eng=RendererEngine(db,str(Path(td)/"data"),str(Path(td)/"uploads"))
        eng.activate_emergency(source="gpio:A")
        assert eng.clear_emergency(source="gpio:B") is False
        assert eng.status()["emergency"]["source"] == "gpio:A"
        assert eng.clear_emergency(source="gpio:A") is True
        assert eng.status()["emergency"] is None


def test_gpio_ui_and_api_are_packaged():
    html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
    js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    for marker in ("GPIO / physical controls", "CN2", "GPIO6", "Pin 31", "normally_closed", "Save physical controls"):
        assert marker in html
    for marker in ("/api/gpio-controls", "loadGpioControls", "saveGpioControls", "testGpioAction"):
        assert marker in app+js


def test_upgrade_package_requires_gpio_module_and_install_has_gpiod():
    helper=(ROOT/"systemd"/"pi-matrix-signage-upgrade").read_text(encoding="utf-8")
    install=(ROOT/"install.sh").read_text(encoding="utf-8")
    assert "PiMatrixSignage/gpio_controls.py" in helper
    assert "gpiod" in install
