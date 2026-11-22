import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shader_support import list_shader_assets, read_shader_document, shader_default_params


def _asset(filename):
    assets = list_shader_assets(ROOT / "missing-uploads", ROOT / "shaders")
    return next(item for item in assets if item["filename"] == filename)


def test_left_and_right_neon_chevrons_are_builtin_procedural_shaders():
    left = _asset("Neon-Chevrons-Left.fs")
    right = _asset("Neon-Chevrons-Right.fs")
    assert left["name"] == "Neon Chevrons – Left"
    assert right["name"] == "Neon Chevrons – Right"
    assert left["origin"] == right["origin"] == "built-in"
    assert "no video file required" in left["description"].lower()
    assert "no video file required" in right["description"].lower()


def test_chevron_direction_and_motion_are_opposite():
    left_source, _ = read_shader_document(ROOT / "shaders" / "Neon-Chevrons-Left.fs")
    right_source, _ = read_shader_document(ROOT / "shaders" / "Neon-Chevrons-Right.fs")
    assert "p.x+travel" in left_source
    assert "p.x-travel" in right_source
    assert "target=-chevron*.5" in left_source
    assert "target=chevron*.5" in right_source
    assert "sampler2D" not in left_source + right_source


def test_chevron_controls_have_safe_defaults_and_ranges():
    for filename in ("Neon-Chevrons-Left.fs", "Neon-Chevrons-Right.fs"):
        asset = _asset(filename)
        defaults = shader_default_params(asset["inputs"])
        assert defaults["Speed"] == 1.0
        assert defaults["ArrowColor"] == [1.0, 1.0, 1.0, 1.0]
        assert defaults["Background"] == [0.0, 0.0, 0.0, 1.0]
        assert defaults["BackgroundOpacity"] == 1.0
        assert {item["name"] for item in asset["inputs"]} == {
            "Speed", "ChevronWidth", "Spacing", "Height", "Thickness", "Glow",
            "Pulse", "ArrowColor", "Background", "BackgroundOpacity",
        }


def test_release_version_is_v0660():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.7.7"
