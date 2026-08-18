from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_messages_ui_is_designer_only():
    html = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
    assert '>Editor mode<' not in html
    assert 'id="msgEditorMode" value="designer"' in html
    assert 'id="quickEditor" hidden' in html
    assert 'id="designerEditor"' in html
