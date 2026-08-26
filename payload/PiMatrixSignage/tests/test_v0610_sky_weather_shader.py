from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shader_support import list_shader_assets, read_shader_document, _normalise_inputs, prepare_fragment_source


def test_sky_weather_builtin_is_packaged_with_expected_controls():
    assets = list_shader_assets(ROOT / "uploads" / "shaders", ROOT / "shaders")
    sky = next((x for x in assets if x.get("id") == "builtin:Sky-Weather.fs"), None)
    assert sky is not None
    assert sky["name"] == "Sky Weather"
    controls = {x["name"]: x for x in sky["inputs"]}
    for name in ("Weather", "SkyPhase", "Speed", "WindDirection", "CloudCover",
                 "PrecipIntensity", "SunSize", "MoonPhase", "MoonBrightness", "SunMoonPosition", "SunMoonHeight",
                 "SunMoonMovement", "SunMoonSpeed", "HorizonGlow", "SkyTop", "SkyBottom",
                 "CloudColor", "RainColor", "SnowColor"):
        assert name in controls
    assert controls["Weather"]["values"] == [0, 1, 2, 3, 4, 5]
    assert controls["Weather"]["labels"] == ["Clear", "Partly cloudy", "Overcast", "Rain", "Snow", "Storm"]
    assert controls["SkyPhase"]["labels"] == ["Day", "Sunset", "Night"]
    assert controls["WindDirection"]["labels"] == ["Left to right", "Right to left"]
    assert controls["SunMoonMovement"]["labels"] == ["Stationary", "Left to right", "Right to left"]
    assert controls["SunMoonMovement"]["default"] == 0


def test_sky_weather_shader_prepares_for_desktop_and_gles():
    source, meta = read_shader_document(ROOT / "shaders" / "Sky-Weather.fs")
    inputs = _normalise_inputs(meta)
    desktop = prepare_fragment_source(source, inputs, es=False)
    gles = prepare_fragment_source(source, inputs, es=True)
    assert "uniform vec2 RENDERSIZE;" in desktop
    assert "uniform int Weather;" in desktop
    assert "uniform int SkyPhase;" in desktop
    assert "uniform int WindDirection;" in desktop
    assert "uniform float PrecipIntensity;" in desktop
    assert "uniform float MoonPhase;" in desktop
    assert "uniform float MoonBrightness;" in desktop
    assert "uniform float SunMoonPosition;" in desktop
    assert "uniform float SunMoonHeight;" in desktop
    assert "uniform int SunMoonMovement;" in desktop
    assert "uniform float SunMoonSpeed;" in desktop
    assert "uniform vec4 CloudColor;" in desktop
    assert "gl_FragColor" in desktop
    assert "precision highp float;" in gles


def test_sky_weather_shader_contains_all_weather_render_paths():
    source = (ROOT / "shaders" / "Sky-Weather.fs").read_text(encoding="utf-8")
    for marker in ("Weather==3", "Weather==4", "Weather==5", "softCircle", "cloudBlob", "RainColor", "SnowColor"):
        assert marker in source


def test_release_version_is_v0611_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 6, 11)
