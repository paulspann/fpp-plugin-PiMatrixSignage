from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def _layer(**updates):
    layer = {
        "id": "nixie", "type": "text", "enabled": True,
        "text": "12345678", "animation": "nixie",
        "font": "made-up-font.ttf", "font_size": 99, "auto_fit": False,
        "wrap": True, "render_mode": "smooth", "pixel_scale": 8,
        "pixel_bold": True, "letter_spacing": 7,
        "color": "#00ff00", "outline_color": "#ff00ff", "outline_width": 5,
        "padding": 0, "align": "center", "valign": "middle", "line_spacing": 0,
        "text_transform": "upper", "line_display": "together",
    }
    layer.update(updates)
    return layer


def _flat(im):
    return list(im.get_flattened_data())


def test_nixie_payload_is_digits_only_and_hard_capped_at_eight():
    assert renderer._nixie_digits("12A34-56.7890") == "12345678"
    assert renderer._nixie_digits("abcdefgh") == ""


def test_nixie_uses_fixed_builtin_face_not_user_font_or_rendering_controls():
    now = datetime(2026, 8, 26, 15, 14)
    a = renderer._render_nixie_text(_layer(font="A.ttf", render_mode="smooth", font_size=90), 128, 32, 1, 0, now)
    b = renderer._render_nixie_text(_layer(font="B.ttf", render_mode="led3x5", font_size=5, pixel_bold=False), 128, 32, 1, 0, now)
    assert _flat(a) == _flat(b)


def test_ninth_and_later_digits_are_not_rendered():
    now = datetime(2026, 8, 26, 15, 14)
    eight = renderer._render_nixie_text(_layer(text="12345678"), 128, 32, 1, 0, now)
    ten = renderer._render_nixie_text(_layer(text="1234567890"), 128, 32, 1, 0, now)
    assert _flat(eight) == _flat(ten)


def test_nixie_renders_glowing_tube_pixels_on_low_resolution_canvas():
    now = datetime(2026, 8, 26, 15, 14)
    im = renderer._render_nixie_text(_layer(text="1800"), 64, 32, 1, 0, now)
    pixels = _flat(im)
    assert any(px[3] > 0 for px in pixels)
    assert any(px[0] > 180 and px[1] > 60 and px[2] < 180 for px in pixels)
    # Fixed dark glass means the tube cell is visibly more than just the digit strokes.
    assert any(px[3] > 100 and px[0] < 100 for px in pixels)


def test_nixie_animation_option_and_designer_constraints_are_present():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert 'value="nixie">Nixie tubes – digits only' in html
    assert 'maximum 8 digits' in html
    assert "replace(/\\D/g,'').slice(0,8)" in js
    for field in ("layerFont", "layerFontSize", "layerRenderMode", "layerPixelScale"):
        assert field in js
    assert "el.disabled=nixie" in js


def test_release_version_is_v0657():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.58"
