import json
from pathlib import Path
from types import SimpleNamespace

import controller_platform as cp

ROOT = Path(__file__).resolve().parents[1]


def test_phase15_certification_matches_this_release():
    cert = json.loads((ROOT / "controller-platform-certification.json").read_text(encoding="utf-8"))
    assert cert["pimatrix_version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.58"
    assert cert["certified_release"] == "10.0-beta3"
    assert cert["platform_name"] == "Falcon Player (FPP)"


def test_certified_platform_update_is_offered_only_for_exact_managed_target(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "PLATFORM_UPDATE_STATUS", tmp_path / "platform-update.json")
    calls = []

    def fake_request(path, method="GET", payload=None, timeout=5):
        calls.append(path)
        if path == "/api/system/status":
            return {"version": "10.0-beta2", "fppd": "running"}
        if path == "/api/git/releases/os":
            return {
                "status": "OK",
                "files": [{
                    "tag": "10.0-beta3",
                    "filename": "Pi64-10.0-beta3_2026-08.fppos",
                    "url": "https://github.com/FalconChristmas/fpp/releases/download/10.0-beta3/Pi64-10.0-beta3_2026-08.fppos",
                    "size": 123456789,
                    "downloaded": False,
                    "prerelease": True,
                }],
            }
        raise AssertionError(path)

    monkeypatch.setattr(cp, "_request_json", fake_request)
    status = cp.controller_platform_update_status()
    assert status["installed_version"] == "10.0-beta2"
    assert status["certified_version"] == "10.0-beta3"
    assert status["update_available"] is True
    assert status["candidate"]["filename"].endswith(".fppos")
    assert calls == ["/api/system/status", "/api/git/releases/os"]


def test_newer_fpp_is_never_managed_downgraded(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "PLATFORM_UPDATE_STATUS", tmp_path / "platform-update.json")
    monkeypatch.setattr(cp, "_request_json", lambda path, **kwargs: {"version": "10.0-rc1", "fppd": "running"} if path == "/api/system/status" else (_ for _ in ()).throw(AssertionError("release lookup should not happen for newer FPP")))
    status = cp.controller_platform_update_status()
    assert status["update_available"] is False
    assert "newer than the certified target" in status["message"]


def test_controller_health_detects_repairable_drift_without_release_lookup(monkeypatch):
    monkeypatch.setattr(cp, "_platform_runtime_info", lambda: {"reachable": True, "fppd_running": True, "version": "10.0-beta3"})
    monkeypatch.setattr(cp, "output_status", lambda *args, **kwargs: {"input_ready": False, "output_ready": False, "can_apply": True, "ok": False})
    monkeypatch.setattr(cp, "interface_mode_status", lambda: {"mode": "appliance", "actual_mode": "fpp", "in_sync": False, "helper_ready": True, "label": "Pi Matrix Signage appliance"})
    monkeypatch.setattr(cp, "software_update_cached_status", lambda *args, **kwargs: {"controller_platform": {"certified": True}})
    h = cp.controller_health({"ddp_host": "192.0.2.50", "ddp_port": 5000, "ddp_offset": 3}, {}, 5000)
    assert h["healthy"] is False
    assert h["drifted"] is True
    assert h["repairable"] is True
    bad = {c["id"] for c in h["checks"] if not c["ok"]}
    assert {"ddp_target", "ddp_input", "panel_output", "interface_mode"}.issubset(bad)


def test_platform_update_helper_has_independent_safety_gates_and_backup_requirement():
    helper = (ROOT / "systemd" / "pi-matrix-signage-platform").read_text(encoding="utf-8")
    assert "--upgrade-platform" in helper
    assert "Only official FalconChristmas FPP release images" in helper
    assert "github\\.com/FalconChristmas/fpp/releases/download" in helper
    assert "A verified pre-update backup filename is required" in helper
    assert '[[ -f "/home/fpp/media/pi-matrix-signage-data/backups/$backup" ]]' in helper
    assert 'expected="$(certified_target)"' in helper
    assert "is not the certified target embedded in this Pi Matrix release" in helper
    assert "managed downgrade is disabled" in helper
    # Both the public queue action and the internal systemd worker must require
    # the backup rather than trusting only the browser route.
    run_platform = helper.split("--run-platform)", 1)[1].split(";;", 1)[0]
    assert 'validate_backup "$backup"' in run_platform
    assert "upgradeOS.php" in helper
    assert "--data-urlencode \"os=$url\"" in helper


def test_platform_update_route_creates_backup_before_starting_root_helper():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    route = app.split('@app.post("/api/controller-platform-update/install")', 1)[1].split('\n\n@app.', 1)[0]
    assert 'software_update_status(APP_VERSION, check=True)' in route
    assert '_create_backup_archive_local(filename, "controller-platform-update")' in route
    assert 'start_controller_platform_update(candidate, backup.name)' in route
    assert route.index('_create_backup_archive_local') < route.index('start_controller_platform_update')


def test_first_run_choice_is_fresh_install_only_and_factory_reset_restores_it():
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    reset = (ROOT / "systemd" / "pi-matrix-signage-reset").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    html = (ROOT / "templates" / "first_setup.html").read_text(encoding="utf-8")
    assert 'fresh_install=0' in install
    assert '! -f "$PERSIST/data/signage.db"' in install
    assert 'first-run-interface-choice.pending' in install
    assert 'first-run-interface-choice.pending' in reset
    assert '@app.route("/first-setup", methods=["GET", "POST"])' in app
    assert 'first_run_interface_choice_pending()' in app
    assert 'complete_first_run_interface_choice()' in app
    assert "FPP + Pi Matrix Signage add-on" in html
    assert "Dedicated Pi Matrix Signage appliance" in html


def test_phase15_ui_has_health_repair_platform_update_and_combined_banner():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="controllerHealthBadge"' in html
    assert 'id="repairControllerHealth"' in html
    assert 'id="platformInstalledVersion"' in html
    assert 'id="platformCertifiedVersion"' in html
    assert 'id="installPlatformUpdate"' in html
    assert "/api/controller-health/repair" in js
    assert "/api/controller-platform-update/install" in js
    assert "const app=!!data?.available" in js and "plat=!!data?.controller_platform?.update_available" in js


def test_release_version_is_v0646_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 46)


def test_browser_zip_updater_preserves_phase15_platform_helper_and_sudo_permission():
    updater = (ROOT / "systemd" / "pi-matrix-signage-upgrade").read_text(encoding="utf-8")
    assert 'PLATFORM_HELPER = Path("/usr/local/sbin/pi-matrix-signage-platform")' in updater
    refresh = updater.split("def refresh_privileged_files", 1)[1].split("def worker", 1)[0]
    assert 'platform_src = root / "systemd" / "pi-matrix-signage-platform"' in refresh
    assert "shutil.copy2(platform_src, PLATFORM_HELPER)" in refresh
    assert "{PLATFORM_HELPER}" in refresh
    required = updater.split("REQUIRED = {", 1)[1].split("}", 1)[0]
    assert '"PiMatrixSignage/controller-platform-certification.json"' in required
    assert '"PiMatrixSignage/systemd/pi-matrix-signage-platform"' in required


def test_certified_release_lookup_does_not_accept_similar_filename_from_wrong_tag(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "PLATFORM_UPDATE_STATUS", tmp_path / "platform-update.json")
    def fake_request(path, **kwargs):
        if path == "/api/system/status":
            return {"version": "10.0-beta2", "fppd": "running"}
        if path == "/api/git/releases/os":
            return {"status": "OK", "files": [{
                "tag": "10.0-beta30",
                "filename": "Pi64-10.0-beta3-lookalike.fppos",
                "url": "https://github.com/FalconChristmas/fpp/releases/download/10.0-beta30/Pi64-10.0-beta3-lookalike.fppos",
                "prerelease": True,
            }]}
        raise AssertionError(path)
    monkeypatch.setattr(cp, "_request_json", fake_request)
    status = cp.controller_platform_update_status()
    assert status["update_available"] is False
    assert "not currently offered" in status["message"]
