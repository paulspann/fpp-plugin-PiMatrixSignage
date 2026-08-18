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


def test_payload_is_v069_or_later():
    version = tuple(int(x) for x in (ROOT / 'payload' / 'PiMatrixSignage' / 'VERSION').read_text().strip().split('.')[:3])
    assert version >= (0, 6, 9)


def test_plugin_info_uses_published_repository():
    info = json.loads((ROOT / 'pluginInfo.json').read_text(encoding='utf-8'))
    assert info['srcURL'] == 'https://github.com/paulspann/fpp-plugin-PiMatrixSignage.git'
    assert info['versions'][0]['branch'] == 'main'


def test_plugin_update_is_the_customer_facing_application_update_path():
    # FPP's documented upgrade flow falls back to scripts/fpp_install.sh when
    # fpp_upgrade.sh is absent.  Deliberately do not ship fpp_upgrade.sh: a file
    # newly uploaded through GitHub can lose its executable bit, which makes
    # FPP's direct sudo execution fail before our script can run.
    assert not (ROOT / 'scripts' / 'fpp_upgrade.sh').exists()
    html = (ROOT / 'payload' / 'PiMatrixSignage' / 'templates' / 'index.html').read_text(encoding='utf-8')
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


def test_plugin_scripts_do_not_source_fpp_common_under_nounset():
    for name in ('fpp_install.sh', 'fpp_uninstall.sh'):
        script = (ROOT / 'scripts' / name).read_text(encoding='utf-8')
        assert 'scripts/common' not in '\n'.join(
            line for line in script.splitlines() if not line.lstrip().startswith('#')
        )
        assert 'MEDIADIR="${MEDIADIR:-/home/fpp/media}"' in script


def test_uninstall_is_self_contained_and_verifies_removal():
    script = (ROOT / 'scripts' / 'fpp_uninstall.sh').read_text(encoding='utf-8')
    assert 'systemctl disable --now "$SERVICE"' in script
    assert 'rm -rf "$APP_DIR"' in script
    assert "pgrep -f '/home/fpp/media/pi-matrix-signage/app.py'" in script
    assert 'systemctl is-active --quiet "$SERVICE"' in script
    assert 'Saved messages, schedules, media and licence data remain' in script
    assert '"$APP_DIR/uninstall.sh"' not in script


def test_install_does_not_require_payload_executable_bit():
    sh=(ROOT/'scripts'/'fpp_install.sh').read_text(encoding='utf-8')
    assert '! -x "$PAYLOAD/install.sh"' not in sh
    assert 'bash "$PAYLOAD/install.sh"' in sh


def test_release_pipeline_runs_tests_and_builds_validated_zip():
    workflow = (ROOT / '.github' / 'workflows' / 'verify-and-package.yml').read_text(encoding='utf-8')
    builder = (ROOT / 'scripts' / 'build_release.sh').read_text(encoding='utf-8')
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8')

    assert 'python -m pytest -q' in workflow
    assert 'node --check payload/PiMatrixSignage/static/app.js' in workflow
    assert 'scripts/build_release.sh' in workflow
    assert 'actions/upload-artifact@v4' in workflow
    assert 'unzip -tq "$TEMP_ZIP"' in builder
    assert 'zipinfo -l "$TEMP_ZIP"' in builder
    assert "__pycache__/" in ignore
    assert "*.py[cod]" in ignore
    assert "dist/" in ignore

def test_plugin_manager_sees_install_errors_while_logging_them():
    install=(ROOT/'scripts'/'fpp_install.sh').read_text(encoding='utf-8')
    uninstall=(ROOT/'scripts'/'fpp_uninstall.sh').read_text(encoding='utf-8')
    assert 'tee -a "$LOG_FILE"' in install
    assert 'tee -a "$LOG_FILE"' in uninstall
