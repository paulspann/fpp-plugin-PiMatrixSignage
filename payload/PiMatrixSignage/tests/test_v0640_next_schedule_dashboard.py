from datetime import datetime
from pathlib import Path
import tempfile
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import Database
from renderer import RendererEngine, _schedule_next_start



def schedule(**overrides):
    data = {
        "enabled": 1, "days": "0,1,2,3,4,5,6", "start_date": "", "end_date": "",
        "start_time": "09:00", "end_time": "17:00",
    }
    data.update(overrides)
    return data


def test_next_schedule_start_today_then_next_week():
    tz = ZoneInfo("Europe/London")
    assert _schedule_next_start(schedule(days="0"), datetime(2026, 8, 24, 8, 0, tzinfo=tz)) == datetime(2026, 8, 24, 9, 0, tzinfo=tz)
    assert _schedule_next_start(schedule(days="0"), datetime(2026, 8, 24, 10, 0, tzinfo=tz)) == datetime(2026, 8, 31, 9, 0, tzinfo=tz)


def test_next_schedule_start_jumps_to_future_start_date_and_honours_disabled():
    tz = ZoneInfo("Europe/London")
    now = datetime(2026, 8, 21, 8, 0, tzinfo=tz)
    assert _schedule_next_start(schedule(start_date="2026-09-10"), now) == datetime(2026, 9, 10, 9, 0, tzinfo=tz)
    assert _schedule_next_start(schedule(enabled=0), now) is None



def test_engine_next_schedule_payload_includes_content_name_and_priority_tiebreak():
    tz = ZoneInfo("Europe/London")
    now = datetime(2026, 8, 21, 8, 0, tzinfo=tz)
    with tempfile.TemporaryDirectory() as td:
        db = Database(str(Path(td) / "signage.db"))
        first = db.save_message({"name": "Breakfast welcome", "text": "Hello", "enabled": 1})
        second = db.save_message({"name": "Priority welcome", "text": "Hello", "enabled": 1})
        db.save_schedule({"name": "Normal morning", "target_type": "message", "target_id": first, "days": "4", "start_time": "09:00", "end_time": "10:00", "priority": 100, "enabled": 1})
        db.save_schedule({"name": "Priority morning", "target_type": "message", "target_id": second, "days": "4", "start_time": "09:00", "end_time": "10:00", "priority": 200, "enabled": 1})
        engine = RendererEngine(db, td, td)
        item = engine._next_timed_schedule(now)
        assert item is not None
        assert item["name"] == "Priority morning"
        assert item["target_name"] == "Priority welcome"
        assert item["start_label"] == "Today at 09:00"
        assert item["window_label"] == "09:00–10:00"
        assert item["priority"] == 200

def test_dashboard_contains_next_schedule_panel():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="nextScheduleCard"' in html
    assert '>Next timed schedule</h2>' in html
    assert 'id="nextScheduleName"' in html
    assert 'id="nextScheduleContent"' in html
    assert 'id="nextScheduleStarts"' in html
    assert 'id="nextScheduleWindow"' in html


def test_status_poll_renders_next_schedule_and_dashboard_link_opens_schedules():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "function renderNextSchedule(item)" in js
    assert "renderNextSchedule(s.next_schedule)" in js
    assert "nextScheduleCountdown(item.start_at)" in js
    assert "openSchedulesFromDashboard" in js


def test_renderer_status_exposes_next_schedule_payload():
    renderer = (ROOT / "renderer.py").read_text(encoding="utf-8")
    assert "def _next_timed_schedule(self, now: datetime)" in renderer
    assert '"next_schedule": next_schedule' in renderer
    assert '"target_name":' in renderer
    assert '"start_label":' in renderer


def test_release_version_is_v0640_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 40)
