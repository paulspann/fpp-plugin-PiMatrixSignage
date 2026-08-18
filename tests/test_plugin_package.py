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


def test_fpp_menu_has_single_content_entry():
    menu = (ROOT / 'menu.inc').read_text(encoding='utf-8')
    assert menu.count("'type' => 'content'") == 1
    assert "'text' => 'Pi Matrix Signage'" in menu


def test_payload_is_v066_or_later():
    version = tuple(int(x) for x in (ROOT / 'payload' / 'PiMatrixSignage' / 'VERSION').read_text().strip().split('.')[:3])
    assert version >= (0, 6, 6)


def test_plugin_info_uses_published_repository():
    info = json.loads((ROOT / 'pluginInfo.json').read_text(encoding='utf-8'))
    assert info['srcURL'] == 'https://github.com/paulspann/fpp-plugin-PiMatrixSignage.git'
    assert info['versions'][0]['branch'] == 'main'
