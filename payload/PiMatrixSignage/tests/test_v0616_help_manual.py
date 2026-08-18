from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_top_bar_help_opens_new_tab_at_current_page_section():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="helpLink"' in html
    assert 'href="/help#dashboard"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener"' in html
    assert "function syncHelpLink(page='dashboard')" in js
    assert "syncHelpLink(btn.dataset.tab)" in js


def test_help_route_and_searchable_manual_are_packaged():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    manual = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    assert '@app.get("/help")' in app_py
    assert 'render_template("help.html", app_version=APP_VERSION)' in app_py
    assert (ROOT / "static" / "help.css").is_file()
    assert 'id="helpSearch"' in manual
    assert 'target="_blank"' not in manual


def test_manual_has_section_for_every_application_page_and_core_workflow():
    manual = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    for section in (
        "dashboard", "messages", "playlists", "schedules", "setup", "backup", "users",
        "getting-started", "shaders", "remote", "maintenance", "troubleshooting", "reference",
    ):
        assert f'id="{section}"' in manual
        assert f'href="#{section}"' in manual
    for topic in (
        "WHMCS", "Designer", "Sky Weather", "Open-Meteo", "Emergency mode",
        "Playback priority", "Portable content", "GPIO", "rollback",
    ):
        assert topic in manual


def test_release_version_is_v0616_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 6, 16)
