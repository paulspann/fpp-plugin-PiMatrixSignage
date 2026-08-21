from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
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
SOFTWARE_UPDATE_CACHE = Path(os.environ.get(
    "PIMATRIX_SOFTWARE_UPDATE_CACHE",
    "/home/fpp/media/pi-matrix-signage-data/software-update-cache.json",
))
PLUGIN_DIR = Path(os.environ.get(
    "PIMATRIX_FPP_PLUGIN_DIR",
    f"/home/fpp/media/plugins/{PLUGIN_REPO}",
))
UPDATE_CHECK_INTERVAL_SECONDS = max(900, int(os.environ.get("PIMATRIX_UPDATE_CHECK_INTERVAL", "21600")))
UPDATE_CHECK_INITIAL_DELAY_SECONDS = max(0, int(os.environ.get("PIMATRIX_UPDATE_CHECK_INITIAL_DELAY", "8")))
CERTIFICATION_FILE = Path(__file__).resolve().parent / "controller-platform-certification.json"
FIRST_RUN_PENDING = Path(os.environ.get(
    "PIMATRIX_FIRST_RUN_PENDING",
    "/home/fpp/media/pi-matrix-signage-data/first-run-interface-choice.pending",
))
FIRST_RUN_COMPLETE = Path(os.environ.get(
    "PIMATRIX_FIRST_RUN_COMPLETE",
    "/home/fpp/media/pi-matrix-signage-data/first-run-interface-choice.complete",
))

_update_cache_lock = threading.RLock()
_update_cache_memory: dict[str, Any] | None = None
_update_monitor_thread: threading.Thread | None = None
_update_monitor_stop = threading.Event()


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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_software_update_cache() -> dict:
    global _update_cache_memory
    with _update_cache_lock:
        if isinstance(_update_cache_memory, dict):
            return dict(_update_cache_memory)
        try:
            data = json.loads(SOFTWARE_UPDATE_CACHE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _update_cache_memory = dict(data)
                return dict(data)
        except Exception:
            pass
        _update_cache_memory = {}
        return {}


def _write_software_update_cache(data: dict) -> None:
    global _update_cache_memory
    clean = dict(data or {})
    with _update_cache_lock:
        _update_cache_memory = clean
        try:
            SOFTWARE_UPDATE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            temp = SOFTWARE_UPDATE_CACHE.with_name(SOFTWARE_UPDATE_CACHE.name + ".tmp")
            temp.write_text(json.dumps(clean, indent=2, sort_keys=True), encoding="utf-8")
            temp.replace(SOFTWARE_UPDATE_CACHE)
        except Exception:
            # The in-memory cache remains useful even on development/test hosts
            # where /home/fpp does not exist or is intentionally read-only.
            pass


def _remote_plugin_version(branch: str) -> str:
    branch = str(branch or "").strip()
    if not branch or not PLUGIN_DIR.is_dir():
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", str(PLUGIN_DIR), "show", f"origin/{branch}:payload/PiMatrixSignage/VERSION"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if result.returncode == 0:
            value = (result.stdout or "").strip().splitlines()[0].strip()
            if value and len(value) <= 32:
                return value
    except Exception:
        pass
    return ""


def _perform_software_update_check(current_version: str) -> dict:
    checked_at = _utc_now_iso()
    base = {
        "current_version": current_version,
        "available": False,
        "platform_ready": False,
        "helper_ready": PLATFORM_UPDATE_HELPER.is_file(),
        "checked_at": checked_at,
        "latest_version": "",
        "message": "Unable to check for Pi Matrix Signage updates",
    }
    try:
        plugin = _request_json(f"/api/plugin/{PLUGIN_REPO}/updates", method="POST", payload={}, timeout=20)
        status = str(plugin.get("Status") or plugin.get("status") or "OK")
        if status.lower() not in {"ok", "success"}:
            raise RuntimeError(str(plugin.get("Message") or plugin.get("message") or status))
        versions = plugin.get("versions") if isinstance(plugin.get("versions"), list) else []
        branch = str((versions or [{}])[0].get("branch") or "") if versions else ""
        base["platform_ready"] = True
        base["available"] = bool(int(plugin.get("updatesAvailable") or 0))
        base["latest_version"] = _remote_plugin_version(branch) if base["available"] else current_version
        if base["available"]:
            suffix = f" v{base['latest_version']}" if base["latest_version"] else ""
            base["message"] = f"Pi Matrix Signage{suffix} is available"
        else:
            base["message"] = "Pi Matrix Signage is up to date"
        base["plugin"] = {
            "name": str(plugin.get("name") or "Pi Matrix Signage"),
            "branch": branch,
        }
    except Exception as exc:
        base["message"] = str(exc)
    _write_software_update_cache(base)
    return base


def _perform_combined_update_check(current_version: str) -> dict:
    base = _perform_software_update_check(current_version)
    try:
        base["controller_platform"] = controller_platform_update_status()
    except Exception as exc:
        base["controller_platform"] = {"reachable": False, "update_available": False, "message": str(exc)}
    _write_software_update_cache(base)
    return base


def software_update_cached_status(current_version: str) -> dict:
    cached = _read_software_update_cache()
    result = {
        "current_version": current_version,
        "available": bool(cached.get("available")),
        "platform_ready": bool(cached.get("platform_ready")),
        "helper_ready": PLATFORM_UPDATE_HELPER.is_file(),
        "checked_at": str(cached.get("checked_at") or ""),
        "latest_version": str(cached.get("latest_version") or ""),
        "message": str(cached.get("message") or "Update check pending"),
        "status": _read_platform_update_status(),
    }
    if isinstance(cached.get("plugin"), dict):
        result["plugin"] = dict(cached["plugin"])
    if isinstance(cached.get("controller_platform"), dict):
        result["controller_platform"] = dict(cached["controller_platform"])
    else:
        result["controller_platform"] = {"update_available": False, "message": "Controller platform check pending"}
    # A cache written by an older installed version is safe as a freshness hint,
    # but its 'up to date' conclusion must not be presented as belonging to a
    # newly upgraded application before the background worker checks again.
    if cached.get("current_version") and str(cached.get("current_version")) != str(current_version):
        result["available"] = False
        result["platform_ready"] = False
        result["message"] = "Update check pending for this version"
        platform = dict(result.get("controller_platform") or {})
        platform["update_available"] = False
        platform["message"] = "Controller platform check pending for this Pi Matrix version"
        result["controller_platform"] = platform
    return result


def software_update_status(current_version: str, check: bool = False) -> dict:
    if check:
        checked = _perform_combined_update_check(current_version)
        result = dict(checked)
        result["helper_ready"] = PLATFORM_UPDATE_HELPER.is_file()
        result["status"] = _read_platform_update_status()
        return result
    return software_update_cached_status(current_version)


def start_software_update_monitor(current_version: str, logger: Any | None = None) -> None:
    global _update_monitor_thread
    if _update_monitor_thread and _update_monitor_thread.is_alive():
        return
    _update_monitor_stop.clear()

    def worker() -> None:
        if _update_monitor_stop.wait(UPDATE_CHECK_INITIAL_DELAY_SECONDS):
            return
        while not _update_monitor_stop.is_set():
            result: dict[str, Any] = {}
            try:
                result = _perform_combined_update_check(current_version)
                if logger:
                    if result.get("available"):
                        logger.info("Pi Matrix Signage software update available%s", f": v{result.get('latest_version')}" if result.get("latest_version") else "")
                    elif result.get("platform_ready"):
                        logger.info("Pi Matrix Signage background software update check: up to date")
                    else:
                        logger.warning("Pi Matrix Signage background software update check failed: %s", result.get("message"))
            except Exception as exc:
                if logger:
                    logger.warning("Pi Matrix Signage background software update check failed: %s", exc)
            wait_seconds = UPDATE_CHECK_INTERVAL_SECONDS if result.get("platform_ready") else min(300, UPDATE_CHECK_INTERVAL_SECONDS)
            if _update_monitor_stop.wait(wait_seconds):
                break

    _update_monitor_thread = threading.Thread(target=worker, name="PiMatrixUpdateCheck", daemon=True)
    _update_monitor_thread.start()


def stop_software_update_monitor() -> None:
    global _update_monitor_thread
    _update_monitor_stop.set()
    thread = _update_monitor_thread
    if thread and thread.is_alive():
        thread.join(timeout=2.0)
    _update_monitor_thread = None



def first_run_interface_choice_pending() -> bool:
    return FIRST_RUN_PENDING.exists() and not FIRST_RUN_COMPLETE.exists()


def complete_first_run_interface_choice() -> None:
    try:
        FIRST_RUN_COMPLETE.parent.mkdir(parents=True, exist_ok=True)
        FIRST_RUN_COMPLETE.write_text(_utc_now_iso() + "\n", encoding="utf-8")
        try:
            FIRST_RUN_PENDING.unlink()
        except FileNotFoundError:
            pass
    except Exception as exc:
        raise RuntimeError(f"Unable to record first-run setup completion: {exc}") from exc


def _certification() -> dict:
    try:
        data = json.loads(CERTIFICATION_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _platform_runtime_info() -> dict:
    info = {"reachable": False, "fppd_running": False, "version": "unknown", "raw": {}}
    try:
        payload = _request_json("/api/system/status", timeout=4)
        if not isinstance(payload, dict):
            return info
        info["reachable"] = True
        info["raw"] = payload
        advanced = payload.get("advancedView") if isinstance(payload.get("advancedView"), dict) else {}
        version = (payload.get("version") or payload.get("fppVersion") or payload.get("fpp_version")
                   or advanced.get("Version") or advanced.get("version") or "unknown")
        info["version"] = str(version)
        fppd = str(payload.get("fppd") or advanced.get("fppd") or payload.get("status_name") or "").lower()
        info["fppd_running"] = fppd in {"running", "active"} or bool(payload.get("status") is not None and fppd == "")
    except Exception as exc:
        info["error"] = str(exc)
    return info


def _version_key(value: str) -> tuple | None:
    raw = str(value or "").strip().lower().replace("fpp", "").strip()
    raw = raw.lstrip("v")
    m = __import__("re").search(r"(\d+)\.(?:(\d+)|x)(?:\.(\d+))?(?:[-._]?(alpha|beta|rc)(\d*)?)?", raw)
    if not m:
        return None
    major = int(m.group(1)); minor = int(m.group(2)) if m.group(2) is not None else 10**6; patch = int(m.group(3) or 0)
    stage = {None: 3, "alpha": 0, "beta": 1, "rc": 2}.get(m.group(4), 3)
    stage_num = int(m.group(5) or 0)
    return (major, minor, patch, stage, stage_num)


def _version_matches(installed: str, target: str) -> bool:
    a = _version_key(installed); b = _version_key(target)
    return bool(a and b and a == b)


def _platform_release_candidate(certified_release: str) -> dict:
    try:
        releases = _request_json("/api/git/releases/os", timeout=20)
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    if not isinstance(releases, dict) or str(releases.get("status") or "").lower() != "ok":
        return {"available": False, "error": str((releases or {}).get("message") or "Controller platform release list unavailable")}
    target = str(certified_release or "").strip().lower().lstrip("v")
    candidates = []
    for row in releases.get("files") or []:
        if not isinstance(row, dict):
            continue
        tag = str(row.get("tag") or "").strip().lower().lstrip("v")
        filename = str(row.get("filename") or "")
        # The managed updater is deliberately exact: a beta3 certification must
        # never be satisfied by beta30, a nightly, or a merely similar filename.
        if tag != target:
            continue
        url = str(row.get("url") or "")
        if filename.lower().endswith(".fppos") and url.startswith("https://github.com/FalconChristmas/fpp/releases/download/"):
            candidates.append(dict(row))
    if not candidates:
        return {"available": False, "error": f"Certified FPP {certified_release} image is not currently offered for this controller"}
    candidates.sort(key=lambda r: (not bool(r.get("downloaded")), int(r.get("size") or 0)))
    out = dict(candidates[0]); out["available"] = True
    return out


def _write_platform_update_status(data: dict) -> None:
    current = _read_platform_update_status()
    current.update(data)
    try:
        PLATFORM_UPDATE_STATUS.parent.mkdir(parents=True, exist_ok=True)
        tmp = PLATFORM_UPDATE_STATUS.with_name(PLATFORM_UPDATE_STATUS.name + ".tmp")
        tmp.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(PLATFORM_UPDATE_STATUS)
    except Exception:
        pass


def _reconcile_platform_update_status(installed_version: str) -> dict:
    status = _read_platform_update_status()
    if str(status.get("kind") or "") != "platform":
        return status
    state = str(status.get("state") or "").lower()
    target = str(status.get("target_version") or "")
    if state in {"queued", "installing", "restarting"} and target and _version_matches(installed_version, target):
        status.update({"state": "completed", "completed": True, "message": f"Controller platform updated to FPP {target}", "updated_at": _utc_now_iso()})
        _write_platform_update_status(status)
    return status


def controller_platform_update_status() -> dict:
    cert = _certification()
    runtime = _platform_runtime_info()
    installed = str(runtime.get("version") or "unknown")
    target = str(cert.get("certified_release") or "")
    cert_for = str(cert.get("pimatrix_version") or "")
    certification_valid = bool(target and cert_for and cert_for == str(_read_app_version()))
    status_file = _reconcile_platform_update_status(installed)
    result = {
        "platform_name": str(cert.get("platform_name") or "Falcon Player (FPP)"),
        "installed_version": installed,
        "certified_version": target,
        "certification_for": cert_for,
        "certification_valid": certification_valid,
        "reachable": bool(runtime.get("reachable")),
        "fppd_running": bool(runtime.get("fppd_running")),
        "certified": bool(certification_valid and _version_matches(installed, target)),
        "update_available": False,
        "candidate": {},
        "status": status_file if str(status_file.get("kind") or "") == "platform" else {},
        "message": "Controller platform certification unavailable",
    }
    if not runtime.get("reachable"):
        result["message"] = str(runtime.get("error") or "Controller platform is not reachable")
        return result
    if not certification_valid:
        result["message"] = "This Pi Matrix release does not contain a matching controller-platform certification"
        return result
    if result["certified"]:
        result["message"] = f"FPP {target} is the certified controller platform for this Pi Matrix release"
        return result
    ik = _version_key(installed); tk = _version_key(target)
    if ik and tk and ik > tk:
        result["message"] = f"FPP {installed} is newer than the certified target {target}; managed downgrade is disabled"
        return result
    candidate = _platform_release_candidate(target)
    result["candidate"] = {k: candidate.get(k) for k in ("tag", "filename", "url", "size", "downloaded") if candidate.get(k) is not None}
    if candidate.get("available") and ik and tk and ik < tk:
        result["update_available"] = True
        result["message"] = f"ISSL-certified controller platform FPP {target} is available"
    elif candidate.get("error"):
        result["message"] = str(candidate["error"])
    else:
        result["message"] = f"Installed FPP {installed} does not match certified target {target}"
    return result


def _read_app_version() -> str:
    try:
        return (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def controller_health(settings: dict, detection: dict | None = None, ddp_port: int = 4048) -> dict:
    runtime = _platform_runtime_info()
    out = output_status(settings, detection, ddp_port)
    mode = interface_mode_status()
    host = str(settings.get("ddp_host") or "127.0.0.1").strip().lower()
    port = int(settings.get("ddp_port") or 4048)
    offset = int(settings.get("ddp_offset") or 0)
    local_target = host in {"127.0.0.1", "localhost", "::1"} and port == 4048 and offset == 0
    checks = [
        {"id": "platform_api", "label": "Controller platform", "ok": bool(runtime.get("reachable")), "detail": runtime.get("version") if runtime.get("reachable") else runtime.get("error", "Not reachable"), "repairable": False},
        {"id": "fppd", "label": "Panel output service", "ok": bool(runtime.get("fppd_running")), "detail": "Running" if runtime.get("fppd_running") else "Not confirmed running", "repairable": False},
        {"id": "ddp_target", "label": "Pi Matrix frame target", "ok": local_target, "detail": f"{host}:{port} · offset {offset}", "repairable": True},
        {"id": "ddp_input", "label": "Controller DDP input", "ok": bool(out.get("input_ready")), "detail": "Enabled" if out.get("input_ready") else "Missing or disabled", "repairable": True},
        {"id": "panel_output", "label": "Panel output configuration", "ok": bool(out.get("output_ready")), "detail": "Matches Pi Matrix" if out.get("output_ready") else "Configuration drift detected", "repairable": bool(out.get("can_apply", True))},
        {"id": "interface_mode", "label": "Controller interface mode", "ok": bool(mode.get("in_sync")), "detail": mode.get("label") if mode.get("in_sync") else f"Stored {mode.get('mode')} / active {mode.get('actual_mode')}", "repairable": bool(mode.get("helper_ready"))},
    ]
    critical = [c for c in checks if c["id"] != "interface_mode"]
    healthy = all(bool(c.get("ok")) for c in critical)
    drifted = any(not bool(c.get("ok")) and bool(c.get("repairable")) for c in checks)
    return {
        "healthy": healthy,
        "drifted": drifted,
        "repairable": drifted and bool(runtime.get("reachable")),
        "checks": checks,
        "output": out,
        "interface_mode": mode,
        "platform": software_update_cached_status(_read_app_version()).get("controller_platform", {}),
        "message": "Controller platform and panel output are healthy" if healthy and not drifted else ("Controller configuration drift detected" if drifted else "Controller platform needs attention"),
    }


def start_controller_platform_update(candidate: dict, backup_filename: str) -> dict:
    if not PLATFORM_UPDATE_HELPER.is_file():
        raise RuntimeError("The controller platform helper is not installed yet")
    target = str(candidate.get("tag") or "").strip()
    url = str(candidate.get("url") or "").strip()
    filename = str(candidate.get("filename") or "").strip()
    cert = _certification()
    expected = str(cert.get("certified_release") or "").strip()
    if target.lstrip("v") != expected.lstrip("v"):
        raise RuntimeError("The selected controller-platform image is not the certified target for this Pi Matrix release")
    if not filename.lower().endswith(".fppos") or not url.startswith("https://github.com/FalconChristmas/fpp/releases/download/"):
        raise RuntimeError("The certified controller-platform image URL was not recognised")
    status = _read_platform_update_status()
    if str(status.get("state") or "").lower() in {"queued", "checking", "installing", "restarting"}:
        raise RuntimeError("A managed software update is already in progress")
    result = subprocess.run(
        ["sudo", "-n", str(PLATFORM_UPDATE_HELPER), "--upgrade-platform", expected, url, filename, str(backup_filename or "")],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Unable to start controller-platform update").strip())
    return {"ok": True, "target_version": expected, "backup_filename": backup_filename, "message": (result.stdout or f"Controller platform update to FPP {expected} queued").strip()}


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
