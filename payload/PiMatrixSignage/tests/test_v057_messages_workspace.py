from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_messages_library_and_editor_are_separate_full_width_views():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="messagesWorkspace"' in html
    assert 'messages-library-view' in html
    assert 'id="backToMessages"' in html
    assert 'id="importMessageLibraryFile"' in html
    assert '.messages-workspace.messages-library-view .messages-editor-card{display:none}' in css
    assert '.messages-workspace.messages-editor-view .messages-list-card{display:none}' in css
    assert 'function showMessageLibrary' in js
    assert 'function showMessageEditor' in js
    assert "showMessageEditor();state.selectedMessage=m.id" in js


def test_editor_tools_and_layers_move_into_left_rail():
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'message-editor-workspace' in css
    assert 'message-editor-rail' in css
    assert "designer?.querySelector('.designer-commandbar')" in js
    assert "designer?.querySelector('.designer-toolbar')" in js
    assert "designer?.querySelector('.designer-layer-panel')" in js


def test_release_version_is_0514_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 5, 14)
