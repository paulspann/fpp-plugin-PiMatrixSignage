from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from renderer import _live_weather_shader_params


def test_live_weather_maps_conditions_to_sky_shader_uniforms():
    current = {
        "status": "ok", "category": "snow-showers", "is_day": False,
        "cloud": 84, "wind": 16, "wind_direction": 270, "precip": 2.5,
    }
    config = {
        "shader_live_weather": True, "shader_weather_lat": 53.55,
        "shader_weather_lon": -2.52, "shader_weather_refresh": 600,
    }
    with patch("renderer._weather_current", return_value=current) as fetch:
        params = _live_weather_shader_params(config, {"Weather": 0, "SunMoonPosition": 0.7})
    assert params["Weather"] == 4
    assert params["SkyPhase"] == 2
    assert params["CloudCover"] == 0.84
    assert params["WindDirection"] == 0
    assert params["Speed"] == 2.05
    assert params["PrecipIntensity"] == 0.5
    assert params["SunMoonPosition"] == 0.7
    assert fetch.call_args.args[0]["weather_lat"] == 53.55


def test_live_weather_is_optional_and_manual_values_are_offline_fallback():
    manual = {"Weather": 1, "SkyPhase": 1, "CloudCover": 0.4}
    with patch("renderer._weather_current") as fetch:
        assert _live_weather_shader_params({"shader_live_weather": False}, manual) == manual
        fetch.assert_not_called()
    with patch("renderer._weather_current", return_value={"status": "error"}):
        assert _live_weather_shader_params({"shader_live_weather": True}, manual) == manual


def test_live_weather_controls_are_available_for_layer_and_background():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for marker in (
        "layerShaderLiveWeather", "layerShaderWeatherLat", "layerShaderWeatherLon",
        "sceneBgShaderLiveWeather", "sceneBgShaderWeatherLat", "sceneBgShaderWeatherLon",
    ):
        assert marker in html
        assert marker in js
    assert "builtin:Sky-Weather.fs" in js


def test_release_version_is_v0612_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 6, 12)
