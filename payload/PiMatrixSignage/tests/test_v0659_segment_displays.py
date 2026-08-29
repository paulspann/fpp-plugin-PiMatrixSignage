from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def _layer(animation="seven-segment", text="12:34", **updates):
    layer = {
        "type": "text", "text": text, "animation": animation,
        "color": "#ff3030", "padding": 0,
        "align": "center", "valign": "middle",
        "font": "ignored.ttf", "font_size": 99,
        "render_mode": "smooth", "auto_fit": False,
    }
    layer.update(updates)
    return layer


def _flat(image):
    return list(image.get_flattened_data())


def test_segment_payloads_keep_cells_and_apply_the_supported_alphabet():
    assert renderer._segment_text("12:34.5", 7) == "12:34.5"
    assert renderer._segment_text("AbCd-EF", 7) == "ABCD-EF"
    assert renderer._segment_text("Hello 2026!", 14) == "HELLO 2026 "
    assert len(renderer._segment_text("A" * 40, 14)) == 32


def test_seven_segment_uses_distinct_physical_digit_bars():
    now = datetime(2026, 8, 28, 21, 34)
    one = renderer._render_segment_text(_layer(text="1"), 32, 32, 1, 0, now, 7)
    eight = renderer._render_segment_text(_layer(text="8"), 32, 32, 1, 0, now, 7)
    one_lit = sum(1 for pixel in _flat(one) if pixel[3] > 200)
    eight_lit = sum(1 for pixel in _flat(eight) if pixel[3] > 200)
    assert one_lit > 0
    assert eight_lit > one_lit


def test_fourteen_segment_renders_diagonals_and_uppercase_letters():
    now = datetime(2026, 8, 28, 21, 34)
    display = renderer._render_segment_text(
        _layer(animation="fourteen-segment", text="MATRIX", color="#32ff66"),
        128, 32, 1, 0, now, 14,
    )
    pixels = _flat(display)
    assert any(pixel[3] == 255 and pixel[1] > pixel[0] for pixel in pixels)
    assert renderer._segment_names(renderer._FOURTEEN_SEGMENT_GLYPHS["X"]) == {"h", "i", "j", "k"}


def test_segment_faces_ignore_font_and_normal_text_rendering_controls():
    now = datetime(2026, 8, 28, 21, 34)
    a = renderer._render_segment_text(_layer(font="A.ttf", render_mode="smooth"), 96, 32, 1, 0, now, 7)
    b = renderer._render_segment_text(_layer(font="B.ttf", render_mode="led3x5", font_size=4), 96, 32, 1, 0, now, 7)
    assert _flat(a) == _flat(b)


def test_segment_modes_support_live_tokens_and_are_exposed_in_designer():
    now = datetime(2026, 8, 28, 21, 34)
    assert renderer._segment_text(renderer._layer_text_value(_layer(text="{TIME}"), now, 0), 7) == "21:34"
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert 'value="seven-segment">7-segment LED display' in html
    assert 'value="fourteen-segment">14-segment LED display' in html
    assert "['seven-segment','fourteen-segment'].includes(animation)" in js
    assert "['nixie','seven-segment','fourteen-segment'].includes(l.animation)" in js


def test_release_version_is_v0659():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.59"
