from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_info_targets_fpp10_raspberry_pi_and_declares_dependencies():
    info = json.loads((ROOT / 'pluginInfo.json').read_text(encoding='utf-8'))
    assert info['repoName'] == 'fpp-plugin-PiMatrixSignage'
    assert info['versions'][0]['minFPPVersion'] == '10.0'
    assert info['versions'][0]['platforms'] == ['Raspberry Pi']
    deps = set(info['dependencies']['packages'])
    for pkg in {'python3-flask', 'python3-pil', 'python3-cryptography', 'ffmpeg', 'gpiod'}:
        assert pkg in deps


def test_plugin_installer_is_idempotent_and_uses_bundled_payload():
    script = (ROOT / 'scripts' / 'fpp_install.sh').read_text(encoding='utf-8')
    assert 'PIMATRIX_SKIP_DEPENDENCY_INSTALL=1' in script
    assert 'sort -V' in script
    assert 'not downgrading' in script
    assert 'http://127.0.0.1:8090/health' in script
    assert 'sudo' not in script


def test_fpp_menu_opens_pimatrix_directly():
    menu = (ROOT / 'menu.inc').read_text(encoding='utf-8')
    assert "$menu === 'content'" in menu
    assert "':8090/'" in menu
    assert 'plugin.php' not in menu
    assert "Pi Matrix Signage" in menu


def test_payload_is_v068_or_later():
    version = tuple(int(x) for x in (ROOT / 'payload' / 'PiMatrixSignage' / 'VERSION').read_text().strip().split('.')[:3])
    assert version >= (0, 6, 8)


def test_plugin_info_uses_published_repository():
    info = json.loads((ROOT / 'pluginInfo.json').read_text(encoding='utf-8'))
    assert info['srcURL'] == 'https://github.com/paulspann/fpp-plugin-PiMatrixSignage.git'
    assert info['versions'][0]['branch'] == 'main'


def test_plugin_update_is_the_customer_facing_application_update_path():
    upgrade = (ROOT / 'scripts' / 'fpp_upgrade.sh').read_text(encoding='utf-8')
    html = (ROOT / 'payload' / 'PiMatrixSignage' / 'templates' / 'index.html').read_text(encoding='utf-8')
    assert 'fpp_install.sh' in upgrade
    assert 'data-tab="upgrade"' not in html
    assert 'Content Setup → Plugin Manager' in html


def test_plugin_verifies_running_application_version_after_update():
    script = (ROOT / 'scripts' / 'fpp_install.sh').read_text(encoding='utf-8')
    assert 'expected_version="$payload_version"' in script
    assert 'running_version=' in script
    assert 'Reported running version:' in script
    assert 'Disk version:' in script
    assert 'json.load(sys.stdin).get("version", "")' in script


def test_payload_installer_restarts_active_service():
    script = (ROOT / 'payload' / 'PiMatrixSignage' / 'install.sh').read_text(encoding='utf-8')
    assert 'systemctl restart "$SERVICE"' in script
