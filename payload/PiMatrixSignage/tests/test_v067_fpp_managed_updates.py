from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_tab_and_permission_card_are_not_customer_facing():
    html = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
    js = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')
    assert 'data-tab="upgrade"' not in html
    assert 'id="page-upgrade"' not in html
    assert 'id="permUpgrade"' not in html
    assert "labels.push('Upgrade')" not in js


def test_display_setup_explains_fpp_plugin_update_path():
    html = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
    assert '<h2>Software updates</h2>' in html
    assert 'Content Setup → Plugin Manager' in html
    assert 'Pi Matrix Signage</strong> and choose <strong>Update</strong>' in html


def test_legacy_upgrade_engine_remains_available_underneath():
    app_py = (ROOT / 'app.py').read_text(encoding='utf-8')
    js = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')
    assert '@app.post("/api/upgrade")' in app_py
    assert '@app.get("/api/upgrade/status")' in app_py
    assert (ROOT / 'systemd' / 'pi-matrix-signage-upgrade').is_file()
    assert "const upgradeZone=$('upgradeDropZone');" in js
    assert 'if(upgradeZone)' in js


def test_release_version_is_067_or_later():
    version = tuple(int(x) for x in (ROOT / 'VERSION').read_text(encoding='utf-8').strip().split('.')[:3])
    assert version >= (0, 6, 7)
