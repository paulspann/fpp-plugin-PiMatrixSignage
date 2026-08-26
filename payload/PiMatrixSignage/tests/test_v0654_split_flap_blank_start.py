from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def _layer(**updates):
    layer = {
        "id": "blank-start", "type": "text", "enabled": True,
        "text": "OPEN", "animation": "split-flap", "effect_period": 2.0,
        "flap_cycles": 6, "flap_stagger": 0.08, "flap_order": "left",
        "font": "", "font_size": 12, "auto_fit": False, "overflow": "manual", "wrap": False,
        "color": "#ffffff", "outline_color": "#000000", "outline_width": 0,
        "padding": 0, "align": "left", "valign": "middle", "line_spacing": 0,
        "render_mode": "led5x7", "pixel_scale": 1, "pixel_bold": False, "letter_spacing": 0,
        "flap_board_style": "none",
    }
    layer.update(updates)
    return layer


def _scene(layer):
    return {
        "duration": 10, "design_width": 64, "design_height": 32,
        "background": {"mode": "solid", "color1": "#000000", "color2": "#000000"},
        "layers": [{**layer, "x": 0, "y": 0, "w": 64, "h": 32, "z": 1, "opacity": 100}],
    }


def _lit(im):
    return sum(1 for px in im.get_flattened_data() if max(px[:3]) > 0)


def test_first_appearance_sequence_uses_ordered_wheel_from_blank():
    assert renderer._split_flap_sequence(_layer(), "OPEN", 0, "O", 8) == [" ", *list("ABCDEFGHIJKLMNO")]


def test_blank_sequential_cell_uses_same_ordered_wheel():
    assert renderer._split_flap_transition_sequence(_layer(), "OPEN", 0, " ", "O", 8) == [" ", *list("ABCDEFGHIJKLMNO")]


def test_existing_character_transition_keeps_fake_flip_behaviour():
    seq = renderer._split_flap_transition_sequence(_layer(), "OPEN", 0, "A", "O", 4)
    assert seq[0] == "A"
    assert seq[-1] == "O"
    assert len(seq) > 2


def test_existing_character_can_still_rotate_through_to_blank():
    seq = renderer._split_flap_transition_sequence(_layer(), "OPEN", 0, "O", " ", 4)
    assert seq[0] == "O"
    assert seq[-1] == " "
    assert any(ch.strip() for ch in seq[1:-1])


def test_plain_split_flap_is_genuinely_blank_at_scene_start():
    now = datetime(2026, 8, 26, 15, 14)
    start = renderer.render_scene(_scene(_layer()), 64, 32, 0.0, now, "/tmp/no")
    during = renderer.render_scene(_scene(_layer()), 64, 32, 1.3, now, "/tmp/no")
    settled = renderer.render_scene(_scene(_layer()), 64, 32, 2.2, now, "/tmp/no")
    assert _lit(start) == 0
    assert _lit(during) > 0
    assert _lit(settled) > 0


def test_release_version_is_v0654():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.56"
