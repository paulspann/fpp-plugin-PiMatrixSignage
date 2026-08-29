from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer
from renderer import _sequenced_text_layer
from datetime import datetime
from PIL import Image


def _layer(**updates):
    layer = {
        "id": "L1", "type": "text", "text": "FIRST\nSECOND\nTHIRD",
        "line_display": "sequence", "delay": 0, "exit_after": 0,
        "animation": "static",
    }
    layer.update(updates)
    return layer


def test_three_lines_share_thirty_second_timeline_evenly():
    layer = _layer()
    first, first_t = _sequenced_text_layer(layer, 0.0, 30.0)
    still_first, _ = _sequenced_text_layer(layer, 9.99, 30.0)
    second, second_t = _sequenced_text_layer(layer, 10.0, 30.0)
    third, third_t = _sequenced_text_layer(layer, 20.0, 30.0)
    assert first["text"] == still_first["text"] == "FIRST"
    assert second["text"] == "SECOND"
    assert third["text"] == "THIRD"
    assert first["_line_sequence_slot"] == 10.0
    assert first_t == second_t == third_t == 0.0


def test_blank_lines_do_not_consume_a_sequence_slot():
    layer = _layer(text="FIRST\n\n   \nSECOND\nTHIRD")
    second, _ = _sequenced_text_layer(layer, 10.0, 30.0)
    assert second["text"] == "SECOND"
    assert second["_line_sequence_count"] == 3
    assert second["_line_sequence_slot"] == 10.0


def test_sequence_uses_layer_available_time_after_delay_and_before_exit():
    layer = _layer(delay=3, exit_after=12)
    first, _ = _sequenced_text_layer(layer, 3.0, 30.0)
    second, second_t = _sequenced_text_layer(layer, 7.0, 30.0)
    third, third_t = _sequenced_text_layer(layer, 11.0, 30.0)
    assert first["text"] == "FIRST"
    assert second["text"] == "SECOND" and second_t == 0.0
    assert third["text"] == "THIRD" and third_t == 0.0
    assert first["_line_sequence_slot"] == 4.0


def test_each_new_line_restarts_content_animation_clock_and_clears_delay():
    layer = _layer(animation="split-flap", delay=2)
    second, local = _sequenced_text_layer(layer, 2 + (28 / 3), 30.0)
    assert second["text"] == "SECOND"
    assert second["delay"] == 0
    assert abs(local) < 1e-9


def test_existing_multiline_layers_keep_display_together_compatibility():
    layer = _layer(line_display="together")
    unchanged, elapsed = _sequenced_text_layer(layer, 15.0, 30.0)
    assert unchanged is layer
    assert unchanged["text"] == "FIRST\nSECOND\nTHIRD"
    assert elapsed == 15.0


def test_designer_exposes_sequence_mode_and_live_timing_help():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="layerLineDisplay"' in html
    assert '<option value="together">Display together</option>' in html
    assert '<option value="sequence">Show one after another</option>' in html
    assert 'id="lineSequenceTiming"' in html
    assert "function updateLineSequenceTiming()" in js
    assert "l.line_display=['nixie','seven-segment','fourteen-segment'].includes(l.animation)?'together':($('layerLineDisplay').value||'together')" in js
    assert "line_display:'together'" in js



def test_render_scene_passes_only_the_active_line_to_text_renderer(monkeypatch):
    seen = []
    def fake_content(layer, ltype, w, h, sy, elapsed, now, upload_fonts_dir, scroll_axis=None):
        seen.append((layer.get("text"), round(float(elapsed), 3)))
        return Image.new("RGBA", (w, h), (255, 255, 255, 255))
    monkeypatch.setattr(renderer, "_render_layer_content", fake_content)
    scene = {
        "duration": 30, "design_width": 64, "design_height": 32,
        "background": {"mode": "solid", "color1": "#000000", "color2": "#000000"},
        "layers": [{
            "id": "L1", "type": "text", "enabled": True, "x": 0, "y": 0, "w": 64, "h": 32,
            "text": "FIRST\nSECOND\nTHIRD", "line_display": "sequence", "delay": 0,
            "animation": "static", "opacity": 100, "z": 1,
        }],
    }
    renderer.render_scene(scene, 64, 32, 15.0, datetime(2026, 8, 25, 9, 0), str(ROOT / "uploads" / "fonts"))
    assert seen == [("SECOND", 5.0)]

def test_release_version_is_v0648():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.59"
