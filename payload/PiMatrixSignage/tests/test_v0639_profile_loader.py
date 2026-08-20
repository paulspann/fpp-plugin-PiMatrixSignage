from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hardware_profile_loader_fetches_and_renders_profiles():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "async function loadHardwareProfiles()" in js
    body = js.split("async function loadHardwareProfiles()", 1)[1].split("function renderHardwareProfiles()", 1)[0]
    assert "api('/api/hardware-profiles')" in body
    assert "state.hardwareProfiles" in body
    assert "renderHardwareProfiles()" in body


def test_profile_panel_still_contains_builtin_and_saved_sections():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "Built-in samples" in js
    assert "Your saved profiles" in js
    assert "data-profile-apply" in js


def test_release_version_is_v0639_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 39)
