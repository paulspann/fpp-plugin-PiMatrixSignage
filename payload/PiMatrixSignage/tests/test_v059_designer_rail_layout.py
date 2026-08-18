from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_template_toolbar_does_not_expand_vertically_in_designer_rail():
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    assert ".message-editor-rail .template-library-toolbar{flex:0 0 auto!important;min-height:0}" in css


def test_designer_rail_uses_compact_control_grids():
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    assert "grid-template-columns:repeat(8,minmax(0,1fr))" in css
    assert ".message-editor-rail .designer-toolbar>.toolbar:last-child{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}" in css
    assert ".message-editor-workspace{grid-template-columns:minmax(310px,330px) minmax(0,1fr)}" in css


def test_release_version_is_0514_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 5, 14)
