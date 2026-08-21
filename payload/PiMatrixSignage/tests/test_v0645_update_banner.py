from pathlib import Path

import controller_platform as cp

ROOT = Path(__file__).resolve().parents[1]


def _reset_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "SOFTWARE_UPDATE_CACHE", tmp_path / "software-update-cache.json")
    monkeypatch.setattr(cp, "_update_cache_memory", None)
    monkeypatch.setattr(cp, "PLATFORM_UPDATE_STATUS", tmp_path / "platform-update.json")


def test_background_check_persists_update_result_and_remote_version(monkeypatch, tmp_path):
    _reset_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(cp, "PLATFORM_UPDATE_HELPER", tmp_path / "platform-helper")
    monkeypatch.setattr(cp, "_remote_plugin_version", lambda branch: "0.6.46")
    calls = []

    def fake_request(path, method="GET", payload=None, timeout=5):
        calls.append((path, method, payload, timeout))
        return {
            "Status": "OK",
            "updatesAvailable": 1,
            "name": "Pi Matrix Signage",
            "versions": [{"branch": "main"}],
        }

    monkeypatch.setattr(cp, "_request_json", fake_request)
    result = cp._perform_software_update_check("0.6.45")
    assert calls == [(f"/api/plugin/{cp.PLUGIN_REPO}/updates", "POST", {}, 20)]
    assert result["available"] is True
    assert result["latest_version"] == "0.6.46"
    assert result["checked_at"]
    assert cp.SOFTWARE_UPDATE_CACHE.exists()

    # Normal cached reads must not perform a controller/network request.
    monkeypatch.setattr(cp, "_request_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call on cached status path")))
    cached = cp.software_update_cached_status("0.6.45")
    assert cached["available"] is True
    assert cached["latest_version"] == "0.6.46"


def test_stale_cache_from_previous_application_version_is_suppressed(monkeypatch, tmp_path):
    _reset_cache(monkeypatch, tmp_path)
    cp._write_software_update_cache({
        "current_version": "0.6.44",
        "available": True,
        "platform_ready": True,
        "latest_version": "0.6.45",
        "checked_at": "2026-08-21T10:00:00+00:00",
        "message": "Pi Matrix Signage v0.6.45 is available",
    })
    status = cp.software_update_cached_status("0.6.45")
    assert status["available"] is False
    assert status["platform_ready"] is False
    assert "pending" in status["message"].lower()


def test_status_poll_exposes_cache_without_running_update_check():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    route = app_source.split('@app.get("/api/status")', 1)[1].split('@app.get("/api/content-options")', 1)[0]
    assert 'software_update_cached_status(APP_VERSION)' in route
    assert 'software_update_status(APP_VERSION' not in route
    assert 'start_software_update_monitor(APP_VERSION, LOG)' in app_source
    assert 'stop_software_update_monitor()' in app_source


def test_background_monitor_is_six_hour_cached_check_with_fast_failure_retry():
    source = (ROOT / "controller_platform.py").read_text(encoding="utf-8")
    assert 'PIMATRIX_UPDATE_CHECK_INTERVAL", "21600"' in source
    assert 'PIMATRIX_UPDATE_CHECK_INITIAL_DELAY", "8"' in source
    assert 'threading.Thread(target=worker, name="PiMatrixUpdateCheck", daemon=True)' in source
    assert 'min(300, UPDATE_CHECK_INTERVAL_SECONDS)' in source


def test_top_banner_settings_badge_and_controller_last_checked_are_present():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="softwareUpdateBanner"' in html
    assert 'id="softwareUpdateBannerText"' in html
    assert 'id="viewSoftwareUpdate"' in html
    assert 'id="settingsUpdateBadge"' in html
    assert 'id="controllerUpdateChecked"' in html
    assert '.software-update-banner' in css
    assert '.settings-update-badge' in css
    assert 'renderSoftwareUpdateNotice(s.software_update)' in js
    assert 'openControllerSoftware' in js
    assert "setSetupSubtab('controller'" in js
    assert "$('controllerUpdateChecked').textContent=formatUpdateChecked" in js


def test_manual_check_bypasses_cached_result_and_updates_banner():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "loadControllerUpdate(true)" in js
    assert "?check=1" in js
    assert "renderSoftwareUpdateNotice(data)" in js


def test_help_explains_background_checks_do_not_slow_normal_status_polling():
    help_html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "every six hours" in help_html
    assert "normal status polling reads only the cached result" in help_html
    assert "top-of-screen update banner" in readme


def test_release_version_is_v0645_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 45)
