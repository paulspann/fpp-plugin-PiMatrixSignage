from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

FPP_BASE = os.environ.get("PIMATRIX_FPP_BASE", "http://127.0.0.1").rstrip("/")
PLUGIN_REPO = "fpp-plugin-PiMatrixSignage"
PLATFORM_UPDATE_HELPER = Path("/usr/local/sbin/pi-matrix-signage-platform")
PLATFORM_UPDATE_STATUS = Path(os.environ.get(
    "PIMATRIX_PLATFORM_UPDATE_STATUS",
    "/home/fpp/media/pi-matrix-signage-data/platform-update.json",
))
INTERFACE_MODE_FILE = Path(os.environ.get(
    "PIMATRIX_INTERFACE_MODE_FILE",
    "/home/fpp/media/pi-matrix-signage-data/interface-mode",
))
APPLIANCE_ENABLED_CONF = Path(os.environ.get(
    "PIMATRIX_APPLIANCE_ENABLED_CONF",
    "/etc/apache2/conf-enabled/pi-matrix-signage-appliance.conf",
))


def _request_json(path: str, method: str = "GET", payload: Any | None = None, timeout: float = 5.0) -> Any:
    url = path if path.startswith("http://") or path.startswith("https://") else FPP_BASE + path
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace").strip()
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Controller platform returned HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Controller platform is not reachable: {exc.reason}") from exc


def _request_raw_json_file(path: str, payload: Any, timeout: float = 8.0) -> Any:
    """POST a JSON configuration file through FPP's configfile endpoint.

    FPP's own Channel Outputs page saves channeloutputs.json this way. Keeping
    the write behind FPP means its normal backup/reload hooks remain in charge.
    """
    url = FPP_BASE + path
    body = json.dumps(payload, indent=2, sort_keys=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace").strip()
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"raw": raw}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Controller platform rejected the configuration (HTTP {exc.code}): {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Controller platform is not reachable: {exc.reason}") from exc


def interface_mode_status() -> dict:
    mode = "fpp"
    try:
        stored = INTERFACE_MODE_FILE.read_text(encoding="utf-8").strip().lower()
        if stored in {"fpp", "appliance"}:
            mode = stored
    except Exception:
        # v0.6.43 migration fallback: an enabled Apache appliance config means
        # appliance mode was active before the persistent choice existed.
        if APPLIANCE_ENABLED_CONF.exists():
            mode = "appliance"
    actual = "appliance" if APPLIANCE_ENABLED_CONF.exists() else "fpp"
    return {
        "mode": mode,
        "actual_mode": actual,
        "in_sync": mode == actual,
        "helper_ready": PLATFORM_UPDATE_HELPER.is_file(),
        "label": "Pi Matrix Signage appliance" if mode == "appliance" else "FPP + Pi Matrix Signage add-on",
        "message": (
            "The controller home page opens Pi Matrix Signage; FPP remains available for engineering and recovery."
            if mode == "appliance"
            else "The controller home page opens FPP; Pi Matrix Signage remains available as an add-on and on port 8090."
        ),
    }


def set_interface_mode(mode: str) -> dict:
    mode = str(mode or "").strip().lower()
    if mode not in {"fpp", "appliance"}:
        raise ValueError("Interface mode must be fpp or appliance")
    if not PLATFORM_UPDATE_HELPER.is_file():
        raise RuntimeError("The controller platform helper is not installed yet. Install this release once before changing interface mode.")
    result = subprocess.run(
        ["sudo", "-n", str(PLATFORM_UPDATE_HELPER), "--interface-mode", mode],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Unable to change controller interface mode").strip())
    status = interface_mode_status()
    status["ok"] = True
    status["message"] = (result.stdout or status["message"]).strip()
    return status


def _read_platform_update_status() -> dict:
    try:
        data = json.loads(PLATFORM_UPDATE_STATUS.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def software_update_status(current_version: str, check: bool = False) -> dict:
    result = {
        "current_version": current_version,
        "available": False,
        "platform_ready": False,
        "helper_ready": PLATFORM_UPDATE_HELPER.is_file(),
        "status": _read_platform_update_status(),
        "message": "Controller platform not checked",
    }
    try:
        if check:
            plugin = _request_json(f"/api/plugin/{PLUGIN_REPO}/updates", method="POST", payload={}, timeout=20)
        else:
            plugin = _request_json(f"/api/plugin/{PLUGIN_REPO}", timeout=4)
        status = str(plugin.get("Status") or plugin.get("status") or "OK")
        if status.lower() not in {"ok", "success"}:
            raise RuntimeError(str(plugin.get("Message") or plugin.get("message") or status))
        result["platform_ready"] = True
        result["available"] = bool(int(plugin.get("updatesAvailable") or 0))
        result["message"] = "Update available" if result["available"] else "Pi Matrix Signage is up to date"
        result["plugin"] = {
            "name": str(plugin.get("name") or "Pi Matrix Signage"),
            "branch": str((plugin.get("versions") or [{}])[0].get("branch") or "") if isinstance(plugin.get("versions"), list) else "",
        }
    except Exception as exc:
        result["message"] = str(exc)
    return result


def start_software_update() -> dict:
    if not PLATFORM_UPDATE_HELPER.is_file():
        raise RuntimeError("The controller update helper is not installed yet. Install this release once before using managed updates.")
    status = _read_platform_update_status()
    if str(status.get("state") or "").lower() in {"queued", "checking", "installing", "restarting"}:
        raise RuntimeError("A software update is already in progress")
    result = subprocess.run(
        ["sudo", "-n", str(PLATFORM_UPDATE_HELPER), "--upgrade-plugin"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Unable to start managed update").strip())
    return {"ok": True, "message": (result.stdout or "Software update queued").strip()}


def _normalised_scan(settings: dict) -> int:
    raw = str(settings.get("panel_scan") or "1/16")
    try:
        return max(1, int(raw.split("/", 1)[1] if "/" in raw else raw))
    except Exception:
        return 16


def _load_current_channel_outputs() -> dict:
    try:
        data = _request_json("/api/configfile/channeloutputs.json", timeout=4)
        return data if isinstance(data, dict) else {"channelOutputs": []}
    except Exception:
        return {"channelOutputs": []}


def _cape_panel_profile() -> dict:
    """Return the one physical panel-cape profile FPP exposed, if any.

    FPP's own LED Panels page only applies a panel-cape profile automatically
    when exactly one profile is present under media/tmp/panels. We follow the
    same rule instead of guessing a Hanson pinout.
    """
    try:
        options = _request_json("/api/cape/panel", timeout=3)
        if not isinstance(options, list):
            return {}
        keys = [str(x) for x in options if str(x).strip() and str(x) != "--None--"]
        if len(keys) != 1:
            return {}
        key = urllib.parse.quote(keys[0], safe="")
        profile = _request_json(f"/api/cape/panel/{key}", timeout=3)
        if isinstance(profile, dict):
            profile = dict(profile)
            profile["_key"] = keys[0]
            return profile
    except Exception:
        pass
    return {}


def _existing_matrix(outputs: dict) -> dict:
    items = outputs.get("channelOutputs") if isinstance(outputs, dict) else None
    if not isinstance(items, list):
        return {}
    for item in items:
        if isinstance(item, dict) and item.get("type") == "LEDPanelMatrix":
            return dict(item)
    return {}


def _panel_mapping(settings: dict, output_type: str, existing: dict) -> list[dict]:
    across = max(1, int(settings.get("panels_across") or 1))
    down = max(1, int(settings.get("panels_down") or 1))
    pw = max(1, int(settings.get("panel_width") or 64))
    ph = max(1, int(settings.get("panel_height") or 32))
    colour = str(settings.get("color_order") or "RGB")
    count = across * down

    old = existing.get("panels") if isinstance(existing, dict) else None
    if isinstance(old, list) and len(old) == count and all(isinstance(p, dict) for p in old):
        # Keep field-tested physical output/chain/orientation mappings. Rebuild
        # only the logical offsets to reflect the dimensions in Pi Matrix.
        mapped = []
        for idx, source in enumerate(old):
            row = int(source.get("row", idx // across))
            col = int(source.get("col", idx % across))
            p = dict(source)
            p.update({
                "row": row,
                "col": col,
                "xOffset": col * pw,
                "yOffset": row * ph,
                "colorOrder": str(source.get("colorOrder") or colour),
            })
            mapped.append(p)
        return mapped

    panels: list[dict] = []
    for row in range(down):
        for col in range(across):
            if output_type == "adafruit_triple":
                output_number = col % 3
                panel_number = row + (col // 3) * down
            else:
                output_number = row
                panel_number = across - col - 1
            panels.append({
                "outputNumber": output_number,
                "panelNumber": panel_number,
                "colorOrder": colour,
                "orientation": "N",
                "xOffset": col * pw,
                "yOffset": row * ph,
                "row": row,
                "col": col,
            })
    return panels


def build_managed_output_config(settings: dict, detection: dict | None = None) -> tuple[dict, dict]:
    detection = detection or {}
    output_type = str(settings.get("panel_output_type") or "rpi_mfc")
    if output_type == "rpi_mfc" and not detection.get("rpi_mfc_detected"):
        output_type = "colorlight"

    current = _load_current_channel_outputs()
    existing = _existing_matrix(current)
    pw = max(8, int(settings.get("panel_width") or 64))
    ph = max(8, int(settings.get("panel_height") or 32))
    across = max(1, int(settings.get("panels_across") or 1))
    down = max(1, int(settings.get("panels_down") or 1))
    width = pw * across
    height = ph * down
    scan = _normalised_scan(settings)
    channels = width * height * 3
    colour = str(settings.get("color_order") or "RGB")
    brightness = max(0, min(100, int(settings.get("brightness") or 60)))

    matrix = dict(existing)
    matrix.update({
        "cfgVersion": 3,
        "type": "LEDPanelMatrix",
        "advanced": 0,
        "LEDPanelUIFrontView": False,
        "panelMatrixID": int(existing.get("panelMatrixID") or 1),
        "enabled": 1,
        "startChannel": 1,
        "channelCount": channels,
        "colorOrder": colour,
        "gamma": str(existing.get("gamma") or "2.2"),
        "brightness": brightness,
        "LEDPanelMatrixName": "Pi Matrix Signage",
        "LEDPanelRows": down,
        "LEDPanelCols": across,
        "ledPanelsLayout": f"{across}x{down}",
        "ledPanelsWidth": pw,
        "ledPanelsHeight": ph,
        "ledPanelsScan": scan,
        "ledPanelsSize": f"{pw}x{ph}x{scan}",
        "panelWidth": pw,
        "panelHeight": ph,
        "panelScan": scan,
        "panelColorDepth": int(existing.get("panelColorDepth") or 8),
        "invertedData": int(existing.get("invertedData") or 0),
        "panelOutputOrder": bool(existing.get("panelOutputOrder", False)),
        "panelOutputBlankRow": bool(existing.get("panelOutputBlankRow", False)),
        "cpuPWM": bool(existing.get("cpuPWM", False)),
        "panelRowAddressType": int(existing.get("panelRowAddressType") or 0),
        "panelType": int(existing.get("panelType") or 0),
        "panelInterleave": str(existing.get("panelInterleave") or "0"),
        "LEDPanelCanvasUIPixelsHigh": int(existing.get("LEDPanelCanvasUIPixelsHigh") or max(192, height)),
        "LEDPanelCanvasUIPixelsWide": int(existing.get("LEDPanelCanvasUIPixelsWide") or max(128, width)),
    })

    engineering: dict[str, Any] = {"managed_output_type": output_type, "used_existing_mapping": bool(existing.get("panels"))}
    if output_type == "colorlight":
        matrix.update({
            "subType": "ColorLight5a75",
            "interface": str(settings.get("colorlight_interface") or "eth1"),
            "firmwareVersion": int(existing.get("firmwareVersion") or 0),
            "linkCheck": int(existing.get("linkCheck", 1)),
            "ledPanelsOutputs": 24,
            "ledPanelsPanelsPerOutput": int(existing.get("ledPanelsPanelsPerOutput") or 24),
            "maxLEDPanels": int(existing.get("maxLEDPanels") or 96),
        })
        matrix.pop("wiringPinout", None)
        matrix.pop("gpioSlowdown", None)
    else:
        matrix["subType"] = "RGBMatrix"
        matrix["gpioSlowdown"] = int(existing.get("gpioSlowdown") or 1)
        if output_type == "adafruit_hat":
            matrix["wiringPinout"] = "adafruit-hat"
            matrix["ledPanelsOutputs"] = 1
            matrix["ledPanelsPanelsPerOutput"] = 1
            matrix["maxLEDPanels"] = 1
        elif output_type == "adafruit_triple":
            matrix["wiringPinout"] = "regular"
            matrix["ledPanelsOutputs"] = 3
            matrix["ledPanelsPanelsPerOutput"] = max(1, down)
            matrix["maxLEDPanels"] = max(3, across * down)
        else:  # Hanson rPi-MFC
            cape = _cape_panel_profile()
            if cape.get("driver"):
                matrix["subType"] = str(cape["driver"])
                engineering["cape_panel_profile"] = str(cape.get("_key") or cape.get("name") or "detected")
            elif existing.get("subType"):
                matrix["subType"] = str(existing["subType"])
            if cape.get("name"):
                matrix["configName"] = str(cape["name"])
            elif existing.get("configName"):
                matrix["configName"] = str(existing["configName"])
            # Do not invent a Hanson wiring pinout. A physical rPi-MFC EEPROM
            # can supply the FPP panel-cape driver; an already commissioned box
            # can also retain its saved subtype/configName.
            if not cape.get("driver") and not existing.get("subType"):
                raise RuntimeError("The Hanson board is detected, but its FPP panel-cape profile is not available yet. Reboot once so the controller platform can load the physical cape profile, then try Apply again.")
            matrix["ledPanelsOutputs"] = int(existing.get("ledPanelsOutputs") or max(1, down))
            matrix["ledPanelsPanelsPerOutput"] = int(existing.get("ledPanelsPanelsPerOutput") or across)
            matrix["maxLEDPanels"] = int(existing.get("maxLEDPanels") or max(9, across * down))

    matrix["panels"] = _panel_mapping(settings, output_type, existing)

    # Preserve unrelated FPP channel outputs. Pi Matrix owns one LEDPanelMatrix.
    unrelated = []
    for item in current.get("channelOutputs", []) if isinstance(current, dict) else []:
        if isinstance(item, dict) and item.get("type") != "LEDPanelMatrix":
            unrelated.append(item)
    config = {"channelOutputs": unrelated + [matrix]}
    engineering["matrix"] = matrix
    return config, engineering


def _normalise_for_compare(value: Any) -> Any:
    if isinstance(value, dict):
        ignored = {"LEDPanelCanvasUIPixelsHigh", "LEDPanelCanvasUIPixelsWide"}
        return {k: _normalise_for_compare(v) for k, v in sorted(value.items()) if k not in ignored}
    if isinstance(value, list):
        return [_normalise_for_compare(v) for v in value]
    return value


def output_status(settings: dict, detection: dict | None = None, ddp_port: int = 4048) -> dict:
    result: dict[str, Any] = {
        "ok": False,
        "configured": False,
        "input_ready": False,
        "output_ready": False,
        "can_apply": True,
        "message": "Checking panel output service",
        "engineering": {},
    }
    try:
        desired, engineering = build_managed_output_config(settings, detection)
        current = _load_current_channel_outputs()
        desired_matrix = _existing_matrix(desired)
        current_matrix = _existing_matrix(current)
        keys = (
            "type", "subType", "enabled", "panelWidth", "panelHeight", "panelScan",
            "LEDPanelRows", "LEDPanelCols", "ledPanelsLayout", "channelCount",
            "brightness", "colorOrder", "wiringPinout", "interface", "panels",
        )
        def compact(matrix: dict) -> dict:
            return {k: matrix.get(k) for k in keys if k in matrix}
        output_ready = bool(current_matrix) and _normalise_for_compare(compact(current_matrix)) == _normalise_for_compare(compact(desired_matrix))
        input_ready = False
        try:
            inp = _request_json("/api/channel/output/universeInputs", timeout=3)
            entries = inp.get("channelInputs") if isinstance(inp, dict) else None
            input_ready = bool(isinstance(entries, list) and any(isinstance(x, dict) and x.get("type") == "universes" and int(x.get("enabled") or 0) == 1 for x in entries))
        except Exception:
            pass
        result.update({
            "configured": output_ready and input_ready,
            "input_ready": input_ready,
            "output_ready": output_ready,
            "ok": output_ready and input_ready,
            "message": "Panel output service is configured" if output_ready and input_ready else "Panel controller configuration needs applying",
            "engineering": {
                **engineering,
                "ddp_port": int(ddp_port),
                "ddp_destination": f"127.0.0.1:{int(ddp_port)}",
                "channel_count": int(desired_matrix.get("channelCount") or 0),
                "start_channel": 1,
                "input_configured": input_ready,
                "output_matches": output_ready,
            },
        })
    except Exception as exc:
        result["can_apply"] = False
        result["message"] = str(exc)
    return result


def apply_output(settings: dict, detection: dict | None = None, ddp_port: int = 4048) -> dict:
    desired, engineering = build_managed_output_config(settings, detection)
    _request_raw_json_file("/api/configfile/channeloutputs.json", desired, timeout=12)

    # Pi Matrix sends DDP to localhost. FPP's DDP input does not require a
    # universe row; enabling the universes input with an empty row list is the
    # same shape its own Channel Inputs page writes.
    input_config = {
        "channelInputs": [{
            "type": "universes",
            "enabled": 1,
            "timeout": 1000,
            "startChannel": 1,
            "channelCount": -1,
            "universes": [],
        }]
    }
    _request_json("/api/channel/output/universeInputs", method="POST", payload=input_config, timeout=12)
    time.sleep(0.15)
    status = output_status(settings, detection, ddp_port)
    if not status.get("output_ready"):
        # Some FPP releases reload asynchronously. The save still succeeded;
        # report that honestly and let the next refresh settle the status.
        status["message"] = "Panel controller configuration saved; output service is reloading"
    else:
        status["message"] = "Panel controller configuration applied"
    status["engineering"] = {**status.get("engineering", {}), **engineering}
    return status
