from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_internal_native_colour_input_is_never_enhanced_again():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'input[type="color"]:not(.colour-native-picker)' in js
    assert "{name:'Black',value:'#000000'}" in js
    assert "{name:'White',value:'#ffffff'}" in js


def test_preset_selection_applies_then_closes_popover():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    handler = "applyColourToActive(b.dataset.presetColour);refreshColourPopover();closeColourPopover();"
    assert handler in js


def test_release_version_is_v0623_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 23)
