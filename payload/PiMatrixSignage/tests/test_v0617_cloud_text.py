from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from renderer import _cloud_random_position, _cloud_text_entries, _led_wrap, _render_cloud_text, _wrap_text_pixels


START = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def opaque_text(_layer, width, height, *_args):
    return Image.new("RGBA", (width, height), (255, 255, 255, 255))


def test_cloud_text_cleans_entries_and_caps_untrusted_lists():
    assert _cloud_text_entries({"cloud_text_items": " Message 1\n\nMessage 2 "}) == ["Message 1", "Message 2"]
    assert len(_cloud_text_entries({"cloud_text_items": [str(i) for i in range(250)]})) == 200


def test_cloud_text_wrapping_never_splits_a_word():
    font = ImageFont.load_default()
    draw = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    wrapped = _wrap_text_pixels("LONGWORD short", font, 24, draw, break_long_words=False)
    assert wrapped.splitlines() == ["LONGWORD", "short"]
    assert _led_wrap("ABCDEFGHIJ next", 4, break_long_words=False).splitlines() == ["ABCDEFGHIJ", "next"]


def test_every_phrase_appears_once_before_the_list_repeats():
    seen = []

    def capture(layer, width, height, *_args):
        seen.append(layer["text"])
        return Image.new("RGBA", (width, height), (255, 255, 255, 255))

    layer = {
        "id": "cloud-order", "cloud_text_items": "One\nTwo\nThree",
        "cloud_visible_for": 0.8, "cloud_interval": 1, "cloud_max_visible": 1,
        "cloud_fade_in": 0, "cloud_fade_out": 0,
    }
    with patch("renderer._render_scene_text", side_effect=capture):
        for occurrence in range(3):
            elapsed = occurrence + 0.4
            _render_cloud_text(layer, 96, 32, 1, elapsed, START + timedelta(seconds=elapsed), "")
    assert len(seen) == 3
    assert set(seen) == {"One", "Two", "Three"}


def test_cloud_renderer_disables_long_word_splitting():
    rendered = []

    def capture(layer, width, height, *_args):
        rendered.append(layer)
        return Image.new("RGBA", (width, height), (255, 255, 255, 255))

    layer = {"cloud_text_items": "DoNotSplitThisWord", "cloud_fade_in": 0, "cloud_fade_out": 0}
    with patch("renderer._render_scene_text", side_effect=capture):
        _render_cloud_text(layer, 64, 32, 1, 1, START + timedelta(seconds=1), "")
    assert rendered[0]["break_long_words"] is False


def test_cloud_text_fades_in_and_out_over_its_visible_lifetime():
    layer = {
        "id": "cloud-fade", "cloud_text_items": "Hello", "cloud_visible_for": 3,
        "cloud_interval": 1, "cloud_max_visible": 1, "cloud_fade_in": 1,
        "cloud_fade_out": 1, "cloud_gap": 0,
    }
    with patch("renderer._render_scene_text", side_effect=opaque_text):
        alpha_in = _render_cloud_text(layer, 32, 16, 1, 0.5, START + timedelta(seconds=0.5), "").getchannel("A")
        alpha_full = _render_cloud_text(layer, 32, 16, 1, 1.5, START + timedelta(seconds=1.5), "").getchannel("A")
        alpha_out = _render_cloud_text(layer, 32, 16, 1, 2.5, START + timedelta(seconds=2.5), "").getchannel("A")
    assert 120 <= alpha_in.getextrema()[1] <= 130
    assert alpha_full.getextrema()[1] == 255
    assert 120 <= alpha_out.getextrema()[1] <= 130


def test_simultaneous_phrases_use_random_non_overlapping_positions():
    occupied = []
    positions = []
    for seed in (101, 202, 303):
        position = _cloud_random_position(20, 6, 96, 32, 2, occupied, __import__("random").Random(seed))
        assert position is not None
        x, y = position
        assert 0 <= x <= 76 and 0 <= y <= 26
        rect = (x, y, x + 20, y + 6)
        for ox0, oy0, ox1, oy1 in occupied:
            assert rect[2] + 2 <= ox0 or rect[0] - 2 >= ox1 or rect[3] + 2 <= oy0 or rect[1] - 2 >= oy1
        occupied.append(rect)
        positions.append(position)
    assert len({y for _x, y in positions}) > 1
    assert [x for x, _y in positions] != sorted(x for x, _y in positions)


def test_cloud_text_designer_controls_and_release_version():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for marker in (
        "addCloudTextLayer", "cloudTextItems", "cloudTextInterval", "cloudTextVisibleFor",
        "cloudTextFadeIn", "cloudTextFadeOut", "cloudTextMaxVisible", "cloudTextGap",
        "cloudTextFont", "cloudTextRenderMode", "cloudTextColorMode", "cloudTextPalette",
    ):
        assert marker in html
        assert marker in js
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 17)
