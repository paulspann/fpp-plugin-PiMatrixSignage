"""Opt-in local power schedules, with no catch-up on service start."""
import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo


def validate_shutdown_schedule(data: dict) -> dict:
    if not isinstance(data, dict) or type(data.get("enabled")) is not bool:
        raise ValueError("Choose whether the shutdown schedule is enabled.")
    days = data.get("days")
    if not isinstance(days, list) or not days or any(type(day) is not int or not 0 <= day <= 6 for day in days):
        raise ValueError("Select at least one valid day.")
    at = data.get("time")
    if not isinstance(at, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", at):
        raise ValueError("Enter a shutdown time in HH:MM format.")
    return {"enabled": data["enabled"], "days": sorted(set(days)), "time": at}


def due_shutdown(config: dict, zone: ZoneInfo, previous: float, current: float) -> str | None:
    # A service that wasn't observing the clock at the scheduled time must
    # never catch up. This also ignores large NTP jumps and resumes from sleep.
    if not config["enabled"] or not 0 < current - previous <= 15:
        return None
    local = datetime.fromtimestamp(current, zone)
    if local.weekday() not in config["days"]:
        return None
    hour, minute = map(int, config["time"].split(":"))
    wall = local.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
    scheduled = wall.timestamp()
    if datetime.fromtimestamp(scheduled, zone).replace(tzinfo=None) != wall.replace(tzinfo=None):
        return None  # A wall-clock time skipped by daylight saving.
    if max(previous, config["armed_at"]) < scheduled <= current:
        return wall.date().isoformat()
    return None


class ShutdownScheduler:
    def __init__(self, db, poweroff, emergency_active, log):
        self.db, self.poweroff, self.emergency_active, self.log = db, poweroff, emergency_active, log
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="PiMatrixShutdownSchedule", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def tick(self, previous: float, current: float):
        config = self.db.get_shutdown_schedule()
        if not config["enabled"]:
            return
        zone = ZoneInfo(str(self.db.get_settings().get("timezone") or "Europe/London"))
        day = due_shutdown(config, zone, previous, current)
        if not day or self._stop.is_set() or not self.db.claim_shutdown_occurrence(config["armed_at"], day):
            return
        if self.emergency_active():
            self.log.warning("Scheduled shutdown skipped: emergency mode is active")
            return
        self.log.warning("Scheduled shutdown requested for %s %s (%s)", day, config["time"], zone.key)
        self.poweroff()

    def _run(self):
        previous = time.time()
        while not self._stop.wait(2):
            current = time.time()
            try:
                self.tick(previous, current)
            except Exception:
                self.log.exception("Scheduled shutdown check failed")
            previous = current
