import os
import json
import sqlite3
import socket
import struct
import sys
import tempfile
import time
import unittest
import zipfile
import importlib.machinery
import importlib.util
from unittest.mock import patch
from datetime import datetime
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import Database
from ddp import DDPSender
from renderer import (
    RendererEngine, _schedule_matches, _message_exit_duration, render_message,
    _load_image, _load_video_frame, _widget_text, _json_path, _apply_scene_transition,
    _live_fetch_async, _LIVE_DATA_CACHE, _weather_visual_category, _weather_template_text,
    _render_weather_widget, _weather_draw_icon, _weather_wind_motion
)
from shader_support import list_shader_assets, prepare_fragment_source, shader_default_params, ShaderClient


def _pixels(image):
    """Pillow 12.1+ replacement for deprecated Image.getdata(), with old-Pillow fallback."""
    getter = getattr(image, "get_flattened_data", None)
    return getter() if getter is not None else image.getdata()


class CoreTests(unittest.TestCase):
    def test_ddp_packetization_offsets_and_push(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(1)
        port = sock.getsockname()[1]
        sender = DDPSender("127.0.0.1", port, 9)
        payload = bytes((i % 251 for i in range(3000)))
        sender.send(payload)
        packets = [sock.recvfrom(2000)[0] for _ in range(3)]
        sender.close(); sock.close()
        chunks = []
        for idx, packet in enumerate(packets):
            flags, seq, datatype, dest, offset, length = struct.unpack("!BBBBLH", packet[:10])
            self.assertEqual(flags & 0x40, 0x40)
            self.assertEqual(datatype, 0x0B)
            self.assertEqual(dest, 1)
            self.assertEqual(offset, 9 + idx * 1440)
            self.assertEqual(length, len(packet) - 10)
            self.assertEqual(bool(flags & 0x01), idx == 2)
            chunks.append(packet[10:])
        self.assertEqual(b"".join(chunks), payload)

    def test_render_message_and_tokens(self):
        msg = {
            "text": "{TIME} TEST", "font": "", "font_size": 14, "auto_fit": 1,
            "text_color": "#ff0000", "background_color": "#000000",
            "outline_color": "#000000", "outline_width": 0,
            "direction": "static", "speed": 30, "align": "center", "valign": "middle",
            "image_path": "", "image_mode": "none", "image_scale": 1, "padding": 1,
        }
        im = render_message(msg, 64, 32, 0, datetime(2026, 8, 16, 9, 42), "/tmp/does-not-exist")
        self.assertEqual(im.size, (64, 32))
        # At least one red text pixel should be present.
        self.assertTrue(any(r > 100 and g < 80 and b < 80 for r, g, b in _pixels(im)))


    def test_render_message_accepts_fractional_text_bounds(self):
        msg = {
            "text": "FLOAT BBOX", "font": "", "font_size": 14, "auto_fit": 0,
            "text_color": "#ffffff", "background_color": "#000000",
            "outline_color": "#000000", "outline_width": 0,
            "direction": "static", "speed": 30, "align": "center", "valign": "middle",
            "image_path": "", "image_mode": "none", "image_scale": 1, "padding": 1,
        }
        from PIL import ImageDraw
        original = ImageDraw.ImageDraw.multiline_textbbox
        def fractional_bbox(draw_self, *args, **kwargs):
            b = original(draw_self, *args, **kwargs)
            return (float(b[0]) + 0.25, float(b[1]) + 0.25, float(b[2]) + 0.75, float(b[3]) + 0.75)
        with patch.object(ImageDraw.ImageDraw, "multiline_textbbox", fractional_bbox):
            im = render_message(msg, 256, 32, 0, datetime(2026, 8, 16, 11, 0), "/tmp/does-not-exist")
        self.assertEqual(im.size, (256, 32))

    def test_designer_scene_layers_gradient_tokens_and_animation(self):
        scene = {
            "version": 1, "design_width": 128, "design_height": 32,
            "background": {"mode": "gradient-h", "color1": "#000010", "color2": "#100000"},
            "layers": [
                {"id":"shape","type":"shape","name":"Band","enabled":True,"x":0,"y":0,"w":24,"h":32,"z":0,"opacity":100,"rotation":0,"animation":"static","fill":"#ff0000","shape":"rounded","radius":3,"border_width":0},
                {"id":"text","type":"text","name":"Clock","enabled":True,"x":24,"y":0,"w":104,"h":32,"z":10,"opacity":100,"rotation":0,"animation":"static","text":"{TIME} TEST","font":"","font_size":18,"auto_fit":True,"wrap":False,"color":"#ffffff","outline_color":"#000000","outline_width":0,"padding":1,"align":"center","valign":"middle","line_spacing":0.12},
            ],
        }
        msg = {"editor_mode": "designer", "scene_json": json.dumps(scene)}
        im = render_message(msg, 128, 32, 0.5, datetime(2026, 8, 16, 11, 22), "/tmp/does-not-exist")
        self.assertEqual(im.size, (128, 32))
        self.assertTrue(any(r > 180 and g < 80 and b < 80 for r, g, b in _pixels(im)))
        self.assertTrue(any(r > 150 and g > 150 and b > 150 for r, g, b in _pixels(im)))

    def test_designer_scroll_can_move_layer_partly_off_canvas(self):
        scene = {"version":1,"design_width":64,"design_height":32,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
            {"id":"t","type":"text","name":"Ticker","enabled":True,"x":0,"y":0,"w":64,"h":32,"z":1,"opacity":100,"animation":"scroll-left","speed":50,"text":"SCROLL","font":"","font_size":14,"auto_fit":False,"wrap":False,"color":"#00ff00","outline_color":"#000000","outline_width":0,"padding":0,"align":"center","valign":"middle","line_spacing":0.12}
        ]}
        msg={"editor_mode":"designer","scene_json":json.dumps(scene)}
        for elapsed in (0, 1.0, 2.0, 4.0):
            im=render_message(msg,64,32,elapsed,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
            self.assertEqual(im.size,(64,32))

    def test_designer_horizontal_scroll_is_clipped_to_layer_width(self):
        for direction in ("scroll-left", "scroll-right"):
            scene = {"version":1,"design_width":64,"design_height":16,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
                {"id":"ticker","type":"text","name":"Ticker","enabled":True,"x":20,"y":2,"w":24,"h":12,"z":1,"opacity":100,
                 "animation":direction,"speed":17,"text":"THIS IS A LONG TICKER","font":"","font_size":10,"auto_fit":False,"wrap":False,
                 "color":"#00ff00","outline_color":"#000000","outline_width":0,"padding":0,"align":"left","valign":"middle",
                 "line_spacing":0.0,"render_mode":"pixel","pixel_scale":1,"pixel_bold":False,"letter_spacing":0}
            ]}
            msg={"editor_mode":"designer","scene_json":json.dumps(scene)}
            saw_text = False
            for elapsed in (0.0, .5, 1.0, 2.0, 4.0, 7.0):
                im=render_message(msg,64,16,elapsed,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
                green=[]
                for yy in range(16):
                    for xx in range(64):
                        r,g,b=im.getpixel((xx,yy))
                        if g > 100 and r < 80 and b < 80:
                            green.append((xx,yy))
                if green:
                    saw_text = True
                    self.assertTrue(all(20 <= xx < 44 and 2 <= yy < 14 for xx,yy in green),
                                    f"{direction} leaked outside layer viewport: {green[:5]}")
            self.assertTrue(saw_text, direction)

    def test_designer_vertical_scroll_is_clipped_to_layer_height(self):
        scene = {"version":1,"design_width":64,"design_height":32,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
            {"id":"crawl","type":"text","name":"Crawl","enabled":True,"x":8,"y":8,"w":48,"h":12,"z":1,"opacity":100,
             "animation":"scroll-up","speed":12,"text":"LINE ONE\nLINE TWO\nLINE THREE","font":"","font_size":8,"auto_fit":False,"wrap":False,
             "color":"#ff0000","outline_color":"#000000","outline_width":0,"padding":0,"align":"center","valign":"top",
             "line_spacing":0.0,"render_mode":"pixel","pixel_scale":1,"pixel_bold":False,"letter_spacing":0}
        ]}
        msg={"editor_mode":"designer","scene_json":json.dumps(scene)}
        saw_text=False
        for elapsed in (0.0, .5, 1.0, 2.0, 4.0):
            im=render_message(msg,64,32,elapsed,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
            red=[]
            for yy in range(32):
                for xx in range(64):
                    r,g,b=im.getpixel((xx,yy))
                    if r > 100 and g < 80 and b < 80:
                        red.append((xx,yy))
            if red:
                saw_text=True
                self.assertTrue(all(8 <= xx < 56 and 8 <= yy < 20 for xx,yy in red))
        self.assertTrue(saw_text)

    def test_designer_horizontal_bounce_is_clipped_to_layer_box(self):
        scene = {"version":1,"design_width":64,"design_height":24,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
            {"id":"bounce","type":"text","name":"Bounce","enabled":True,"x":10,"y":4,"w":30,"h":12,"z":1,"opacity":100,
             "animation":"bounce-horizontal","speed":13,"text":"HI","font":"","font_size":8,"auto_fit":False,"wrap":False,
             "color":"#00ff00","outline_color":"#000000","outline_width":0,"padding":1,"align":"center","valign":"middle",
             "line_spacing":0.0,"render_mode":"led5x7","pixel_scale":1,"pixel_bold":False,"letter_spacing":0}
        ]}
        msg={"editor_mode":"designer","scene_json":json.dumps(scene)}
        seen_x=[]
        for elapsed in (0.0, .4, .8, 1.2, 2.0):
            im=render_message(msg,64,24,elapsed,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
            green=[]
            for yy in range(24):
                for xx in range(64):
                    r,g,b=im.getpixel((xx,yy))
                    if g > 100 and r < 80 and b < 80:
                        green.append((xx,yy))
            self.assertTrue(green)
            self.assertTrue(all(10 <= xx < 40 and 4 <= yy < 16 for xx,yy in green),
                            f"horizontal bounce leaked outside viewport: {green[:5]}")
            seen_x.append(min(xx for xx,_ in green))
        self.assertGreater(len(set(seen_x)), 1, "bounce should move within the viewport")

    def test_designer_vertical_bounce_is_clipped_to_layer_box(self):
        scene = {"version":1,"design_width":48,"design_height":32,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
            {"id":"bounce","type":"text","name":"Bounce","enabled":True,"x":12,"y":5,"w":20,"h":20,"z":1,"opacity":100,
             "animation":"bounce-vertical","speed":11,"text":"HI","font":"","font_size":8,"auto_fit":False,"wrap":False,
             "color":"#ff0000","outline_color":"#000000","outline_width":0,"padding":1,"align":"center","valign":"middle",
             "line_spacing":0.0,"render_mode":"led5x7","pixel_scale":1,"pixel_bold":False,"letter_spacing":0}
        ]}
        msg={"editor_mode":"designer","scene_json":json.dumps(scene)}
        seen_y=[]
        for elapsed in (0.0, .4, .8, 1.2, 2.0):
            im=render_message(msg,48,32,elapsed,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
            red=[]
            for yy in range(32):
                for xx in range(48):
                    r,g,b=im.getpixel((xx,yy))
                    if r > 100 and g < 80 and b < 80:
                        red.append((xx,yy))
            self.assertTrue(red)
            self.assertTrue(all(12 <= xx < 32 and 5 <= yy < 25 for xx,yy in red),
                            f"vertical bounce leaked outside viewport: {red[:5]}")
            seen_y.append(min(yy for _,yy in red))
        self.assertGreater(len(set(seen_y)), 1, "bounce should move within the viewport")

    def test_designer_text_entrance_slide_is_clipped_to_layer_box(self):
        scene = {"version":1,"design_width":64,"design_height":24,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
            {"id":"entrance","type":"text","name":"Entrance","enabled":True,"x":18,"y":5,"w":28,"h":12,"z":1,"opacity":100,
             "delay":0,"animation":"static","entrance_effect":"slide-left","entrance_duration":1.0,"exit_effect":"none","exit_after":0,"exit_duration":.5,
             "text":"HI","font":"","font_size":8,"auto_fit":False,"wrap":False,"color":"#00ff00","outline_color":"#000000","outline_width":0,
             "padding":1,"align":"center","valign":"middle","line_spacing":0.0,"render_mode":"led5x7","pixel_scale":1,"pixel_bold":False,"letter_spacing":0}
        ]}
        msg={"editor_mode":"designer","scene_json":json.dumps(scene)}
        for elapsed in (.1,.5,.9,1.2):
            im=render_message(msg,64,24,elapsed,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
            green=[(x,y) for y in range(24) for x in range(64) if (lambda p:p[1]>100 and p[0]<80 and p[2]<80)(im.getpixel((x,y)))]
            if green:
                self.assertTrue(all(18 <= x < 46 and 5 <= y < 17 for x,y in green), f"entrance leaked outside viewport: {green[:5]}")

    def test_designer_image_fade_exit_turns_layer_off(self):
        with tempfile.TemporaryDirectory() as td:
            img_path=Path(td)/"block.png"
            Image.new("RGB",(12,8),(255,0,0)).save(img_path)
            scene={"version":1,"design_width":40,"design_height":20,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
                {"id":"exit","type":"image","name":"Exit","enabled":True,"x":10,"y":5,"w":12,"h":8,"z":1,"opacity":100,"delay":0,"animation":"static",
                 "entrance_effect":"none","entrance_duration":.5,"exit_effect":"fade","exit_after":1.0,"exit_duration":1.0,"image_path":str(img_path),"fit":"stretch"}
            ]}
            msg={"editor_mode":"designer","scene_json":json.dumps(scene)}
            before=render_message(msg,40,20,.8,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
            during=render_message(msg,40,20,1.5,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
            after=render_message(msg,40,20,2.2,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
            self.assertGreater(sum(1 for p in _pixels(before) if p[0]>200), 50)
            self.assertGreater(sum(1 for p in _pixels(during) if p[0]>20), 0)
            self.assertEqual(sum(1 for p in _pixels(after) if p[0]>0), 0)

    def test_designer_scroll_can_combine_with_wipe_entrance_and_exit(self):
        scene={"version":1,"design_width":64,"design_height":24,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
            {"id":"combo","type":"text","name":"Combo","enabled":True,"x":8,"y":4,"w":42,"h":14,"z":1,"opacity":100,"delay":0,"animation":"scroll-left","speed":10,
             "entrance_effect":"wipe-left","entrance_duration":.6,"exit_effect":"slide-right","exit_after":1.5,"exit_duration":.6,
             "text":"HELLO WORLD","font":"","font_size":8,"auto_fit":False,"wrap":False,"color":"#ffffff","outline_color":"#000000","outline_width":0,
             "padding":1,"align":"center","valign":"middle","line_spacing":0.0,"render_mode":"led5x7","pixel_scale":1,"pixel_bold":False,"letter_spacing":0}
        ]}
        msg={"editor_mode":"designer","scene_json":json.dumps(scene)}
        for elapsed in (.2,.8,1.7,2.2):
            im=render_message(msg,64,24,elapsed,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
            lit=[(x,y) for y in range(24) for x in range(64) if max(im.getpixel((x,y)))>0]
            self.assertTrue(all(8 <= x < 50 and 4 <= y < 18 for x,y in lit), f"combined effect leaked: {lit[:5]}")


    def test_forced_message_change_exit_ignores_exit_after_and_uses_duration(self):
        scene={"version":1,"design_width":32,"design_height":16,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
            {"id":"txt","type":"text","name":"Text","enabled":True,"x":0,"y":0,"w":32,"h":16,"z":1,"opacity":100,"delay":0,"animation":"static",
             "entrance_effect":"none","entrance_duration":.5,"exit_effect":"fade","exit_after":0,"exit_duration":1.0,
             "text":"HI","font":"","font_size":8,"auto_fit":False,"wrap":False,"color":"#ffffff","outline_color":"#000000","outline_width":0,
             "padding":0,"align":"center","valign":"middle","line_spacing":0.0,"render_mode":"led5x7","pixel_scale":1,"pixel_bold":False,"letter_spacing":0}
        ]}
        msg={"id":99,"enabled":1,"editor_mode":"designer","scene_json":json.dumps(scene)}
        self.assertEqual(_message_exit_duration(msg), 1.0)
        normal=render_message(msg,32,16,5.0,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
        halfway=render_message(msg,32,16,5.5,datetime(2026,8,16,11,0),"/tmp/does-not-exist",forced_exit_elapsed=.5)
        finished=render_message(msg,32,16,6.1,datetime(2026,8,16,11,0),"/tmp/does-not-exist",forced_exit_elapsed=1.1)
        normal_sum=sum(sum(p) for p in _pixels(normal))
        halfway_sum=sum(sum(p) for p in _pixels(halfway))
        finished_sum=sum(sum(p) for p in _pixels(finished))
        self.assertGreater(normal_sum, halfway_sum)
        self.assertGreater(halfway_sum, 0)
        self.assertEqual(finished_sum, 0)

    def test_engine_holds_outgoing_message_until_exit_completes(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(str(Path(td)/"signage.db"))
            scene={"version":1,"design_width":32,"design_height":16,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
                {"id":"txt","type":"text","name":"Text","enabled":True,"x":0,"y":0,"w":32,"h":16,"z":1,"opacity":100,"delay":0,"animation":"static",
                 "entrance_effect":"none","entrance_duration":.2,"exit_effect":"fade","exit_after":0,"exit_duration":.35,
                 "text":"A","font":"","font_size":8,"auto_fit":False,"wrap":False,"color":"#ffffff","outline_color":"#000000","outline_width":0,
                 "padding":0,"align":"center","valign":"middle","line_spacing":0.0,"render_mode":"led5x7","pixel_scale":1,"pixel_bold":False,"letter_spacing":0}
            ]}
            aid=db.save_message({"name":"A","editor_mode":"designer","scene_json":json.dumps(scene),"enabled":1})
            bid=db.save_message({"name":"B","text":"B","direction":"static","enabled":1})
            db.update_settings({"default_message_id":aid,"panel_width":32,"panel_height":16,"panels_across":1,"panels_down":1,"frame_rate":40,"ddp_host":"127.0.0.1","ddp_port":4048})
            engine=RendererEngine(db,td,td)
            engine.start()
            try:
                deadline=time.time()+1.0
                while time.time()<deadline:
                    st=engine.status()
                    if st.get("active") and st["active"].get("id")==aid and st.get("frames_sent",0)>1:
                        break
                    time.sleep(.02)
                self.assertEqual(engine.status()["active"]["id"],aid)
                engine.show_target("message",bid)
                deadline=time.time()+.4
                saw_transition=False
                while time.time()<deadline:
                    st=engine.status()
                    if st.get("transition"):
                        saw_transition=True
                        self.assertEqual(st["active"]["id"],aid)
                        break
                    time.sleep(.01)
                self.assertTrue(saw_transition)
                time.sleep(.12)
                self.assertEqual(engine.status()["active"]["id"],aid)
                deadline=time.time()+1.0
                while time.time()<deadline and engine.status()["active"]["id"]!=bid:
                    time.sleep(.02)
                self.assertEqual(engine.status()["active"]["id"],bid)
                self.assertIsNone(engine.status().get("transition"))
            finally:
                engine.stop()

    def test_user_table_default_admin_and_tab_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(str(Path(td)/"signage.db"))
            self.assertEqual(db.list_users(), [])
            admin_id=db.ensure_default_admin("hashed-default")
            admin=db.get_user(admin_id)
            self.assertEqual(admin["username"], "admin")
            self.assertTrue(admin["must_change_password"])
            self.assertTrue(all(admin[k] for k in ("can_messages","can_playlists","can_schedules","can_display_setup","can_upgrade","can_users")))
            viewer_id=db.save_user({"username":"viewer","display_name":"Viewer","password_hash":"hash","is_active":True,"must_change_password":True})
            viewer=db.get_user(viewer_id)
            self.assertFalse(viewer["can_messages"])
            self.assertFalse(viewer["can_users"])
            self.assertEqual(db.active_user_manager_count(), 1)
            self.assertIsNone(db.ensure_default_admin("another-hash"))

    def test_v1_database_migrates_designer_columns(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"old.db"
            con=sqlite3.connect(path)
            con.executescript("""
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,text TEXT NOT NULL DEFAULT '',font TEXT NOT NULL DEFAULT '',font_size INTEGER NOT NULL DEFAULT 18,auto_fit INTEGER NOT NULL DEFAULT 0,text_color TEXT NOT NULL DEFAULT '#ffffff',background_color TEXT NOT NULL DEFAULT '#000000',outline_color TEXT NOT NULL DEFAULT '#000000',outline_width INTEGER NOT NULL DEFAULT 0,direction TEXT NOT NULL DEFAULT 'left',speed REAL NOT NULL DEFAULT 30,align TEXT NOT NULL DEFAULT 'center',valign TEXT NOT NULL DEFAULT 'middle',image_path TEXT NOT NULL DEFAULT '',image_mode TEXT NOT NULL DEFAULT 'none',image_scale REAL NOT NULL DEFAULT 1.0,padding INTEGER NOT NULL DEFAULT 1,enabled INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE playlists (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,enabled INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE playlist_items (id INTEGER PRIMARY KEY AUTOINCREMENT,playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,position INTEGER NOT NULL DEFAULT 0,duration REAL NOT NULL DEFAULT 10);
                CREATE TABLE schedules (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,target_type TEXT NOT NULL,target_id INTEGER NOT NULL,days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',start_date TEXT NOT NULL DEFAULT '',end_date TEXT NOT NULL DEFAULT '',start_time TEXT NOT NULL DEFAULT '00:00',end_time TEXT NOT NULL DEFAULT '23:59',priority INTEGER NOT NULL DEFAULT 100,enabled INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            """)
            con.execute("INSERT INTO messages(name,text,created_at,updated_at) VALUES('Old','HELLO','now','now')")
            con.commit();con.close()
            db=Database(str(path))
            row=db.get_message(1)
            self.assertEqual(row["editor_mode"],"quick")
            self.assertEqual(row["scene_json"],"")
            db.save_message({**row,"editor_mode":"designer","scene_json":json.dumps({"layers":[]})},1)
            self.assertEqual(db.get_message(1)["editor_mode"],"designer")


    def test_pixel_sharp_quick_text_has_hard_edges(self):
        msg = {
            "text": "SHARP", "font": "", "font_size": 20, "auto_fit": 0,
            "text_color": "#ff0000", "background_color": "#000000",
            "outline_color": "#000000", "outline_width": 0,
            "direction": "static", "speed": 30, "align": "center", "valign": "middle",
            "image_path": "", "image_mode": "none", "image_scale": 1, "padding": 1,
            "render_mode": "pixel", "pixel_scale": 1, "pixel_bold": 0, "letter_spacing": 0,
        }
        im = render_message(msg, 128, 32, 0, datetime(2026,8,16,11,30), "/tmp/does-not-exist")
        colours = set(_pixels(im))
        self.assertTrue(any(r == 255 and g == 0 and b == 0 for r,g,b in colours))
        # Pixel mode should not leave dim anti-aliased red edge pixels on a black background.
        self.assertFalse(any(0 < r < 255 and g == 0 and b == 0 for r,g,b in colours))

    def test_led5x7_builtin_font_renders_without_external_font(self):
        msg = {
            "text": "WELCOME 12:34", "font": "/missing/font.ttf", "font_size": 18, "auto_fit": 1,
            "text_color": "#00ff00", "background_color": "#000000",
            "outline_color": "#000000", "outline_width": 0,
            "direction": "static", "speed": 30, "align": "center", "valign": "middle",
            "image_path": "", "image_mode": "none", "image_scale": 1, "padding": 1,
            "render_mode": "led5x7", "pixel_scale": 2, "pixel_bold": 0, "letter_spacing": 0,
        }
        im = render_message(msg, 256, 32, 0, datetime(2026,8,16,11,30), "/tmp/does-not-exist")
        self.assertEqual(im.size, (256,32))
        colours = set(_pixels(im))
        self.assertIn((0,255,0), colours)
        self.assertTrue(colours.issubset({(0,0,0),(0,255,0)}))

    def test_v2_database_migrates_sharp_text_columns(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"v2.db"
            db=Database(str(path))
            # Simulate the fields an upgraded row exposes and verify they can be saved.
            mid=db.save_message({"name":"Sharp","text":"HELLO","render_mode":"led5x7","pixel_scale":3,"pixel_bold":1,"letter_spacing":2})
            row=db.get_message(mid)
            self.assertEqual(row["render_mode"],"led5x7")
            self.assertEqual(row["pixel_scale"],3)
            self.assertEqual(row["pixel_bold"],1)
            self.assertEqual(row["letter_spacing"],2)

    def test_designer_shadow_uses_unoutlined_glyph_body(self):
        scene={"version":1,"design_width":96,"design_height":32,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
            {"id":"shadow","type":"text","name":"Shadow","enabled":True,"x":0,"y":0,"w":96,"h":32,"z":1,"opacity":100,"animation":"static",
             "text":"TEST","font":"","font_size":18,"auto_fit":False,"wrap":False,"color":"#ffffff","outline_color":"#ff0000","outline_width":1,
             "padding":2,"align":"center","valign":"middle","line_spacing":0.0,"shadow_color":"#0000ff","shadow_x":1,"shadow_y":1,
             "render_mode":"led5x7","pixel_scale":1,"pixel_bold":False,"letter_spacing":0}
        ]}
        msg={"editor_mode":"designer","scene_json":json.dumps(scene)}
        im=render_message(msg,96,32,0,datetime(2026,8,16,11,0),"/tmp/does-not-exist")
        white={(x,y) for y in range(32) for x in range(96) if im.getpixel((x,y)) == (255,255,255)}
        blue={(x,y) for y in range(32) for x in range(96) if im.getpixel((x,y)) == (0,0,255)}
        self.assertTrue(white)
        self.assertTrue(blue)
        # Every visible shadow pixel must be a one-pixel translation of a glyph-body
        # pixel, never a translated copy of the red outline.
        self.assertTrue(all((x-1,y-1) in white for x,y in blue),
                        f"shadow contains outlined pixels: {sorted(blue)[:10]}")

    def test_schedule_matching_including_overnight(self):
        sched = {"enabled": 1, "days": "6", "start_date": "", "end_date": "", "start_time": "22:00", "end_time": "06:00"}
        self.assertTrue(_schedule_matches(sched, datetime(2026, 8, 16, 23, 30)))  # Sunday
        self.assertTrue(_schedule_matches({**sched, "days": "0"}, datetime(2026, 8, 17, 2, 0)))  # Monday
        self.assertFalse(_schedule_matches(sched, datetime(2026, 8, 16, 12, 0)))

    def test_database_crud_and_engine_ddp_frame(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"; uploads = Path(td) / "uploads"
            (uploads / "fonts").mkdir(parents=True); (uploads / "images").mkdir(parents=True)
            db = Database(str(data / "signage.db"))
            mid = db.save_message({"name": "Test", "text": "HELLO", "direction": "static"})
            self.assertEqual(db.get_message(mid)["name"], "Test")
            pid = db.save_playlist({"name": "Loop", "items": [{"message_id": mid, "duration": 1.5}]})
            self.assertEqual(len(db.get_playlist(pid)["items"]), 1)
            sid = db.save_schedule({"name": "Always", "target_type": "message", "target_id": mid})
            self.assertEqual(db.get_schedule(sid)["target_id"], mid)

            recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            recv.bind(("127.0.0.1", 0)); recv.settimeout(2)
            db.update_settings({"ddp_port": recv.getsockname()[1], "panel_width": 16, "panel_height": 16, "panels_across": 1, "panels_down": 1, "frame_rate": 10, "default_message_id": mid})
            engine = RendererEngine(db, str(data), str(uploads)); engine.start()
            packet, _ = recv.recvfrom(2000)
            engine.stop(); recv.close()
            self.assertGreater(len(packet), 10)
            self.assertEqual(packet[0] & 0x40, 0x40)
            self.assertGreater(engine.frames_sent, 0)

    def test_upgrade_helper_accepts_valid_release_and_rejects_zip_slip(self):
        helper_path = ROOT / "systemd" / "pi-matrix-signage-upgrade"
        loader = importlib.machinery.SourceFileLoader("pimatrix_upgrade_helper", str(helper_path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        helper = importlib.util.module_from_spec(spec)
        loader.exec_module(helper)
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "good.zip"
            with zipfile.ZipFile(good, "w", zipfile.ZIP_DEFLATED) as z:
                for name in sorted(helper.REQUIRED):
                    data = b"0.2.7\n" if name.endswith("/VERSION") else b"placeholder\n"
                    z.writestr(name, data)
            self.assertEqual(helper.inspect_zip(good), "0.2.7")

            bad = Path(td) / "bad.zip"
            with zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as z:
                for name in sorted(helper.REQUIRED):
                    data = b"0.2.7\n" if name.endswith("/VERSION") else b"placeholder\n"
                    z.writestr(name, data)
                z.writestr("PiMatrixSignage/../escape", b"bad")
            with self.assertRaises(ValueError):
                helper.inspect_zip(bad)

    def test_upgrade_engine_is_packaged_without_customer_upgrade_tab(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        install = (ROOT / "install.sh").read_text(encoding="utf-8")
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('data-tab="upgrade"', html)
        self.assertNotIn('id="upgradeDropZone"', html)
        self.assertNotIn('Software updates', html)
        self.assertNotIn('Update from FPP:', html)
        self.assertIn('/api/upgrade', app_py)
        self.assertIn('/usr/local/sbin/pi-matrix-signage-upgrade', install)
        self.assertTrue((ROOT / "systemd" / "pi-matrix-signage-upgrade").is_file())



    def test_led_font_family_variants_render_as_hard_pixels(self):
        modes = ("led4x6","led5x7","led6x8","led8x8","led8x12","led8x16",
                 "led-condensed","led-bold","led-digital","led-scoreboard","led-dot")
        for mode in modes:
            scene={"version":2,"design_width":96,"design_height":32,
                   "background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
                {"id":"t","type":"text","name":"T","enabled":True,"x":0,"y":0,"w":96,"h":32,"z":1,"opacity":100,
                 "delay":0,"animation":"static","text":"LED 123","font":"","font_size":12,"auto_fit":True,
                 "overflow":"shrink","wrap":False,"color":"#00ff00","outline_color":"#000000","outline_width":0,
                 "padding":0,"align":"center","valign":"middle","line_spacing":0,"render_mode":mode,"pixel_scale":1,
                 "pixel_bold":False,"letter_spacing":0}
            ]}
            im=render_message({"editor_mode":"designer","scene_json":json.dumps(scene)},96,32,0,
                              datetime(2026,8,16,20,0),"/tmp/does-not-exist")
            colours=set(_pixels(im))
            self.assertIn((0,255,0), colours, mode)
            self.assertTrue(colours.issubset({(0,0,0),(0,255,0)}), mode)

    def test_animated_gif_playback_loop_speed_and_hold(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"anim.gif"
            frames=[Image.new("RGB",(4,4),c) for c in ((255,0,0),(0,255,0),(0,0,255))]
            frames[0].save(path,save_all=True,append_images=frames[1:],duration=[100,100,100],loop=0)
            self.assertEqual(_load_image(str(path),0.02).getpixel((0,0))[:3],(255,0,0))
            self.assertEqual(_load_image(str(path),0.12).getpixel((0,0))[:3],(0,255,0))
            self.assertEqual(_load_image(str(path),0.06,speed=2.0).getpixel((0,0))[:3],(0,255,0))
            self.assertEqual(_load_image(str(path),2.0,loop=False).getpixel((0,0))[:3],(0,0,255))

    def test_predecoded_video_frame_playback(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"clip"; root.mkdir()
            colors=[(255,0,0),(0,255,0),(0,0,255)]
            for i,c in enumerate(colors,1):
                Image.new("RGB",(8,4),c).save(root/f"frame-{i:06d}.png")
            (root/"metadata.json").write_text(json.dumps({"frames":3,"fps":2.0,"duration":1.5}),encoding="utf-8")
            self.assertEqual(_load_video_frame(str(root),0.0).getpixel((0,0))[:3],colors[0])
            self.assertEqual(_load_video_frame(str(root),0.55).getpixel((0,0))[:3],colors[1])
            self.assertEqual(_load_video_frame(str(root),1.05).getpixel((0,0))[:3],colors[2])
            self.assertEqual(_load_video_frame(str(root),5.0,loop=False).getpixel((0,0))[:3],colors[2])

    def test_live_widget_clock_date_countdown_and_json_path(self):
        now=datetime(2026,8,16,21,42,5)
        self.assertEqual(_widget_text({"widget_type":"clock","widget_format":"%H:%M:%S"},now),"21:42:05")
        self.assertEqual(_widget_text({"widget_type":"date","widget_format":"%d/%m/%Y"},now),"16/08/2026")
        countdown={"widget_type":"countdown","countdown_target":"2026-08-17T00:00:05",
                   "countdown_format":"{HH}:{MM}:{SS}","widget_prefix":"T-"}
        self.assertEqual(_widget_text(countdown,now),"T-02:18:00")
        payload={"shop":{"queue":[{"name":"Alice"},{"name":"Bob"}]}}
        self.assertEqual(_json_path(payload,"shop.queue.1.name"),"Bob")

    def test_live_data_async_replaces_loading_placeholder(self):
        key="test-live-ready"
        _LIVE_DATA_CACHE.pop(key,None)
        self.addCleanup(_LIVE_DATA_CACHE.pop,key,None)
        workers=[]

        class DeferredThread:
            def __init__(self,target,**_kwargs): workers.append(target)
            def start(self): pass

        with patch("renderer.threading.Thread",DeferredThread), patch("renderer.time.monotonic",return_value=1.0):
            self.assertEqual(_live_fetch_async(key,60,lambda:"Ready"),"Loading…")
        self.assertEqual(len(workers),1)
        workers[0]()
        self.assertEqual(_live_fetch_async(key,60,lambda:"Ready"),"Ready")

    def test_live_data_watchdog_replaces_stuck_weather_loading(self):
        key="test-live-stuck"
        _LIVE_DATA_CACHE[key]={"value":"Loading…","fetched":0.0,"fetching":True,"error":"",
                               "started":1.0,"generation":1}
        with patch("renderer.time.monotonic",return_value=10.0):
            value=_live_fetch_async(key,60,lambda:"Too late",error_value="Weather unavailable",fetch_timeout=3.0)
        self.assertEqual(value,"Weather unavailable")
        self.assertFalse(_LIVE_DATA_CACHE[key]["fetching"])
        self.assertIn("timed out",_LIVE_DATA_CACHE[key]["error"])
        _LIVE_DATA_CACHE.pop(key,None)

    def test_v042_static_designer_preview_refreshes_live_widgets(self):
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        self.assertIn("sceneHasLiveWidget()",js)
        self.assertIn("lastWidgetPreviewAt",js)
        self.assertIn("updateEditorPreview()",js)

    def test_typewriter_reveals_more_text_over_time(self):
        base={"version":2,"design_width":128,"design_height":32,
              "background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
            {"id":"t","type":"text","name":"T","enabled":True,"x":0,"y":0,"w":128,"h":32,"z":1,"opacity":100,
             "delay":0,"animation":"typewriter","typewriter_speed":4,"text":"TYPEWRITER","font":"","font_size":12,
             "auto_fit":False,"overflow":"manual","wrap":False,"color":"#ffffff","outline_color":"#000000","outline_width":0,
             "padding":0,"align":"left","valign":"middle","line_spacing":0,"render_mode":"led5x7","pixel_scale":1,
             "pixel_bold":False,"letter_spacing":0}
        ]}
        msg={"editor_mode":"designer","scene_json":json.dumps(base)}
        a=render_message(msg,128,32,.3,datetime(2026,8,16,21,42),"/tmp/no")
        b=render_message(msg,128,32,1.5,datetime(2026,8,16,21,42),"/tmp/no")
        lit_a=sum(1 for p in _pixels(a) if max(p)>0)
        lit_b=sum(1 for p in _pixels(b) if max(p)>0)
        self.assertGreater(lit_b,lit_a)


    def test_random_reveal_shows_more_characters_over_effect_period(self):
        base={"version":2,"design_width":128,"design_height":32,
              "background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
            {"id":"rr","type":"text","name":"RR","enabled":True,"x":0,"y":0,"w":128,"h":32,"z":1,"opacity":100,
             "delay":0,"animation":"random-reveal","effect_period":2.0,"text":"RANDOM","font":"","font_size":12,
             "auto_fit":False,"overflow":"manual","wrap":False,"color":"#ffffff","outline_color":"#000000","outline_width":0,
             "padding":0,"align":"left","valign":"middle","line_spacing":0,"render_mode":"led5x7","pixel_scale":1,
             "pixel_bold":False,"letter_spacing":0}
        ]}
        msg={"editor_mode":"designer","scene_json":json.dumps(base)}
        a=render_message(msg,128,32,0.2,datetime(2026,8,16,21,42),"/tmp/no")
        b=render_message(msg,128,32,1.2,datetime(2026,8,16,21,42),"/tmp/no")
        c=render_message(msg,128,32,2.2,datetime(2026,8,16,21,42),"/tmp/no")
        lit_a=sum(1 for p in _pixels(a) if max(p)>0)
        lit_b=sum(1 for p in _pixels(b) if max(p)>0)
        lit_c=sum(1 for p in _pixels(c) if max(p)>0)
        self.assertGreater(lit_b,lit_a)
        self.assertGreater(lit_c,lit_b)

    def test_auto_marquee_only_moves_when_text_overflows(self):
        def scene_for(text):
            return {"version":2,"design_width":64,"design_height":16,
                    "background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
                {"id":"t","type":"text","name":"T","enabled":True,"x":8,"y":2,"w":32,"h":12,"z":1,"opacity":100,
                 "delay":0,"animation":"auto-marquee","speed":12,"text":text,"font":"","font_size":8,"auto_fit":False,
                 "overflow":"manual","wrap":False,"color":"#00ff00","outline_color":"#000000","outline_width":0,
                 "padding":0,"align":"left","valign":"middle","line_spacing":0,"render_mode":"led5x7","pixel_scale":1,
                 "pixel_bold":False,"letter_spacing":0}
            ]}
        short={"editor_mode":"designer","scene_json":json.dumps(scene_for("HI"))}
        long={"editor_mode":"designer","scene_json":json.dumps(scene_for("THIS IS MUCH TOO LONG"))}
        s0=render_message(short,64,16,0,datetime(2026,8,16,21,42),"/tmp/no")
        s1=render_message(short,64,16,1,datetime(2026,8,16,21,42),"/tmp/no")
        l0=render_message(long,64,16,0,datetime(2026,8,16,21,42),"/tmp/no")
        l1=render_message(long,64,16,1,datetime(2026,8,16,21,42),"/tmp/no")
        self.assertEqual(list(_pixels(s0)),list(_pixels(s1)))
        self.assertNotEqual(list(_pixels(l0)),list(_pixels(l1)))

    def test_scene_transitions_and_exit_duration(self):
        base=Image.new("RGB",(32,16),(255,255,255))
        scene={"transition_in":"wipe-left","transition_in_duration":1.0,
               "transition_out":"fade","transition_out_duration":1.25}
        early=_apply_scene_transition(base,scene,.2)
        finished=_apply_scene_transition(base,scene,1.2)
        self.assertLess(sum(sum(p) for p in _pixels(early)),sum(sum(p) for p in _pixels(finished)))
        message={"editor_mode":"designer","scene_json":json.dumps({**scene,"layers":[]})}
        self.assertEqual(_message_exit_duration(message),1.25)
        outgoing=_apply_scene_transition(base,scene,9.0,forced_exit_elapsed=.7)
        gone=_apply_scene_transition(base,scene,9.0,forced_exit_elapsed=1.3)
        self.assertGreater(sum(sum(p) for p in _pixels(outgoing)),0)
        self.assertEqual(sum(sum(p) for p in _pixels(gone)),0)

    def test_gradient_rainbow_glow_and_character_colours_render(self):
        effects=("gradient","rainbow","cycle","characters","words")
        for effect in effects:
            scene={"version":2,"design_width":96,"design_height":32,
                   "background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
                {"id":"t","type":"text","name":"T","enabled":True,"x":0,"y":0,"w":96,"h":32,"z":1,"opacity":100,
                 "delay":0,"animation":"static","text":"RED BLUE","font":"","font_size":10,"auto_fit":False,
                 "overflow":"manual","wrap":False,"color":"#ff0000","color2":"#0000ff","color_effect":effect,
                 "color_speed":.2,"color_palette":"#ff0000,#00ff00,#0000ff","glow":1,"glow_color":"#ffffff",
                 "outline_color":"#000000","outline_width":0,"padding":2,"align":"center","valign":"middle",
                 "line_spacing":0,"render_mode":"led5x7","pixel_scale":1,"pixel_bold":False,"letter_spacing":0}
            ]}
            im=render_message({"editor_mode":"designer","scene_json":json.dumps(scene)},96,32,.7,
                              datetime(2026,8,16,21,42),"/tmp/no")
            nonblack={p for p in _pixels(im) if max(p)>0}
            self.assertGreater(len(nonblack),1,effect)

    def test_v030_ui_contains_timeline_media_widgets_and_shutdown(self):
        html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        install=(ROOT/"install.sh").read_text(encoding="utf-8")
        for marker in ('id="timelineLanes"','id="sceneTransitionIn"','id="addVideoLayer"',
                       'id="addWidgetLayer"','id="shutdownPi"','id="layerOverflow"',
                       'id="layerColorEffect"'):
            self.assertIn(marker,html)
        self.assertIn('/api/shutdown',js)
        self.assertIn('pi-matrix-signage-poweroff',install)
        self.assertTrue((ROOT/"systemd"/"pi-matrix-signage-poweroff").is_file())


    def test_v040_zone_hard_clips_layer_at_render_time(self):
        scene={"version":3,"design_width":64,"design_height":16,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},
               "zones":[{"id":"z1","name":"Middle","x":20,"y":2,"w":24,"h":12}],"layers":[
            {"id":"s","type":"shape","name":"Wide","enabled":True,"x":0,"y":0,"w":64,"h":16,"z":1,"opacity":100,
             "rotation":0,"animation":"static","shape":"rectangle","fill":"#ff0000","border_width":0,"zone_id":"z1"}
        ]}
        im=render_message({"editor_mode":"designer","scene_json":json.dumps(scene)},64,16,0,
                          datetime(2026,8,16,22,0),"/tmp/no")
        red=[(x,y) for y in range(16) for x in range(64) if im.getpixel((x,y))[0]>200]
        self.assertTrue(red)
        self.assertTrue(all(20<=x<44 and 2<=y<14 for x,y in red))

    def test_v040_analogue_clock_widget_renders_hands_and_face(self):
        scene={"version":3,"design_width":32,"design_height":32,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"zones":[],"layers":[
            {"id":"clock","type":"widget","name":"Analogue","enabled":True,"x":0,"y":0,"w":32,"h":32,"z":1,"opacity":100,
             "rotation":0,"delay":0,"animation":"static","widget_type":"analog-clock","clock_ring_color":"#ffffff",
             "clock_tick_color":"#ffffff","clock_hour_color":"#ffffff","clock_minute_color":"#ffffff",
             "clock_second_color":"#ff0000","clock_show_seconds":True,"clock_fill_face":False}
        ]}
        im=render_message({"editor_mode":"designer","scene_json":json.dumps(scene)},32,32,0,
                          datetime(2026,8,16,3,0,0),"/tmp/no")
        pixels=list(_pixels(im))
        self.assertTrue(any(r>220 and g>220 and b>220 for r,g,b in pixels))
        self.assertTrue(any(r>220 and g<80 and b<80 for r,g,b in pixels))

    def test_v040_component_library_persists_json(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(str(Path(td)/"signage.db"))
            cid=db.save_component({"name":"Header","component":{"version":1,"width":32,"height":8,"zones":[],"layers":[{"id":"a","type":"text","x":0,"y":0,"w":32,"h":8}]}})
            item=db.get_component(cid)
            self.assertEqual(item["name"],"Header")
            self.assertEqual(item["component"]["layers"][0]["type"],"text")
            self.assertEqual(len(db.list_components()),1)
            db.delete_component(cid)
            self.assertEqual(db.list_components(),[])

    def test_v040_led_compact_and_seven_segment_faces_are_hard_edged(self):
        def render(mode,text):
            scene={"version":3,"design_width":96,"design_height":24,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"zones":[],"layers":[
                {"id":"t","type":"text","name":"T","enabled":True,"x":0,"y":0,"w":96,"h":24,"z":1,"opacity":100,"animation":"static",
                 "text":text,"font":"","font_size":12,"auto_fit":False,"wrap":False,"color":"#00ff00","outline_color":"#000000","outline_width":0,
                 "padding":0,"align":"center","valign":"middle","line_spacing":0,"render_mode":mode,"pixel_scale":2,"pixel_bold":False,"letter_spacing":0}
            ]}
            return render_message({"editor_mode":"designer","scene_json":json.dumps(scene)},96,24,0,datetime(2026,8,16,22,0),"/tmp/no")
        compact=render("led3x5","1234")
        digital=render("led-digital","1234")
        self.assertNotEqual(list(_pixels(compact)),list(_pixels(digital)))
        self.assertTrue(set(_pixels(digital)).issubset({(0,0,0),(0,255,0)}))

    def test_v041_video_upload_progress_ui_and_async_api_are_packaged(self):
        html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        app_py=(ROOT/"app.py").read_text(encoding="utf-8")
        for marker in ('id="videoUploadProgress"','id="videoUploadBar"','id="videoUploadStage"','id="videoUploadPercent"'):
            self.assertIn(marker,html)
        for marker in ('xhr.upload.onprogress','/api/upload/video/start','waitForVideoJob','Creating LED frames'):
            self.assertIn(marker,js)
        for marker in ('/api/upload/video/start','/api/upload/video/status/<job_id>','-progress", "pipe:1"'):
            self.assertIn(marker,app_py)

    def test_v040_ui_contains_designer_workflow_and_live_preview_controls(self):
        html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        for marker in ('id="undoDesigner"','id="redoDesigner"','id="groupLayers"','id="designerSnapGrid"',
                       'id="designerZoneList"','id="componentPicker"','value="analog-clock"','id="livePreviewEnabled"'):
            self.assertIn(marker,html)
        for marker in ('function undoDesigner','function alignSelection','function saveSelectionAsComponent','function scheduleLivePreview'):
            self.assertIn(marker,js)

    def test_v043_messages_designer_workspace_is_compacted(self):
        html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        css=(ROOT/"static"/"app.css").read_text(encoding="utf-8")
        for marker in ('id="messageSearch"','class="timeline-panel"','class="sidebar-group"','class="inspector-group inspector-motion"','id="widgetTextStyle"','class="font-manager"'):
            self.assertIn(marker,html)
        for marker in ('initDesignerPanelPreferences','widgetTextStyle','No matching messages.'):
            self.assertIn(marker,js)
        for marker in ('.messages-layout','.content-properties{order:1;','.designer-layer-panel{position:sticky'):
            self.assertIn(marker,css)


    def test_colour_picker_has_preset_and_custom_modes(self):
        js = (ROOT / "static" / "app.js").read_text()
        css = (ROOT / "static" / "app.css").read_text()
        for colour in ("#b84921", "#e1b2c2", "#b5d889", "#91cad6", "#003748"):
            self.assertIn(colour, js)
        self.assertIn("Preset colours", js)
        self.assertIn("Custom colour", js)
        self.assertIn("colour-picker-popover", css)

    def test_v045_custom_colour_picker_has_reliable_controls(self):
        js = (ROOT / "static" / "app.js").read_text()
        css = (ROOT / "static" / "app.css").read_text()
        for marker in ("Choose custom colour…", "colour-rgb-grid", "colour-hex-input", "native.showPicker", "rgbToHex"):
            self.assertIn(marker, js)
        for marker in (".colour-custom-choose", ".colour-custom-swatch", ".colour-rgb-grid"):
            self.assertIn(marker, css)


    def test_v047_upgrade_restart_disconnect_is_not_reported_as_failure(self):
        js = (ROOT / "static" / "app.js").read_text()
        helper = (ROOT / "systemd" / "pi-matrix-signage-upgrade").read_text()
        app_py = (ROOT / "app.py").read_text()
        for marker in ("releaseVersionFromFilename", "showUpgradeRestarting", "alreadyDisconnected",
                       "uploaded. Verifying the restarted service", "if(!e.status)"):
            self.assertIn(marker, js)
        self.assertIn("time.sleep(3.0)", helper)
        self.assertIn('"version": APP_VERSION', app_py)

    def test_v0418_upgrade_reconnect_uses_public_health_and_forces_fresh_page(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")
        for marker in ("probeUpgradeHealth", "/health?upgrade_probe=", "forceReloadAfterUpgrade",
                       "window.location.replace", "upgraded", "cache:'no-store'"):
            self.assertIn(marker, js)
        self.assertIn('response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"', app_py)
        self.assertIn('response.headers["X-PiMatrix-Version"] = APP_VERSION', app_py)

    def test_v048_recovery_settings_and_event_history_persist(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(str(Path(td)/"signage.db"))
            settings=db.get_settings()
            self.assertTrue(settings["auto_recovery_enabled"])
            self.assertTrue(settings["auto_recover_renderer"])
            self.assertTrue(settings["auto_recover_fppd"])
            db.update_settings({"renderer_stall_seconds":9,"recovery_cooldown_seconds":120})
            self.assertEqual(db.get_settings()["renderer_stall_seconds"],9)
            db.add_recovery_event("renderer","restart-renderer","success","watchdog test")
            rows=db.list_recovery_events()
            self.assertEqual(rows[0]["result"],"success")
            self.assertIn("watchdog",rows[0]["details"])
            db.clear_recovery_events()
            self.assertEqual(db.list_recovery_events(),[])

    def test_v048_renderer_can_restart_without_web_service_restart(self):
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as td:
                db=Database(str(Path(td)/"signage.db"));db.update_settings({"ddp_host":"127.0.0.1","ddp_port":port,"frame_rate":15})
                engine=RendererEngine(db,td,td);engine.start()
                deadline=time.time()+1.5
                while engine.frames_sent<2 and time.time()<deadline:time.sleep(.03)
                before=engine.frames_sent
                self.assertGreaterEqual(before,1)
                self.assertTrue(engine.restart())
                deadline=time.time()+1.5
                while engine.frames_sent<=before and time.time()<deadline:time.sleep(.03)
                self.assertGreater(engine.frames_sent,before)
                self.assertGreaterEqual(engine.status()["renderer_restarts"],1)
                engine.stop()
        finally:
            sock.close()

    def test_v048_diagnostics_and_safe_recovery_are_packaged(self):
        html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        helper=(ROOT/"systemd"/"pi-matrix-signage-upgrade").read_text(encoding="utf-8")
        service=(ROOT/"systemd"/"pi-matrix-signage.service").read_text(encoding="utf-8")
        diagnostics=(ROOT/"diagnostics.py").read_text(encoding="utf-8")
        for marker in ('id="diagOverall"','id="diagCpu"','id="autoRecoveryEnabled"','id="restartRenderer"','id="restartFppd"','id="recoveryHistory"'):
            self.assertIn(marker,html)
        for marker in ('loadDiagnostics','saveRecoverySettings','restart-renderer','restart-fppd'):
            self.assertIn(marker,js)
        self.assertIn('--recover-fppd',helper)
        self.assertIn('systemctl", "restart", "fppd.service',helper)
        self.assertIn('Restart=always',service)
        self.assertIn('never reboots or powers off',diagnostics)



    def test_v0410_weather_codes_map_to_animated_visuals(self):
        expected={0:"clear",1:"partly-cloudy",2:"partly-cloudy",3:"cloudy",45:"fog",51:"drizzle",61:"rain",71:"snow",80:"showers",85:"snow-showers",95:"thunder"}
        for code,category in expected.items():
            self.assertEqual(_weather_visual_category(code),category)

    def test_v0410_weather_icon_library_covers_requested_conditions(self):
        for category in ("clear","partly-cloudy","cloudy","rain","snow","fog","thunder"):
            a=_weather_draw_icon(category,32,32,.2,True,True,12,270,"mph")
            b=_weather_draw_icon(category,32,32,1.0,True,True,12,270,"mph")
            self.assertGreater(sum(1 for px in _pixels(a) if px[3]>0),4,category)
            self.assertNotEqual(list(_pixels(a)),list(_pixels(b)),category)

    def test_v0410_weather_template_supports_extended_current_conditions(self):
        layer={"weather_template":"{TEMP}{TEMP_UNIT} feels {FEELS}{TEMP_UNIT} · {WIND_DIR} {WIND}{WIND_UNIT} · gust {GUST}{WIND_UNIT} · RH {HUMIDITY}% · {PRECIP}mm"}
        data={"status":"ok","temp":13.4,"feels":11.2,"temp_unit":"°C","wind_compass":"WNW","wind":12.3,"wind_unit":"mph","gust":20.8,"humidity":74,"precip":0.2,"condition":"Rain","code":61}
        text=_weather_template_text(layer,data)
        for value in ("13.4°C","11.2°C","WNW 12.3mph","20.8mph","RH 74%","0.2mm"):
            self.assertIn(value,text)

    def test_v0410_animated_weather_panel_changes_frames_and_stays_in_box(self):
        data={"status":"ok","code":61,"condition":"Rain","category":"rain","temp":12.0,"feels":9.0,"humidity":80,"precip":1.2,"rain":1.2,"showers":0,"snow":0,"cloud":95,"wind":14,"wind_direction":285,"wind_compass":"WNW","gust":22,"is_day":True,"temp_unit":"°C","wind_unit":"mph"}
        layer={"type":"widget","widget_type":"weather","weather_display":"animated","weather_show_icon":True,"weather_animate_icon":True,"weather_show_condition":True,"weather_show_feels":True,"weather_show_wind":True,"weather_show_gusts":False,"weather_show_humidity":False,"weather_show_precip":False,"render_mode":"led5x7","color":"#ffffff","auto_fit":True,"padding":0,"align":"left","valign":"middle","font_size":12}
        with patch("renderer._weather_current",return_value=data):
            a=_render_weather_widget(layer,96,32,1.0,.1,datetime(2026,8,17,9,0),"/tmp/does-not-exist")
            b=_render_weather_widget(layer,96,32,1.0,.8,datetime(2026,8,17,9,0),"/tmp/does-not-exist")
        self.assertEqual(a.size,(96,32));self.assertEqual(b.size,(96,32))
        self.assertNotEqual(list(_pixels(a)),list(_pixels(b)))
        self.assertGreater(sum(1 for px in _pixels(a) if px[3]>0),20)

    def test_v0410_weather_ui_exposes_animation_metrics_and_units(self):
        html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        renderer=(ROOT/"renderer.py").read_text(encoding="utf-8")
        for marker in ('id="layerWeatherDisplay"','id="weatherShowIcon"','id="weatherAnimateIcon"','id="weatherShowFeels"','id="weatherShowWind"','id="weatherShowGusts"','id="weatherShowHumidity"','id="weatherShowPrecip"','id="layerWeatherTempUnit"','id="layerWeatherWindUnit"'):
            self.assertIn(marker,html)
        for marker in ('weather_display','weather_show_feels','weather_show_wind','weather_show_humidity','weather_animate_icon'):
            self.assertIn(marker,js)
        for marker in ('relative_humidity_2m','wind_direction_10m','wind_gusts_10m','cloud_cover','snowfall','_render_weather_widget'):
            self.assertIn(marker,renderer)

    def test_v0411_weather_drift_speed_tracks_wind_and_direction(self):
        calm=_weather_wind_motion(0,270,"mph")
        light=_weather_wind_motion(5,270,"mph")
        strong=_weather_wind_motion(20,270,"mph")
        easterly=_weather_wind_motion(20,90,"mph")
        self.assertLess(abs(calm[0]),abs(light[0]))
        self.assertLess(abs(light[0]),abs(strong[0]))
        self.assertGreater(strong[0],0)   # wind from west travels east/right
        self.assertLess(easterly[0],0)   # wind from east travels west/left
        kmh=_weather_wind_motion(16.09344,270,"km/h")
        mph=_weather_wind_motion(10,270,"mph")
        self.assertAlmostEqual(kmh[0],mph[0],places=5)

    def test_v0411_clouds_drift_one_way_instead_of_bouncing(self):
        def cloud_centroid(t,wind,direction=270):
            im=_weather_draw_icon("partly-cloudy",32,32,t,True,True,wind,direction,"mph")
            cloud={(205,220,230),(175,195,208),(145,165,180)}
            xs=[x for y in range(32) for x in range(32) if im.getpixel((x,y))[:3] in cloud]
            return sum(xs)/len(xs)
        west=[cloud_centroid(t,15,270) for t in (0,.5,1.0,1.5)]
        east=[cloud_centroid(t,15,90) for t in (0,.5,1.0,1.5)]
        self.assertTrue(all(b>a for a,b in zip(west,west[1:])),west)
        self.assertTrue(all(b<a for a,b in zip(east,east[1:])),east)
        slow=abs(cloud_centroid(1.0,5)-cloud_centroid(0,5))
        fast=abs(cloud_centroid(1.0,20)-cloud_centroid(0,20))
        self.assertGreater(fast,slow)

    def test_v0411_rain_snow_fog_use_wind_aware_motion(self):
        for category in ("rain","snow","fog"):
            slow=_weather_draw_icon(category,32,32,1.5,True,True,3,270,"mph")
            fast=_weather_draw_icon(category,32,32,1.5,True,True,25,270,"mph")
            reverse=_weather_draw_icon(category,32,32,1.5,True,True,25,90,"mph")
            self.assertNotEqual(list(_pixels(slow)),list(_pixels(fast)),category)
            self.assertNotEqual(list(_pixels(fast)),list(_pixels(reverse)),category)

    def test_v049_builtin_icon_library_renders_crisp_pictograms(self):
        icons=("arrow-left","arrow-right","arrow-up","arrow-down","warning","info","wheelchair","toilet","parking","wifi","phone","tick","cross","heart","smile","walking","bell","star","gift","snowflake","sale-tag","queue")
        for name in icons:
            scene={"version":4,"design_width":32,"design_height":32,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[
                {"id":"i","type":"icon","name":name,"enabled":True,"x":0,"y":0,"w":32,"h":32,"z":1,"opacity":100,"rotation":0,"delay":0,"animation":"static","icon_name":name,"icon_color":"#ffffff","icon_color2":"#003748","icon_effect":"none","icon_period":1}
            ]}
            im=render_message({"editor_mode":"designer","scene_json":json.dumps(scene)},32,32,.2,datetime(2026,8,17,8,45),"/tmp/does-not-exist")
            self.assertGreater(sum(1 for px in _pixels(im) if max(px)>0),2,name)
            self.assertTrue(set(_pixels(im)).issubset({(0,0,0),(255,255,255),(0,55,72)}),name)

    def test_v049_icon_effects_animate_without_moving_layer_box(self):
        base={"id":"i","type":"icon","name":"Walking","enabled":True,"x":8,"y":0,"w":24,"h":24,"z":1,"opacity":100,"rotation":0,"delay":0,"animation":"static","icon_name":"walking","icon_color":"#00ff00","icon_color2":"#003300","icon_effect":"native","icon_period":1}
        scene={"version":4,"design_width":48,"design_height":24,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},"layers":[base]}
        a=render_message({"editor_mode":"designer","scene_json":json.dumps(scene)},48,24,.1,datetime(2026,8,17,8,45),"/tmp/does-not-exist")
        b=render_message({"editor_mode":"designer","scene_json":json.dumps(scene)},48,24,.35,datetime(2026,8,17,8,45),"/tmp/does-not-exist")
        self.assertNotEqual(list(_pixels(a)),list(_pixels(b)))
        for im in (a,b):
            lit=[(x,y) for y in range(24) for x in range(48) if max(im.getpixel((x,y)))>0]
            self.assertTrue(lit)
            self.assertTrue(all(8<=x<32 for x,y in lit))

    def test_v049_template_library_and_icon_controls_are_packaged(self):
        html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        for marker in ('id="templateLibrary"','id="applyTemplateLibrary"','id="addIconLayer"','id="iconLayerProperties"','id="layerIconName"','id="layerIconEffect"'):
            self.assertIn(marker,html)
        for kind in ('welcome','opening-hours','information','queue','direction-left','direction-right','parking','wifi','sale','price','event','birthday','christmas','emergency','accessibility','countdown','weather','split-screen'):
            self.assertIn(f"value=\"{kind}\"",html)
            if kind.startswith('direction-'):
                self.assertIn("kind.startsWith('direction-')",js)
            else:
                self.assertIn(kind,js)
        for marker in ('defaultIconLayer','icon_effect','templateScene'):
            self.assertIn(marker,js)
        self.assertIn('Arrow chase',html)


    def test_v0412_backup_permission_and_schema(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(str(Path(td)/"signage.db"))
            db.ensure_default_admin("hash","admin")
            admin=db.get_user_by_username("admin")
            self.assertIn("can_backup",admin)
            self.assertEqual(int(admin["can_backup"]),1)
            self.assertEqual(db.USER_PERMISSION_FIELDS[-2:],("can_backup","can_users"))

    def test_v0412_backup_tab_and_controls_are_packaged(self):
        html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        for marker in ('data-tab="backup"','id="page-backup"','id="createBackup"','id="backupList"','id="backupDropZone"','id="permBackup"'):
            self.assertIn(marker,html)
        for marker in ('loadBackups','createBackup','restoreExistingBackup','restoreUploadedBackup','can_backup'):
            self.assertIn(marker,js)

    def test_v0412_helper_uses_fpp_supported_backup_restore(self):
        helper=(ROOT/"systemd"/"pi-matrix-signage-upgrade").read_text(encoding="utf-8")
        for marker in ('backup.php','backuparea=all','restorearea=all','keepExitingNetwork=1','keepMasterSlave=1','fpp/fpp-backup.json','pre-restore'):
            self.assertIn(marker,helper)

    def test_v0413_backup_creation_is_unprivileged_and_has_raw_fpp_fallback(self):
        app_py=(ROOT/"app.py").read_text(encoding="utf-8")
        helper=(ROOT/"systemd"/"pi-matrix-signage-upgrade").read_text(encoding="utf-8")
        self.assertIn('target=_backup_create_worker_local', app_py)
        self.assertIn('FPP official backup unavailable; using raw fallback', app_py)
        self.assertIn('fpp/raw-media/settings', app_py)
        self.assertIn('restore_fpp_raw', helper)
        self.assertIn('raw-fallback', helper)
        create_section=app_py.split('def backup_create_api():',1)[1].split('@app.get("/api/backups/',1)[0]
        self.assertNotIn('_run_backup_helper', create_section)

    def test_v0414_shader_metadata_and_uniform_initialisers_are_supported(self):
        src = '''/*{
          "INPUTS":[
            {"NAME":"rate","TYPE":"float","DEFAULT":1.5,"MIN":0.1,"MAX":3},
            {"NAME":"tint","TYPE":"color","DEFAULT":[1,0,0,1]}
          ],"ISFVSN":"2"
        }*/
        float moving = TIME * rate;
        void main(){ gl_FragColor=vec4(vec3(fract(moving)),1.0); }
        '''
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); built=root/"built"; upload=root/"upload"; built.mkdir();upload.mkdir()
            (built/"Test.fs").write_text(src,encoding="utf-8")
            assets=list_shader_assets(upload,built)
            self.assertEqual(len(assets),1)
            self.assertEqual(assets[0]["inputs"][0]["name"],"rate")
            defaults=shader_default_params(assets[0]["inputs"])
            self.assertEqual(defaults["rate"],1.5)
            prepared=prepare_fragment_source(src,assets[0]["inputs"],False)
            self.assertIn("uniform float TIME;",prepared)
            self.assertIn("uniform vec2 RENDERSIZE;",prepared)
            self.assertIn("uniform float rate;",prepared)
            self.assertIn("float moving;",prepared)
            self.assertIn("moving = TIME * rate;",prepared)

    def test_v0414_shader_layer_uses_normal_zone_clipping(self):
        scene={"version":4,"design_width":64,"design_height":32,"background":{"mode":"solid","color1":"#000000","color2":"#000000"},
               "zones":[{"id":"z","name":"Shader zone","x":16,"y":4,"w":16,"h":20}],
               "layers":[{"id":"shader1","type":"shader","name":"Shader","enabled":True,"x":8,"y":0,"w":40,"h":32,"z":1,"opacity":100,"rotation":0,"delay":0,"animation":"static","zone_id":"z","shader_id":"builtin:LED-Plasma.fs","shader_params":{},"shader_fps":15,"shader_time_scale":1}]}
        fake=Image.new("RGBA",(40,32),(255,0,0,255))
        with patch("renderer._shader_client") as client_factory:
            client_factory.return_value.get_frame.return_value=fake
            im=render_message({"editor_mode":"designer","scene_json":json.dumps(scene)},64,32,.5,datetime(2026,8,17,13,0),str(ROOT/"uploads"/"fonts"))
        lit=[(x,y) for y in range(32) for x in range(64) if im.getpixel((x,y))[0]>0]
        self.assertTrue(lit)
        self.assertTrue(all(16<=x<32 and 4<=y<24 for x,y in lit))

    def test_v0414_shader_ui_and_builtins_are_packaged(self):
        html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        app_py=(ROOT/"app.py").read_text(encoding="utf-8")
        for marker in ('id="addShaderLayer"','id="designerShaderUpload"','id="shaderLayerProperties"','id="layerShader"','id="shaderParameterFields"'):
            self.assertIn(marker,html)
        for marker in ('defaultShaderLayer','renderShaderParameterFields','shader_params','/api/shaders','/api/upload/shader'):
            self.assertIn(marker,js+app_py)
        for name in ("LED-Plasma.fs","Aurora.fs","Pixel-Waves.fs"):
            self.assertTrue((ROOT/"shaders"/name).is_file(),name)
        self.assertIn('PiMatrixSignage/shader_support.py', app_py)

    def test_v0414_shader_client_keeps_old_frame_only_at_same_size(self):
        # Unit-level assertion of the resize safety rule without requiring a GPU.
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);upload=root/"u";built=root/"b";upload.mkdir();built.mkdir()
            (built/"T.fs").write_text('void main(){gl_FragColor=vec4(1.0);}',encoding='utf-8')
            c=ShaderClient(upload,built)
            old=Image.new('RGBA',(8,8),(255,0,0,255))
            c._frames['k']=(('old',),old)
            with patch.object(c,'_start_thread'):
                frame=c.get_frame('k','builtin:T.fs',16,8,0,{},15,1)
            self.assertEqual(frame.size,(16,8))
            self.assertEqual(frame.getbbox(),None)


    def test_v0415_shader_extensions_are_emitted_before_injected_uniforms(self):
        src = '''/*{"INPUTS":[{"NAME":"mouse","TYPE":"point2D"}]}*/
#extension GL_OES_standard_derivatives : enable
void main(){ float edge=fwidth(gl_FragCoord.x); gl_FragColor=vec4(edge); }
'''
        inputs=[{"name":"mouse","type":"point2D","default":[0,0]}]
        desktop=prepare_fragment_source(src,inputs,False)
        self.assertNotIn("GL_OES_standard_derivatives",desktop)
        self.assertIn("uniform float TIME;",desktop)
        self.assertIn("uniform vec2 RENDERSIZE;",desktop)
        es=prepare_fragment_source(src,inputs,True)
        ext_pos=es.index("#extension GL_OES_standard_derivatives : enable")
        precision_pos=es.index("precision highp float;")
        uniform_pos=es.index("uniform float TIME;")
        self.assertLess(ext_pos,precision_pos)
        self.assertLess(ext_pos,uniform_pos)


    def test_v0416_shader_auto_quality_falls_back_after_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); upload=root/"u"; built=root/"b"; upload.mkdir(); built.mkdir()
            c=ShaderClient(upload,built)
            item={"key":"preview:test","sig":("x",),"source":"void main(){}","source_hash":"abc",
                  "inputs":[],"w":256,"h":32,"time":0.0,"params":{},"quality":"auto"}
            calls=[]
            def fake_once(_item,scale,timeout_s):
                calls.append(scale)
                if scale==1.0:return None,f"Shader render timed out after {timeout_s:g}s",0.0
                return Image.new("RGBA",(256,32),(1,2,3,255)),"",120.0
            with patch.object(c,"_request_once",side_effect=fake_once):
                im,error=c._request(item)
            self.assertEqual(error,"")
            self.assertEqual(im.size,(256,32))
            self.assertEqual(calls[:2],[1.0,.5])
            self.assertEqual(c.stats("preview:test")["render_scale"],.5)

    def test_v0416_scene_shader_can_render_as_true_background(self):
        scene={"version":4,"design_width":64,"design_height":32,"duration":10,
               "background":{"mode":"shader","color1":"#000000","color2":"#000000",
                             "shader_id":"builtin:LED-Plasma.fs","shader_params":{},
                             "shader_fps":15,"shader_time_scale":1,"shader_quality":"auto"},
               "zones":[],"layers":[]}
        fake=Image.new("RGBA",(64,32),(200,10,20,255))
        with patch("renderer._shader_client") as client_factory:
            client_factory.return_value.get_frame.return_value=fake
            im=render_message({"editor_mode":"designer","scene_json":json.dumps(scene)},64,32,.5,datetime(2026,8,17,14,0),str(ROOT/"uploads"/"fonts"))
        self.assertEqual(im.getpixel((10,10)),(200,10,20))
        args=client_factory.return_value.get_frame.call_args.args
        self.assertEqual(args[0],"preview:__background__")
        self.assertEqual(args[-1],"auto")

    def test_v0416_shader_background_ui_and_performance_controls_are_packaged(self):
        html=(ROOT/"templates"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"static"/"app.js").read_text(encoding="utf-8")
        for marker in ('<option value="shader">Shader</option>','id="sceneBgShader"','id="sceneBgShaderQuality"',
                       'id="sceneBgShaderParameterFields"','id="backgroundShaderUpload"','id="layerShaderQuality"'):
            self.assertIn(marker,html)
        for marker in ('renderBackgroundShaderParameterFields','uploadBackgroundShader','__background__','shader_quality'):
            self.assertIn(marker,js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
