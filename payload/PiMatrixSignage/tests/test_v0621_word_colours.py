from pathlib import Path
import sys

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from renderer import _apply_sprite_color_effect


def test_colour_by_word_uses_actual_word_bounds_not_equal_width_slices():
    sprite = Image.new("RGBA", (50, 7), (255, 255, 255, 0))
    draw = ImageDraw.Draw(sprite)
    draw.rectangle((0, 0, 5, 6), fill=(255, 255, 255, 255))
    draw.rectangle((15, 0, 30, 6), fill=(255, 255, 255, 255))
    draw.rectangle((40, 0, 49, 6), fill=(255, 255, 255, 255))
    layer = {
        "text": "A WIDE END", "color_effect": "words",
        "color_palette": "#ff0000,#00ff00,#0000ff",
    }
    result = _apply_sprite_color_effect(sprite, layer, 0, "A WIDE END")
    assert result.getpixel((2, 3))[:3] == (255, 0, 0)
    assert result.getpixel((20, 3))[:3] == (0, 255, 0)
    assert result.getpixel((45, 3))[:3] == (0, 0, 255)
    assert {result.getpixel((x, 3))[:3] for x in range(15, 31)} == {(0, 255, 0)}


def test_release_version_is_v0621_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 21)
