from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable

SCHEMA_VERSION = 11

DEFAULT_SETTINGS = {
    "panel_width": 64,
    "panel_height": 32,
    "panel_model": "Custom P5/P10 panel",
    "panels_across": 1,
    "panels_down": 1,
    "panel_scan": "1/16",
    "panel_output_type": "rpi_mfc",
    "colorlight_receiver_model": "5a-75b",
    "colorlight_interface": "eth1",
    "colorlight_commissioned": False,
    "colorlight_commissioned_at": "",
    "colorlight_commissioned_by": "",
    "colorlight_commissioning_tests": {},
    "display_rotation": 0,
    "brightness": 60,
    "frame_rate": 25,
    "ddp_host": "127.0.0.1",
    "ddp_port": 4048,
    "ddp_offset": 0,
    "color_order": "RGB",
    "default_message_id": None,
    "web_password": "",
    "timezone": "Europe/London",
    "auto_recovery_enabled": True,
    "auto_recover_renderer": True,
    "auto_recover_fppd": True,
    "renderer_stall_seconds": 5,
    "recovery_cooldown_seconds": 60,
    "emergency_message_id": None,
    "gpio_controls_enabled": False,
    "gpio_inputs": [
        {"id":"A","enabled":False,"action":"emergency","contact_type":"normally_open","emergency_behaviour":"latch","debounce_ms":100},
        {"id":"B","enabled":False,"action":"none","contact_type":"normally_open","emergency_behaviour":"latch","debounce_ms":100},
        {"id":"C","enabled":False,"action":"none","contact_type":"normally_open","emergency_behaviour":"latch","debounce_ms":100},
    ],
}


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def conn(self):
        with self._lock:
            con = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            try:
                yield con
                con.commit()
            finally:
                con.close()

    def _init_db(self):
        with self.conn() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    font TEXT NOT NULL DEFAULT '',
                    font_size INTEGER NOT NULL DEFAULT 18,
                    auto_fit INTEGER NOT NULL DEFAULT 0,
                    text_color TEXT NOT NULL DEFAULT '#ffffff',
                    background_color TEXT NOT NULL DEFAULT '#000000',
                    outline_color TEXT NOT NULL DEFAULT '#000000',
                    outline_width INTEGER NOT NULL DEFAULT 0,
                    direction TEXT NOT NULL DEFAULT 'left',
                    speed REAL NOT NULL DEFAULT 30,
                    align TEXT NOT NULL DEFAULT 'center',
                    valign TEXT NOT NULL DEFAULT 'middle',
                    image_path TEXT NOT NULL DEFAULT '',
                    image_mode TEXT NOT NULL DEFAULT 'none',
                    image_scale REAL NOT NULL DEFAULT 1.0,
                    padding INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    editor_mode TEXT NOT NULL DEFAULT 'quick',
                    scene_json TEXT NOT NULL DEFAULT '',
                    render_mode TEXT NOT NULL DEFAULT 'smooth',
                    pixel_scale INTEGER NOT NULL DEFAULT 1,
                    pixel_bold INTEGER NOT NULL DEFAULT 0,
                    letter_spacing INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    editor_mode TEXT NOT NULL DEFAULT 'quick',
                    scene_json TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS playlist_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL DEFAULT 0,
                    duration REAL NOT NULL DEFAULT 10
                );

                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    target_type TEXT NOT NULL CHECK(target_type IN ('message','playlist')),
                    target_id INTEGER NOT NULL,
                    days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
                    start_date TEXT NOT NULL DEFAULT '',
                    end_date TEXT NOT NULL DEFAULT '',
                    start_time TEXT NOT NULL DEFAULT '00:00',
                    end_time TEXT NOT NULL DEFAULT '23:59',
                    priority INTEGER NOT NULL DEFAULT 100,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    editor_mode TEXT NOT NULL DEFAULT 'quick',
                    scene_json TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS components (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    component_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    can_messages INTEGER NOT NULL DEFAULT 0,
                    can_playlists INTEGER NOT NULL DEFAULT 0,
                    can_schedules INTEGER NOT NULL DEFAULT 0,
                    can_display_setup INTEGER NOT NULL DEFAULT 0,
                    can_upgrade INTEGER NOT NULL DEFAULT 0,
                    can_backup INTEGER NOT NULL DEFAULT 0,
                    can_users INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS recovery_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_recovery_events_created_at
                    ON recovery_events(created_at DESC);

                CREATE TABLE IF NOT EXISTS hardware_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conditional_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    target_type TEXT NOT NULL CHECK(target_type IN ('message','playlist')),
                    target_id INTEGER NOT NULL,
                    condition_type TEXT NOT NULL,
                    operator TEXT NOT NULL DEFAULT 'gt',
                    compare_value TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    priority INTEGER NOT NULL DEFAULT 150,
                    true_for_seconds REAL NOT NULL DEFAULT 0,
                    minimum_hold_seconds REAL NOT NULL DEFAULT 30,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS brightness_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
                    start_time TEXT NOT NULL DEFAULT '00:00',
                    end_time TEXT NOT NULL DEFAULT '23:59',
                    brightness INTEGER NOT NULL DEFAULT 60,
                    priority INTEGER NOT NULL DEFAULT 100,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS message_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    version_number INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    saved_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(message_id, version_number)
                );
                CREATE INDEX IF NOT EXISTS idx_message_versions_message
                    ON message_versions(message_id, version_number DESC);
                """
            )
            # v2 message designer migration. SQLite cannot add multiple columns in one
            # statement, so detect legacy v1 databases and add the fields in place.
            message_columns = {row["name"] for row in con.execute("PRAGMA table_info(messages)").fetchall()}
            if "editor_mode" not in message_columns:
                con.execute("ALTER TABLE messages ADD COLUMN editor_mode TEXT NOT NULL DEFAULT 'quick'")
            if "scene_json" not in message_columns:
                con.execute("ALTER TABLE messages ADD COLUMN scene_json TEXT NOT NULL DEFAULT ''")
            if "render_mode" not in message_columns:
                con.execute("ALTER TABLE messages ADD COLUMN render_mode TEXT NOT NULL DEFAULT 'smooth'")
            if "pixel_scale" not in message_columns:
                con.execute("ALTER TABLE messages ADD COLUMN pixel_scale INTEGER NOT NULL DEFAULT 1")
            if "pixel_bold" not in message_columns:
                con.execute("ALTER TABLE messages ADD COLUMN pixel_bold INTEGER NOT NULL DEFAULT 0")
            if "letter_spacing" not in message_columns:
                con.execute("ALTER TABLE messages ADD COLUMN letter_spacing INTEGER NOT NULL DEFAULT 0")

            # v7: dedicated Backup & Restore tab permission. Existing user administrators
            # inherit it so upgrades do not lock the administrator out of backups.
            user_columns = {row["name"] for row in con.execute("PRAGMA table_info(users)").fetchall()}
            if "can_backup" not in user_columns:
                con.execute("ALTER TABLE users ADD COLUMN can_backup INTEGER NOT NULL DEFAULT 0")
                con.execute("UPDATE users SET can_backup=1 WHERE can_users=1")

            # v9: persistent message version history.  Existing messages receive
            # a baseline revision so History is immediately useful after upgrade.
            existing_messages = con.execute("SELECT * FROM messages").fetchall()
            for row in existing_messages:
                mid = int(row["id"])
                have = con.execute("SELECT 1 FROM message_versions WHERE message_id=? LIMIT 1", (mid,)).fetchone()
                if not have:
                    base = dict(row)
                    base.pop("created_at", None); base.pop("updated_at", None)
                    snapshot = json.dumps(base, separators=(",", ":"), ensure_ascii=False)
                    con.execute(
                        "INSERT INTO message_versions(message_id,version_number,snapshot_json,saved_by,created_at) VALUES(?,?,?,?,?)",
                        (mid, 1, snapshot, "Upgrade baseline", row["updated_at"] or row["created_at"]),
                    )

            con.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
            for key, value in DEFAULT_SETTINGS.items():
                con.execute(
                    "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                    (key, json.dumps(value)),
                )

            count = con.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
            if count == 0:
                now = datetime.now().isoformat(timespec="seconds")
                cur = con.execute(
                    """
                    INSERT INTO messages(
                        name,text,font,font_size,auto_fit,text_color,background_color,
                        outline_color,outline_width,direction,speed,align,valign,
                        image_path,image_mode,image_scale,padding,enabled,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "Welcome",
                        "WELCOME",
                        "",
                        18,
                        1,
                        "#ffffff",
                        "#000000",
                        "#000000",
                        0,
                        "left",
                        30,
                        "center",
                        "middle",
                        "",
                        "none",
                        1.0,
                        1,
                        1,
                        now,
                        now,
                    ),
                )
                con.execute("UPDATE messages SET render_mode='pixel' WHERE id=?", (cur.lastrowid,))
                con.execute(
                    "UPDATE settings SET value=? WHERE key='default_message_id'",
                    (json.dumps(cur.lastrowid),),
                )

            # Ensure every message, including a freshly-created Welcome message, has
            # a baseline history entry.
            for row in con.execute("SELECT * FROM messages").fetchall():
                mid = int(row["id"])
                have = con.execute("SELECT 1 FROM message_versions WHERE message_id=? LIMIT 1", (mid,)).fetchone()
                if not have:
                    base = dict(row)
                    base.pop("created_at", None); base.pop("updated_at", None)
                    con.execute(
                        "INSERT INTO message_versions(message_id,version_number,snapshot_json,saved_by,created_at) VALUES(?,?,?,?,?)",
                        (mid, 1, json.dumps(base, separators=(",", ":"), ensure_ascii=False), "Initial version", row["updated_at"] or row["created_at"]),
                    )

    def get_settings(self) -> dict[str, Any]:
        with self.conn() as con:
            rows = con.execute("SELECT key,value FROM settings").fetchall()
        out = dict(DEFAULT_SETTINGS)
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value"])
            except Exception:
                out[row["key"]] = row["value"]
        return out

    def update_settings(self, values: dict[str, Any]):
        allowed = set(DEFAULT_SETTINGS)
        with self.conn() as con:
            for key, value in values.items():
                if key not in allowed:
                    continue
                con.execute(
                    "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                    (key, json.dumps(value)),
                )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def list_messages(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute("SELECT * FROM messages ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def get_message(self, message_id: int) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        return self._row(row)

    def save_message(self, data: dict[str, Any], message_id: int | None = None) -> int:
        fields = [
            "name", "text", "font", "font_size", "auto_fit", "text_color",
            "background_color", "outline_color", "outline_width", "direction",
            "speed", "align", "valign", "image_path", "image_mode", "image_scale",
            "padding", "enabled", "editor_mode", "scene_json", "render_mode",
            "pixel_scale", "pixel_bold", "letter_spacing"
        ]
        defaults = {
            "name": "Untitled",
            "text": "",
            "font": "",
            "font_size": 18,
            "auto_fit": 0,
            "text_color": "#ffffff",
            "background_color": "#000000",
            "outline_color": "#000000",
            "outline_width": 0,
            "direction": "left",
            "speed": 30,
            "align": "center",
            "valign": "middle",
            "image_path": "",
            "image_mode": "none",
            "image_scale": 1.0,
            "padding": 1,
            "enabled": 1,
            "editor_mode": "quick",
            "scene_json": "",
            "render_mode": "pixel",
            "pixel_scale": 1,
            "pixel_bold": 0,
            "letter_spacing": 0,
        }
        clean = {k: data.get(k, defaults[k]) for k in fields}
        clean["name"] = str(clean["name"]).strip() or "Untitled"
        clean["text"] = str(clean["text"])
        clean["font_size"] = max(5, min(256, int(clean["font_size"] or 18)))
        clean["auto_fit"] = 1 if bool(clean["auto_fit"]) else 0
        clean["outline_width"] = max(0, min(12, int(clean["outline_width"] or 0)))
        clean["speed"] = max(0.1, min(1000.0, float(clean["speed"] or 30)))
        clean["image_scale"] = max(0.05, min(20.0, float(clean["image_scale"] or 1.0)))
        clean["padding"] = max(0, min(100, int(clean["padding"] or 1)))
        clean["enabled"] = 1 if bool(clean["enabled"]) else 0
        clean["editor_mode"] = str(clean.get("editor_mode") or "quick").lower()
        if clean["editor_mode"] not in ("quick", "designer"):
            clean["editor_mode"] = "quick"
        clean["scene_json"] = str(clean.get("scene_json") or "")
        clean["render_mode"] = str(clean.get("render_mode") or "pixel").lower()
        led_modes = {"led3x5","led4x6","led5x7","led6x8","led7x9","led8x8","led8x12","led8x16","led-condensed","led-bold","led-digital","led-scoreboard","led-dot"}
        if clean["render_mode"] not in ({"smooth", "pixel"} | led_modes):
            clean["render_mode"] = "pixel"
        clean["pixel_scale"] = max(1, min(8, int(clean.get("pixel_scale") or 1)))
        clean["pixel_bold"] = 1 if bool(clean.get("pixel_bold")) else 0
        clean["letter_spacing"] = max(0, min(8, int(clean.get("letter_spacing") or 0)))
        if len(clean["scene_json"].encode("utf-8")) > 1024 * 1024:
            raise ValueError("Designer scene is too large (1MB maximum)")
        if clean["scene_json"]:
            try:
                scene = json.loads(clean["scene_json"])
            except Exception as exc:
                raise ValueError("Designer scene is not valid JSON") from exc
            if not isinstance(scene, dict) or not isinstance(scene.get("layers", []), list):
                raise ValueError("Designer scene is invalid")
            if len(scene.get("layers", [])) > 64:
                raise ValueError("A message can contain at most 64 designer layers")
            if not isinstance(scene.get("zones", []), list):
                raise ValueError("Designer zones are invalid")
            if len(scene.get("zones", [])) > 32:
                raise ValueError("A message can contain at most 32 zones")
        now = datetime.now().isoformat(timespec="seconds")

        with self.conn() as con:
            if message_id:
                set_clause = ",".join(f"{k}=?" for k in fields)
                vals = [clean[k] for k in fields] + [now, message_id]
                con.execute(f"UPDATE messages SET {set_clause},updated_at=? WHERE id=?", vals)
                return message_id
            cols = ",".join(fields) + ",created_at,updated_at"
            marks = ",".join("?" for _ in range(len(fields) + 2))
            vals = [clean[k] for k in fields] + [now, now]
            cur = con.execute(f"INSERT INTO messages({cols}) VALUES({marks})", vals)
            return int(cur.lastrowid)

    def save_message_version(self, message_id: int, saved_by: str = "") -> dict[str, Any] | None:
        """Store the current message state as the next immutable revision."""
        with self.conn() as con:
            row = con.execute("SELECT * FROM messages WHERE id=?", (int(message_id),)).fetchone()
            if not row:
                return None
            current = dict(row)
            current.pop("created_at", None); current.pop("updated_at", None)
            last = con.execute(
                "SELECT version_number,snapshot_json FROM message_versions WHERE message_id=? ORDER BY version_number DESC LIMIT 1",
                (int(message_id),),
            ).fetchone()
            snapshot = json.dumps(current, separators=(",", ":"), ensure_ascii=False)
            # Do not create duplicate revisions when Save is pressed without changes.
            if last and str(last["snapshot_json"]) == snapshot:
                found = con.execute(
                    "SELECT * FROM message_versions WHERE message_id=? AND version_number=?",
                    (int(message_id), int(last["version_number"])),
                ).fetchone()
                return dict(found) if found else None
            version = (int(last["version_number"]) + 1) if last else 1
            now = datetime.now().isoformat(timespec="seconds")
            cur = con.execute(
                "INSERT INTO message_versions(message_id,version_number,snapshot_json,saved_by,created_at) VALUES(?,?,?,?,?)",
                (int(message_id), version, snapshot, str(saved_by or ""), now),
            )
            # Keep a useful but bounded history per message.
            con.execute(
                "DELETE FROM message_versions WHERE message_id=? AND id NOT IN (SELECT id FROM message_versions WHERE message_id=? ORDER BY version_number DESC LIMIT 60)",
                (int(message_id), int(message_id)),
            )
            found = con.execute("SELECT * FROM message_versions WHERE id=?", (int(cur.lastrowid),)).fetchone()
            return dict(found) if found else None

    def list_message_versions(self, message_id: int) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT id,message_id,version_number,saved_by,created_at FROM message_versions WHERE message_id=? ORDER BY version_number DESC",
                (int(message_id),),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_message_version(self, message_id: int, version_id: int) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute(
                "SELECT * FROM message_versions WHERE id=? AND message_id=?",
                (int(version_id), int(message_id)),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["snapshot"] = json.loads(d.get("snapshot_json") or "{}")
        except Exception:
            d["snapshot"] = {}
        return d

    def restore_message_version(self, message_id: int, version_id: int, saved_by: str = "") -> dict[str, Any]:
        version = self.get_message_version(message_id, version_id)
        if not version or not isinstance(version.get("snapshot"), dict):
            raise ValueError("Message version not found")
        snap = dict(version["snapshot"])
        snap.pop("id", None); snap.pop("created_at", None); snap.pop("updated_at", None)
        self.save_message(snap, int(message_id))
        self.save_message_version(int(message_id), saved_by or f"Restored v{version['version_number']}")
        restored = self.get_message(int(message_id))
        if not restored:
            raise ValueError("Message could not be restored")
        return restored

    def delete_message(self, message_id: int):
        with self.conn() as con:
            con.execute("DELETE FROM messages WHERE id=?", (message_id,))

    def list_message_options(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute("SELECT id,name FROM messages WHERE enabled=1 ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def list_playlist_options(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute("SELECT id,name FROM playlists WHERE enabled=1 ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def list_playlists(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            pls = con.execute("SELECT * FROM playlists ORDER BY name COLLATE NOCASE").fetchall()
            result = []
            for p in pls:
                d = dict(p)
                items = con.execute(
                    """
                    SELECT pi.*,m.name AS message_name FROM playlist_items pi
                    JOIN messages m ON m.id=pi.message_id
                    WHERE pi.playlist_id=? ORDER BY pi.position,pi.id
                    """,
                    (p["id"],),
                ).fetchall()
                d["items"] = [dict(i) for i in items]
                result.append(d)
        return result

    def get_playlist(self, playlist_id: int) -> dict[str, Any] | None:
        for p in self.list_playlists():
            if int(p["id"]) == int(playlist_id):
                return p
        return None

    def save_playlist(self, data: dict[str, Any], playlist_id: int | None = None) -> int:
        name = str(data.get("name", "Playlist")).strip() or "Playlist"
        enabled = 1 if bool(data.get("enabled", True)) else 0
        items = data.get("items") or []
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as con:
            if playlist_id:
                con.execute(
                    "UPDATE playlists SET name=?,enabled=?,updated_at=? WHERE id=?",
                    (name, enabled, now, playlist_id),
                )
                pid = playlist_id
                con.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
            else:
                cur = con.execute(
                    "INSERT INTO playlists(name,enabled,created_at,updated_at) VALUES(?,?,?,?)",
                    (name, enabled, now, now),
                )
                pid = int(cur.lastrowid)
            for pos, item in enumerate(items):
                mid = int(item.get("message_id"))
                duration = max(0.5, min(86400.0, float(item.get("duration", 10))))
                con.execute(
                    "INSERT INTO playlist_items(playlist_id,message_id,position,duration) VALUES(?,?,?,?)",
                    (pid, mid, pos, duration),
                )
        return int(pid)

    def delete_playlist(self, playlist_id: int):
        with self.conn() as con:
            con.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))

    def list_schedules(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute("SELECT * FROM schedules ORDER BY priority DESC,name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def get_schedule(self, schedule_id: int) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
        return self._row(row)

    def save_schedule(self, data: dict[str, Any], schedule_id: int | None = None) -> int:
        fields = [
            "name", "target_type", "target_id", "days", "start_date", "end_date",
            "start_time", "end_time", "priority", "enabled"
        ]
        clean = {
            "name": str(data.get("name", "Schedule")).strip() or "Schedule",
            "target_type": data.get("target_type", "message"),
            "target_id": int(data.get("target_id", 0)),
            "days": str(data.get("days", "0,1,2,3,4,5,6")),
            "start_date": str(data.get("start_date", "")),
            "end_date": str(data.get("end_date", "")),
            "start_time": str(data.get("start_time", "00:00")),
            "end_time": str(data.get("end_time", "23:59")),
            "priority": int(data.get("priority", 100)),
            "enabled": 1 if bool(data.get("enabled", True)) else 0,
        }
        if clean["target_type"] not in ("message", "playlist"):
            raise ValueError("target_type must be message or playlist")
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as con:
            if schedule_id:
                set_clause = ",".join(f"{k}=?" for k in fields)
                vals = [clean[k] for k in fields] + [now, schedule_id]
                con.execute(f"UPDATE schedules SET {set_clause},updated_at=? WHERE id=?", vals)
                return int(schedule_id)
            cols = ",".join(fields) + ",created_at,updated_at"
            marks = ",".join("?" for _ in range(len(fields) + 2))
            vals = [clean[k] for k in fields] + [now, now]
            cur = con.execute(f"INSERT INTO schedules({cols}) VALUES({marks})", vals)
            return int(cur.lastrowid)

    def delete_schedule(self, schedule_id: int):
        with self.conn() as con:
            con.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))

    # Conditional content ------------------------------------------------
    def list_conditional_rules(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute("SELECT * FROM conditional_rules ORDER BY priority DESC,name COLLATE NOCASE").fetchall()
        out=[]
        for row in rows:
            d=dict(row)
            try: d["config"] = json.loads(d.get("config_json") or "{}")
            except Exception: d["config"] = {}
            out.append(d)
        return out

    def get_conditional_rule(self, rule_id: int) -> dict[str, Any] | None:
        with self.conn() as con:
            row=con.execute("SELECT * FROM conditional_rules WHERE id=?",(int(rule_id),)).fetchone()
        if not row: return None
        d=dict(row)
        try: d["config"] = json.loads(d.get("config_json") or "{}")
        except Exception: d["config"] = {}
        return d

    def save_conditional_rule(self, data: dict[str, Any], rule_id: int | None = None) -> int:
        name=str(data.get("name") or "Conditional rule").strip() or "Conditional rule"
        target_type=str(data.get("target_type") or "message")
        if target_type not in ("message","playlist"): raise ValueError("target_type must be message or playlist")
        target_id=int(data.get("target_id") or 0)
        if target_id <= 0: raise ValueError("Choose content for the rule")
        ctype=str(data.get("condition_type") or "weather_temp").strip().lower()
        allowed={"weather_temp","weather_feels","weather_wind","weather_gust","weather_humidity","weather_condition","json"}
        if ctype not in allowed: raise ValueError("Unsupported condition type")
        op=str(data.get("operator") or "gt").strip().lower()
        if op not in {"gt","gte","lt","lte","eq","neq","contains","not_contains"}: raise ValueError("Unsupported condition operator")
        compare=str(data.get("compare_value") if data.get("compare_value") is not None else "").strip()
        config=data.get("config") if isinstance(data.get("config"),dict) else {}
        raw=json.dumps(config,separators=(",",":"))
        if len(raw.encode())>64*1024: raise ValueError("Condition configuration is too large")
        priority=max(-100000,min(100000,int(data.get("priority",150) or 0)))
        true_for=max(0.0,min(86400.0,float(data.get("true_for_seconds",0) or 0)))
        hold=max(0.0,min(86400.0,float(data.get("minimum_hold_seconds",30) or 0)))
        enabled=1 if bool(data.get("enabled",True)) else 0
        now=datetime.now().isoformat(timespec="seconds")
        with self.conn() as con:
            if rule_id:
                con.execute("""UPDATE conditional_rules SET name=?,target_type=?,target_id=?,condition_type=?,operator=?,compare_value=?,config_json=?,priority=?,true_for_seconds=?,minimum_hold_seconds=?,enabled=?,updated_at=? WHERE id=?""",
                            (name,target_type,target_id,ctype,op,compare,raw,priority,true_for,hold,enabled,now,int(rule_id)))
                return int(rule_id)
            cur=con.execute("""INSERT INTO conditional_rules(name,target_type,target_id,condition_type,operator,compare_value,config_json,priority,true_for_seconds,minimum_hold_seconds,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (name,target_type,target_id,ctype,op,compare,raw,priority,true_for,hold,enabled,now,now))
            return int(cur.lastrowid)

    def delete_conditional_rule(self, rule_id: int):
        with self.conn() as con: con.execute("DELETE FROM conditional_rules WHERE id=?",(int(rule_id),))

    # Brightness schedules -----------------------------------------------
    def list_brightness_schedules(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows=con.execute("SELECT * FROM brightness_schedules ORDER BY priority DESC,name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def get_brightness_schedule(self, schedule_id: int) -> dict[str, Any] | None:
        with self.conn() as con: row=con.execute("SELECT * FROM brightness_schedules WHERE id=?",(int(schedule_id),)).fetchone()
        return self._row(row)

    def save_brightness_schedule(self, data: dict[str, Any], schedule_id: int | None = None) -> int:
        name=str(data.get("name") or "Brightness schedule").strip() or "Brightness schedule"
        days=str(data.get("days") or "0,1,2,3,4,5,6")
        start=str(data.get("start_time") or "00:00")
        end=str(data.get("end_time") or "23:59")
        brightness=max(0,min(100,int(data.get("brightness",60) or 0)))
        priority=max(-100000,min(100000,int(data.get("priority",100) or 0)))
        enabled=1 if bool(data.get("enabled",True)) else 0
        now=datetime.now().isoformat(timespec="seconds")
        with self.conn() as con:
            if schedule_id:
                con.execute("UPDATE brightness_schedules SET name=?,days=?,start_time=?,end_time=?,brightness=?,priority=?,enabled=?,updated_at=? WHERE id=?",(name,days,start,end,brightness,priority,enabled,now,int(schedule_id)))
                return int(schedule_id)
            cur=con.execute("INSERT INTO brightness_schedules(name,days,start_time,end_time,brightness,priority,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(name,days,start,end,brightness,priority,enabled,now,now))
            return int(cur.lastrowid)

    def delete_brightness_schedule(self, schedule_id: int):
        with self.conn() as con: con.execute("DELETE FROM brightness_schedules WHERE id=?",(int(schedule_id),))

    def list_components(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute("SELECT * FROM components ORDER BY name COLLATE NOCASE").fetchall()
        out = []
        for row in rows:
            d = dict(row)
            try:
                d["component"] = json.loads(d.get("component_json") or "{}")
            except Exception:
                d["component"] = {}
            out.append(d)
        return out

    def get_component(self, component_id: int) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM components WHERE id=?", (component_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["component"] = json.loads(d.get("component_json") or "{}")
        except Exception:
            d["component"] = {}
        return d

    def save_component(self, data: dict[str, Any], component_id: int | None = None) -> int:
        name = str(data.get("name") or "Component").strip() or "Component"
        component = data.get("component")
        if component is None and data.get("component_json"):
            try:
                component = json.loads(str(data.get("component_json")))
            except Exception as exc:
                raise ValueError("Component JSON is invalid") from exc
        if not isinstance(component, dict):
            raise ValueError("Component must be an object")
        layers = component.get("layers", [])
        zones = component.get("zones", [])
        if not isinstance(layers, list) or len(layers) > 64:
            raise ValueError("A component can contain at most 64 layers")
        if not isinstance(zones, list) or len(zones) > 32:
            raise ValueError("A component can contain at most 32 zones")
        raw = json.dumps(component, separators=(",", ":"))
        if len(raw.encode("utf-8")) > 512 * 1024:
            raise ValueError("Component is too large (512KB maximum)")
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as con:
            conflict = con.execute(
                "SELECT id FROM components WHERE name=? AND (? IS NULL OR id<>?)",
                (name, component_id, component_id),
            ).fetchone()
            if conflict:
                raise ValueError("A component with that name already exists")
            if component_id:
                con.execute("UPDATE components SET name=?,component_json=?,updated_at=? WHERE id=?",
                            (name, raw, now, component_id))
                return int(component_id)
            cur = con.execute("INSERT INTO components(name,component_json,created_at,updated_at) VALUES(?,?,?,?)",
                              (name, raw, now, now))
            return int(cur.lastrowid)

    def delete_component(self, component_id: int):
        with self.conn() as con:
            con.execute("DELETE FROM components WHERE id=?", (component_id,))

    # Users / permissions -------------------------------------------------
    USER_PERMISSION_FIELDS = (
        "can_messages", "can_playlists", "can_schedules",
        "can_display_setup", "can_upgrade", "can_backup", "can_users",
    )

    def ensure_default_admin(self, password_hash: str, username: str = "admin") -> int | None:
        """Create the initial full-rights account only when no users exist."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as con:
            count = int(con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] or 0)
            if count:
                return None
            cur = con.execute(
                """
                INSERT INTO users(
                    username,display_name,password_hash,is_active,must_change_password,
                    can_messages,can_playlists,can_schedules,can_display_setup,can_upgrade,can_backup,can_users,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (username, "Administrator", password_hash, 1, 1, 1, 1, 1, 1, 1, 1, 1, now, now),
            )
            return int(cur.lastrowid)

    def list_users(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute(
                """SELECT id,username,display_name,is_active,must_change_password,
                          can_messages,can_playlists,can_schedules,can_display_setup,can_upgrade,can_backup,can_users,
                          created_at,updated_at,last_login_at
                   FROM users ORDER BY username COLLATE NOCASE"""
            ).fetchall()
        return [dict(r) for r in rows]

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
        return self._row(row)

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (str(username).strip(),)).fetchone()
        return self._row(row)

    def save_user(self, data: dict[str, Any], user_id: int | None = None) -> int:
        username = str(data.get("username") or "").strip()
        display_name = str(data.get("display_name") or username).strip() or username
        if not username:
            raise ValueError("Username is required")
        now = datetime.now().isoformat(timespec="seconds")
        perms = {field: 1 if bool(data.get(field, False)) else 0 for field in self.USER_PERMISSION_FIELDS}
        active = 1 if bool(data.get("is_active", True)) else 0
        must_change = 1 if bool(data.get("must_change_password", False)) else 0
        with self.conn() as con:
            conflict = con.execute(
                "SELECT id FROM users WHERE username=? COLLATE NOCASE AND (? IS NULL OR id<>?)",
                (username, user_id, user_id),
            ).fetchone()
            if conflict:
                raise ValueError("That username already exists")
            if user_id:
                con.execute(
                    """UPDATE users SET username=?,display_name=?,is_active=?,must_change_password=?,
                       can_messages=?,can_playlists=?,can_schedules=?,can_display_setup=?,can_upgrade=?,can_backup=?,can_users=?,updated_at=?
                       WHERE id=?""",
                    (username, display_name, active, must_change,
                     perms["can_messages"], perms["can_playlists"], perms["can_schedules"],
                     perms["can_display_setup"], perms["can_upgrade"], perms["can_backup"], perms["can_users"], now, int(user_id)),
                )
                return int(user_id)
            password_hash = str(data.get("password_hash") or "")
            if not password_hash:
                raise ValueError("Password is required for a new user")
            cur = con.execute(
                """INSERT INTO users(username,display_name,password_hash,is_active,must_change_password,
                   can_messages,can_playlists,can_schedules,can_display_setup,can_upgrade,can_backup,can_users,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (username, display_name, password_hash, active, must_change,
                 perms["can_messages"], perms["can_playlists"], perms["can_schedules"],
                 perms["can_display_setup"], perms["can_upgrade"], perms["can_backup"], perms["can_users"], now, now),
            )
            return int(cur.lastrowid)

    def set_user_password(self, user_id: int, password_hash: str, must_change_password: bool = False) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as con:
            con.execute(
                "UPDATE users SET password_hash=?,must_change_password=?,updated_at=? WHERE id=?",
                (password_hash, 1 if must_change_password else 0, now, int(user_id)),
            )

    def touch_user_login(self, user_id: int) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as con:
            con.execute("UPDATE users SET last_login_at=? WHERE id=?", (now, int(user_id)))

    def delete_user(self, user_id: int) -> None:
        with self.conn() as con:
            con.execute("DELETE FROM users WHERE id=?", (int(user_id),))

    def active_user_manager_count(self, exclude_user_id: int | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM users WHERE is_active=1 AND can_users=1"
        args: tuple[Any, ...] = ()
        if exclude_user_id is not None:
            sql += " AND id<>?"
            args = (int(exclude_user_id),)
        with self.conn() as con:
            return int(con.execute(sql, args).fetchone()["n"] or 0)
    def add_recovery_event(self, event_type: str, action: str, result: str, details: str = "") -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as con:
            cur = con.execute(
                "INSERT INTO recovery_events(event_type,action,result,details,created_at) VALUES(?,?,?,?,?)",
                (str(event_type)[:80], str(action)[:80], str(result)[:40], str(details)[:2000], now),
            )
            # Keep the history useful without allowing unattended systems to grow forever.
            con.execute(
                "DELETE FROM recovery_events WHERE id NOT IN (SELECT id FROM recovery_events ORDER BY id DESC LIMIT 500)"
            )
            return int(cur.lastrowid)

    def list_recovery_events(self, limit: int = 40) -> list[dict[str, Any]]:
        limit = max(1, min(200, int(limit)))
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM recovery_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_recovery_events(self) -> None:
        with self.conn() as con:
            con.execute("DELETE FROM recovery_events")

    # Hardware profiles --------------------------------------------------
    def list_hardware_profiles(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute("SELECT * FROM hardware_profiles ORDER BY name COLLATE NOCASE").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["config"] = json.loads(item.pop("config_json"))
            result.append(item)
        return result

    def save_hardware_profile(self, name: str, config: dict[str, Any], profile_id: int | None = None) -> int:
        name = str(name or "").strip()
        if not name:
            raise ValueError("Profile name is required")
        if len(name) > 80:
            raise ValueError("Profile name is too long")
        raw = json.dumps(config, separators=(",", ":"), sort_keys=True)
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as con:
            conflict = con.execute("SELECT id FROM hardware_profiles WHERE name=? COLLATE NOCASE AND (? IS NULL OR id<>?)", (name, profile_id, profile_id)).fetchone()
            if conflict:
                raise ValueError("A hardware profile with that name already exists")
            if profile_id:
                found = con.execute("SELECT id FROM hardware_profiles WHERE id=?", (int(profile_id),)).fetchone()
                if not found:
                    raise ValueError("Hardware profile not found")
                con.execute("UPDATE hardware_profiles SET name=?,config_json=?,updated_at=? WHERE id=?", (name, raw, now, int(profile_id)))
                return int(profile_id)
            cur = con.execute("INSERT INTO hardware_profiles(name,config_json,created_at,updated_at) VALUES(?,?,?,?)", (name, raw, now, now))
            return int(cur.lastrowid)

    def get_hardware_profile(self, profile_id: int) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM hardware_profiles WHERE id=?", (int(profile_id),)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json"))
        return item

    def delete_hardware_profile(self, profile_id: int) -> None:
        with self.conn() as con:
            con.execute("DELETE FROM hardware_profiles WHERE id=?", (int(profile_id),))
