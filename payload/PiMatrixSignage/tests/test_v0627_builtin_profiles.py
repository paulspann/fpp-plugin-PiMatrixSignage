from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_builtin_profiles_cover_hanson_and_colorlight_p5_p10():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "BUILTIN_HARDWARE_PROFILES" in app
    assert app.count('"builtin": True') == 4
    assert "Hanson P5 64×32" in app
    assert "Colorlight P5 64×32" in app
    assert "Colorlight P10 32×16" in app
    assert '"panel_scan": "1/4"' in app
    assert '<int(signed=True):profile_id>' in app


def test_builtin_profiles_are_labelled_and_not_deletable():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "Built-in starter profiles cannot be deleted" in app
    assert "Starter profiles are not electrical specifications" in html
    assert "Built-in starter" in js
    assert "verify scan rate, driver mapping and colour order" in js


def test_release_version_is_v0627():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.27"
