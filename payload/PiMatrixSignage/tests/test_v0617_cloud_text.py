from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from renderer import _cloud_text_entries, _render_cloud_text


START = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def opaque_text(_layer, width, height, *_args):
    return Image.new("RGBA", (width, height), (255, 255, 255, 255))


def test_cloud_text_cleans_entries_and_caps_untrusted_lists():
    assert _cloud_text_entries({"cloud_text_items": " Message 1\n\nMessage 2 "}) == ["Message 1", "Message 2"]
    assert len(_cloud_text_entries({"cloud_text_items": [str(i) for i in range(250)]})) == 200


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


def test_simultaneous_phrases_use_separate_in_bounds_areas():
    layer = {
        "id": "cloud-layout", "cloud_text_items": "One\nTwo\nThree",
        "cloud_visible_for": 3, "cloud_interval": 1, "cloud_max_visible": 3,
        "cloud_fade_in": 0, "cloud_fade_out": 0, "cloud_gap": 2,
    }
    with patch("renderer._render_scene_text", side_effect=opaque_text):
        image = _render_cloud_text(layer, 96, 32, 1, 2.5, START + timedelta(seconds=2.5), "")
    alpha = image.getchannel("A")
    assert alpha.getbbox() == (2, 2, 94, 30)
    assert alpha.crop((30, 0, 34, 32)).getbbox() is None
    assert alpha.crop((62, 0, 66, 32)).getbbox() is None


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
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.17"
