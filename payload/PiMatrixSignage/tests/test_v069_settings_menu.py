from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_settings_destinations_are_in_cogwheel_menu_not_main_navigation():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    main_nav = html.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
    settings_menu = html.split('id="settingsMenu"', 1)[1].split('<div class="user-strip">', 1)[0]

    for tab in ("setup", "backup", "users"):
        assert f'data-tab="{tab}"' not in main_nav
        assert f'data-tab="{tab}"' in settings_menu

    assert 'id="settingsMenuToggle"' in settings_menu
    assert 'aria-haspopup="true"' in settings_menu


def test_settings_menu_keeps_existing_permission_gates():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    for tab, permission in (("setup", "display_setup"), ("backup", "backup"), ("users", "users")):
        assert f'data-tab="{tab}" data-permission="{permission}"' in html

    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "settingsItems.some(el=>can(el.dataset.permission))" in js
    assert "if (btn.dataset.tab === 'setup')" in js
    assert "if (btn.dataset.tab === 'backup')" in js
    assert "if (btn.dataset.tab === 'users')" in js


def test_release_version_is_v069_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 6, 9)
