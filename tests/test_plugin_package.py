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


def test_payload_is_v0610_or_later():
    version = tuple(int(x) for x in (ROOT / 'payload' / 'PiMatrixSignage' / 'VERSION').read_text().strip().split('.')[:3])
    assert version >= (0, 6, 10)


def test_plugin_info_uses_published_repository():
    info = json.loads((ROOT / 'pluginInfo.json').read_text(encoding='utf-8'))
    assert info['srcURL'] == 'https://github.com/paulspann/fpp-plugin-PiMatrixSignage.git'
    assert info['versions'][0]['branch'] == 'main'


def test_plugin_update_path_remains_packaged_without_customer_update_ui():
    # FPP's documented upgrade flow falls back to scripts/fpp_install.sh when
    # fpp_upgrade.sh is absent.  Deliberately do not ship fpp_upgrade.sh: a file
    # newly uploaded through GitHub can lose its executable bit, which makes
    # FPP's direct sudo execution fail before our script can run.
    assert not (ROOT / 'scripts' / 'fpp_upgrade.sh').exists()
    html = (ROOT / 'payload' / 'PiMatrixSignage' / 'templates' / 'index.html').read_text(encoding='utf-8')
    assert 'data-tab="upgrade"' not in html
    assert '<h2>Software updates</h2>' not in html
    assert (ROOT / 'scripts' / 'fpp_install.sh').is_file()


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


def test_phase1_appliance_bootstrap_and_update_helper_are_packaged():
    install = (ROOT / 'payload' / 'PiMatrixSignage' / 'install.sh').read_text(encoding='utf-8')
    uninstall = (ROOT / 'scripts' / 'fpp_uninstall.sh').read_text(encoding='utf-8')
    conf = (ROOT / 'payload' / 'PiMatrixSignage' / 'systemd' / 'pi-matrix-signage-appliance.conf').read_text(encoding='utf-8')
    entry = (ROOT / 'payload' / 'PiMatrixSignage' / 'systemd' / 'pimatrix-appliance.php').read_text(encoding='utf-8')
    helper = (ROOT / 'payload' / 'PiMatrixSignage' / 'systemd' / 'pi-matrix-signage-platform').read_text(encoding='utf-8')
    builder = (ROOT / 'scripts' / 'build_release.sh').read_text(encoding='utf-8')

    assert 'a2enconf pi-matrix-signage-appliance' in install
    assert 'apache2ctl configtest' in install
    assert 'DirectoryIndex pimatrix-appliance.php index.php index.html' in conf
    assert "header('Location: http://' . $host . ':8090/'" in entry
    assert '/opt/fpp/scripts/upgrade_plugin' in helper
    assert 'fpp-plugin-PiMatrixSignage' in helper
    assert 'a2disconf pi-matrix-signage-appliance' in uninstall
    assert 'payload/PiMatrixSignage/systemd/pi-matrix-signage-platform' in builder


def test_v0644_controller_interface_mode_is_optional_and_fpp_first_by_default():
    install = (ROOT / 'payload' / 'PiMatrixSignage' / 'install.sh').read_text(encoding='utf-8')
    helper = (ROOT / 'payload' / 'PiMatrixSignage' / 'systemd' / 'pi-matrix-signage-platform').read_text(encoding='utf-8')
    ui = (ROOT / 'payload' / 'PiMatrixSignage' / 'templates' / 'index.html').read_text(encoding='utf-8')
    assert 'Defaulting controller interface to FPP-first add-on mode' in install
    assert '/etc/apache2/conf-enabled/pi-matrix-signage-appliance.conf' in install
    assert 'Preserving existing Pi Matrix Signage appliance mode' in install
    assert '--interface-mode' in helper
    assert 'Controller &amp; FPP</button>' in ui
    assert 'FPP + Pi Matrix Signage add-on' in ui
    assert 'Pi Matrix Signage appliance' in ui


def test_v0647_split_flap_designer_controls_are_packaged():
    html = (ROOT / 'payload' / 'PiMatrixSignage' / 'templates' / 'index.html').read_text(encoding='utf-8')
    js = (ROOT / 'payload' / 'PiMatrixSignage' / 'static' / 'app.js').read_text(encoding='utf-8')
    renderer = (ROOT / 'payload' / 'PiMatrixSignage' / 'renderer.py').read_text(encoding='utf-8')
    assert '<option value="split-flap">Split-flap display</option>' in html
    assert 'id="splitFlapOptions"' in html
    assert 'id="layerFlapCycles"' in html
    assert 'id="layerFlapStagger"' in html
    assert 'id="layerFlapOrder"' in html
    assert "l.flap_cycles=clamp" in js
    assert "updateAnimationFieldVisibility" in js
    assert 'def _render_split_flap_text' in renderer
    assert 'def _split_flap_cell' in renderer


def test_v0650_effects_and_shader_expansion_is_packaged():
    payload = ROOT / 'payload' / 'PiMatrixSignage'
    html = (payload / 'templates' / 'index.html').read_text(encoding='utf-8')
    renderer = (payload / 'renderer.py').read_text(encoding='utf-8')
    version = (payload / 'VERSION').read_text(encoding='utf-8').strip()
    assert version == '0.6.57'
    for name in ('Fire-Embers.fs','Starfield-Warp.fs','Particle-Fall.fs','Radar-Sweep.fs','Matrix-Rain.fs','LED-Marquee.fs','Aurora.fs'):
        assert (payload / 'shaders' / name).is_file(), name
    for marker in ('pixel-assemble','pixel-dissolve','neon-flicker','glitch','character-wave','rolling-digits'):
        assert f'value="{marker}"' in html
    assert 'Departure board – black' in html
    assert 'Moving colour wave' in html
    for marker in ('columns','rows','center-out','spiral','random-leds'):
        assert f'value="{marker}"' in html
    assert 'def _render_rolling_digits_text' in renderer
    assert 'def _pixel_transition_rank_mask' in renderer



def test_v0651_departure_board_strengthening_is_packaged():
    payload = ROOT / 'payload' / 'PiMatrixSignage'
    renderer = (payload / 'renderer.py').read_text(encoding='utf-8')
    version = (payload / 'VERSION').read_text(encoding='utf-8').strip()
    assert version == '0.6.57'
    assert 'def _split_flap_board_overlay' in renderer
    assert 'A mechanical casing must surround the glyph, not share its pixels' in renderer
    assert 'separate upper/lower flap face' in renderer


def test_v0652_outer_departure_casing_is_packaged():
    payload = ROOT / 'payload' / 'PiMatrixSignage'
    renderer = (payload / 'renderer.py').read_text(encoding='utf-8')
    html = (payload / 'templates' / 'index.html').read_text(encoding='utf-8')
    js = (payload / 'static' / 'app.js').read_text(encoding='utf-8')
    version = (payload / 'VERSION').read_text(encoding='utf-8').strip()
    assert version == '0.6.57'
    assert '_flap_content_inset_x' in renderer
    assert "Render the glyph into the flap's *inner face*" in renderer
    assert 'id="layerFlapCasePadding"' in html
    assert 'flap_case_padding:2' in js


def test_v0653_live_moon_phase_is_packaged():
    payload = ROOT / 'payload' / 'PiMatrixSignage'
    version = (payload / 'VERSION').read_text(encoding='utf-8').strip()
    shader = (payload / 'shaders' / 'Sky-Weather.fs').read_text(encoding='utf-8')
    renderer = (payload / 'renderer.py').read_text(encoding='utf-8')
    help_html = (payload / 'templates' / 'help.html').read_text(encoding='utf-8')
    cert = json.loads((payload / 'controller-platform-certification.json').read_text(encoding='utf-8'))
    assert version == '0.6.57'
    assert cert['pimatrix_version'] == version
    assert '"NAME":"MoonPhase"' in shader
    assert '"NAME":"MoonBrightness"' in shader
    assert 'vec3 moonLight' in shader
    assert 'bodyDelta' in shader and '(W/H)' in shader
    assert 'def _moon_phase_fraction' in renderer
    assert '"MoonPhase": moon_phase' in renderer
    assert 'calculates the current moon phase locally' in help_html
