from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def _layer(**updates):
    layer = {
        "id": "ordered-wheel", "type": "text", "enabled": True,
        "text": "W7", "animation": "split-flap", "effect_period": 2.0,
        "flap_cycles": 4, "flap_stagger": 0.0, "flap_order": "left",
        "font": "", "font_size": 12, "auto_fit": False, "overflow": "manual", "wrap": False,
        "color": "#ffffff", "outline_color": "#000000", "outline_width": 0,
        "padding": 0, "align": "left", "valign": "middle", "line_spacing": 0,
        "render_mode": "led5x7", "pixel_scale": 1, "pixel_bold": False, "letter_spacing": 0,
        "flap_board_style": "none",
    }
    layer.update(updates)
    return layer


def _scene(text="W"):
    return {
        "duration": 10, "design_width": 64, "design_height": 32,
        "background": {"mode": "solid", "color1": "#000000", "color2": "#000000"},
        "layers": [{**_layer(text=text), "x": 0, "y": 0, "w": 64, "h": 32, "z": 1, "opacity": 100}],
    }


def test_blank_letter_flips_in_alphabetic_order_until_target():
    assert renderer._split_flap_blank_wheel("E") == [" ", "A", "B", "C", "D", "E"]
    assert renderer._split_flap_blank_wheel("W") == [" ", *list("ABCDEFGHIJKLMNOPQRSTUVW")]


def test_blank_digit_flips_numerically_until_target():
    assert renderer._split_flap_blank_wheel("0") == [" ", "0"]
    assert renderer._split_flap_blank_wheel("7") == [" ", *list("01234567")]


def test_lowercase_preserves_lowercase_wheel_and_punctuation_is_one_turn():
    assert renderer._split_flap_blank_wheel("d") == [" ", "a", "b", "c", "d"]
    assert renderer._split_flap_blank_wheel(":") == [" ", ":"]


def test_fake_flip_count_does_not_change_blank_start_wheel():
    low = renderer._split_flap_sequence(_layer(flap_cycles=1), "W", 0, "W", 1)
    high = renderer._split_flap_sequence(_layer(flap_cycles=12), "W", 0, "W", 12)
    assert low == high == [" ", *list("ABCDEFGHIJKLMNOPQRSTUVW")]


def test_intermediate_scene_frames_are_not_just_blank_or_final_w():
    now = datetime(2026, 8, 26, 15, 14)
    blank = renderer.render_scene(_scene("W"), 64, 32, 0.0, now, "/tmp/no")
    middle = renderer.render_scene(_scene("W"), 64, 32, 0.9, now, "/tmp/no")
    final = renderer.render_scene(_scene("W"), 64, 32, 2.1, now, "/tmp/no")
    assert list(middle.get_flattened_data()) != list(blank.get_flattened_data())
    assert list(middle.get_flattened_data()) != list(final.get_flattened_data())



def test_early_letter_settles_before_late_letter_at_same_mechanical_cadence():
    now = datetime(2026, 8, 26, 15, 14)
    a_mid = renderer.render_scene(_scene("A"), 64, 32, 0.4, now, "/tmp/no")
    a_final = renderer.render_scene(_scene("A"), 64, 32, 2.1, now, "/tmp/no")
    w_mid = renderer.render_scene(_scene("W"), 64, 32, 0.4, now, "/tmp/no")
    w_final = renderer.render_scene(_scene("W"), 64, 32, 2.1, now, "/tmp/no")
    assert list(a_mid.get_flattened_data()) == list(a_final.get_flattened_data())
    assert list(w_mid.get_flattened_data()) != list(w_final.get_flattened_data())

def test_release_version_is_v0657():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.57"
