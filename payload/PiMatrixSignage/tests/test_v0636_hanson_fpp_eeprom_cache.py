from pathlib import Path

from hardware_detection import detect_panel_hardware


def _eeprom(name: str, version: str = "1.2", serial: str = "TEST") -> bytes:
    def field(value: str, size: int) -> bytes:
        raw = value.encode("ascii")[: size - 1] + b"\x00"
        return raw.ljust(size, b"\x00")
    return field("FPP02", 6) + field(name, 26) + field(version, 10) + field(serial, 16) + b"\x00" * 70


def _paths(tmp_path: Path, monkeypatch):
    cape = tmp_path / "cape-info.json"
    location = tmp_path / "eeprom_location.txt"
    cache = tmp_path / "eeprom.bin"
    monkeypatch.setenv("PIMATRIX_FPP_CAPE_INFO", str(cape))
    monkeypatch.setenv("PIMATRIX_FPP_EEPROM_LOCATION", str(location))
    monkeypatch.setenv("PIMATRIX_FPP_EEPROM_CACHE", str(cache))
    monkeypatch.setenv("PIMATRIX_EEPROM_PATHS", str(tmp_path / "sysfs-node-already-removed" / "eeprom"))
    monkeypatch.delenv("PIMATRIX_FORCE_RPI_MFC", raising=False)
    return cape, location, cache


def test_fpp_recorded_physical_location_detects_v12_after_sysfs_node_removed(tmp_path, monkeypatch):
    cape, location, _ = _paths(tmp_path, monkeypatch)
    cape.write_text(
        '{"id":"rPi-MFC","name":"rPi-MFC","version":"1.2",'
        '"validEepromLocation":true,"eepromLocation":"/sys/bus/i2c/devices/1-0050/eeprom"}',
        encoding="utf-8",
    )
    location.write_text("/sys/bus/i2c/devices/1-0050/eeprom", encoding="utf-8")

    result = detect_panel_hardware()
    assert result["rpi_mfc_detected"] is True
    assert result["source"] == "fpp_physical_eeprom_identity"
    assert result["cape_version"] == "1.2"
    assert result["eeprom"] == "/sys/bus/i2c/devices/1-0050/eeprom"


def test_fpp_cached_physical_eeprom_detects_when_cape_info_name_is_missing(tmp_path, monkeypatch):
    cape, location, cache = _paths(tmp_path, monkeypatch)
    cape.write_text('{"validEepromLocation":true}', encoding="utf-8")
    location.write_text("/sys/bus/i2c/devices/1-0050/eeprom", encoding="utf-8")
    cache.write_bytes(_eeprom("Hanson rPi-MFC", "1.2"))

    result = detect_panel_hardware()
    assert result["rpi_mfc_detected"] is True
    assert result["source"] == "fpp_physical_eeprom_cache"
    assert result["cape_version"] == "1.2"


def test_virtual_rpi_mfc_cape_info_still_does_not_count_as_physical(tmp_path, monkeypatch):
    cape, location, cache = _paths(tmp_path, monkeypatch)
    cape.write_text(
        '{"name":"rPi-MFC","version":"Latest","validEepromLocation":false,'
        '"eepromLocation":"/home/fpp/media/config/cape-eeprom.bin"}',
        encoding="utf-8",
    )
    cache.write_bytes(_eeprom("rPi-MFC", "virtual"))

    result = detect_panel_hardware()
    assert result["rpi_mfc_detected"] is False
    assert result["source"] == "virtual_rpi_mfc_only"


def test_unrelated_physical_cape_does_not_enable_hanson(tmp_path, monkeypatch):
    cape, location, cache = _paths(tmp_path, monkeypatch)
    cape.write_text(
        '{"name":"PiHat","version":"1.0","validEepromLocation":true,'
        '"eepromLocation":"/sys/bus/i2c/devices/1-0050/eeprom"}',
        encoding="utf-8",
    )
    location.write_text("/sys/bus/i2c/devices/1-0050/eeprom", encoding="utf-8")
    cache.write_bytes(_eeprom("PiHat", "1.0"))

    result = detect_panel_hardware()
    assert result["rpi_mfc_detected"] is False
    assert result["source"] == "other_or_unidentified_eeprom"


def test_ui_and_help_explain_fpp_post_startup_detection():
    root = Path(__file__).resolve().parents[1]
    js = (root / "static" / "app.js").read_text(encoding="utf-8")
    help_html = (root / "templates" / "help.html").read_text(encoding="utf-8")
    install = (root / "INSTALL.md").read_text(encoding="utf-8")
    assert "rPi-MFC configured but not physically confirmed" in js
    assert "The controller platform has confirmed the Hanson cape hardware" in js
    assert "controller platform's physical cape detection data" in help_html
    assert "does not require that temporary sysfs node to remain present" in install
