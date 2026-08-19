from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_software_licence_panel_links_to_issl_support():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="licenceHelp"' in html
    assert 'id="licenceSupportLink"' in html
    assert 'https://www.issl.co.uk/support' in html
    assert 'To buy a licence, reissue a licence or get licensing support:' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html


def test_help_manual_documents_licence_support_route():
    html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    assert 'To buy a licence, request a reissue or get licensing support' in html
    assert 'https://www.issl.co.uk/support' in html


def test_runtime_licence_render_cannot_overwrite_support_link():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    licence_help_start = html.index('id="licenceHelp"')
    licence_support_start = html.index('id="licenceSupportLink"')
    assert licence_support_start > licence_help_start
    assert "$('licenceHelp').innerHTML" in js
    assert "$('licenceSupportLink').innerHTML" not in js
    assert "$('licenceSupportLink').textContent" not in js


def test_release_version_is_v0631_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 31)
