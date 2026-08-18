from pathlib import Path


def test_file_import_buttons_do_not_inherit_form_label_spacing():
    css=(Path(__file__).resolve().parents[1]/"static"/"app.css").read_text(encoding="utf-8")
    assert ".file-btn.btn{display:inline-flex;align-items:center;justify-content:center;margin:0;flex-direction:row;gap:0}" in css


def test_message_and_playlist_imports_use_file_button_class():
    html=(Path(__file__).resolve().parents[1]/"templates"/"index.html").read_text(encoding="utf-8")
    assert 'id="importMessageFile"' in html and 'compact-file-btn' in html
    assert 'id="importPlaylistFile"' in html and 'compact-file-btn' in html
