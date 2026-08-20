from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sixteen_builtin_sample_configurations_cover_all_output_families():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert app.count('"builtin": True') == 16
    for needle in (
        "Hanson · P5 64×32 · 4×1 · 256×32",
        "Colorlight 5A-75B · P5 64×32 · 4×1 · 256×32",
        "Colorlight 5A-75E · P10 32×16 · 8×2 · 256×32",
        "Adafruit HAT/Bonnet · P10 32×16 · 1 panel",
        "Adafruit Triple · P5 64×32 · 3×2 · 192×64",
        "Adafruit Triple · P10 32×16 · 3×2 · 96×32",
    ):
        assert needle in app


def test_profiles_are_grouped_and_moved_before_commissioning():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "Hardware profiles &amp; sample configurations" in html
    assert html.index('id="hardwareProfilesCard"') < html.index('id="colorlightWizardCard"')
    assert "16 built-in sample configurations are included" in html
    assert "Built-in samples" in js
    assert "Your saved profiles" in js
    assert "canvas ${canvas}" in js
    assert "profile-group" in js


def test_release_version_is_v0638_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 38)
