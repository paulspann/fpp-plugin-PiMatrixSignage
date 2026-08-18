from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shader_support import list_shader_assets, read_shader_document, _normalise_inputs, prepare_fragment_source



def test_water_ripples_builtin_is_packaged_with_expected_controls():
    assets = list_shader_assets(ROOT / 'uploads' / 'shaders', ROOT / 'shaders')
    water = next((x for x in assets if x.get('id') == 'builtin:Water-Ripples.fs'), None)
    assert water is not None
    assert water['name'] == 'Water Ripples'
    controls = {x['name']: x for x in water['inputs']}
    for name in ('Style', 'Speed', 'WaveHeight', 'RippleSize', 'Choppiness',
                 'WaterColor', 'DeepColor', 'HighlightColor', 'WaterOpacity'):
        assert name in controls
    assert controls['Style']['values'] == [0, 1, 2]
    assert controls['Style']['labels'] == ['Gentle water', 'Ripples', 'Pool shimmer']


def test_water_ripples_shader_prepares_for_desktop_and_gles():
    source, meta = read_shader_document(ROOT / 'shaders' / 'Water-Ripples.fs')
    inputs = _normalise_inputs(meta)
    desktop = prepare_fragment_source(source, inputs, es=False)
    gles = prepare_fragment_source(source, inputs, es=True)
    assert 'uniform vec2 RENDERSIZE;' in desktop
    assert 'uniform int Style;' in desktop
    assert 'uniform vec4 WaterColor;' in desktop
    assert 'gl_FragColor' in desktop
    assert 'precision highp float;' in gles


def test_water_swim_template_uses_bottom_shader_strip():
    html = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
    js = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')
    assert 'value="water-swim">Water / swim</option>' in html
    assert "kind==='water-swim'" in js
    assert "shader_id:'builtin:Water-Ripples.fs'" in js
    assert "waterY=Math.max(0,h-waterH)" in js


def test_release_version_includes_v056_or_later():
    version = tuple(int(x) for x in (ROOT / 'VERSION').read_text(encoding='utf-8').strip().split('.')[:3])
    assert version >= (0, 5, 6)
