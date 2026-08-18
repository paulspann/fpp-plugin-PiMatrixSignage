from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installer_restarts_already_active_service():
    script = (ROOT / 'install.sh').read_text(encoding='utf-8')
    assert 'if systemctl is-active --quiet "$SERVICE"; then' in script
    assert 'systemctl restart "$SERVICE"' in script
    assert 'systemctl enable --now "$SERVICE"' in script


def test_release_version_is_v068_or_later():
    version = tuple(int(x) for x in (ROOT / 'VERSION').read_text(encoding='utf-8').strip().split('.')[:3])
    assert version >= (0, 6, 8)
