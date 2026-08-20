from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

FPP_CAPE_INFO = Path(os.environ.get("PIMATRIX_FPP_CAPE_INFO", "/home/fpp/media/tmp/cape-info.json"))

def _clean_ascii(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


def parse_fpp_eeprom(raw: bytes) -> dict:
    """Parse the fixed FPP EEPROM identity header documented by FPP."""
    if len(raw) < 58 or not raw[:6].rstrip(b"\x00").startswith(b"FPP"):
        return {}
    return {
        "format": _clean_ascii(raw[0:6]),
        "name": _clean_ascii(raw[6:32]),
        "version": _clean_ascii(raw[32:42]),
        "serial": _clean_ascii(raw[42:58]),
    }


def _is_rpi_mfc_name(value: str) -> bool:
    compact = "".join(ch.lower() for ch in str(value or "") if ch.isalnum())
    return "rpimfc" in compact


def _flatten_strings(value) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _flatten_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _flatten_strings(item)
    elif isinstance(value, (str, int, float, bool)):
        yield str(value)


def _cape_info_name(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return ""
    for text in _flatten_strings(payload):
        if _is_rpi_mfc_name(text):
            return text
    return ""


def _candidate_eeproms() -> list[Path]:
    override = os.environ.get("PIMATRIX_EEPROM_PATHS", "").strip()
    if override:
        return [Path(p) for p in override.split(os.pathsep) if p]
    found: list[Path] = []
    # FPP documents the Pi cape EEPROM on the primary I2C bus. Search all
    # instantiated 0x50 EEPROM devices so this also tolerates a bus-number
    # change without probing arbitrary I2C addresses ourselves.
    for path in Path("/sys/bus/i2c/devices").glob("*-0050/eeprom"):
        if path not in found:
            found.append(path)
    return found


def detect_panel_hardware() -> dict:
    """Detect a physically-present Hanson rPi-MFC conservatively.

    We only advertise Hanson when an actual 0x50 EEPROM device exists and its
    FPP identity names rPi-MFC, either from direct readable bytes or from FPP's
    parsed cape-info. A virtual cape-info file by itself is deliberately not
    enough because the user asked for physical-board detection.
    """
    forced = os.environ.get("PIMATRIX_FORCE_RPI_MFC", "").strip().lower() in {"1", "true", "yes", "on"}
    if forced:
        return {
            "rpi_mfc_detected": True,
            "source": "support_override",
            "cape_name": "Hanson rPi-MFC",
            "message": "Hanson rPi-MFC enabled by support override.",
        }

    paths = [p for p in _candidate_eeproms() if p.exists()]
    cape_info_path = Path(os.environ.get("PIMATRIX_FPP_CAPE_INFO", str(FPP_CAPE_INFO)))
    cape_info_name = _cape_info_name(cape_info_path)

    for path in paths:
        try:
            with path.open("rb") as handle:
                parsed = parse_fpp_eeprom(handle.read(128))
        except Exception:
            parsed = {}
        name = str(parsed.get("name") or "")
        if _is_rpi_mfc_name(name):
            return {
                "rpi_mfc_detected": True,
                "source": "physical_eeprom",
                "cape_name": name,
                "cape_version": str(parsed.get("version") or ""),
                "eeprom": str(path),
                "message": f"Detected {name} from its physical FPP EEPROM.",
            }

    if paths and cape_info_name:
        # The EEPROM sysfs node proves a physical 0x50 device is present; FPP's
        # parsed cape info identifies it when the unprivileged web process cannot
        # read the EEPROM bytes directly.
        return {
            "rpi_mfc_detected": True,
            "source": "physical_eeprom_fpp_identity",
            "cape_name": cape_info_name,
            "eeprom": str(paths[0]),
            "message": "Detected a physical FPP cape EEPROM identified by FPP as rPi-MFC.",
        }

    if paths:
        return {
            "rpi_mfc_detected": False,
            "source": "other_or_unidentified_eeprom",
            "cape_name": "",
            "eeprom": str(paths[0]),
            "message": "A physical cape EEPROM is present but it is not identified as a Hanson rPi-MFC; Colorlight is assumed.",
        }

    return {
        "rpi_mfc_detected": False,
        "source": "no_physical_cape_eeprom",
        "cape_name": "",
        "message": "No physical Hanson rPi-MFC EEPROM was detected; Colorlight is assumed.",
    }
