import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import Database  # noqa: E402


def _load_reset_helper():
    path = ROOT / "systemd" / "pi-matrix-signage-reset"
    spec = importlib.util.spec_from_file_location("pimatrix_reset_helper", path)
    if spec is None or spec.loader is None:
        # Extensionless executable: load it explicitly as Python source.
        from importlib.machinery import SourceFileLoader
        spec = importlib.util.spec_from_loader("pimatrix_reset_helper", SourceFileLoader("pimatrix_reset_helper", str(path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_commissioning_test_results_are_persistent_settings(tmp_path):
    db = Database(str(tmp_path / "data" / "signage.db"))
    results = {"fpp": {"passed": True, "message": "OK"}, "grid": True, "white": True}
    db.update_settings({"colorlight_commissioning_tests": results})
    assert db.get_settings()["colorlight_commissioning_tests"] == results


def test_support_package_contains_human_readable_commissioning_certificate():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'zf.writestr("commissioning-certificate.txt"' in app
    assert "Device ID:" in app
    assert "Hardware profile:" in app
    assert "Panel dimensions:" in app
    assert "PASS (legacy commissioning record)" in app
    assert "TEST RESULTS" in app
    assert "Commissioning certificate" in html


def test_factory_reset_is_password_and_phrase_guarded_and_has_privileged_helper():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert '@app.post("/api/factory-reset")' in app
    assert "_verify_password" in app[app.index('def factory_reset_api():'):app.index('@app.get("/api/backups")')]
    assert "RESET THIS CONTROLLER" in app
    assert "can_backup" in app and "can_users" in app and "can_display_setup" in app
    assert 'id="factoryResetController"' in html
    assert "function factoryResetController" in js
    assert "pi-matrix-signage-reset" in install
    assert (ROOT / "systemd" / "pi-matrix-signage-reset").is_file()


def test_reset_helper_wipes_app_state_and_can_clear_fpp_network(tmp_path):
    helper = _load_reset_helper()
    persist = tmp_path / "persist"
    media = tmp_path / "media"
    connman = tmp_path / "connman"
    helper.PERSIST = persist
    helper.FPP_MEDIA = media
    helper.STATUS = persist / "factory-reset-status.json"
    helper.CONNMAN_DIR = connman

    for name in ("data", "uploads", "backups", "upgrade"):
        (persist / name).mkdir(parents=True, exist_ok=True)
        (persist / name / "customer-secret.txt").write_text("secret", encoding="utf-8")
    (persist / "data" / "license-state.json").write_text('{"license_key":"PMS-SECRET"}', encoding="utf-8")
    (persist / "license.env").write_text("PIMATRIX_LICENSE_MODE=whmcs\n", encoding="utf-8")

    (media / "config").mkdir(parents=True)
    (media / "config" / "interface.wlan0").write_text('SSID="customer"\nPSK="secret"\n', encoding="utf-8")
    (media / "config" / "channeloutputs.json").write_text("{}", encoding="utf-8")
    (media / "settings").write_text("fppMode=remote\nHostName=CustomerSign\n", encoding="utf-8")
    for name in ("playlists", "scripts", "events", "channelmemorymaps"):
        (media / name).mkdir()
        (media / name / "site.txt").write_text("site", encoding="utf-8")
    (media / "schedule").write_text("site schedule", encoding="utf-8")
    connman.mkdir()
    (connman / "fpp.config").write_text("Passphrase=secret", encoding="utf-8")

    helper.reset_application_state()
    helper.reset_fpp_site(True)

    assert not (persist / "data" / "license-state.json").exists()
    assert (persist / "license.env").is_file()  # product endpoint configuration survives
    assert not (media / "config" / "interface.wlan0").exists()
    assert not (media / "config" / "channeloutputs.json").exists()
    assert (media / "settings").read_text(encoding="utf-8") == "fppMode=remote\n"
    assert not (media / "schedule").exists()
    assert not (connman / "fpp.config").exists()
    for name in ("playlists", "scripts", "events", "channelmemorymaps"):
        assert list((media / name).iterdir()) == []


def test_pillow_tests_use_non_deprecated_flattened_pixel_api():
    core = (ROOT / "tests" / "test_core.py").read_text(encoding="utf-8")
    assert "get_flattened_data" in core
    # One compatibility fallback is allowed for Pillow versions before the new API.
    assert core.count(".getdata()") == 2  # docstring text + compatibility fallback


def test_release_version_is_v0628():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.29"
