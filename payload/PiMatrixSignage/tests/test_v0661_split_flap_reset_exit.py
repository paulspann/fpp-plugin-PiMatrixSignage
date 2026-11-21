from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def _layer(**updates):
    layer = {
        "id": "reset-board", "name": "Reset board", "type": "text", "enabled": True,
        "text": "AZ9", "animation": "split-flap", "delay": 0,
        "effect_period": 1.0, "flap_cycles": 4, "flap_stagger": 0.06,
        "flap_order": "left", "flap_board_style": "departure",
        "flap_cell_gap": 1, "flap_case_padding": 2,
        "render_mode": "led5x7", "pixel_scale": 1, "pixel_bold": False,
        "font_size": 12, "auto_fit": True, "wrap": False, "overflow": "manual",
        "letter_spacing": 0, "line_spacing": 0.12, "padding": 0,
        "color": "#ffffff", "outline_color": "#000000", "outline_width": 0,
        "align": "center", "valign": "middle", "text_transform": "none",
        "entrance_effect": "none", "entrance_duration": 0.5,
        "exit_effect": "reset-slats", "exit_after": 2.0, "exit_duration": 1.0,
        "opacity": 100, "rotation": 0, "x": 0, "y": 0, "w": 64, "h": 32, "z": 1,
    }
    layer.update(updates)
    return layer


def _bright_count(image):
    return sum(1 for r, g, b, a in image.get_flattened_data() if a > 0 and max(r, g, b) > 200)


def test_reset_wheel_advances_forward_to_the_physical_blank_card():
    assert renderer._split_flap_reset_wheel("A") == [*"ABCDEFGHIJKLMNOPQRSTUVWXYZ", " "]
    assert renderer._split_flap_reset_wheel("X") == ["X", "Y", "Z", " "]
    assert renderer._split_flap_reset_wheel("7") == ["7", "8", "9", " "]
    assert renderer._split_flap_reset_wheel(":") == [":", " "]
    assert renderer._split_flap_reset_wheel(" ") == [" "]


def test_completed_reset_remains_as_blank_physical_modules():
    now = datetime(2026, 9, 9, 22, 30)
    start = renderer._render_split_flap_text(
        _layer(_flap_reset_progress=0.0, _flap_reset_duration=1.0), 64, 32, 1, 0, now, ""
    )
    middle = renderer._render_split_flap_text(
        _layer(_flap_reset_progress=0.5, _flap_reset_duration=1.0), 64, 32, 1, 0, now, ""
    )
    blank = renderer._render_split_flap_text(
        _layer(_flap_reset_progress=1.0, _flap_reset_duration=1.0), 64, 32, 1, 0, now, ""
    )
    assert _bright_count(start) > 0
    assert list(middle.get_flattened_data()) != list(start.get_flattened_data())
    assert _bright_count(blank) == 0
    assert blank.getchannel("A").getbbox() is not None  # casing and blank cards remain


def test_reset_exit_stays_visible_at_blank_while_normal_exit_disappears():
    effect, progress, entering, visible = renderer._layer_transition_phase(_layer(), 3.2)
    assert (effect, progress, entering, visible) == ("reset-slats", 1.0, False, True)
    effect, progress, entering, visible = renderer._layer_transition_phase(_layer(exit_effect="fade"), 3.2)
    assert effect == "fade" and progress == 1.0 and not entering and not visible
    # Imported/hand-edited scenes cannot make an incompatible normal text layer
    # persist indefinitely by assigning the split-flap-only exit value.
    effect, progress, entering, visible = renderer._layer_transition_phase(
        _layer(animation="static"), 3.2
    )
    assert effect == "reset-slats" and progress == 1.0 and not entering and not visible


def test_forced_message_exit_drives_the_board_to_blank():
    now = datetime(2026, 9, 9, 22, 30)
    scene = {
        "design_width": 64, "design_height": 32, "duration": 10,
        "background": {"mode": "solid", "color1": "#000000"},
        "layers": [_layer(exit_after=0)],
    }
    start = renderer.render_scene(scene, 64, 32, 5, now, "", forced_exit_elapsed=0.0)
    finished = renderer.render_scene(scene, 64, 32, 5, now, "", forced_exit_elapsed=1.0)
    assert _bright_count(start.convert("RGBA")) > 0
    assert _bright_count(finished.convert("RGBA")) == 0
    assert finished.getbbox() is not None


def test_designer_only_offers_reset_slats_for_split_flap_text():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert '<option value="reset-slats">Reset slats to blank</option>' in html
    assert 'option[value="reset-slats"]' in js
    assert "resetOption.disabled=!flap" in js


def test_release_version_is_v0661():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.7.1"
