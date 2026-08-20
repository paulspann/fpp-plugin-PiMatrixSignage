from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_support_package_panel_explains_how_to_request_support():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index('id="systemSupportPackageCard"')
    end = html.index('</article>', start)
    panel = html[start:end]

    assert "Requesting support:" in panel
    assert "support@issl.co.uk" in panel
    assert "mailto:support@issl.co.uk?subject=Pi%20Matrix%20Signage%20support" in panel
    assert "what you expected to happen" in panel
    assert "what actually happened" in panel
    assert "approximate date/time" in panel
    assert "attach the generated ZIP" in panel
    assert "screenshot or photo" in panel
    assert "rather than extracting or editing" in panel


def test_help_documents_support_email_and_zip_workflow():
    html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    diagnostics_start = html.index('<section id="diagnostics">')
    diagnostics_end = html.index('</section>', diagnostics_start)
    section = html[diagnostics_start:diagnostics_end]

    assert "support@issl.co.uk" in section
    assert "Attach the generated support-package ZIP" in section
    assert "without extracting or editing it" in section
