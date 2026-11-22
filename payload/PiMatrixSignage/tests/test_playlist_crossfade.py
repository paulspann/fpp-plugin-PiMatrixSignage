import json

import pytest

import renderer
from database import Database


def test_playlist_crossfade_into_shopify_keeps_position(monkeypatch, tmp_path):
    db = Database(str(tmp_path / "signage.db"))
    first = db.save_message({"name": "Welcome", "text": "Welcome"})
    scene = {"duration": 4, "transition_in": "crossfade", "transition_in_duration": 2,
             "layers": [{"id": "products", "type": "widget", "widget_type": "shopify-products"}]}
    products = db.save_message({"name": "New products", "editor_mode": "designer",
                                "scene_json": json.dumps(scene)})
    last = db.save_message({"name": "Opening hours", "text": "Opening hours"})
    playlist = db.save_playlist({"name": "Shop display", "items": [
        {"message_id": first, "duration": 5},
        {"message_id": products, "duration": 12},
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


@pytest.mark.parametrize("stored_duration", [6, 12])
def test_designer_scene_end_fades_once_and_hands_off_at_scene_duration(monkeypatch, tmp_path, stored_duration):
    db = Database(str(tmp_path / "signage.db"))
    scene = {"duration": 10, "layers": [{"type": "text", "text": "ON",
                                         "exit_effect": "fade", "exit_duration": 2,
                                         "exit_timing": "scene-end"}]}
    first = db.save_message({"name": "Designer", "editor_mode": "designer",
                             "scene_json": json.dumps(scene)})
    last = db.save_message({"name": "Quick", "text": "NEXT"})
    playlist = db.save_playlist({"items": [{"message_id": first, "duration": stored_duration},
                                           {"message_id": last, "duration": 3}]})
    engine = renderer.RendererEngine(db, str(tmp_path), str(tmp_path))
    ticks = iter([100, 107.9, 109, 110, 112.9, 113])
    tick = [next(ticks)]
    shown = []

    def step(_seconds):
        shown.append((engine._display_message_id, bool(engine._transition)))
        tick[0] = next(ticks, None)
        if tick[0] is None:
            engine._running = False

    monkeypatch.setattr(renderer.time, "monotonic", lambda: tick[0])
    monkeypatch.setattr(renderer.time, "sleep", step)
    monkeypatch.setattr(engine._ddp, "send", lambda _: None)
    engine.show_target("playlist", playlist)
    engine._running = True
    engine._run()

    assert engine.frame_failures == 0
    assert shown == [(first, False)] * 3 + [(last, False)] * 2 + [(first, False)]
    assert [item["scene_duration"] for item in db.get_playlist(playlist)["items"]] == [10, None]
    scene["duration"] = 11.5
    db.save_message({"name": "Designer", "editor_mode": "designer", "scene_json": json.dumps(scene)}, first)
    assert db.get_playlist(playlist)["items"][0]["scene_duration"] == 11.5
    assert engine._message_for_target(engine._manual, 111)[0]["id"] == first
    assert engine._message_for_target(engine._manual, 111.5)[0]["id"] == last
