from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

FPP_CAPE_INFO = Path(os.environ.get("PIMATRIX_FPP_CAPE_INFO", "/home/fpp/media/tmp/cape-info.json"))
FPP_EEPROM_LOCATION = Path(os.environ.get("PIMATRIX_FPP_EEPROM_LOCATION", "/home/fpp/media/tmp/eeprom_location.txt"))
FPP_EEPROM_CACHE = Path(os.environ.get("PIMATRIX_FPP_EEPROM_CACHE", "/home/fpp/media/tmp/eeprom.bin"))


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


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _cape_identity(payload: dict) -> dict:
    """Return the useful FPP cape identity fields without depending on one schema revision."""
    name = ""
    version = ""
    location = ""
    valid_location = False

    # Current FPP cape-info is normally a flat object, but tolerate wrappers used
    # by older/test data and future API representations.
    candidates = [payload]
    for key in ("cape", "cape-info", "cape_info"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)

    for item in candidates:
        if not name:
            for key in ("name", "id", "capeName", "cape_name"):
                value = item.get(key)
                if _is_rpi_mfc_name(str(value or "")):
                    name = str(value)
                    break
        if not version:
            for key in ("version", "capeVersion", "cape_version", "hardwareVersion"):
                value = item.get(key)
                if value not in (None, ""):
                    version = str(value)
                    break
        if not location:
            for key in ("eepromLocation", "eeprom_location", "EEPROM", "eeprom"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    location = value.strip()
                    break
        for key in ("validEepromLocation", "valid_eeprom_location"):
            if key in item:
                value = item.get(key)
                valid_location = bool(value is True or str(value).strip().lower() in {"1", "true", "yes", "on"})
                break

    # Older cape-info variants may not have a canonical name field. Keep the old
    # tolerant string search as a final identity fallback.
    if not name:
        for text in _flatten_strings(payload):
            if _is_rpi_mfc_name(text):
                name = text
                break

    return {
        "name": name,
        "version": version,
        "eeprom_location": location,
        "valid_eeprom_location": valid_location,
    }


def _is_physical_eeprom_location(value: str) -> bool:
    value = str(value or "").strip()
    return value.startswith("/sys/bus/i2c/devices/") and value.endswith("/eeprom") and "-0050/" in value


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def _read_eeprom(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return parse_fpp_eeprom(handle.read(128))
    except Exception:
        return {}


def _candidate_eeproms() -> list[Path]:
    override = os.environ.get("PIMATRIX_EEPROM_PATHS", "").strip()
    if override:
        return [Path(p) for p in override.split(os.pathsep) if p]
    found: list[Path] = []
    # FPP may temporarily instantiate the physical 0x50 EEPROM as a Linux sysfs
    # device. Keep this live check as a fallback, but do not rely on it because
    # current FPP removes the sysfs device again after caching the EEPROM.
    for path in Path("/sys/bus/i2c/devices").glob("*-0050/eeprom"):
        if path not in found:
            found.append(path)
    return found


def detect_panel_hardware() -> dict:
    """Detect a Hanson rPi-MFC while avoiding false positives from virtual capes.

    Current FPP probes the physical 0x50 cape EEPROM, records its original sysfs
    path in ``media/tmp/eeprom_location.txt``, copies the bytes to
    ``media/tmp/eeprom.bin``, and may then remove the temporary sysfs EEPROM
    device.  Consequently the FPP-recorded physical location is the primary
    signal; requiring the sysfs node to still exist causes genuine capes to be
    missed after FPP has completed startup.

    A virtual cape-info/config by itself remains insufficient.  Hanson is only
    advertised when FPP says the EEPROM came from a physical I2C 0x50 path, a
    current live physical 0x50 EEPROM is readable, or support explicitly forces
    the known legacy path.
    """
    forced = os.environ.get("PIMATRIX_FORCE_RPI_MFC", "").strip().lower() in {"1", "true", "yes", "on"}
    if forced:
        return {
            "rpi_mfc_detected": True,
            "source": "support_override",
            "cape_name": "Hanson rPi-MFC",
            "message": "Hanson rPi-MFC enabled by support override.",
        }

    cape_info_path = Path(os.environ.get("PIMATRIX_FPP_CAPE_INFO", str(FPP_CAPE_INFO)))
    location_path = Path(os.environ.get("PIMATRIX_FPP_EEPROM_LOCATION", str(FPP_EEPROM_LOCATION)))
    cache_path = Path(os.environ.get("PIMATRIX_FPP_EEPROM_CACHE", str(FPP_EEPROM_CACHE)))

    cape = _cape_identity(_read_json(cape_info_path))
    recorded_location = _read_text(location_path) or str(cape.get("eeprom_location") or "")
    recorded_physical = _is_physical_eeprom_location(recorded_location)
    cape_name = str(cape.get("name") or "")
    cape_version = str(cape.get("version") or "")

    # This is the normal post-startup state on current FPP: the physical sysfs
    # EEPROM node has already been removed, but FPP has retained both the origin
    # path and the parsed cape identity. This is the v0.6.35 false-negative fix.
    if recorded_physical and _is_rpi_mfc_name(cape_name):
        return {
            "rpi_mfc_detected": True,
            "source": "fpp_physical_eeprom_identity",
            "cape_name": cape_name,
            "cape_version": cape_version,
            "eeprom": recorded_location,
            "message": "FPP identified a physical Hanson rPi-MFC cape EEPROM during startup.",
        }

    # If cape-info is incomplete/unreadable, FPP's cached physical EEPROM bytes
    # provide an independent identity while eeprom_location.txt proves that the
    # cache came from real I2C hardware rather than a virtual EEPROM file.
    if recorded_physical and cache_path.exists():
        parsed = _read_eeprom(cache_path)
        name = str(parsed.get("name") or "")
        if _is_rpi_mfc_name(name):
            return {
                "rpi_mfc_detected": True,
                "source": "fpp_physical_eeprom_cache",
                "cape_name": name,
                "cape_version": str(parsed.get("version") or cape_version),
                "eeprom": recorded_location,
                "eeprom_cache": str(cache_path),
                "message": "Detected a physical Hanson rPi-MFC from FPP's cached cape EEPROM.",
            }

    # Fallback for the brief period when the kernel sysfs EEPROM node still
    # exists, or for FPP revisions that leave it instantiated.
    paths = [p for p in _candidate_eeproms() if p.exists()]
    for path in paths:
        parsed = _read_eeprom(path)
        name = str(parsed.get("name") or "")
        if _is_rpi_mfc_name(name):
            return {
                "rpi_mfc_detected": True,
                "source": "physical_eeprom",
                "cape_name": name,
                "cape_version": str(parsed.get("version") or ""),
                "eeprom": str(path),
                "message": f"Detected {name} from its live physical FPP EEPROM.",
            }

    if paths and _is_rpi_mfc_name(cape_name):
        return {
            "rpi_mfc_detected": True,
            "source": "physical_eeprom_fpp_identity",
            "cape_name": cape_name,
            "cape_version": cape_version,
            "eeprom": str(paths[0]),
            "message": "Detected a physical FPP cape EEPROM identified by FPP as rPi-MFC.",
        }

    if paths or recorded_physical:
        return {
            "rpi_mfc_detected": False,
            "source": "other_or_unidentified_eeprom",
            "cape_name": cape_name if _is_rpi_mfc_name(cape_name) else "",
            "eeprom": recorded_location or (str(paths[0]) if paths else ""),
            "message": "A physical cape EEPROM was reported but it is not identified as a Hanson rPi-MFC; Colorlight is assumed.",
        }

    if _is_rpi_mfc_name(cape_name):
        return {
            "rpi_mfc_detected": False,
            "source": "virtual_rpi_mfc_only",
            "cape_name": cape_name,
            "cape_version": cape_version,
            "eeprom": str(cape.get("eeprom_location") or ""),
            "message": "FPP is configured for rPi-MFC via a virtual/non-physical cape identity, but no physical EEPROM was confirmed; Colorlight is assumed.",
        }

    return {
        "rpi_mfc_detected": False,
        "source": "no_physical_cape_eeprom",
        "cape_name": "",
        "message": "No physical Hanson rPi-MFC EEPROM was detected; Colorlight is assumed.",
    }
