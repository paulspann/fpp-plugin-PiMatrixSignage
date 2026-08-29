from datetime import datetime
from pathlib import Path
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def _alpha_pixels(im):
    return sum(1 for px in im.get_flattened_data() if px[3] > 0)


def _lit(im):
    return sum(1 for px in im.get_flattened_data() if max(px[:3]) > 0)


def _layer(**updates):
    layer = {
        "id": "physical-turn", "type": "text", "enabled": True,
        "text": "8", "animation": "split-flap", "effect_period": 2.0,
        "flap_cycles": 6, "flap_stagger": 0.0, "flap_order": "left",
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
        "duration": 10, "design_width": 32, "design_height": 16,
        "background": {"mode": "solid", "color1": "#000000", "color2": "#000000"},
        "layers": [{**layer, "x": 0, "y": 0, "w": 32, "h": 16, "z": 1, "opacity": 100}],
    }


def test_blank_to_character_unfolds_progressively_from_hinge():
    src = Image.new("RGBA", (9, 11), (0, 0, 0, 0))
    dst = Image.new("RGBA", (9, 11), (0, 0, 0, 0))
    ImageDraw.Draw(dst).rectangle((1, 1, 7, 9), fill=(255, 255, 255, 255))

    frames = [renderer._split_flap_cell(src, dst, p, True) for p in (0.0, 0.2, 0.5, 0.8, 1.0)]
    counts = [_alpha_pixels(frame) for frame in frames]
    assert counts[0] == 0
    assert 0 < counts[1] < counts[2] < counts[3] <= counts[4]
    assert frames[1].getbbox() != frames[-1].getbbox()


def test_character_to_blank_folds_progressively_instead_of_dropping_halfway():
    src = Image.new("RGBA", (9, 11), (0, 0, 0, 0))
    ImageDraw.Draw(src).rectangle((1, 1, 7, 9), fill=(255, 255, 255, 255))
    dst = Image.new("RGBA", src.size, (0, 0, 0, 0))
    counts = [_alpha_pixels(renderer._split_flap_cell(src, dst, p, True)) for p in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert counts[0] > counts[1] > counts[2] > counts[3] > counts[4] == 0


def test_real_split_flap_scene_has_visible_partial_target_before_settling():
    now = datetime(2026, 8, 26, 15, 14)
    scene = _scene(_layer())
    start = renderer.render_scene(scene, 32, 16, 0.0, now, "/tmp/no")
    early = renderer.render_scene(scene, 32, 16, 0.45, now, "/tmp/no")
    middle = renderer.render_scene(scene, 32, 16, 1.0, now, "/tmp/no")
    settled = renderer.render_scene(scene, 32, 16, 2.1, now, "/tmp/no")
    assert _lit(start) == 0
    assert 0 < _lit(early) < _lit(settled)
    # An exact mechanical hinge crossing may briefly have no lit glyph pixels.
    assert _lit(middle) <= _lit(settled)
    assert list(early.get_flattened_data()) != list(settled.get_flattened_data())
    assert list(middle.get_flattened_data()) != list(settled.get_flattened_data())


def test_blank_start_uses_ordered_not_random_intermediate_characters():
    expected = [" ", *list("ABCDEFGHIJKLMNO")]
    assert renderer._split_flap_sequence(_layer(text="OPEN"), "OPEN", 0, "O", 8) == expected
    assert renderer._split_flap_transition_sequence(_layer(text="OPEN"), "OPEN", 0, " ", "O", 8) == expected


def test_release_version_is_v0655():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.59"
