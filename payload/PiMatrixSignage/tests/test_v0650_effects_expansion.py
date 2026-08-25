from datetime import datetime
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from renderer import (
    _apply_layer_transition,
    _apply_scene_transition,
    _apply_sprite_color_effect,
    _render_scene_text,
)
from shader_support import list_shader_assets, prepare_fragment_source, read_shader_document, _normalise_inputs

NOW = datetime(2026, 8, 25, 19, 48, 12, 400000)


def _layer(**overrides):
    layer = {
        "id": "fx", "type": "text", "text": "OPEN 10:00", "animation": "static",
        "font": "", "font_size": 24, "auto_fit": True, "wrap": False,
        "overflow": "manual", "text_transform": "none", "typewriter_speed": 12,
        "color": "#ffffff", "color2": "#00ffff", "color_effect": "none",
        "color_speed": 1, "color_palette": "", "glow": 0, "glow_color": "#ffffff",
        "outline_color": "#000000", "outline_width": 0, "padding": 1,
        "align": "center", "valign": "middle", "line_spacing": .12,
        "shadow_color": "#000000", "shadow_x": 0, "shadow_y": 0,
        "render_mode": "led-5x7", "pixel_scale": 2, "pixel_bold": False,
        "letter_spacing": 0, "delay": 0, "effect_period": 1,
        "effect_amount": 2, "effect_stagger": .08,
        "flap_cycles": 4, "flap_stagger": .06, "flap_order": "left",
        "flap_board_style": "none", "flap_bg_color": "#171717",
        "flap_seam_color": "#000000", "flap_border_color": "#454545",
        "flap_cell_gap": 1, "entrance_effect": "none", "exit_effect": "none",
    }
    layer.update(overrides)
    return layer


def _alpha_count(im):
    return sum(1 for v in im.getchannel("A").get_flattened_data() if v)


def test_new_text_effects_render_and_change_over_time():
    assemble_early = _render_scene_text(_layer(animation="pixel-assemble"), 192, 48, 1, .08, NOW, str(ROOT / "uploads/fonts"))
    assemble_late = _render_scene_text(_layer(animation="pixel-assemble"), 192, 48, 1, 1.2, NOW, str(ROOT / "uploads/fonts"))
    assert 0 < _alpha_count(assemble_early) < _alpha_count(assemble_late)

    dissolve_full = _render_scene_text(_layer(animation="pixel-dissolve"), 192, 48, 1, 0, NOW, str(ROOT / "uploads/fonts"))
    dissolve_gone = _render_scene_text(_layer(animation="pixel-dissolve"), 192, 48, 1, .5, NOW, str(ROOT / "uploads/fonts"))
    assert _alpha_count(dissolve_full) > _alpha_count(dissolve_gone)

    neon_off = _render_scene_text(_layer(animation="neon-flicker"), 192, 48, 1, .01, NOW, str(ROOT / "uploads/fonts"))
    neon_on = _render_scene_text(_layer(animation="neon-flicker"), 192, 48, 1, 1.2, NOW, str(ROOT / "uploads/fonts"))
    assert _alpha_count(neon_off) < _alpha_count(neon_on)

    wave_a = _render_scene_text(_layer(animation="character-wave"), 192, 48, 1, .1, NOW, str(ROOT / "uploads/fonts"))
    wave_b = _render_scene_text(_layer(animation="character-wave"), 192, 48, 1, .35, NOW, str(ROOT / "uploads/fonts"))
    assert wave_a.tobytes() != wave_b.tobytes()

    glitch_a = _render_scene_text(_layer(animation="glitch"), 192, 48, 1, .2, NOW, str(ROOT / "uploads/fonts"))
    glitch_b = _render_scene_text(_layer(animation="glitch"), 192, 48, 1, .9, NOW, str(ROOT / "uploads/fonts"))
    assert glitch_a.tobytes() != glitch_b.tobytes()


def test_split_flap_departure_board_keeps_physical_blank_cell():
    layer = _layer(text=" ", animation="split-flap", flap_board_style="departure")
    im = _render_scene_text(layer, 32, 24, 1, .5, NOW, str(ROOT / "uploads/fonts"))
    assert im.getbbox() is not None
    assert _alpha_count(im) > 0


def test_rolling_digits_support_live_clock_widgets():
    widget = _layer(type="widget", widget_type="clock", widget_format="%H:%M:%S", animation="rolling-digits", effect_period=.5)
    a = _render_scene_text(widget, 192, 48, 1, 2, NOW.replace(microsecond=50000), str(ROOT / "uploads/fonts"))
    b = _render_scene_text(widget, 192, 48, 1, 2, NOW.replace(microsecond=350000), str(ROOT / "uploads/fonts"))
    assert a.tobytes() != b.tobytes()


def test_moving_colour_wave_changes_colour_without_moving_alpha():
    sprite = Image.new("RGBA", (12, 4), (255, 255, 255, 255))
    layer = _layer(color_effect="wave", color="#ff0000", color2="#0000ff", color_speed=1)
    a = _apply_sprite_color_effect(sprite, layer, 0)
    b = _apply_sprite_color_effect(sprite, layer, .25)
    assert a.getchannel("A").tobytes() == b.getchannel("A").tobytes()
    assert a.convert("RGB").tobytes() != b.convert("RGB").tobytes()


def test_new_builtin_shader_library_and_metadata_prepare_for_gl_and_gles():
    assets = {a["filename"]: a for a in list_shader_assets(ROOT / "uploads/shaders", ROOT / "shaders")}
    wanted = {
        "Fire-Embers.fs", "Starfield-Warp.fs", "Particle-Fall.fs",
        "Radar-Sweep.fs", "Matrix-Rain.fs", "LED-Marquee.fs", "Aurora.fs",
    }
    assert wanted <= set(assets)
    assert assets["Particle-Fall.fs"]["inputs"][0]["labels"] == ["Snow", "Confetti", "Bubbles", "Stars", "Hearts"]
    assert assets["Starfield-Warp.fs"]["inputs"][0]["labels"][-1] == "Warp speed"
    assert len(assets["Aurora.fs"]["inputs"]) >= 8
    for filename in wanted:
        source, meta = read_shader_document(ROOT / "shaders" / filename)
        inputs = _normalise_inputs(meta)
        assert "void main" in prepare_fragment_source(source, inputs, False)
        assert "precision highp float;" in prepare_fragment_source(source, inputs, True)


def test_new_pixel_transition_family_progresses_for_scene_and_layer():
    white = Image.new("RGB", (32, 16), "white")
    rgba = Image.new("RGBA", (32, 16), (255, 255, 255, 255))
    for effect in ("columns", "rows", "center-out", "spiral", "random-leds"):
        early = _apply_scene_transition(white, {"transition_in": effect, "transition_in_duration": 1}, .1)
        late = _apply_scene_transition(white, {"transition_in": effect, "transition_in_duration": 1}, .8)
        early_lit = sum(1 for p in early.get_flattened_data() if p != (0, 0, 0))
        late_lit = sum(1 for p in late.get_flattened_data() if p != (0, 0, 0))
        assert early_lit < late_lit
        layer_early, visible = _apply_layer_transition(rgba, {"delay": 0, "entrance_effect": effect, "entrance_duration": 1, "exit_effect": "none", "exit_after": 0}, .1)
        layer_late, _ = _apply_layer_transition(rgba, {"delay": 0, "entrance_effect": effect, "entrance_duration": 1, "exit_effect": "none", "exit_after": 0}, .8)
        assert visible
        assert _alpha_count(layer_early) < _alpha_count(layer_late)


def test_designer_exposes_all_15_effect_family_entries():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    for marker in (
        "Pixel assemble", "Pixel dissolve / reform", "Departure board – black", "Neon flicker",
        "LED Marquee Chase", "Fire &amp; Embers", "Aurora", "Starfield", "Falling Particles",
        "Radar", "Matrix", "Glitch / signal interference", "Moving colour wave",
        "Character wave", "Rolling number display", "Pixel spiral", "Random LEDs",
    ):
        # Shader names are populated dynamically, so their literal names live in
        # shader metadata rather than necessarily in the template itself.
        if marker in ("LED Marquee Chase", "Fire &amp; Embers", "Aurora", "Starfield", "Falling Particles", "Radar", "Matrix"):
            continue
        assert marker in html
