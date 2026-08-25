from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def _layer(**changes):
    layer = {
        "type": "text", "text": "A B", "animation": "split-flap",
        "flap_board_style": "departure", "flap_cell_gap": 1,
        "render_mode": "led5x7", "pixel_scale": 1, "pixel_bold": False,
        "font_size": 14, "auto_fit": False, "overflow": "manual",
        "padding": 0, "align": "center", "valign": "middle",
        "line_spacing": .12, "letter_spacing": 0,
    }
    layer.update(changes)
    return layer


def test_departure_casing_reserves_real_led_space_around_glyph():
    plain = _layer(flap_board_style="none")
    board = _layer(flap_board_style="departure")
    p = renderer._split_flap_text_layout(plain, "ABC", 128, 32, 1, str(Path("uploads/fonts")))
    b = renderer._split_flap_text_layout(board, "ABC", 128, 32, 1, str(Path("uploads/fonts")))
    assert b[4] >= p[4] + 2  # cell width: one physical LED each side
    assert b[5] >= p[5] + 2  # cell height: one physical LED top/bottom


def test_departure_cell_has_visible_gap_frame_and_two_flap_faces():
    cell = renderer._split_flap_board_cell(_layer(), 10, 9)
    assert cell is not None
    assert cell.getpixel((0, 0))[3] == 0  # transparent module gap
    border = cell.getpixel((1, 1))
    assert border[0] >= 80 and border[3] == 255
    # Upper and lower halves deliberately have different luminance.
    assert cell.getpixel((3, 2))[:3] != cell.getpixel((3, 6))[:3]


def test_departure_hinge_overlay_is_drawn_above_the_character():
    overlay = renderer._split_flap_board_overlay(_layer(), 10, 9)
    assert overlay is not None
    seam_y = (1 + (9 - 1 - 1)) // 2
    middle = overlay.getpixel((5, seam_y))
    assert middle[:3] == (0, 0, 0)
    assert middle[3] == 255


def test_named_departure_and_airport_presets_force_at_least_one_led_gap():
    for style in ("departure", "airport"):
        cell = renderer._split_flap_board_cell(_layer(flap_board_style=style, flap_cell_gap=0), 10, 9)
        assert cell is not None
        assert cell.getpixel((0, 0))[3] == 0
        assert cell.getpixel((1, 1))[3] == 255
