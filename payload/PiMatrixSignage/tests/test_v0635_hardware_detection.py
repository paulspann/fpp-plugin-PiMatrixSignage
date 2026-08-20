from pathlib import Path

from hardware_detection import detect_panel_hardware, parse_fpp_eeprom

ROOT = Path(__file__).resolve().parents[1]


def _eeprom(name: str, version: str = "1.1", serial: str = "TEST") -> bytes:
    def field(value: str, size: int) -> bytes:
        raw = value.encode("ascii")[: size - 1] + b"\x00"
        return raw.ljust(size, b"\x00")
    return field("FPP02", 6) + field(name, 26) + field(version, 10) + field(serial, 16) + b"\x00" * 70


def test_fpp_eeprom_header_parses_rpi_mfc_identity():
    parsed = parse_fpp_eeprom(_eeprom("rPi-MFC", "1.1"))
    assert parsed["format"] == "FPP02"
    assert parsed["name"] == "rPi-MFC"
    assert parsed["version"] == "1.1"


def test_physical_rpi_mfc_eeprom_is_detected(tmp_path, monkeypatch):
    eeprom = tmp_path / "1-0050" / "eeprom"
    eeprom.parent.mkdir()
    eeprom.write_bytes(_eeprom("Hanson rPi-MFC", "1.1"))
    monkeypatch.setenv("PIMATRIX_EEPROM_PATHS", str(eeprom))
    monkeypatch.setenv("PIMATRIX_FPP_CAPE_INFO", str(tmp_path / "missing.json"))
    monkeypatch.delenv("PIMATRIX_FORCE_RPI_MFC", raising=False)

    result = detect_panel_hardware()
    assert result["rpi_mfc_detected"] is True
    assert result["source"] == "physical_eeprom"
    assert "rPi-MFC" in result["cape_name"]


def test_virtual_cape_info_alone_does_not_fake_physical_detection(tmp_path, monkeypatch):
    cape = tmp_path / "cape-info.json"
    cape.write_text('{"name":"rPi-MFC","vendor":"Hanson Electronics"}', encoding="utf-8")
    monkeypatch.setenv("PIMATRIX_EEPROM_PATHS", str(tmp_path / "not-present" / "eeprom"))
    monkeypatch.setenv("PIMATRIX_FPP_CAPE_INFO", str(cape))
    monkeypatch.delenv("PIMATRIX_FORCE_RPI_MFC", raising=False)

    result = detect_panel_hardware()
    assert result["rpi_mfc_detected"] is False
    assert result["source"] == "no_physical_cape_eeprom"


def test_physical_eeprom_plus_fpp_identity_handles_unreadable_or_unparsed_bytes(tmp_path, monkeypatch):
    eeprom = tmp_path / "1-0050" / "eeprom"
    eeprom.parent.mkdir()
    eeprom.write_bytes(b"not-an-fpp-header")
    cape = tmp_path / "cape-info.json"
    cape.write_text('{"cape":{"name":"rPi-MFC"}}', encoding="utf-8")
    monkeypatch.setenv("PIMATRIX_EEPROM_PATHS", str(eeprom))
    monkeypatch.setenv("PIMATRIX_FPP_CAPE_INFO", str(cape))
    monkeypatch.delenv("PIMATRIX_FORCE_RPI_MFC", raising=False)

    result = detect_panel_hardware()
    assert result["rpi_mfc_detected"] is True
    assert result["source"] == "physical_eeprom_fpp_identity"


def test_support_override_can_restore_known_legacy_rpi_mfc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIMATRIX_EEPROM_PATHS", str(tmp_path / "missing"))
    monkeypatch.setenv("PIMATRIX_FORCE_RPI_MFC", "1")
    result = detect_panel_hardware()
    assert result["rpi_mfc_detected"] is True
    assert result["source"] == "support_override"


def test_display_setup_hides_hanson_until_detection_enables_it():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    static_select = html.split('id="panelOutputType"', 1)[1].split('</select>', 1)[0]
    assert 'value="rpi_mfc"' not in static_select
    assert 'value="colorlight"' in static_select
    assert 'id="hardwareDetectionStatus"' in html
    assert 'detected?\'<option value="rpi_mfc">Hanson rPI-MFC</option><option value="colorlight">Colorlight receiver card</option>\'' in js
    assert "the Hanson option has been hidden and Colorlight is selected automatically" in js
    assert "panel_output_type:'colorlight'" in js
    assert "Hanson rPi-MFC is not physically detected on this Raspberry Pi" in app


def test_hanson_profiles_are_filtered_when_board_is_absent():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'profiles = [item for item in profiles if str((item.get("config") or {}).get("panel_output_type") or "") != "rpi_mfc"]' in app
    assert '@app.get("/api/hardware-detection")' in app


def test_help_documents_auto_detection_and_legacy_board_caveat():
    manual = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    assert "checks for the Hanson rPi-MFC physical FPP cape EEPROM" in manual
    assert "Hanson choice is hidden and Colorlight is selected automatically" in manual
    assert "old or unprogrammed board may not expose a usable EEPROM identity" in manual
