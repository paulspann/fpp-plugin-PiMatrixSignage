from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from renderer import live_data_diagnostics


class SystemDiagnostics:
    """Background health monitor and conservative recovery watchdog.

    It intentionally never reboots or powers off the Pi. Recovery actions are
    limited to restarting the in-process LED renderer and asking the fixed,
    root-owned support helper to restart FPPD when FPPD is actually inactive.
    """

    def __init__(self, engine, db, data_dir: str | Path, recovery_helper: str | Path, log):
        self.engine = engine
        self.db = db
        self.data_dir = Path(data_dir)
        self.recovery_helper = Path(recovery_helper)
        self.log = log
        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._snapshot: dict = {}
        self._started_monotonic = time.monotonic()
        self._last_cpu: tuple[int, int] | None = None
        self._last_internet_check = 0.0
        self._internet = {"ok": None, "dns": None, "checked_at": 0.0, "error": ""}
        self._last_recovery: dict[str, float] = {}
        self._fppd_bad_checks = 0
        self._last_renderer_frames = 0
        self._last_renderer_progress = time.monotonic()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="PiMatrixDiagnostics", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.5)

    @staticmethod
    def _read_text(path: str, default: str = "") -> str:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            return default

    def _cpu_percent(self) -> float | None:
        try:
            parts = self._read_text("/proc/stat").splitlines()[0].split()[1:]
            values = [int(x) for x in parts]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
            previous = self._last_cpu
            self._last_cpu = (idle, total)
            if previous is None:
                return None
            idle_delta = idle - previous[0]
            total_delta = total - previous[1]
            if total_delta <= 0:
                return None
            return round(max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta))), 1)
        except Exception:
            return None

    @staticmethod
    def _memory() -> dict:
        values: dict[str, int] = {}
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if ":" not in line:
                    continue
                key, raw = line.split(":", 1)
                number = raw.strip().split()[0]
                values[key] = int(number) * 1024
        except Exception:
            pass
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        used = max(0, total - available) if total else 0
        return {
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": used,
            "percent": round(used * 100.0 / total, 1) if total else None,
        }

    @staticmethod
    def _process_rss() -> int:
        try:
            for line in Path("/proc/self/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
        except Exception:
            pass
        return 0

    @staticmethod
    def _temperature() -> float | None:
        candidates = sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
        for path in candidates:
            try:
                raw = float(path.read_text().strip())
                value = raw / 1000.0 if raw > 500 else raw
                if -20 <= value <= 150:
                    return round(value, 1)
            except Exception:
                continue
        try:
            result = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=1.5)
            if result.returncode == 0:
                raw = result.stdout.strip().split("=")[-1].replace("'C", "")
                return round(float(raw), 1)
        except Exception:
            pass
        return None

    @staticmethod
    def _uptime_seconds() -> float:
        try:
            return float(Path("/proc/uptime").read_text().split()[0])
        except Exception:
            return 0.0

    @staticmethod
    def _service_state(name: str) -> str:
        try:
            result = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=2)
            value = (result.stdout or result.stderr or "unknown").strip()
            return value or ("active" if result.returncode == 0 else "inactive")
        except Exception as exc:
            return f"unknown ({exc})"

    @staticmethod
    def _ddp_listener(port: int) -> bool:
        target = int(port)
        for proc_path in ("/proc/net/udp", "/proc/net/udp6"):
            try:
                lines = Path(proc_path).read_text().splitlines()[1:]
                for line in lines:
                    cols = line.split()
                    if len(cols) < 2 or ":" not in cols[1]:
                        continue
                    local_port = int(cols[1].rsplit(":", 1)[1], 16)
                    if local_port == target:
                        return True
            except Exception:
                continue
        return False

    @staticmethod
    def _ip_addresses() -> list[str]:
        try:
            result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=1.5)
            return [x for x in result.stdout.split() if x]
        except Exception:
            return []

    def _check_internet(self) -> None:
        now_m = time.monotonic()
        if now_m - self._last_internet_check < 30:
            return
        self._last_internet_check = now_m
        dns_ok = False
        internet_ok = False
        error = ""
        try:
            socket.getaddrinfo("api.open-meteo.com", 443, type=socket.SOCK_STREAM)
            dns_ok = True
        except Exception as exc:
            error = f"DNS: {exc}"
        try:
            with socket.create_connection(("1.1.1.1", 443), timeout=1.5):
                internet_ok = True
        except Exception as exc:
            if not error:
                error = str(exc)
        self._internet = {
            "ok": internet_ok,
            "dns": dns_ok,
            "checked_at": time.time(),
            "error": error,
        }

    def _recovery_allowed(self, key: str, cooldown: float) -> bool:
        return (time.monotonic() - self._last_recovery.get(key, 0.0)) >= cooldown

    def _record(self, event_type: str, action: str, result: str, details: str = "") -> None:
        try:
            self.db.add_recovery_event(event_type, action, result, details)
        except Exception:
            self.log.exception("Unable to record recovery event")

    def restart_renderer(self, reason: str = "Manual request") -> dict:
        try:
            ok = bool(self.engine.restart())
            if ok:
                self._last_recovery["renderer"] = time.monotonic()
                self._last_renderer_progress = time.monotonic()
                self._last_renderer_frames = int(self.engine.status().get("frames_sent") or 0)
                self._record("renderer", "restart-renderer", "success", reason)
                self.log.warning("Renderer restarted: %s", reason)
                return {"ok": True, "message": "LED renderer restarted"}
            self._record("renderer", "restart-renderer", "failed", reason + "; existing thread did not stop")
            return {"ok": False, "message": "Renderer thread did not stop cleanly; service-level recovery remains active"}
        except Exception as exc:
            self._record("renderer", "restart-renderer", "failed", f"{reason}: {exc}")
            self.log.exception("Renderer restart failed")
            return {"ok": False, "message": str(exc)}

    def restart_fppd(self, reason: str = "Manual request") -> dict:
        if not self.recovery_helper.is_file():
            return {"ok": False, "message": "Privileged support helper is not installed"}
        try:
            result = subprocess.run(
                ["sudo", "-n", str(self.recovery_helper), "--recover-fppd"],
                capture_output=True, text=True, timeout=25,
            )
            ok = result.returncode == 0
            message = (result.stdout or result.stderr or ("FPPD restarted" if ok else "FPPD restart failed")).strip()
            self._last_recovery["fppd"] = time.monotonic()
            self._record("fppd", "restart-fppd", "success" if ok else "failed", f"{reason}: {message}")
            if ok:
                self.log.warning("FPPD restarted: %s", reason)
            else:
                self.log.error("FPPD restart failed: %s", message)
            return {"ok": ok, "message": message}
        except Exception as exc:
            self._record("fppd", "restart-fppd", "failed", f"{reason}: {exc}")
            return {"ok": False, "message": str(exc)}

    def _automatic_recovery(self, renderer: dict, fppd_state: str) -> None:
        settings = self.db.get_settings()
        if not bool(settings.get("auto_recovery_enabled", True)):
            self._fppd_bad_checks = 0
            return
        cooldown = max(15.0, float(settings.get("recovery_cooldown_seconds", 60) or 60))
        stall = max(3.0, float(settings.get("renderer_stall_seconds", 5) or 5))
        now_m = time.monotonic()

        frames = int(renderer.get("frames_sent") or 0)
        if frames != self._last_renderer_frames:
            self._last_renderer_frames = frames
            self._last_renderer_progress = now_m

        renderer_bad = not bool(renderer.get("running")) or not bool(renderer.get("thread_alive"))
        if not renderer_bad and now_m - self._started_monotonic > max(10.0, stall):
            renderer_bad = (now_m - self._last_renderer_progress) > stall
        if bool(settings.get("auto_recover_renderer", True)) and renderer_bad and self._recovery_allowed("renderer", cooldown):
            reason = f"Watchdog detected no renderer progress for {now_m - self._last_renderer_progress:.1f}s"
            self.restart_renderer(reason)

        if fppd_state == "active":
            self._fppd_bad_checks = 0
        else:
            self._fppd_bad_checks += 1
        if (bool(settings.get("auto_recover_fppd", True)) and self._fppd_bad_checks >= 2 and
                self._recovery_allowed("fppd", max(cooldown, 60.0))):
            result = self.restart_fppd(f"Watchdog saw FPPD state '{fppd_state}' on {self._fppd_bad_checks} consecutive checks")
            if result.get("ok"):
                self._fppd_bad_checks = 0

    def _collect(self) -> dict:
        self._check_internet()
        settings = self.db.get_settings()
        renderer = self.engine.status()
        try:
            usage = shutil.disk_usage(self.data_dir)
            disk = {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free,
                    "percent": round(usage.used * 100.0 / usage.total, 1) if usage.total else None}
        except Exception:
            disk = {"total_bytes": 0, "used_bytes": 0, "free_bytes": 0, "percent": None}
        try:
            load1, load5, load15 = os.getloadavg()
        except Exception:
            load1 = load5 = load15 = 0.0
        temp = self._temperature()
        fppd_state = self._service_state("fppd.service")
        app_state = self._service_state("pi-matrix-signage.service")
        ddp_port = int(settings.get("ddp_port") or 4048)
        ddp_listening = self._ddp_listener(ddp_port)
        widgets = live_data_diagnostics()
        self._automatic_recovery(renderer, fppd_state)

        checks = []
        def add(name: str, level: str, message: str):
            checks.append({"name": name, "level": level, "message": message})
        frame_age = None if not renderer.get("last_frame_at") else max(0.0, time.time() - float(renderer["last_frame_at"]))
        add("Renderer", "ok" if renderer.get("running") and renderer.get("thread_alive") and (frame_age is None or frame_age < 5) else "error",
            f"{renderer.get('actual_fps', 0):.1f} fps" if renderer.get("running") else "Stopped")
        add("FPPD", "ok" if fppd_state == "active" else "error", fppd_state)
        add("DDP input", "ok" if ddp_listening else "warn", f"UDP {ddp_port} listening" if ddp_listening else f"No listener detected on UDP {ddp_port}")
        if temp is not None:
            add("Temperature", "error" if temp >= 85 else "warn" if temp >= 75 else "ok", f"{temp:.1f}°C")
        free = int(disk.get("free_bytes") or 0)
        add("Storage", "error" if free < 250*1024*1024 else "warn" if free < 1024*1024*1024 else "ok", f"{free/1024/1024/1024:.1f} GB free")
        memp = self._memory()
        mp = memp.get("percent")
        if mp is not None:
            add("Memory", "error" if mp >= 95 else "warn" if mp >= 85 else "ok", f"{mp:.1f}% used")
        add("Internet", "ok" if self._internet.get("ok") else "warn", "Connected" if self._internet.get("ok") else "Unavailable")
        add("Live widgets", "warn" if widgets.get("errors") else "ok", f"{widgets.get('errors',0)} errors · {widgets.get('fetching',0)} fetching")
        overall = "error" if any(c["level"] == "error" for c in checks) else "warn" if any(c["level"] == "warn" for c in checks) else "ok"

        return {
            "collected_at": time.time(),
            "overall": overall,
            "checks": checks,
            "system": {
                "cpu_percent": self._cpu_percent(),
                "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
                "temperature_c": temp,
                "memory": memp,
                "process_rss_bytes": self._process_rss(),
                "disk": disk,
                "uptime_seconds": self._uptime_seconds(),
                "ips": self._ip_addresses(),
                "internet": dict(self._internet),
            },
            "services": {
                "app": app_state,
                "fppd": fppd_state,
                "ddp_port": ddp_port,
                "ddp_listening": ddp_listening,
            },
            "renderer": renderer,
            "widgets": widgets,
            "recovery": {
                "enabled": bool(settings.get("auto_recovery_enabled", True)),
                "renderer": bool(settings.get("auto_recover_renderer", True)),
                "fppd": bool(settings.get("auto_recover_fppd", True)),
                "renderer_stall_seconds": int(settings.get("renderer_stall_seconds", 5) or 5),
                "cooldown_seconds": int(settings.get("recovery_cooldown_seconds", 60) or 60),
                "events": self.db.list_recovery_events(30),
            },
        }

    def snapshot(self) -> dict:
        with self._lock:
            if self._snapshot:
                return dict(self._snapshot)
        # Useful during the first couple of seconds after startup.
        try:
            return self._collect()
        except Exception as exc:
            self.log.exception("Diagnostics collection failed")
            return {"overall": "error", "error": str(exc), "checks": []}

    def _run(self) -> None:
        while self._running:
            started = time.monotonic()
            try:
                snap = self._collect()
                with self._lock:
                    self._snapshot = snap
            except Exception:
                self.log.exception("Diagnostics collection failed")
            delay = max(0.5, 3.0 - (time.monotonic() - started))
            time.sleep(delay)
