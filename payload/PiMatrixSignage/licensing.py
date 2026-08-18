from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import platform
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
except Exception:  # pragma: no cover - handled at runtime with a clear configuration error
    InvalidSignature = Exception
    hashes = serialization = padding = None

LOG = logging.getLogger("pimatrix.licensing")

SCHEMA_VERSION = 1
DEFAULT_CHECK_INTERVAL_HOURS = 24 * 7
DEFAULT_GRACE_DAYS = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _read_text(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def _cpu_serial() -> str:
    text = _read_text("/proc/cpuinfo")
    for line in text.splitlines():
        if line.lower().startswith("serial") and ":" in line:
            value = line.split(":", 1)[1].strip()
            if value:
                return value
    return ""


def _machine_id() -> str:
    return _read_text("/etc/machine-id") or _read_text("/var/lib/dbus/machine-id")


def device_identity() -> dict[str, str]:
    """Return a stable, privacy-minimised identity for binding one licence to one controller.

    Raspberry Pi serial is preferred.  A machine-id fallback keeps development/test systems usable.
    Only the hashed public Device ID is sent to the licensing service by default.
    """
    serial = _cpu_serial()
    machine_id = _machine_id()
    if serial:
        material = "pi-serial:" + serial
        source = "Raspberry Pi serial"
    elif machine_id:
        material = "machine-id:" + machine_id
        source = "machine ID"
    else:
        material = "host:" + socket.gethostname() + "|" + platform.machine()
        source = "host fallback"
    digest = hashlib.sha256(("PiMatrixSignage/device/v1|" + material).encode("utf-8")).hexdigest().upper()
    device_id = "PMS-" + "-".join((digest[0:8], digest[8:16], digest[16:24], digest[24:32]))
    return {
        "device_id": device_id,
        "source": source,
        "hostname": socket.gethostname(),
        "platform": platform.machine() or "unknown",
    }


def _mask_key(key: str) -> str:
    key = str(key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * max(4, len(key))
    return key[:4] + "…" + key[-4:]


class LicenseError(RuntimeError):
    pass


class LicenseManager:
    """Commercial licence state with WHMCS-backed signed entitlements.

    The Raspberry Pi never needs the WHMCS licensing secret or signing private key.
    The WHMCS bridge returns a JSON entitlement plus an RSA/SHA-256 signature.  The
    public key on the Pi verifies the response before it can enable LED output.
    """

    def __init__(self, data_dir: str | Path, app_version: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.app_version = str(app_version)
        self.mode = str(os.environ.get("PIMATRIX_LICENSE_MODE", "development") or "development").strip().lower()
        if self.mode not in {"development", "whmcs"}:
            self.mode = "development"
        self.endpoint = str(os.environ.get("PIMATRIX_LICENSE_ENDPOINT", "https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/api.php") or "").strip()
        self.public_key_url = str(os.environ.get("PIMATRIX_LICENSE_PUBLIC_KEY_URL", "https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/public-key.php") or "").strip()
        self.public_key_path = Path(os.environ.get("PIMATRIX_LICENSE_PUBLIC_KEY", str(self.data_dir / "license-public.pem")))
        self.prefix = str(os.environ.get("PIMATRIX_LICENSE_PREFIX", "PMS-") or "").strip()
        try:
            self.check_interval_hours = max(1, int(os.environ.get("PIMATRIX_LICENSE_CHECK_HOURS", DEFAULT_CHECK_INTERVAL_HOURS)))
        except Exception:
            self.check_interval_hours = DEFAULT_CHECK_INTERVAL_HOURS
        try:
            self.grace_days = max(1, int(os.environ.get("PIMATRIX_LICENSE_GRACE_DAYS", DEFAULT_GRACE_DAYS)))
        except Exception:
            self.grace_days = DEFAULT_GRACE_DAYS
        self.state_path = self.data_dir / "license-state.json"
        self.identity = device_identity()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = self._load_state()
        self._last_remote_attempt = 0.0

    def _load_state(self) -> dict:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _save_state(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.state_path)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="PiMatrixLicense", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        # Do not block app startup. A controller with an installed key reports a
        # newly installed app version shortly after restart, even when its cached
        # entitlement is still within the normal online-validity window.
        if self._stop.wait(4):
            return
        while not self._stop.is_set():
            try:
                if self._version_refresh_due() or (self.mode == "whmcs" and self._should_refresh()):
                    self.check_now(silent=True)
            except Exception as exc:
                LOG.warning("Licence background refresh failed: %s", exc)
            self._stop.wait(60 * 30)

    def _version_refresh_due(self) -> bool:
        """Return true when an installed key has not reported this app version."""
        with self._lock:
            key_installed = bool(str(self._state.get("license_key") or "").strip())
            reported = str(self._state.get("reported_app_version") or "")
            return key_installed and reported != self.app_version

    def _download_public_key(self, force: bool = False) -> None:
        if serialization is None:
            raise LicenseError("Python cryptography support is not installed")
        if self.public_key_path.is_file() and not force:
            return
        if not self.public_key_url:
            raise LicenseError(f"Licence public key is not installed: {self.public_key_path}")
        if not self.public_key_url.lower().startswith("https://") and os.environ.get("PIMATRIX_LICENSE_ALLOW_HTTP", "0") != "1":
            raise LicenseError("Licence public-key URL must use HTTPS")
        req = urllib.request.Request(
            self.public_key_url,
            headers={"Accept": "application/x-pem-file,text/plain", "User-Agent": f"PiMatrixSignage/{self.app_version}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                pem = response.read(128 * 1024)
        except urllib.error.HTTPError as exc:
            raise LicenseError(f"WHMCS public-key endpoint returned HTTP {exc.code}") from exc
        except Exception as exc:
            raise LicenseError(f"Unable to download WHMCS signing public key: {exc}") from exc
        try:
            serialization.load_pem_public_key(pem)
        except Exception as exc:
            raise LicenseError("WHMCS public-key endpoint returned an invalid public key") from exc
        self.public_key_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.public_key_path.with_suffix(self.public_key_path.suffix + ".tmp")
        tmp.write_bytes(pem)
        os.chmod(tmp, 0o644)
        os.replace(tmp, self.public_key_path)
        LOG.info("Installed WHMCS signing public key from %s", self.public_key_url)

    def _public_key(self):
        if serialization is None:
            raise LicenseError("Python cryptography support is not installed")
        if not self.public_key_path.is_file():
            self._download_public_key()
        try:
            return serialization.load_pem_public_key(self.public_key_path.read_bytes())
        except Exception as exc:
            raise LicenseError("Licence public key is invalid") from exc

    def _verify_signed_entitlement(self, entitlement_b64: str, signature_b64: str) -> dict:
        try:
            payload = base64.b64decode(str(entitlement_b64), validate=True)
            signature = base64.b64decode(str(signature_b64), validate=True)
        except Exception as exc:
            raise LicenseError("Licensing server returned invalid signed data") from exc
        try:
            self._public_key().verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature as first_exc:
            # A WHMCS addon reinstall/key rotation can legitimately replace the signing
            # key. Refresh it over HTTPS once and retry rather than permanently bricking
            # an already-installed controller.
            if not self.public_key_url:
                raise LicenseError("Licensing server signature verification failed") from first_exc
            try:
                self._download_public_key(force=True)
                self._public_key().verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
            except Exception as exc:
                raise LicenseError("Licensing server signature verification failed") from exc
        except LicenseError:
            raise
        except Exception as exc:
            raise LicenseError("Unable to verify licensing server signature") from exc
        try:
            entitlement = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise LicenseError("Licensing server entitlement is not valid JSON") from exc
        if not isinstance(entitlement, dict) or int(entitlement.get("schema") or 0) != SCHEMA_VERSION:
            raise LicenseError("Licensing server entitlement schema is unsupported")
        return entitlement

    def _validate_entitlement(self, entitlement: dict, license_key: str) -> tuple[bool, str]:
        status = str(entitlement.get("status") or "").strip()
        if str(entitlement.get("device_id") or "") != self.identity["device_id"]:
            return False, "Licence is bound to a different controller"
        expected_hash = hashlib.sha256(str(license_key or "").strip().encode("utf-8")).hexdigest()
        if str(entitlement.get("license_key_hash") or "").lower() != expected_hash.lower():
            return False, "Licence entitlement does not match this licence key"
        if status.lower() != "active":
            return False, f"WHMCS licence status is {status or 'invalid'}"
        grace_until = _parse_time(entitlement.get("grace_until"))
        if not grace_until or _utcnow() > grace_until:
            return False, "Licence verification grace period has expired"
        return True, ""

    def _current_entitlement(self) -> dict:
        raw = self._state.get("signed_entitlement")
        if not isinstance(raw, dict):
            return {}
        b64 = str(raw.get("entitlement_b64") or "")
        sig = str(raw.get("signature") or "")
        if not b64 or not sig:
            return {}
        try:
            return self._verify_signed_entitlement(b64, sig)
        except Exception as exc:
            LOG.warning("Stored licence entitlement rejected: %s", exc)
            return {}

    def is_licensed(self) -> bool:
        if self.mode != "whmcs":
            return True
        with self._lock:
            key = str(self._state.get("license_key") or "").strip()
            if not key:
                return False
            entitlement = self._current_entitlement()
            if not entitlement:
                return False
            ok, _ = self._validate_entitlement(entitlement, key)
            return ok

    def _should_refresh(self) -> bool:
        if self.mode != "whmcs":
            return False
        key = str(self._state.get("license_key") or "").strip()
        if not key:
            return False
        entitlement = self._current_entitlement()
        if not entitlement:
            return True
        valid_until = _parse_time(entitlement.get("valid_until"))
        if not valid_until:
            return True
        # Refresh before the signed online-validity window actually expires.
        return _utcnow().timestamp() >= valid_until.timestamp() - 60 * 60

    def _remote(self, license_key: str) -> dict:
        if not self.endpoint:
            raise LicenseError("WHMCS licence endpoint is not configured")
        if not self.endpoint.lower().startswith("https://") and os.environ.get("PIMATRIX_LICENSE_ALLOW_HTTP", "0") != "1":
            raise LicenseError("WHMCS licence endpoint must use HTTPS")
        previous = self._current_entitlement()
        payload = {
            "schema": 1,
            "product": "Pi Matrix Signage",
            "app_version": self.app_version,
            "license_key": license_key,
            "device_id": self.identity["device_id"],
            "device": {
                "hostname": self.identity["hostname"],
                "platform": self.identity["platform"],
            },
            "whmcs_local_key": str(previous.get("whmcs_local_key") or ""),
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": f"PiMatrixSignage/{self.app_version}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                raw = response.read(1024 * 1024)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(4096).decode("utf-8", "replace")
            except Exception:
                pass
            raise LicenseError(f"WHMCS licensing server returned HTTP {exc.code}" + (f": {detail[:200]}" if detail else "")) from exc
        except Exception as exc:
            raise LicenseError(f"Unable to contact WHMCS licensing server: {exc}") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise LicenseError("WHMCS licensing server did not return JSON") from exc
        if not isinstance(result, dict):
            raise LicenseError("WHMCS licensing server returned an invalid response")
        entitlement = self._verify_signed_entitlement(result.get("entitlement_b64", ""), result.get("signature", ""))
        ok, reason = self._validate_entitlement(entitlement, license_key)
        return {
            "ok": ok,
            "reason": reason,
            "entitlement": entitlement,
            "signed_entitlement": {
                "entitlement_b64": str(result.get("entitlement_b64") or ""),
                "signature": str(result.get("signature") or ""),
            },
        }

    def activate(self, license_key: str) -> dict:
        key = str(license_key or "").strip()
        if not key:
            raise LicenseError("Enter a licence key")
        if self.prefix and not key.upper().startswith(self.prefix.upper()):
            raise LicenseError(f"Licence key must begin {self.prefix}")
        with self._lock:
            self._last_remote_attempt = time.time()
            result = self._remote(key)
            self._state["last_check_at"] = _iso(_utcnow())
            if not result["ok"]:
                # A rejected activation is not an installed licence. Keep the currently
                # working cached entitlement (if any) and record the diagnostic only.
                self._state["last_error"] = result["reason"]
                self._state["last_failed_check_at"] = _iso(_utcnow())
                self._save_state()
                raise LicenseError(result["reason"])
            self._state["license_key"] = key
            self._state["signed_entitlement"] = result["signed_entitlement"]
            self._state["reported_app_version"] = self.app_version
            self._state["last_error"] = ""
            self._state.pop("last_failed_check_at", None)
            self._save_state()
            LOG.info("Licence activated for device %s", self.identity["device_id"])
            return self.info()

    def check_now(self, silent: bool = False) -> dict:
        # Manual checks are useful in development mode too: development disables
        # enforcement, not WHMCS activation testing.  Background refresh remains
        # WHMCS-mode-only in _run/_should_refresh.
        with self._lock:
            key = str(self._state.get("license_key") or "").strip()
            if not key:
                if silent:
                    return self.info()
                raise LicenseError("No licence key is installed")
            self._last_remote_attempt = time.time()
            try:
                result = self._remote(key)
                self._state["signed_entitlement"] = result["signed_entitlement"]
                self._state["last_check_at"] = _iso(_utcnow())
                self._state["last_error"] = "" if result["ok"] else result["reason"]
                if result["ok"]:
                    self._state["reported_app_version"] = self.app_version
                self._save_state()
                if not result["ok"] and not silent:
                    raise LicenseError(result["reason"])
            except Exception as exc:
                self._state["last_error"] = str(exc)
                self._state["last_failed_check_at"] = _iso(_utcnow())
                self._save_state()
                if not silent:
                    raise
            return self.info()

    def deactivate_local(self) -> dict:
        """Remove only this Pi's cached key/entitlement.

        WHMCS reissue remains authoritative for moving a licence to another physical Pi.
        """
        with self._lock:
            self._state = {}
            self._save_state()
            LOG.info("Local licence data cleared for device %s", self.identity["device_id"])
            return self.info()

    def info(self) -> dict:
        with self._lock:
            if self.mode != "whmcs":
                # Development mode deliberately keeps the renderer unlocked, but we
                # still expose any real WHMCS activation stored on this controller so
                # a licence can be proven before commercial enforcement is enabled.
                key = str(self._state.get("license_key") or "").strip()
                entitlement = self._current_entitlement() if key else {}
                activation_ok = False
                activation_reason = "No test licence has been activated"
                if entitlement:
                    activation_ok, activation_reason = self._validate_entitlement(entitlement, key)
                valid_until = _parse_time(entitlement.get("valid_until")) if entitlement else None
                grace_until = _parse_time(entitlement.get("grace_until")) if entitlement else None
                last_error = str(self._state.get("last_error") or "")
                if activation_ok:
                    development_message = "WHMCS activation succeeded for this controller; commercial enforcement remains disabled."
                elif key:
                    development_message = "WHMCS test activation failed: " + activation_reason
                elif last_error:
                    development_message = "Last WHMCS activation attempt failed: " + last_error
                else:
                    development_message = "Commercial licence enforcement is disabled; enter a licence key below to test WHMCS activation."
                return {
                    "mode": "development",
                    "licensed": True,
                    "test_licensed": bool(activation_ok),
                    "status": "Active (development mode)" if activation_ok else "Development mode",
                    "message": development_message,
                    "test_activation_error": "" if activation_ok else (activation_reason if key else ""),
                    "device_id": self.identity["device_id"],
                    "device_source": self.identity["source"],
                    "license_key_masked": _mask_key(key),
                    "customer": str(entitlement.get("customer") or "") if entitlement else "",
                    "product_name": str(entitlement.get("product_name") or entitlement.get("product") or "") if entitlement else "",
                    "valid_until": _iso(valid_until) if valid_until else "",
                    "grace_until": _iso(grace_until) if grace_until else "",
                    "updates_until": str(entitlement.get("updates_until") or "") if entitlement else "",
                    "features": entitlement.get("features") if isinstance(entitlement.get("features"), (dict, list)) else {},
                    "last_check_at": str(self._state.get("last_check_at") or ""),
                    "last_failed_check_at": str(self._state.get("last_failed_check_at") or ""),
                    "last_error": str(self._state.get("last_error") or ""),
                    "app_version": self.app_version,
                    "reported_app_version": str(self._state.get("reported_app_version") or ""),
                    "endpoint_configured": bool(self.endpoint),
                    "public_key_configured": self.public_key_path.is_file(),
                    "public_key_url_configured": bool(self.public_key_url),
                    "public_key_url": self.public_key_url,
                    "check_interval_hours": self.check_interval_hours,
                    "grace_days": self.grace_days,
                }
            key = str(self._state.get("license_key") or "").strip()
            entitlement = self._current_entitlement() if key else {}
            ok = False
            reason = "No licence key is installed" if not key else "No valid signed entitlement is stored"
            if entitlement:
                ok, reason = self._validate_entitlement(entitlement, key)
            valid_until = _parse_time(entitlement.get("valid_until")) if entitlement else None
            grace_until = _parse_time(entitlement.get("grace_until")) if entitlement else None
            now = _utcnow()
            if ok and valid_until and now <= valid_until:
                status = "Active"
                message = "Licence is active and recently verified with WHMCS."
            elif ok:
                status = "Offline grace"
                message = "Licence is using its signed offline grace period; a WHMCS refresh is due."
            else:
                status = str(entitlement.get("status") or "Unlicensed") if entitlement else "Unlicensed"
                message = reason
            return {
                "mode": "whmcs",
                "licensed": bool(ok),
                "status": status,
                "message": message,
                "device_id": self.identity["device_id"],
                "device_source": self.identity["source"],
                "license_key_masked": _mask_key(key),
                "customer": str(entitlement.get("customer") or "") if entitlement else "",
                "product_name": str(entitlement.get("product_name") or entitlement.get("product") or "") if entitlement else "",
                "valid_until": _iso(valid_until) if valid_until else "",
                "grace_until": _iso(grace_until) if grace_until else "",
                "updates_until": str(entitlement.get("updates_until") or "") if entitlement else "",
                "features": entitlement.get("features") if isinstance(entitlement.get("features"), (dict, list)) else {},
                "last_check_at": str(self._state.get("last_check_at") or ""),
                "last_failed_check_at": str(self._state.get("last_failed_check_at") or ""),
                "last_error": str(self._state.get("last_error") or ""),
                "app_version": self.app_version,
                "reported_app_version": str(self._state.get("reported_app_version") or ""),
                "endpoint_configured": bool(self.endpoint),
                "public_key_configured": self.public_key_path.is_file(),
                "public_key_url_configured": bool(self.public_key_url),
                "public_key_url": self.public_key_url,
                "public_key_path": str(self.public_key_path),
                "check_interval_hours": self.check_interval_hours,
                "grace_days": self.grace_days,
            }
