import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from database import Database
from shutdown_schedule import ShutdownScheduler, due_shutdown, validate_shutdown_schedule


LONDON = ZoneInfo("Europe/London")


def local_timestamp(day, hour, minute, fold=0):
    return datetime(2026, 8, day, hour, minute, tzinfo=LONDON, fold=fold).timestamp()


def test_shutdown_only_on_observed_crossing(tmp_path):
    db = Database(str(tmp_path / "signage.db"))
    powered_off = []
    scheduler = ShutdownScheduler(db, lambda: powered_off.append(True), lambda: False, logging.getLogger(__name__))
    monday = local_timestamp(17, 18, 30)
    cfg = {"enabled": True, "days": [0], "time": "18:30"}
    scheduler.tick(monday - 2, monday + 1)
    assert powered_off == []
    db.save_shutdown_schedule(cfg, monday - 10)
    scheduler.tick(monday + 1, monday + 3)  # Booted after the time.
    scheduler.tick(monday - 90, monday + 1)  # Stalled across the time.
    scheduler.tick(monday + 86400 - 2, monday + 86400 + 1)  # Wrong day.
    assert powered_off == []
    scheduler.tick(monday - 2, monday + 1)
    assert powered_off == [True]
    db.save_shutdown_schedule(cfg, monday - 1)
    another = ShutdownScheduler(db, lambda: powered_off.append(True), lambda: False, logging.getLogger(__name__))
    another.tick(monday - 2, monday + 1)  # Same occurrence, even after saving/restarting.
    assert powered_off == [True]


def test_shutdown_skips_emergency_and_does_not_catch_up(tmp_path):
    db = Database(str(tmp_path / "signage.db"))
    moment = local_timestamp(17, 18, 30)
    db.save_shutdown_schedule({"enabled": True, "days": [0], "time": "18:30"}, moment - 60)
    emergency = [True]
    scheduler = ShutdownScheduler(db, lambda: pytest.fail("Unexpected poweroff"),
                                  lambda: emergency[0], logging.getLogger(__name__))
    scheduler.tick(moment - 1, moment)
    emergency[0] = False
    scheduler.tick(moment, moment + 1)


def test_dst_skipped_and_repeated_wall_times():
    config = {"enabled": True, "days": [6], "time": "01:30", "armed_at": 0}
    spring = datetime(2026, 3, 29, 1, 30, tzinfo=LONDON).timestamp()
    first = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=0).timestamp()
    second = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=1).timestamp()
    assert due_shutdown(config, LONDON, spring - 1, spring) is None
    assert due_shutdown(config, LONDON, first - 1, first) == "2026-10-25"
    assert due_shutdown(config, LONDON, second - 1, second) is None


@pytest.mark.parametrize("change", [{"enabled": "false"}, {"days": []}, {"days": [True]}, {"time": "24:00"}])
def test_shutdown_rejects_invalid_settings(change):
    with pytest.raises(ValueError):
        validate_shutdown_schedule({"enabled": True, "days": [1], "time": "18:30", **change})
