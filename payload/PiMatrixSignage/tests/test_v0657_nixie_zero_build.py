from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer


def _layer(**updates):
    layer = {
        "id": "nixie-build", "type": "text", "enabled": True,
        "text": "1965", "animation": "nixie",
        "nixie_build": True, "nixie_build_duration": 4.0,
        "padding": 0, "align": "center", "valign": "middle",
    }
    layer.update(updates)
    return layer


def test_nixie_zero_build_resolves_tubes_independently_not_as_a_counter():
    # Four seconds means one second per tube.  These are the settled boundary
    # states requested by the feature, not a numeric count from 0000 to 1965.
    assert renderer._nixie_build_digits("1965", 0.0, 4.0, True) == "0000"
    assert renderer._nixie_build_digits("1965", 1.0, 4.0, True) == "1000"
    assert renderer._nixie_build_digits("1965", 2.0, 4.0, True) == "1900"
    assert renderer._nixie_build_digits("1965", 3.0, 4.0, True) == "1960"
    assert renderer._nixie_build_digits("1965", 4.0, 4.0, True) == "1965"


def test_active_tube_walks_0_to_target_while_later_tubes_remain_zero():
    # Halfway through the second tube's one-second slot the first tube is already
    # settled, the second is part-way through 0..9, and the last two are still 0.
    state = renderer._nixie_build_digits("1965", 1.5, 4.0, True)
    assert state[0] == "1"
    assert 0 < int(state[1]) < 9
    assert state[2:] == "00"
    # This is specifically not whole-number counting behaviour.
    assert state != f"{int(1965 * (1.5 / 4.0)):04d}"


def test_zero_targets_stay_zero_and_disabled_mode_is_immediate():
    assert renderer._nixie_build_digits("1005", 2.5, 4.0, True)[1:3] == "00"
    assert renderer._nixie_build_digits("1965", 0.0, 4.0, False) == "1965"


def test_renderer_starts_with_zero_tubes_then_finishes_on_requested_value():
    now = datetime(2026, 8, 26, 15, 30)
    start = renderer._render_nixie_text(_layer(), 96, 32, 1, 0.0, now)
    zeros = renderer._render_nixie_text(_layer(text="0000", nixie_build=False), 96, 32, 1, 0.0, now)
    final = renderer._render_nixie_text(_layer(), 96, 32, 1, 4.0, now)
    target = renderer._render_nixie_text(_layer(nixie_build=False), 96, 32, 1, 0.0, now)
    assert list(start.get_flattened_data()) == list(zeros.get_flattened_data())
    assert list(final.get_flattened_data()) == list(target.get_flattened_data())


def test_designer_has_zero_build_option_duration_and_persists_them():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert 'id="nixieOptions"' in html
    assert 'id="layerNixieBuild"' in html
    assert 'Build up from 0000' in html
    assert 'id="layerNixieBuildDuration"' in html
    assert "l.nixie_build=$('layerNixieBuild').checked" in js
    assert "l.nixie_build_duration=clamp(+$('layerNixieBuildDuration').value||4,.5,60)" in js
    assert "$('layerNixieBuild').checked=!!l.nixie_build" in js


def test_release_version_is_v0657():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.6.59"
