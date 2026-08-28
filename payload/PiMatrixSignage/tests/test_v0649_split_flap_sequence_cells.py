from pathlib import Path
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def _layer(**updates):
    layer = {
        "id": "flap-seq", "type": "text", "enabled": True,
        "text": "ABCDE\nAB", "line_display": "sequence", "delay": 0,
        "animation": "split-flap", "effect_period": 2.0,
        "flap_cycles": 3, "flap_stagger": 0.0, "flap_order": "left",
        "font": "", "font_size": 12, "auto_fit": False, "overflow": "manual", "wrap": False,
        "color": "#ffffff", "outline_color": "#000000", "outline_width": 0,
        "padding": 0, "align": "left", "valign": "middle", "line_spacing": 0,
        "render_mode": "led5x7", "pixel_scale": 1, "pixel_bold": False, "letter_spacing": 0,
    }
    layer.update(updates)
    return layer


def _scene(layer):
    return {
        "duration": 20, "design_width": 64, "design_height": 32,
        "background": {"mode": "solid", "color1": "#000000", "color2": "#000000"},
        "layers": [{**layer, "x": 0, "y": 0, "w": 64, "h": 32, "z": 1, "opacity": 100}],
    }


def _lit_in_x(im, x0, x1):
    px = im.load()
    return sum(1 for y in range(im.height) for x in range(x0, x1) if max(px[x, y][:3]) > 0)


def test_sequence_child_carries_previous_line_context_for_physical_flaps():
    first, _ = renderer._sequenced_text_layer(_layer(), 0.0, 20.0)
    second, _ = renderer._sequenced_text_layer(_layer(), 10.0, 20.0)
    assert first["_line_sequence_previous_text"] == ""
    assert second["_line_sequence_previous_text"] == "ABCDE"
    assert second["_line_sequence_lines"] == ["ABCDE", "AB"]


def test_fixed_board_padding_uses_same_cell_bank_for_all_alignments():
    assert renderer._split_flap_fixed_row("AB", 5, "left") == "AB   "
    assert renderer._split_flap_fixed_row("AB", 5, "right") == "   AB"
    assert renderer._split_flap_fixed_row("AB", 5, "center") == " AB  "


def test_transition_to_blank_has_real_intermediate_flaps_and_finishes_blank():
    seq = renderer._split_flap_transition_sequence(_layer(), "AB   ", 2, "C", " ", 3)
    assert seq[0] == "C"
    assert seq[-1] == " "
    assert any(ch.strip() for ch in seq[1:-1])


def test_second_line_starts_from_previous_settled_board_without_position_jump():
    scene = _scene(_layer())
    now = datetime(2026, 8, 25, 9, 30)
    before = renderer.render_scene(scene, 64, 32, 9.9, now, "/tmp/no")
    boundary = renderer.render_scene(scene, 64, 32, 10.0, now, "/tmp/no")
    assert list(before.get_flattened_data()) == list(boundary.get_flattened_data())


def test_surplus_cells_flip_to_blank_instead_of_disappearing_at_line_change():
    scene = _scene(_layer())
    now = datetime(2026, 8, 25, 9, 30)
    boundary = renderer.render_scene(scene, 64, 32, 10.0, now, "/tmp/no")
    mid = renderer.render_scene(scene, 64, 32, 10.5, now, "/tmp/no")
    settled = renderer.render_scene(scene, 64, 32, 12.2, now, "/tmp/no")
    # With 5x7 at 1x the first two cells occupy x=0..11; C/D/E are x>=12.
    assert _lit_in_x(boundary, 12, 64) > 0
    assert _lit_in_x(mid, 12, 64) > 0
    assert _lit_in_x(settled, 12, 64) == 0
    # The unchanged A/B cells remain in exactly the same physical positions.
    assert list(boundary.crop((0, 0, 12, 32)).get_flattened_data()) == list(settled.crop((0, 0, 12, 32)).get_flattened_data())


def test_designer_and_help_explain_fixed_cell_blank_transition():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    help_html = (ROOT / "templates/help.html").read_text(encoding="utf-8")
    assert "fixed bank of character cells" in html
    assert "rotate to blank" in help_html


def test_release_version_is_v0649():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.58"
