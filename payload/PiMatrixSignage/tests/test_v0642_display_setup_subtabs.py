from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _setup_section() -> str:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    return html.split('id="page-setup"', 1)[1].split('id="page-diagnostics"', 1)[0]


def _pane(setup: str, name: str, next_name: str | None = None) -> str:
    start = setup.split(f'id="setup-pane-{name}"', 1)[1]
    if next_name:
        return start.split(f'id="setup-pane-{next_name}"', 1)[0]
    return start


def test_display_setup_has_five_task_based_subtabs():
    setup = _setup_section()
    expected = {
        "display": "Display",
        "profiles": "Profiles",
        "testing": "Testing &amp; commissioning",
        "controls": "Physical controls",
        "controller": "Controller &amp; FPP",
    }
    for key, label in expected.items():
        assert f'data-setup-tab="{key}"' in setup
        assert f'id="setup-pane-{key}"' in setup
        assert label in setup
    assert setup.count('<button class="setup-subtab') == 5
    assert 'class="setup-subtab active" data-setup-tab="display"' in setup
    assert 'class="setup-pane active" id="setup-pane-display"' in setup


def test_cards_are_grouped_by_task_in_the_expected_panes():
    setup = _setup_section()
    display = _pane(setup, "display", "profiles")
    profiles = _pane(setup, "profiles", "testing")
    testing = _pane(setup, "testing", "controls")
    controls = _pane(setup, "controls", "controller")
    controller = _pane(setup, "controller")

    assert "Panel layout" in display and "Display output" in display
    assert "Hardware profiles &amp; sample configurations" in profiles
    assert "Panel test" in testing and "Colorlight setup &amp; commissioning" in testing
    assert "GPIO / physical controls" in controls
    for title in ("Software licence", "FPP setup helper", "Raspberry Pi power"):
        assert title in controller

    assert "Software licence" not in display
    assert "GPIO / physical controls" not in display
    assert "FPP setup helper" not in display


def test_subtab_state_is_remembered_and_keyboard_accessible():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "const SETUP_SUBTAB_KEY='pimatrixSetupSection'" in js
    assert "function setSetupSubtab" in js
    assert "localStorage.setItem(SETUP_SUBTAB_KEY,name)" in js
    assert "ArrowLeft" in js and "ArrowRight" in js and "Home" in js and "End" in js
    assert "aria-selected" in js
    assert "btn.tabIndex=active?0:-1" in js


def test_licence_banner_opens_controller_subtab():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    body = js.split("function openLicenceSetup()", 1)[1].split("function", 1)[0]
    assert "setSetupSubtab('controller')" in body
    assert "licenceCard" in body


def test_gpio_live_polling_only_runs_on_physical_controls_subtab():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "function setupControlsVisible()" in js
    body = js.split("function setupControlsVisible()", 1)[1].split("function", 1)[0]
    assert "currentSetupSubtab()==='controls'" in body
    assert "if(setupControlsVisible()&&can('display_setup'))loadGpioControls(false)" in js


def test_help_documents_new_display_setup_structure():
    help_html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    assert "Display Setup is split into five task-based sub-tabs" in help_html
    for label in ("Display", "Profiles", "Testing &amp; commissioning", "Physical controls", "Controller &amp; FPP"):
        assert label in help_html
    assert "Open Display setup → <strong>Testing &amp; commissioning</strong>" in help_html


def test_release_version_is_v0642_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 42)
