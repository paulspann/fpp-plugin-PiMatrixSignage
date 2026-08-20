from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable

# Hanson rPi-MFC dedicated user inputs.  The current Hanson V1.1 manual's
# GPIO table shows header pins 31/33/37 as GPIO6/GPIO13/GPIO26 respectively.
RPI_MFC_INPUTS = {
    "A": {"connector": "CN2", "gpio": 6, "header_pin": 31},
    "B": {"connector": "CN3", "gpio": 13, "header_pin": 33},
    "C": {"connector": "CN4", "gpio": 26, "header_pin": 37},
}

ACTIONS = {
    "none", "emergency", "end_emergency", "next_message", "previous_message",
    "blank", "automatic", "brightness_cycle",
}
CONTACT_TYPES = {"normally_open", "normally_closed"}
EMERGENCY_BEHAVIOURS = {"latch", "while_active"}


def default_gpio_inputs() -> list[dict]:
    return [
        {"id": key, "enabled": False, "action": "emergency" if key == "A" else "none",
         "contact_type": "normally_open", "emergency_behaviour": "latch", "debounce_ms": 100}
        for key in ("A", "B", "C")
    ]


def normalise_gpio_inputs(value) -> list[dict]:
    supplied = {str(x.get("id") or "").upper(): x for x in (value if isinstance(value, list) else []) if isinstance(x, dict)}
    out = []
    for key in ("A", "B", "C"):
        raw = supplied.get(key, {})
        action = str(raw.get("action") or ("emergency" if key == "A" else "none")).lower()
        if action not in ACTIONS:
            action = "none"
        contact = str(raw.get("contact_type") or "normally_open").lower()
        if contact not in CONTACT_TYPES:
            contact = "normally_open"
        behaviour = str(raw.get("emergency_behaviour") or "latch").lower()
        if behaviour not in EMERGENCY_BEHAVIOURS:
            behaviour = "latch"
        try:
            debounce = max(20, min(2000, int(raw.get("debounce_ms", 100))))
        except Exception:
            debounce = 100
        info = RPI_MFC_INPUTS[key]
        out.append({
            "id": key,
            "enabled": bool(raw.get("enabled", False)),
            "action": action,
            "contact_type": contact,
            "emergency_behaviour": behaviour,
            "debounce_ms": debounce,
            "connector": info["connector"],
            "gpio": info["gpio"],
            "header_pin": info["header_pin"],
            "pull": "pull-up",
        })
    return out


@dataclass
class _Worker:
    key: str
    stop: threading.Event
    thread: threading.Thread
    process: subprocess.Popen | None = None


class GPIOControlManager:
    """Monitor the three dedicated rPi-MFC user inputs with libgpiod tools.

    FPP images already ship libgpiod/gpiomon.  We deliberately use the Linux
    character-device tools instead of legacy /sys/class/gpio.  If another FPP
    feature already owns a line, gpiomon fails cleanly and the UI reports that
    conflict rather than stealing the line.
    """

    def __init__(self, db, engine, logger):
        self.db = db
        self.engine = engine
        self.log = logger
        self._lock = threading.RLock()
        self._running = False
        self._supervisor: threading.Thread | None = None
        self._workers: dict[str, _Worker] = {}
        self._states: dict[str, dict] = {k: self._blank_state(k) for k in RPI_MFC_INPUTS}
        self._config_signature = ""
        self._gpiomon_major: int | None = None

    def _blank_state(self, key: str) -> dict:
        info = RPI_MFC_INPUTS[key]
        return {"id": key, **info, "enabled": False, "available": False, "active": False,
                "level": None, "last_event_at": None, "last_action_at": None,
                "error": "GPIO controls are disabled"}

    def start(self):
        if self._running:
            return
        self._running = True
        self._supervisor = threading.Thread(target=self._supervise, name="PiMatrixGPIO", daemon=True)
        self._supervisor.start()

    def stop(self):
        self._running = False
        self._stop_all_workers()
        if self._supervisor and self._supervisor is not threading.current_thread():
            self._supervisor.join(timeout=2)

    def reload(self):
        with self._lock:
            self._config_signature = ""

    def settings(self) -> tuple[bool, list[dict]]:
        s = self.db.get_settings()
        return bool(s.get("gpio_controls_enabled", False)), normalise_gpio_inputs(s.get("gpio_inputs"))

    def status(self) -> dict:
        enabled, config = self.settings()
        with self._lock:
            states = []
            for item in config:
                st = dict(self._states.get(item["id"], self._blank_state(item["id"])))
                st.update({k: item[k] for k in ("enabled", "action", "contact_type", "emergency_behaviour", "debounce_ms", "connector", "gpio", "header_pin", "pull")})
                states.append(st)
        output_type = str(self.db.get_settings().get("panel_output_type") or "rpi_mfc")
        profile = "Raspberry Pi GPIO (Colorlight mode)" if output_type == "colorlight" else "Hanson rPi-MFC inputs"
        return {
            "enabled": enabled,
            "profile": profile,
            "backend": "libgpiod/gpiomon" if shutil.which("gpiomon") else "unavailable",
            "inputs": states,
        }

    def test_action(self, key: str):
        enabled, config = self.settings()
        item = next((x for x in config if x["id"] == str(key).upper()), None)
        if not item:
            raise ValueError("Unknown GPIO input")
        if item["action"] == "none":
            raise ValueError("No action is assigned to this input")
        self._perform_action(item, active=True, test=True)

    def _supervise(self):
        while self._running:
            try:
                enabled, config = self.settings()
                sig = repr((enabled, [(x["id"], x["enabled"], x["action"], x["contact_type"], x["emergency_behaviour"], x["debounce_ms"]) for x in config]))
                with self._lock:
                    changed = sig != self._config_signature
                    if changed:
                        self._config_signature = sig
                if changed:
                    self._stop_all_workers()
                    with self._lock:
                        for x in config:
                            self._states[x["id"]] = self._blank_state(x["id"])
                            self._states[x["id"]]["enabled"] = bool(enabled and x["enabled"])
                            if enabled and x["enabled"]:
                                self._states[x["id"]]["error"] = "Starting GPIO monitor…"
                    if enabled:
                        for item in config:
                            if item["enabled"]:
                                self._start_worker(item)
            except Exception as exc:
                self.log.exception("GPIO supervisor failed")
                with self._lock:
                    for st in self._states.values():
                        st["error"] = str(exc)
            time.sleep(0.75)

    def _stop_all_workers(self):
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop.set()
            if worker.process and worker.process.poll() is None:
                try:
                    worker.process.terminate()
                except Exception:
                    pass
        for worker in workers:
            if worker.thread.is_alive() and worker.thread is not threading.current_thread():
                worker.thread.join(timeout=1.2)

    def _start_worker(self, item: dict):
        stop = threading.Event()
        holder: dict[str, _Worker] = {}
        def run():
            self._worker_loop(item, holder["worker"])
        thread = threading.Thread(target=run, name=f"PiMatrixGPIO-{item['id']}", daemon=True)
        worker = _Worker(item["id"], stop, thread)
        holder["worker"] = worker
        with self._lock:
            self._workers[item["id"]] = worker
        thread.start()

    def _version_major(self) -> int:
        if self._gpiomon_major is not None:
            return self._gpiomon_major
        exe = shutil.which("gpiomon")
        if not exe:
            self._gpiomon_major = 0
            return 0
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=2)
            m = re.search(r"(?:gpiomon|libgpiod)\s+v?(\d+)", (r.stdout or "") + " " + (r.stderr or ""), re.I)
            self._gpiomon_major = int(m.group(1)) if m else 1
        except Exception:
            self._gpiomon_major = 1
        return self._gpiomon_major

    def _monitor_command(self, gpio: int) -> list[str]:
        exe = shutil.which("gpiomon")
        if not exe:
            raise RuntimeError("gpiomon is not installed")
        major = self._version_major()
        if major >= 2:
            cmd = [exe, "--bias", "pull-up", "--edges", "both", "--format", "%E", "--chip", "gpiochip0", str(gpio)]
        else:
            cmd = [exe, "--line-buffered", "--bias=pull-up", "--format=%e", "gpiochip0", str(gpio)]
        stdbuf = shutil.which("stdbuf")
        return ([stdbuf, "-oL"] + cmd) if stdbuf else cmd

    def _get_level(self, gpio: int) -> int | None:
        exe = shutil.which("gpioget")
        if not exe:
            return None
        major = self._version_major()
        cmd = [exe, "--bias", "pull-up", "--chip", "gpiochip0", str(gpio)] if major >= 2 else [exe, "--bias=pull-up", "gpiochip0", str(gpio)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if r.returncode != 0:
                return None
            m = re.search(r"(?<!\d)([01])(?!\d)", r.stdout or "")
            return int(m.group(1)) if m else None
        except Exception:
            return None

    @staticmethod
    def _event_level(line: str) -> int | None:
        text = str(line or "").strip().lower()
        if not text:
            return None
        if "rising" in text:
            return 1
        if "falling" in text:
            return 0
        # libgpiod v1 custom %e: 0 falling, 1 rising.
        if re.fullmatch(r"0", text):
            return 0
        if re.fullmatch(r"1", text):
            return 1
        # libgpiod v2 numeric event type: 1 rising, 2 falling.
        if re.fullmatch(r"2", text):
            return 0
        return None

    @staticmethod
    def _is_active(item: dict, level: int) -> bool:
        # The Hanson rPi-MFC inputs and direct Raspberry Pi GPIO wiring used in
        # Colorlight mode both use pull-ups with a voltage-free contact to GND.
        # A normally-open switch is active low; a normally-closed safety loop is
        # active when the loop opens and the line rises.
        return (level == 0) if item.get("contact_type") == "normally_open" else (level == 1)

    def _worker_loop(self, item: dict, worker: _Worker):
        key = item["id"]
        last_accepted = 0.0
        last_active: bool | None = None
        while self._running and not worker.stop.is_set():
            try:
                level = self._get_level(int(item["gpio"]))
                if level is not None:
                    active = self._is_active(item, level)
                    last_active = active
                    with self._lock:
                        st = self._states[key]; st.update(available=True, level=level, active=active, error="")
                cmd = self._monitor_command(int(item["gpio"]))
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
                worker.process = proc
                time.sleep(0.05)
                if proc.poll() is not None:
                    stderr = proc.stderr.read().strip() if proc.stderr else ""
                    raise RuntimeError(stderr or f"gpiomon stopped (exit {proc.returncode})")
                with self._lock:
                    self._states[key].update(available=True, error="")
                # Honour a contact that is already active when the application starts
                # (important for normally-closed/fail-safe emergency loops).
                if level is not None and last_active and item.get("action") == "emergency":
                    # Only an emergency contact is honoured immediately on startup.
                    # Momentary actions such as Next or Brightness must never repeat
                    # merely because a monitor process is restarted while held.
                    self._perform_action(item, True)
                    last_accepted = time.monotonic()
                while self._running and not worker.stop.is_set():
                    assert proc.stdout is not None
                    line = proc.stdout.readline()
                    if line == "":
                        break
                    level = self._event_level(line)
                    if level is None:
                        continue
                    active = self._is_active(item, level)
                    now = time.monotonic()
                    with self._lock:
                        st = self._states[key]; st.update(available=True, level=level, active=active, last_event_at=time.time(), error="")
                    if last_active is not None and active == last_active:
                        continue
                    last_active = active
                    if now - last_accepted < max(0.02, float(item.get("debounce_ms", 100)) / 1000.0):
                        continue
                    last_accepted = now
                    self._perform_action(item, active)
                if worker.stop.is_set() or not self._running:
                    break
                stderr = ""
                try:
                    if proc.stderr:
                        stderr = proc.stderr.read().strip()
                except Exception:
                    pass
                rc = proc.poll()
                message = stderr or f"gpiomon stopped (exit {rc})"
                if "busy" in message.lower() or "resource" in message.lower():
                    message = "GPIO line is already in use (possibly by FPP GPIO/OLED controls). Disable that FPP input/control before using it here."
                with self._lock:
                    self._states[key].update(available=False, error=message)
            except Exception as exc:
                message = str(exc)
                if "busy" in message.lower() or "resource" in message.lower():
                    message = "GPIO line is already in use (possibly by FPP GPIO/OLED controls). Disable that FPP input/control before using it here."
                with self._lock:
                    self._states[key].update(available=False, error=message)
                self.log.warning("GPIO input %s monitor error: %s", key, message)
            finally:
                proc = worker.process
                if proc and proc.poll() is None:
                    try: proc.terminate()
                    except Exception: pass
                worker.process = None
            worker.stop.wait(4.0)

    def _perform_action(self, item: dict, active: bool, test: bool = False):
        action = item.get("action") or "none"
        source = f"gpio:{item['id']}"
        try:
            if action == "emergency":
                if active:
                    self.engine.activate_emergency(source=source)
                elif item.get("emergency_behaviour") == "while_active":
                    self.engine.clear_emergency(source=source)
            elif not active:
                return
            elif action == "end_emergency":
                self.engine.clear_emergency()
            elif action == "next_message":
                self.engine.step_message(1)
            elif action == "previous_message":
                self.engine.step_message(-1)
            elif action == "blank":
                self.engine.show_blank()
            elif action == "automatic":
                self.engine.clear_manual()
            elif action == "brightness_cycle":
                self.engine.cycle_brightness_override()
            elif action == "none":
                return
            with self._lock:
                self._states[item["id"]]["last_action_at"] = time.time()
            self.log.info("GPIO %s%s action %s (%s)", item["id"], " test" if test else "", action, "active" if active else "inactive")
        except Exception as exc:
            with self._lock:
                self._states[item["id"]]["error"] = f"Action failed: {exc}"
            self.log.warning("GPIO %s action %s failed: %s", item["id"], action, exc)
            if test:
                raise
