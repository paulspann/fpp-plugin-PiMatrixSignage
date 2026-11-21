from datetime import datetime

from PIL import Image

import renderer


def test_shopify_variant_range_uses_from_price():
    assert renderer._shopify_price({"min": "12.5", "max": "19.99", "currency": "GBP"}) == "From £12.50"
    assert renderer._shopify_price({"min": "12.5", "max": "12.50", "currency": "GBP"}) == "£12.50"


def test_shopify_stock_query_paginates_and_uses_only_local_available_variants(monkeypatch):
    def variant(price, quantity, tracked=True, name="available"):
        return {"price": price, "inventoryItem": {"tracked": tracked, "inventoryLevel":
                None if quantity is None else {"quantities": [{"name": name, "quantity": quantity}]}}}

    def page(nodes, cursor=None):
        return {"nodes": nodes, "pageInfo": {"hasNextPage": bool(cursor), "endCursor": cursor}}

    def product(pid, variants, status="ACTIVE"):
        return {"id": pid, "title": pid, "status": status, "variants": variants}

    def graphql(store, token, version, query, variables, timeout):
        assert variables["location"] == "gid://shopify/Location/9090105380"
        assert 'inventoryLevel(locationId: $location)' in query
        assert 'quantities(names: ["available"])' in query
        if "query MoreStock" in query:
            assert variables["cursor"] == "variants-2"
            return {"product": {"variants": page([variant("14.00", 1)])}}
        if not variables["cursor"]:
            nodes = [
                product("other locations only", page([variant("1", None)])),
                product("zero, negative or untracked", page([
                    variant("2", 0), variant("3", -1), variant("4", 5, tracked=False),
                    variant("5", 10, name="on_hand"),
                ])),
                product("draft", page([variant("5", 2)]), status="DRAFT"),
            ]
            products = page(nodes, "products-2")
        else:
            assert variables["cursor"] == "products-2"
            products = page([product("stocked", page(
                [variant("6", 0), variant("18", 3)], "variants-2"))])
        return {"shop": {"name": "Fledglings", "currencyCode": "GBP"}, "products": products}

    monkeypatch.setattr(renderer, "_shopify_graphql", graphql)
    name, products = renderer.fetch_shopify_stock("fledglings.myshopify.com", "token", "2026-07", 2)
    assert name == "Fledglings"
    assert [p["id"] for p in products] == ["stocked"]
    assert renderer._shopify_price(products[0]) == "From £14.00"


def _rotation_fixture(monkeypatch, count):
    products = [{"id": str(i), "title": str(i)} for i in range(count)]
    clock = [0.0]
    monkeypatch.setattr(renderer, "_SHOPIFY_ROTATIONS", {})
    monkeypatch.setattr(renderer, "_shopify_products", lambda layer: products)
    monkeypatch.setattr(renderer.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(renderer.random, "choice", lambda values: values[0])
    def pick(seconds, elapsed=None):
        clock[0] = seconds
        return renderer._shopify_selected_product(
            {"id": "fledglings", "shopify_rotate_seconds": 10},
            seconds if elapsed is None else elapsed,
        )["id"]
    return products, pick


def test_shopify_uses_fresh_products_and_holds_when_pool_is_cooling(monkeypatch):
    products, pick = _rotation_fixture(monkeypatch, 3)
    assert [pick(t) for t in (0, 9, 10, 20, 30)] == ["0", "0", "1", "2", "2"]
    products.reverse()  # A refresh can change list order but not product IDs.
    assert pick(308) == "2"
    assert pick(309) == "0"  # 300 seconds since the last frame showing product 0.


def test_shopify_live_history_survives_scene_restart_and_preview_is_separate(monkeypatch):
    _, pick = _rotation_fixture(monkeypatch, 3)
    real_thread = renderer.threading.current_thread()
    monkeypatch.setattr(real_thread, "name", "PiMatrixRenderer")
    assert pick(0, 0) == "0"
    assert pick(1, 1) == "0"
    assert pick(5, 0) == "1"  # Same widget on its next playlist visit.
    monkeypatch.setattr(real_thread, "name", "preview")
    assert pick(6, 0) == "0"
    monkeypatch.setattr(real_thread, "name", "PiMatrixRenderer")
    assert pick(7, 2) == "1"


def test_shopify_single_product_and_catalogue_removal(monkeypatch):
    products, pick = _rotation_fixture(monkeypatch, 2)
    assert pick(0) == "0"
    assert pick(10) == "1"
    products.pop()
    assert pick(11) == "0"
    assert pick(30) == "0"


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
