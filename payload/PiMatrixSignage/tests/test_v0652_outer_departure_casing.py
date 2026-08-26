from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def _layer(**changes):
    layer = {
        "id": "v0652", "type": "text", "text": "WELCOME", "animation": "split-flap",
        "flap_board_style": "departure", "flap_cell_gap": 1, "flap_case_padding": 2,
        "flap_cycles": 4, "flap_stagger": .06, "flap_order": "left",
        "render_mode": "led5x7", "pixel_scale": 1, "pixel_bold": False,
        "font_size": 14, "auto_fit": False, "overflow": "manual",
        "padding": 0, "align": "center", "valign": "middle",
        "line_spacing": .12, "letter_spacing": 0, "color": "#ffffff",
        "outline_width": 0, "text_transform": "none", "effect_period": 1.5, "delay": 0,
    }
    layer.update(changes)
    return layer


def test_mechanical_cell_reserves_clear_space_between_frame_and_5x7_glyph():
    layout = renderer._split_flap_text_layout(_layer(), "A", 64, 32, 1, str(ROOT / "uploads/fonts"))
    cell_w, cell_h, child = layout[4], layout[5], layout[-1]
    # 5x7 glyph + (gap 1 + casing padding 2) on every side.
    assert cell_w >= 11
    assert cell_h >= 13
    assert child["_flap_content_inset_x"] >= 3
    assert child["_flap_content_inset_y"] >= 3


def test_casing_padding_control_actually_enlarges_physical_module():
    small = renderer._split_flap_text_layout(_layer(flap_case_padding=2), "A", 64, 32, 1, str(ROOT / "uploads/fonts"))
    large = renderer._split_flap_text_layout(_layer(flap_case_padding=5), "A", 64, 32, 1, str(ROOT / "uploads/fonts"))
    assert large[4] >= small[4] + 6
    assert large[5] >= small[5] + 6


def test_plain_split_flap_geometry_is_not_expanded_by_mechanical_casing_change():
    plain = renderer._split_flap_text_layout(_layer(flap_board_style="none"), "A", 64, 32, 1, str(ROOT / "uploads/fonts"))
    board = renderer._split_flap_text_layout(_layer(), "A", 64, 32, 1, str(ROOT / "uploads/fonts"))
    assert plain[4] == 6  # original 5x7 glyph + normal one-cell character gap
    assert plain[5] == 7
    assert board[4] > plain[4]
    assert board[5] > plain[5]


def test_rendered_departure_cell_has_frame_clearance_before_bright_glyph_pixels():
    image = renderer._render_split_flap_text(_layer(text="A"), 32, 20, 1, 2.0, datetime.now(), str(ROOT / "uploads/fonts"))
    # Find the physical frame (grey) and bright glyph.  There must be at least
    # one full output pixel between them horizontally and vertically.
    frame_pts, glyph_pts = [], []
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = image.getpixel((x, y))
            if a and 70 <= r <= 180 and 70 <= g <= 180 and 70 <= b <= 180:
                frame_pts.append((x, y))
            if a and r >= 220 and g >= 220 and b >= 220:
                glyph_pts.append((x, y))
    assert frame_pts and glyph_pts
    fx0, fx1 = min(x for x, _ in frame_pts), max(x for x, _ in frame_pts)
    fy0, fy1 = min(y for _, y in frame_pts), max(y for _, y in frame_pts)
    gx0, gx1 = min(x for x, _ in glyph_pts), max(x for x, _ in glyph_pts)
    gy0, gy1 = min(y for _, y in glyph_pts), max(y for _, y in glyph_pts)
    assert gx0 >= fx0 + 2 and gx1 <= fx1 - 2
    assert gy0 >= fy0 + 2 and gy1 <= fy1 - 2


def test_designer_exposes_casing_padding_and_defaults_existing_layers_safely():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert 'id="layerFlapCasePadding"' in html
    assert 'Casing padding (LED px)' in html
    assert "flap_case_padding:2" in js
    assert "if(l.flap_case_padding===undefined)l.flap_case_padding=2" in js
    assert "l.flap_case_padding=clamp" in js


def test_v0652_version():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.54"
