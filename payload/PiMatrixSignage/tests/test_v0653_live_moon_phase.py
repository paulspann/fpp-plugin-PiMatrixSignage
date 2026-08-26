from datetime import datetime, timezone
from pathlib import Path
import math
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from renderer import _live_weather_shader_params, _moon_illumination, _moon_phase_fraction
from shader_support import list_shader_assets, read_shader_document, _normalise_inputs, prepare_fragment_source


def circular_distance(a, b):
    d = abs((a - b) % 1.0)
    return min(d, 1.0 - d)


def test_local_lunar_cycle_tracks_known_new_and_full_moons():
    # 8 Apr 2024 solar eclipse occurred at new moon; 23 Apr was a full moon.
    new_phase = _moon_phase_fraction(datetime(2024, 4, 8, 18, 21, tzinfo=timezone.utc))
    full_phase = _moon_phase_fraction(datetime(2024, 4, 23, 23, 49, tzinfo=timezone.utc))
    assert circular_distance(new_phase, 0.0) < 0.02
    assert circular_distance(full_phase, 0.5) < 0.02
    assert _moon_illumination(new_phase) < 0.01
    assert _moon_illumination(full_phase) > 0.99


def test_live_weather_injects_moon_phase_without_changing_weather_fetch_contract():
    current = {
        "status": "ok", "category": "clear", "is_day": False,
        "cloud": 5, "wind": 2, "wind_direction": 90, "precip": 0,
    }
    config = {
        "shader_live_weather": True, "shader_weather_lat": 53.55,
        "shader_weather_lon": -2.52, "shader_weather_refresh": 600,
    }
    with patch("renderer._weather_current", return_value=current), patch("renderer._moon_phase_fraction", return_value=0.25):
        params = _live_weather_shader_params(config, {"MoonPhase": 0.5})
    assert params["SkyPhase"] == 2
    assert params["MoonPhase"] == 0.25


def test_southern_hemisphere_reverses_visual_waxing_orientation():
    current = {
        "status": "ok", "category": "clear", "is_day": False,
        "cloud": 0, "wind": 0, "wind_direction": 0, "precip": 0,
    }
    config = {"shader_live_weather": True, "shader_weather_lat": -33.86, "shader_weather_lon": 151.21}
    with patch("renderer._weather_current", return_value=current), patch("renderer._moon_phase_fraction", return_value=0.25):
        params = _live_weather_shader_params(config, {})
    assert math.isclose(params["MoonPhase"], 0.75)


def test_manual_mode_preserves_saved_manual_moon_phase():
    manual = {"SkyPhase": 2, "MoonPhase": 0.75, "MoonBrightness": 0.8}
    with patch("renderer._weather_current") as weather, patch("renderer._moon_phase_fraction") as moon:
        assert _live_weather_shader_params({"shader_live_weather": False}, manual) == manual
        weather.assert_not_called()
        moon.assert_not_called()


def test_sky_weather_shader_has_low_resolution_phase_mask_controls():
    assets = list_shader_assets(ROOT / "uploads" / "shaders", ROOT / "shaders")
    sky = next(x for x in assets if x.get("id") == "builtin:Sky-Weather.fs")
    controls = {x["name"]: x for x in sky["inputs"]}
    assert controls["MoonPhase"]["default"] == 0.5
    assert controls["MoonBrightness"]["default"] == 0.95
    source, meta = read_shader_document(ROOT / "shaders" / "Sky-Weather.fs")
    prepared = prepare_fragment_source(source, _normalise_inputs(meta), es=False)
    for marker in ("uniform float MoonPhase;", "uniform float MoonBrightness;", "moonLight", "litHemisphere", "illumination", "bodyDelta", "(W/H)"):
        assert marker in prepared


def test_clouds_are_composited_after_moon_so_live_weather_can_obscure_it():
    source = (ROOT / "shaders" / "Sky-Weather.fs").read_text(encoding="utf-8")
    assert source.index("moonLit") < source.index("float cloud=0.0")


def test_help_explains_live_moon_phase_is_local_and_automatic():
    help_html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    index_html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "calculates the current moon phase locally" in help_html
    assert "current moon phase is calculated locally" in index_html


def test_release_version_is_v0653_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text().strip().split(".")[:3])
    assert version >= (0, 6, 53)
