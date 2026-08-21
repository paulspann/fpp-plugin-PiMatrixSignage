from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_diagnostics_has_dedicated_cog_page():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'data-tab="diagnostics" data-permission="display_setup"' in html
    assert '>System diagnostics</button>' in html
    assert 'id="page-diagnostics" data-permission="display_setup"' in html

    setup_start = html.index('id="page-setup"')
    diagnostics_start = html.index('id="page-diagnostics"')
    backup_start = html.index('id="page-backup"')
    assert setup_start < diagnostics_start < backup_start
    assert 'System diagnostics &amp; recovery' not in html[setup_start:diagnostics_start]
    assert 'System diagnostics &amp; recovery' in html[diagnostics_start:backup_start]


def test_diagnostics_polling_follows_dedicated_page():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "btn.dataset.tab === 'diagnostics') loadDiagnostics(true)" in js
    assert "function diagnosticsTabVisible()" in js
    assert "if(diagnosticsTabVisible())loadDiagnostics(false)" in js
    assert "if (btn.dataset.tab === 'setup') setSetupSubtab" in js
    assert "if(setupControlsVisible()&&can('display_setup'))loadGpioControls(false)" in js


def test_help_documents_new_diagnostics_location():
    help_html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    assert 'href="#diagnostics">System diagnostics &amp; recovery</a>' in help_html
    assert '<section id="diagnostics">' in help_html
    assert 'choose <strong>System diagnostics</strong>' in help_html
