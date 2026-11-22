import json

import renderer
from database import Database


def test_playlist_crossfade_into_shopify_keeps_position(monkeypatch, tmp_path):
    db = Database(str(tmp_path / "signage.db"))
    first = db.save_message({"name": "Welcome", "text": "Welcome"})
    scene = {"transition_in": "crossfade", "transition_in_duration": 2,
             "layers": [{"id": "products", "type": "widget", "widget_type": "shopify-products"}]}
    products = db.save_message({"name": "New products", "editor_mode": "designer",
                                "scene_json": json.dumps(scene)})
    last = db.save_message({"name": "Opening hours", "text": "Opening hours"})
    playlist = db.save_playlist({"name": "Shop display", "items": [
        {"message_id": first, "duration": 5},
        {"message_id": products, "duration": 4},
        {"message_id": last, "duration": 3},
    ]})
    engine = renderer.RendererEngine(db, str(tmp_path), str(tmp_path))
    clock = iter([100, 104.9, 105, 106, 107, 108.9, 109.1, 112.1])
    tick = [next(clock)]
    shown = []

    def step(_seconds):
        shown.append((engine._display_message_id, bool(engine._transition)))
        tick[0] = next(clock, None)
        if tick[0] is None:
            engine._running = False

    monkeypatch.setattr(renderer.time, "monotonic", lambda: tick[0])
    monkeypatch.setattr(renderer.time, "sleep", step)
    monkeypatch.setattr(engine._ddp, "send", lambda _: None)
    monkeypatch.setattr(renderer, "_shopify_products", lambda _: [
        {"id": "product-1", "title": "Demo product", "min": "12.00", "max": "12.00"},
    ])
    engine.show_target("playlist", playlist)
    engine._running = True
    engine._run()

    assert engine.frame_failures == 0
    assert shown == [(first, False), (first, False), (first, True), (first, True),
                     (products, False), (products, False), (last, False), (first, False)]
    assert engine._manual.activated_monotonic == 100
