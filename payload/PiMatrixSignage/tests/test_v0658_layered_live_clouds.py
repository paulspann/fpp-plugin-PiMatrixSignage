from pathlib import Path
import json
import sys
import urllib.parse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from renderer import _live_weather_shader_params, _weather_current
from shader_support import list_shader_assets, read_shader_document, _normalise_inputs, prepare_fragment_source


def test_weather_fetch_requests_and_returns_total_low_mid_high_cloud_cover():
    seen = {}
    payload = {"current": {
        "weather_code": 3, "temperature_2m": 15.8, "apparent_temperature": 15.4,
        "relative_humidity_2m": 90, "precipitation": 0, "rain": 0, "showers": 0,
        "snowfall": 0, "cloud_cover": 100, "cloud_cover_low": 96,
        "cloud_cover_mid": 87, "cloud_cover_high": 72, "wind_speed_10m": 4,
        "wind_direction_10m": 250, "wind_gusts_10m": 8, "is_day": 1,
    }}

    def fake_http(url, *args, **kwargs):
        seen["url"] = url
        return json.dumps(payload)

    def run_fetch(key, refresh, fetch, **kwargs):
        return fetch()

    layer = {"weather_lat": 53.55, "weather_lon": -2.52, "refresh_seconds": 600}
    with patch("renderer._http_text", side_effect=fake_http), patch("renderer._live_fetch_async", side_effect=run_fetch):
        data = _weather_current(layer)
    current = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)["current"][0]
    for name in ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high"):
        assert name in current
    assert data["cloud"] == 100
    assert data["cloud_low"] == 96
    assert data["cloud_mid"] == 87
    assert data["cloud_high"] == 72


def test_live_shader_receives_layered_cloud_fractions_and_missing_layers_fall_back_to_total():
    current = {
        "status": "ok", "category": "cloudy", "is_day": True,
        "cloud": 100, "cloud_low": 92, "cloud_mid": 70, "cloud_high": 45,
        "wind": 5, "wind_direction": 270, "precip": 0,
    }
    with patch("renderer._weather_current", return_value=current):
        params = _live_weather_shader_params({"shader_live_weather": True}, {})
    assert params["CloudCover"] == 1.0
    assert params["LowCloudCover"] == 0.92
    assert params["MidCloudCover"] == 0.70
    assert params["HighCloudCover"] == 0.45

    without_layers = dict(current)
    without_layers.pop("cloud_low"); without_layers.pop("cloud_mid"); without_layers.pop("cloud_high")
    with patch("renderer._weather_current", return_value=without_layers):
        params = _live_weather_shader_params({"shader_live_weather": True}, {})
    assert params["LowCloudCover"] == params["MidCloudCover"] == params["HighCloudCover"] == 1.0


def test_sky_weather_has_layer_controls_and_dense_overcast_deck_logic():
    assets = list_shader_assets(ROOT / "uploads" / "shaders", ROOT / "shaders")
    sky = next(x for x in assets if x.get("id") == "builtin:Sky-Weather.fs")
    controls = {x["name"]: x for x in sky["inputs"]}
    for name in ("CloudCover", "LowCloudCover", "MidCloudCover", "HighCloudCover"):
        assert name in controls
    source, meta = read_shader_document(ROOT / "shaders" / "Sky-Weather.fs")
    prepared = prepare_fragment_source(source, _normalise_inputs(meta), es=False)
    for marker in (
        "uniform float LowCloudCover;", "uniform float MidCloudCover;",
        "uniform float HighCloudCover;", "float overcast=", "float deckMask=",
        "float layerCover=", "densityScale",
    ):
        assert marker in prepared


def test_help_explains_layered_live_overcast():
    help_html = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")
    index_html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "total/low/mid/high cloud cover" in help_html
    assert "100% cover no longer leaves large blue gaps" in help_html
    assert "continuous cloud deck" in index_html


def test_release_version_is_v0658():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.59"
