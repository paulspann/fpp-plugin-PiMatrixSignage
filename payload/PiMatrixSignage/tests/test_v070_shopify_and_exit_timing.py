from datetime import datetime

from PIL import Image

import renderer


def test_shopify_variant_range_uses_from_price():
    assert renderer._shopify_price({"min": "12.5", "max": "19.99", "currency": "GBP"}) == "From £12.50"
    assert renderer._shopify_price({"min": "12.5", "max": "12.50", "currency": "GBP"}) == "£12.50"


def test_random_product_rotation_never_immediately_repeats(monkeypatch):
    products = [{"id": str(i), "title": str(i)} for i in range(5)]
    monkeypatch.setattr(renderer, "_shopify_products", lambda layer: products)
    layer = {"id": "fledglings", "shopify_rotate_seconds": 10}
    picked = [renderer._shopify_selected_product(layer, t * 10.0)["id"] for t in range(20)]
    assert all(a != b for a, b in zip(picked, picked[1:]))


def test_shopify_widget_has_offline_setup_placeholder(tmp_path):
    renderer.configure_shopify({})
    layer = {"id": "products", "type": "widget", "widget_type": "shopify-products", "color": "#ffffff"}
    image = renderer._render_shopify_product(layer, 128, 32, 1.0, 0.0, datetime(2026, 11, 21), str(tmp_path))
    assert image.size == (128, 32)
    assert image.getbbox() is not None


def test_scene_end_exit_gets_real_transition_window(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer, "_render_layer_content", lambda *args, **kwargs: Image.new("RGBA", (32, 16), (255, 255, 255, 255)))
    scene = {"duration": 10, "design_width": 32, "design_height": 16, "background": {"mode": "solid", "color1": "#000000"},
             "layers": [{"id": "x", "type": "text", "enabled": True, "x": 0, "y": 0, "w": 32, "h": 16,
                         "opacity": 100, "animation": "static", "exit_effect": "fade", "exit_timing": "scene-end",
                         "exit_after": 0, "exit_duration": 2}]}
    now = datetime(2026, 11, 21)
    before = renderer.render_scene(scene, 32, 16, 7.9, now, str(tmp_path))
    during = renderer.render_scene(scene, 32, 16, 9.0, now, str(tmp_path))
    ended = renderer.render_scene(scene, 32, 16, 10.0, now, str(tmp_path))
    assert before.getpixel((10, 10))[0] == 255
    assert 0 < during.getpixel((10, 10))[0] < 255
    assert ended.getpixel((10, 10))[0] == 0
