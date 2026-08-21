from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _section(html: str, page_id: str, next_page_id: str) -> str:
    return html.split(f'id="{page_id}"', 1)[1].split(f'id="{next_page_id}"', 1)[0]


def test_panel_test_is_not_on_dashboard_and_is_on_display_setup():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    dashboard = _section(html, "page-dashboard", "page-messages")
    setup = _section(html, "page-setup", "page-diagnostics")
    assert 'id="panelTestCard"' not in dashboard
    assert '>Panel test</h2>' not in dashboard
    assert 'test-pattern' not in dashboard
    assert 'id="panelTestCard"' in setup
    assert '>Panel test</h2>' in setup
    for pattern in ("grid", "checker", "red", "green", "blue", "white"):
        assert f'data-pattern="{pattern}"' in setup


def test_existing_test_pattern_binding_and_endpoint_are_retained():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "$$('.test-pattern').forEach" in js
    assert "api('/api/test-pattern'" in js
    assert '@app.post("/api/test-pattern")' in app


def test_help_points_panel_tests_to_display_setup_not_dashboard():
    help_html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    assert "use the Panel test card" in help_html or "Panel test card" in help_html
    dashboard = help_html.split('<section id="dashboard">', 1)[1].split('</section>', 1)[0]
    setup = help_html.split('<section id="setup">', 1)[1].split('</section>', 1)[0]
    assert "Panel tests" not in dashboard
    assert "Panel tests" in setup


def test_release_version_is_v0641_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 41)
