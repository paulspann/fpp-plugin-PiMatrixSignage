from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_support_package_panel_lives_only_on_diagnostics_page():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    diagnostics_start = html.index('id="page-diagnostics"')
    backup_start = html.index('id="page-backup"')
    users_start = html.index('id="page-users"')

    diagnostics_html = html[diagnostics_start:backup_start]
    backup_html = html[backup_start:users_start]

    assert 'id="systemSupportPackageCard"' in diagnostics_html
    assert '<h2>System support package</h2>' in diagnostics_html
    assert 'id="createSupportPackage"' in diagnostics_html
    assert 'id="supportIncludePreview"' in diagnostics_html
    assert '<h2>System support package</h2>' not in backup_html
    assert html.count('id="createSupportPackage"') == 1


def test_support_package_permission_matches_system_diagnostics():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    route = app.index('@app.get("/api/support-package")')
    function = app.index('def support_package_api():', route)
    decorator = app[route:function]
    assert '@permission_required("display_setup")' in decorator
    assert '@permission_required("backup")' not in decorator


def test_help_places_support_package_under_diagnostics():
    help_html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    diagnostics_start = help_html.index('<section id="diagnostics">')
    backup_start = help_html.index('<section id="backup">')
    users_start = help_html.index('<section id="users">')
    assert '<h3>System support package</h3>' in help_html[diagnostics_start:backup_start]
    assert '<h3>System support package</h3>' not in help_html[backup_start:users_start]
    assert 'System diagnostics and its System support package use the Display setup permission.' in help_html
