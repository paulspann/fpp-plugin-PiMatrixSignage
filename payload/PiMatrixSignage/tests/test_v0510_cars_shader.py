from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shader_support import list_shader_assets, read_shader_document, _normalise_inputs, prepare_fragment_source


def test_cars_on_road_builtin_is_packaged_with_expected_controls():
    assets = list_shader_assets(ROOT / 'uploads' / 'shaders', ROOT / 'shaders')
    road = next((x for x in assets if x.get('id') == 'builtin:Cars-On-Road.fs'), None)
    assert road is not None
    assert road['name'] == 'Cars on Road'
    controls = {x['name']: x for x in road['inputs']}
    for name in ('Speed', 'Direction', 'TrafficDensity', 'CarScale', 'RoadColor',
                 'HeadlightColor', 'TaillightColor'):
        assert name in controls
    assert controls['TrafficDensity']['type'] == 'int'
    assert controls['TrafficDensity']['default'] == 4
    assert controls['Direction']['values'] == [0, 1]
    assert controls['Direction']['labels'] == ['Left to right', 'Right to left']
    assert controls['TrafficDensity']['label'] == 'Cars'
    assert controls['CarScale']['label'] == 'Car size'


def test_cars_on_road_shader_prepares_for_desktop_and_gles():
    source, meta = read_shader_document(ROOT / 'shaders' / 'Cars-On-Road.fs')
    inputs = _normalise_inputs(meta)
    desktop = prepare_fragment_source(source, inputs, es=False)
    gles = prepare_fragment_source(source, inputs, es=True)
    assert 'uniform vec2 RENDERSIZE;' in desktop
    assert 'uniform float Speed;' in desktop
    assert 'uniform int Direction;' in desktop
    assert 'uniform int TrafficDensity;' in desktop
    assert 'uniform float CarScale;' in desktop
    assert 'uniform vec4 HeadlightColor;' in desktop
    assert 'gl_FragColor' in desktop
    assert 'precision highp float;' in gles


def test_right_to_left_motion_is_not_double_reversed():
    source = (ROOT / 'shaders' / 'Cars-On-Road.fs').read_text(encoding='utf-8')
    # One track always advances with positive time. Direction 1 mirrors that
    # track, which makes the x position decrease as time increases.
    assert 'float track=mod(start+motion+travel*4.0,travel)-carW;' in source
    assert 'float cx=(dir>0.0)?track:(W-track);' in source
    assert 'start+dir*motion' not in source


def test_release_version_includes_v0514_or_later():
    version = tuple(int(x) for x in (ROOT / 'VERSION').read_text(encoding='utf-8').strip().split('.')[:3])
    assert version >= (0, 5, 14)
