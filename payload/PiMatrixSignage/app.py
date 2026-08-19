from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import shutil
import threading
import time
import sys
import zipfile
import sqlite3
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, Response, g, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for
from PIL import Image
from werkzeug.utils import secure_filename

from database import Database
from renderer import RendererEngine, list_fonts, render_message, shader_layer_status
from diagnostics import SystemDiagnostics
from shader_support import SHADER_EXTENSIONS, list_shader_assets, shader_asset_from_path
from gpio_controls import GPIOControlManager, normalise_gpio_inputs
from licensing import LicenseError, LicenseManager

BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = (BASE_DIR / "VERSION").read_text(encoding="utf-8").strip() if (BASE_DIR / "VERSION").exists() else "dev"
DATA_DIR = Path(os.environ.get("PIMATRIX_DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = Path(os.environ.get("PIMATRIX_UPLOAD_DIR", str(BASE_DIR / "uploads")))
DB_PATH = DATA_DIR / "signage.db"
LOG_DIR = Path(os.environ.get("LOGDIR", str(DATA_DIR)))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "pi-matrix-signage.log"
UPGRADE_DIR = Path(os.environ.get("PIMATRIX_UPGRADE_DIR", str(DATA_DIR.parent / "upgrade")))
UPGRADE_PENDING = UPGRADE_DIR / "pending.zip"
UPGRADE_STATUS = UPGRADE_DIR / "status.json"
BACKUP_DIR = DATA_DIR.parent / "backups"
BACKUP_STATUS = BACKUP_DIR / "status.json"
BACKUP_FORMAT = 1
PORTABLE_FORMAT = 1
PORTABLE_MAX_FILES = 12000
PORTABLE_MAX_UNCOMPRESSED = 4 * 1024 * 1024 * 1024
UPGRADE_HELPER = Path("/usr/local/sbin/pi-matrix-signage-upgrade")
POWER_HELPER = Path("/usr/local/sbin/pi-matrix-signage-poweroff")

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOG = logging.getLogger("pimatrix")

for p in (DATA_DIR, UPLOAD_DIR / "images", UPLOAD_DIR / "fonts", UPLOAD_DIR / "videos", UPLOAD_DIR / "video-src", UPLOAD_DIR / "shaders", UPGRADE_DIR, BACKUP_DIR):
    p.mkdir(parents=True, exist_ok=True)

db = Database(str(DB_PATH))
license_manager = LicenseManager(DATA_DIR, APP_VERSION)
engine = RendererEngine(db, str(DATA_DIR), str(UPLOAD_DIR), license_checker=license_manager.is_licensed)
diagnostics = SystemDiagnostics(engine, db, DATA_DIR, UPGRADE_HELPER, LOG)
gpio_controls = GPIOControlManager(db, engine, LOG)
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
SESSION_SECRET_PATH = DATA_DIR / "session-secret"
if SESSION_SECRET_PATH.exists():
    app.secret_key = SESSION_SECRET_PATH.read_bytes()
else:
    secret = secrets.token_bytes(32)
    SESSION_SECRET_PATH.write_bytes(secret)
    try:
        os.chmod(SESSION_SECRET_PATH, 0o600)
    except OSError:
        pass
    app.secret_key = secret

IMAGE_EXTENSIONS = {"png", "apng", "jpg", "jpeg", "gif", "webp", "bmp"}
FONT_EXTENSIONS = {"ttf", "otf"}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "mkv", "m4v", "avi"}

# Video upload/preprocessing jobs are intentionally in-memory.  The source file
# is already safely stored before a job is created, and the job only needs to
# live long enough for the browser to show preprocessing progress.
VIDEO_JOBS: dict[str, dict] = {}
VIDEO_JOBS_LOCK = threading.Lock()
VIDEO_JOB_TTL = 60 * 60

# Backup creation is read-only and does not require privileged/root access.
# Keeping it inside the web service avoids coupling Create backup to sudo/systemd.
BACKUP_CREATE_LOCK = threading.Lock()
FPP_BACKUP_URL = "http://127.0.0.1/backup.php"


UPGRADE_REQUIRED = {
    "PiMatrixSignage/VERSION",
    "PiMatrixSignage/app.py",
    "PiMatrixSignage/database.py",
    "PiMatrixSignage/renderer.py",
    "PiMatrixSignage/shader_support.py",
    "PiMatrixSignage/diagnostics.py",
    "PiMatrixSignage/gpio_controls.py",
    "PiMatrixSignage/licensing.py",
    "PiMatrixSignage/ddp.py",
    "PiMatrixSignage/templates/index.html",
    "PiMatrixSignage/templates/login.html",
    "PiMatrixSignage/templates/change_password.html",
    "PiMatrixSignage/templates/remote.html",
    "PiMatrixSignage/static/app.js",
    "PiMatrixSignage/static/app.css",
}
UPGRADE_MAX_FILES = 2500
UPGRADE_MAX_UNCOMPRESSED = 300 * 1024 * 1024


def _version_key(value: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, m.groups())) if m else (0, 0, 0)


def _safe_upgrade_member(name: str) -> str:
    if not name or "\\" in name or name.startswith("/"):
        raise ValueError(f"Unsafe ZIP path: {name!r}")
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in ("", ".", "..") for part in p.parts):
        raise ValueError(f"Unsafe ZIP path: {name!r}")
    if not p.parts or p.parts[0] != "PiMatrixSignage":
        raise ValueError("Release ZIP must contain a single PiMatrixSignage/ folder")
    return str(p)


def _inspect_upgrade_zip(path: Path) -> dict:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid ZIP archive") from exc
    with zf:
        infos = zf.infolist()
        if not infos or len(infos) > UPGRADE_MAX_FILES:
            raise ValueError("Release ZIP contains an unreasonable number of files")
        names = set()
        total = 0
        for info in infos:
            raw = info.filename.rstrip("/") if info.is_dir() else info.filename
            canonical = _safe_upgrade_member(raw)
            if canonical in names and not info.is_dir():
                raise ValueError(f"Duplicate ZIP entry: {canonical}")
            names.add(canonical)
            total += int(info.file_size)
            if total > UPGRADE_MAX_UNCOMPRESSED:
                raise ValueError("Release ZIP is too large when unpacked")
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and stat.S_IFMT(mode) and not info.is_dir() and not stat.S_ISREG(mode):
                raise ValueError(f"Release ZIP contains a non-regular file: {canonical}")
        missing = UPGRADE_REQUIRED - names
        if missing:
            raise ValueError("Not a complete Pi Matrix Signage release; missing " + ", ".join(sorted(missing)))
        raw_version = zf.read("PiMatrixSignage/VERSION")
        if len(raw_version) > 80:
            raise ValueError("Invalid VERSION file")
        version = raw_version.decode("utf-8", "strict").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?", version):
            raise ValueError(f"Invalid release version: {version!r}")
        return {"version": version, "files": len(infos), "uncompressed_bytes": total}


def _read_upgrade_status() -> dict:
    try:
        value = json.loads(UPGRADE_STATUS.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_upgrade_status(value: dict) -> None:
    UPGRADE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = UPGRADE_STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, UPGRADE_STATUS)


def _hash_password(raw: str) -> str:
    if not raw:
        return ""
    salt = secrets.token_bytes(16)
    rounds = 240_000
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, rounds)
    return "pbkdf2_sha256${}${}${}".format(
        rounds,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def _verify_password(stored: str, raw: str) -> bool:
    if not stored:
        return False
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _alg, rounds_s, salt_s, digest_s = stored.split("$", 3)
            salt = base64.urlsafe_b64decode(salt_s.encode("ascii"))
            expected = base64.urlsafe_b64decode(digest_s.encode("ascii"))
            actual = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, int(rounds_s))
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False
    # Backward compatibility for any early database that stored the password directly.
    return hmac.compare_digest(raw, stored)




# Portable import/export -------------------------------------------------
# These packages are deliberately separate from disaster-recovery backups.
# They are intended for moving creative content/configuration between signs.
def _portable_safe_rel(value: str) -> PurePosixPath:
    raw = str(value or "").replace("\\", "/").strip("/")
    p = PurePosixPath(raw)
    if not raw or p.is_absolute() or any(part in ("", ".", "..") for part in p.parts):
        raise ValueError("Portable package contains an unsafe path")
    if p.parts[0] not in {"images", "fonts", "videos", "video-src", "shaders"}:
        raise ValueError("Portable package contains an unsupported upload path")
    return p


def _within_uploads(path_value: str) -> tuple[Path, str] | None:
    try:
        path = Path(path_value).expanduser().resolve()
        root = UPLOAD_DIR.resolve()
        rel = path.relative_to(root)
        if not rel.parts or rel.parts[0] not in {"images", "fonts", "videos", "video-src", "shaders"}:
            return None
        return path, rel.as_posix()
    except Exception:
        return None


def _portable_collect_asset_refs(obj, found: dict[str, dict]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "scene_json" and isinstance(value, str) and value.strip():
                try:
                    _portable_collect_asset_refs(json.loads(value), found)
                except Exception:
                    pass
                continue
            if key in {"image_path", "video_path", "font"} and isinstance(value, str) and value:
                hit = _within_uploads(value)
                if hit:
                    path, rel = hit
                    primary = rel
                    if path.is_dir():
                        primary = rel.rstrip("/")
                    found.setdefault(value, {"reference": value, "relative": primary, "ref_type": "path", "is_dir": path.is_dir()})
            elif key == "shader_id" and isinstance(value, str) and value.startswith("upload:"):
                name = secure_filename(value.split(":", 1)[1])
                path = (UPLOAD_DIR / "shaders" / name)
                if name and path.is_file():
                    found.setdefault(value, {"reference": value, "relative": f"shaders/{name}", "ref_type": "shader_id", "is_dir": False})
            _portable_collect_asset_refs(value, found)
    elif isinstance(obj, list):
        for value in obj:
            _portable_collect_asset_refs(value, found)


def _portable_message_record(row: dict) -> dict:
    return {k: v for k, v in dict(row).items() if k not in {"created_at", "updated_at"}}


def _portable_component_record(row: dict) -> dict:
    return {"id": int(row.get("id") or 0), "name": str(row.get("name") or "Component"), "component": row.get("component") if isinstance(row.get("component"), dict) else {}}


def _portable_playlist_record(row: dict) -> dict:
    return {
        "id": int(row.get("id") or 0), "name": str(row.get("name") or "Playlist"), "enabled": bool(row.get("enabled", True)),
        "items": [{"message_id": int(i.get("message_id") or 0), "duration": float(i.get("duration") or 10)} for i in (row.get("items") or [])],
    }


def _portable_build_payload(kind: str, object_id: int | None = None) -> dict:
    kind = str(kind or "").lower()
    payload: dict = {"kind": kind}
    if kind == "message":
        row = db.get_message(int(object_id or 0))
        if not row: raise ValueError("Message not found")
        payload["message"] = _portable_message_record(row)
    elif kind == "component":
        row = db.get_component(int(object_id or 0))
        if not row: raise ValueError("Component not found")
        payload["component"] = _portable_component_record(row)
    elif kind == "playlist":
        row = db.get_playlist(int(object_id or 0))
        if not row: raise ValueError("Playlist not found")
        payload["playlist"] = _portable_playlist_record(row)
        mids = []
        for item in row.get("items") or []:
            mid = int(item.get("message_id") or 0)
            if mid and mid not in mids: mids.append(mid)
        payload["messages"] = [_portable_message_record(db.get_message(mid)) for mid in mids if db.get_message(mid)]
    elif kind == "configuration":
        settings = dict(db.get_settings())
        settings.pop("web_password", None)
        payload.update({
            "settings": settings,
            "messages": [_portable_message_record(x) for x in db.list_messages()],
            "components": [_portable_component_record(x) for x in db.list_components()],
            "playlists": [_portable_playlist_record(x) for x in db.list_playlists()],
            "schedules": db.list_schedules(),
            "conditional_rules": db.list_conditional_rules(),
            "brightness_schedules": db.list_brightness_schedules(),
        })
    else:
        raise ValueError("Unsupported export type")
    return payload


def _portable_package(kind: str, object_id: int | None = None) -> tuple[Path, str]:
    payload = _portable_build_payload(kind, object_id)
    refs: dict[str, dict] = {}
    _portable_collect_asset_refs(payload, refs)
    include_all = kind == "configuration"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_kind = {"message":"message", "component":"component", "playlist":"playlist", "configuration":"configuration"}[kind]
    name_hint = ""
    if kind in payload:
        name_hint = secure_filename(str(payload[kind].get("name") or ""))[:50]
    filename = f"PiMatrix-{safe_kind}{('-'+name_hint) if name_hint else ''}-{stamp}.zip"
    fd, temp_name = tempfile.mkstemp(prefix="pimatrix-export-", suffix=".zip", dir=str(DATA_DIR))
    os.close(fd)
    temp = Path(temp_name)
    manifest = {
        "product": "Pi Matrix Signage Portable",
        "format": PORTABLE_FORMAT,
        "kind": kind,
        "app_version": APP_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "asset_refs": list(refs.values()),
        "payload": payload,
    }
    added: set[str] = set()
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        def add_path(src: Path, rel: str):
            rel = _portable_safe_rel(rel).as_posix()
            if src.is_dir():
                for child in src.rglob("*"):
                    if child.is_file():
                        arc = "uploads/" + (PurePosixPath(rel) / child.relative_to(src).as_posix()).as_posix()
                        if arc not in added: zf.write(child, arc); added.add(arc)
            elif src.is_file():
                arc = "uploads/" + rel
                if arc not in added: zf.write(src, arc); added.add(arc)
        if include_all:
            for root in ("images", "fonts", "videos", "video-src", "shaders"):
                base = UPLOAD_DIR / root
                if base.exists():
                    for child in base.iterdir():
                        add_path(child, f"{root}/{child.name}")
        else:
            for item in refs.values():
                src = UPLOAD_DIR / _portable_safe_rel(item["relative"])
                if src.exists(): add_path(src, item["relative"])
    return temp, filename


def _portable_inspect(path: Path) -> tuple[dict, zipfile.ZipFile]:
    try: zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc: raise ValueError("Not a valid Pi Matrix portable ZIP") from exc
    infos = zf.infolist()
    if not infos or len(infos) > PORTABLE_MAX_FILES:
        zf.close(); raise ValueError("Portable package contains too many files")
    total = 0
    for info in infos:
        name = info.filename.replace("\\", "/")
        pp = PurePosixPath(name)
        if pp.is_absolute() or any(part in ("", ".", "..") for part in pp.parts):
            zf.close(); raise ValueError("Portable package contains an unsafe path")
        total += int(info.file_size)
        if total > PORTABLE_MAX_UNCOMPRESSED:
            zf.close(); raise ValueError("Portable package is too large when unpacked")
    if "manifest.json" not in zf.namelist():
        zf.close(); raise ValueError("This is not a Pi Matrix portable package")
    try: manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except Exception as exc:
        zf.close(); raise ValueError("Portable package manifest is invalid") from exc
    if manifest.get("product") != "Pi Matrix Signage Portable" or int(manifest.get("format") or 0) != PORTABLE_FORMAT:
        zf.close(); raise ValueError("Unsupported Pi Matrix portable package")
    return manifest, zf


def _unique_import_file(dest: Path) -> Path:
    if not dest.exists(): return dest
    stem, suffix = dest.stem, dest.suffix
    for n in range(2, 10000):
        candidate = dest.with_name(f"{stem}-{n}{suffix}")
        if not candidate.exists(): return candidate
    raise ValueError("Could not choose a unique imported filename")


def _unique_import_dir(dest: Path) -> Path:
    if not dest.exists(): return dest
    for n in range(2, 10000):
        candidate = dest.with_name(f"{dest.name}-{n}")
        if not candidate.exists(): return candidate
    raise ValueError("Could not choose a unique imported folder")


def _portable_install_uploads(zf: zipfile.ZipFile, manifest: dict) -> dict[str, str]:
    refs = manifest.get("asset_refs") if isinstance(manifest.get("asset_refs"), list) else []
    primary: dict[str, Path] = {}
    # Install each referenced primary asset first so we can rewrite stored paths.
    for item in refs:
        if not isinstance(item, dict): continue
        rel = _portable_safe_rel(str(item.get("relative") or "")).as_posix()
        if rel in primary: continue
        dest = UPLOAD_DIR / rel
        prefix = "uploads/" + rel
        if bool(item.get("is_dir")):
            dest = _unique_import_dir(dest); dest.mkdir(parents=True, exist_ok=False)
            wanted = prefix.rstrip("/") + "/"
            for info in zf.infolist():
                if info.is_dir() or not info.filename.startswith(wanted): continue
                sub = PurePosixPath(info.filename[len(wanted):])
                if sub.is_absolute() or any(part in ("", ".", "..") for part in sub.parts): continue
                out = dest.joinpath(*sub.parts); out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(out, "wb") as dst: shutil.copyfileobj(src, dst)
        else:
            if prefix not in zf.namelist(): continue
            dest.parent.mkdir(parents=True, exist_ok=True); dest = _unique_import_file(dest)
            with zf.open(prefix) as src, open(dest, "wb") as dst: shutil.copyfileobj(src, dst)
        primary[rel] = dest
    mapping: dict[str, str] = {}
    for item in refs:
        if not isinstance(item, dict): continue
        rel = str(item.get("relative") or "")
        dest = primary.get(rel)
        if not dest: continue
        old = str(item.get("reference") or "")
        mapping[old] = ("upload:" + dest.name) if item.get("ref_type") == "shader_id" else str(dest)
    # Full-configuration exports also carry unreferenced uploads.  Preserve them
    # where possible without overwriting anything already on this sign.
    if str(manifest.get("kind")) == "configuration":
        referenced_prefixes = {"uploads/" + rel.rstrip("/") for rel in primary}
        for info in zf.infolist():
            if info.is_dir() or not info.filename.startswith("uploads/"): continue
            rel = info.filename[len("uploads/"):]
            try: safe = _portable_safe_rel(rel)
            except ValueError: continue
            # Files under an already installed referenced directory are done.
            if any(info.filename == p or info.filename.startswith(p + "/") for p in referenced_prefixes): continue
            dest = UPLOAD_DIR.joinpath(*safe.parts)
            if dest.exists(): continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as dst: shutil.copyfileobj(src, dst)
    return mapping


def _portable_rewrite(value, mapping: dict[str, str]):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "scene_json" and isinstance(v, str) and v.strip():
                try: out[k] = json.dumps(_portable_rewrite(json.loads(v), mapping), separators=(",", ":"), ensure_ascii=False)
                except Exception: out[k] = v
            elif isinstance(v, str) and v in mapping: out[k] = mapping[v]
            else: out[k] = _portable_rewrite(v, mapping)
        return out
    if isinstance(value, list): return [_portable_rewrite(v, mapping) for v in value]
    if isinstance(value, str) and value in mapping: return mapping[value]
    return value


def _unique_component_name(name: str) -> str:
    existing = {str(x.get("name") or "").casefold() for x in db.list_components()}
    base = str(name or "Imported component").strip() or "Imported component"
    if base.casefold() not in existing: return base
    n = 2
    while f"{base} {n}".casefold() in existing: n += 1
    return f"{base} {n}"


def _unique_playlist_name(name: str) -> str:
    existing = {str(x.get("name") or "").casefold() for x in db.list_playlists()}
    base = str(name or "Imported playlist").strip() or "Imported playlist"
    if base.casefold() not in existing: return base
    n = 2
    while f"{base} {n}".casefold() in existing: n += 1
    return f"{base} {n}"


def _portable_import_payload(manifest: dict, mapping: dict[str, str], saved_by: str) -> dict:
    payload = manifest.get("payload") if isinstance(manifest.get("payload"), dict) else {}
    payload = _portable_rewrite(payload, mapping)
    kind = str(manifest.get("kind") or payload.get("kind") or "")
    result: dict = {"kind": kind}
    if kind == "message":
        row = dict(payload.get("message") or {}); row.pop("id", None)
        row["name"] = str(row.get("name") or "Imported message")
        mid = db.save_message(row); db.save_message_version(mid, saved_by or "Import")
        result.update(message_id=mid, message=db.get_message(mid))
    elif kind == "component":
        comp = dict(payload.get("component") or {}); name = _unique_component_name(comp.get("name"))
        cid = db.save_component({"name": name, "component": comp.get("component") or {}})
        result.update(component_id=cid)
    elif kind == "playlist":
        idmap: dict[int, int] = {}
        for raw in payload.get("messages") or []:
            row = dict(raw); old = int(row.pop("id", 0) or 0); row["name"] = str(row.get("name") or "Imported message")
            mid = db.save_message(row); db.save_message_version(mid, saved_by or "Import")
            if old: idmap[old] = mid
        pl = dict(payload.get("playlist") or {})
        items = [{"message_id": idmap.get(int(i.get("message_id") or 0), int(i.get("message_id") or 0)), "duration": i.get("duration", 10)} for i in (pl.get("items") or [])]
        pid = db.save_playlist({"name": _unique_playlist_name(pl.get("name")), "enabled": pl.get("enabled", True), "items": items})
        result.update(playlist_id=pid, imported_messages=len(idmap))
    elif kind == "configuration":
        # A portable full configuration deliberately replaces creative/automation
        # content but does not replace users/passwords or the FPP configuration.
        with db.conn() as con:
            con.execute("DELETE FROM schedules"); con.execute("DELETE FROM conditional_rules"); con.execute("DELETE FROM brightness_schedules")
            con.execute("DELETE FROM playlist_items"); con.execute("DELETE FROM playlists"); con.execute("DELETE FROM components"); con.execute("DELETE FROM messages")
        msgmap: dict[int, int] = {}
        for raw in payload.get("messages") or []:
            row = dict(raw); old = int(row.pop("id", 0) or 0)
            mid = db.save_message(row); db.save_message_version(mid, saved_by or "Configuration import")
            if old: msgmap[old] = mid
        for comp in payload.get("components") or []:
            db.save_component({"name": _unique_component_name(comp.get("name")), "component": comp.get("component") or {}})
        plmap: dict[int, int] = {}
        for pl in payload.get("playlists") or []:
            oldpid = int(pl.get("id") or 0)
            items = [{"message_id": msgmap.get(int(i.get("message_id") or 0), int(i.get("message_id") or 0)), "duration": i.get("duration", 10)} for i in (pl.get("items") or [])]
            pid = db.save_playlist({"name": _unique_playlist_name(pl.get("name")), "enabled": pl.get("enabled", True), "items": items})
            if oldpid: plmap[oldpid] = pid
        for sched in payload.get("schedules") or []:
            x = dict(sched); x.pop("id", None); x.pop("created_at", None); x.pop("updated_at", None)
            if x.get("target_type") == "message": x["target_id"] = msgmap.get(int(x.get("target_id") or 0), int(x.get("target_id") or 0))
            else: x["target_id"] = plmap.get(int(x.get("target_id") or 0), int(x.get("target_id") or 0))
            db.save_schedule(x)
        for rule in payload.get("conditional_rules") or []:
            x = dict(rule); x.pop("id", None); x.pop("created_at", None); x.pop("updated_at", None); x.pop("config_json", None)
            if x.get("target_type") == "message": x["target_id"] = msgmap.get(int(x.get("target_id") or 0), int(x.get("target_id") or 0))
            else: x["target_id"] = plmap.get(int(x.get("target_id") or 0), int(x.get("target_id") or 0))
            db.save_conditional_rule(x)
        for item in payload.get("brightness_schedules") or []:
            x = dict(item); x.pop("id", None); x.pop("created_at", None); x.pop("updated_at", None); db.save_brightness_schedule(x)
        settings = dict(payload.get("settings") or {})
        if settings.get("default_message_id") is not None: settings["default_message_id"] = msgmap.get(int(settings["default_message_id"]), None)
        if settings.get("emergency_message_id") is not None: settings["emergency_message_id"] = msgmap.get(int(settings["emergency_message_id"]), None)
        settings.pop("web_password", None); db.update_settings(settings); engine.reload_settings()
        result.update(messages=len(msgmap), playlists=len(plmap), configuration=True)
    else:
        raise ValueError("Unsupported portable package type")
    return result

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "pimatrix"
PASSWORD_MIN_LENGTH = 8
PERMISSION_COLUMNS = {
    "messages": "can_messages",
    "playlists": "can_playlists",
    "schedules": "can_schedules",
    "display_setup": "can_display_setup",
    "upgrade": "can_upgrade",
    "backup": "can_backup",
    "users": "can_users",
}

# A clean install or first run after the user-account migration always has a
# known recovery account.  The default password must be changed before the
# main application can be used.
db.ensure_default_admin(_hash_password(DEFAULT_ADMIN_PASSWORD), DEFAULT_ADMIN_USERNAME)
DUMMY_PASSWORD_HASH = _hash_password("this-is-not-a-real-account")


def _permission_map(user: dict | None) -> dict[str, bool]:
    out = {"dashboard": True}
    for name, column in PERMISSION_COLUMNS.items():
        out[name] = bool(user and user.get(column))
    return out


def _client_user(user: dict) -> dict:
    return {
        "id": int(user["id"]),
        "username": str(user.get("username") or ""),
        "display_name": str(user.get("display_name") or user.get("username") or ""),
        "must_change_password": bool(user.get("must_change_password")),
        "permissions": _permission_map(user),
    }


def _new_csrf_token() -> str:
    token = secrets.token_urlsafe(32)
    session["csrf_token"] = token
    return token


def _csrf_token() -> str:
    return str(session.get("csrf_token") or _new_csrf_token())


def _api_request() -> bool:
    return request.path.startswith("/api/")


def permission_required(permission: str):
    if permission not in PERMISSION_COLUMNS:
        raise ValueError(f"Unknown permission: {permission}")
    column = PERMISSION_COLUMNS[permission]

    def decorate(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if not user or not bool(user.get(column)):
                if _api_request():
                    return jsonify({"error": "You do not have permission to use this area."}), 403
                return Response("Permission denied", 403)
            return func(*args, **kwargs)
        return wrapped
    return decorate


@app.before_request
def require_login_and_csrf():
    # FPP/updater health checks and login/static assets must remain available
    # without a session.  Everything else requires a named active account.
    if request.path == "/health" or request.path == "/login" or request.path.startswith("/static/"):
        return None

    user = None
    uid = session.get("user_id")
    if uid is not None:
        try:
            user = db.get_user(int(uid))
        except Exception:
            user = None
    if not user or not bool(user.get("is_active")):
        session.clear()
        if _api_request():
            return jsonify({"error": "Sign in required"}), 401
        return redirect(url_for("login", next=request.full_path if request.path != "/" else ""))

    g.current_user = user

    allowed_while_changing = {
        "/change-password", "/api/auth/me", "/api/auth/logout",
    }
    if bool(user.get("must_change_password")) and request.path not in allowed_while_changing:
        if _api_request():
            return jsonify({"error": "You must change the initial password before continuing."}), 403
        return redirect(url_for("change_password"))

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
        if not hmac.compare_digest(str(supplied), str(session.get("csrf_token") or "")):
            if _api_request():
                return jsonify({"error": "Security token expired. Reload the page and try again."}), 403
            return Response("Security token expired", 403)
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        user = db.get_user(int(session["user_id"]))
        if user and bool(user.get("is_active")):
            return redirect(url_for("change_password" if user.get("must_change_password") else "index"))
        session.clear()

    error = ""
    username = ""
    if request.method == "POST":
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        user = db.get_user_by_username(username)
        if user and bool(user.get("is_active")) and _verify_password(str(user.get("password_hash") or ""), password):
            session.clear()
            session["user_id"] = int(user["id"])
            session.permanent = True
            _new_csrf_token()
            db.touch_user_login(int(user["id"]))
            LOG.info("User %s signed in from %s", user.get("username"), request.remote_addr)
            return redirect(url_for("change_password" if user.get("must_change_password") else "index"))
        error = "Invalid username or password."
        # Keep the timing less dependent on whether the account exists.
        if not user:
            _verify_password(DUMMY_PASSWORD_HASH, password)
        LOG.warning("Failed sign-in for %s from %s", username or "(blank)", request.remote_addr)
    default_admin = db.get_user_by_username(DEFAULT_ADMIN_USERNAME)
    show_default_credentials = bool(default_admin and default_admin.get("must_change_password") and
                                    _verify_password(str(default_admin.get("password_hash") or ""), DEFAULT_ADMIN_PASSWORD))
    return render_template("login.html", app_version=APP_VERSION, error=error, username=username,
                           default_username=DEFAULT_ADMIN_USERNAME, default_password=DEFAULT_ADMIN_PASSWORD,
                           show_default_credentials=show_default_credentials)


@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    user = g.current_user
    error = ""
    if request.method == "POST":
        current = str(request.form.get("current_password") or "")
        new_password = str(request.form.get("new_password") or "")
        confirm = str(request.form.get("confirm_password") or "")
        if not _verify_password(str(user.get("password_hash") or ""), current):
            error = "Current password is incorrect."
        elif len(new_password) < PASSWORD_MIN_LENGTH:
            error = f"New password must be at least {PASSWORD_MIN_LENGTH} characters."
        elif new_password != confirm:
            error = "The new passwords do not match."
        elif hmac.compare_digest(new_password, current):
            error = "Choose a different password."
        else:
            db.set_user_password(int(user["id"]), _hash_password(new_password), must_change_password=False)
            _new_csrf_token()
            LOG.info("User %s changed their password", user.get("username"))
            return redirect(url_for("index"))
    return render_template("change_password.html", app_version=APP_VERSION, error=error,
                           user=_client_user(user), csrf_token=_csrf_token(),
                           forced=bool(user.get("must_change_password")))


@app.get("/api/auth/me")
def auth_me_api():
    return jsonify({"user": _client_user(g.current_user), "csrf_token": _csrf_token()})


@app.post("/api/auth/logout")
def auth_logout_api():
    username = str(g.current_user.get("username") or "")
    session.clear()
    LOG.info("User %s signed out", username)
    return jsonify({"ok": True})


@app.get("/")
def index():
    response = app.make_response(render_template("index.html", app_version=APP_VERSION))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/remote")
def remote_control():
    response=app.make_response(render_template("remote.html",app_version=APP_VERSION))
    response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"]="no-cache"
    return response


@app.get("/help")
def help_manual():
    response = app.make_response(render_template("help.html", app_version=APP_VERSION))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/health")
def health():
    response = jsonify({"ok": True, "version": APP_VERSION, "status": engine.status()})
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-PiMatrix-Version"] = APP_VERSION
    return response


@app.get("/api/status")
def api_status():
    return jsonify(engine.status())


@app.get("/api/content-options")
def content_options_api():
    permissions = _permission_map(g.current_user)
    return jsonify({
        # Dashboard always needs message names for Show something now.
        "messages": db.list_message_options(),
        # Playlist names are only needed by Playlist/Schedule users.
        "playlists": db.list_playlist_options() if (permissions.get("playlists") or permissions.get("schedules")) else [],
    })


@app.get("/api/settings")
def get_settings():
    s = db.get_settings()
    safe = dict(s)
    safe.pop("web_password", None)
    safe["display_width"] = int(s["panel_width"]) * int(s["panels_across"])
    safe["display_height"] = int(s["panel_height"]) * int(s["panels_down"])
    safe["channel_count"] = safe["display_width"] * safe["display_height"] * 3
    return jsonify(safe)


@app.put("/api/settings")
@permission_required("display_setup")
def put_settings():
    data = request.get_json(force=True) or {}
    current = db.get_settings()
    clean = {}
    ints = {
        "panel_width": (8, 512), "panel_height": (8, 512),
        "panels_across": (1, 32), "panels_down": (1, 32),
        "display_rotation": (0, 270), "brightness": (0, 100),
        "frame_rate": (1, 60), "ddp_port": (1, 65535), "ddp_offset": (0, 100000000),
        "renderer_stall_seconds": (3, 60), "recovery_cooldown_seconds": (15, 3600),
    }
    for key, bounds in ints.items():
        if key in data:
            value = int(data[key])
            if key == "display_rotation":
                if value not in (0, 90, 180, 270):
                    raise ValueError("display_rotation must be 0, 90, 180 or 270")
            elif not (bounds[0] <= value <= bounds[1]):
                raise ValueError(f"{key} out of range")
            clean[key] = value
    output_type = str(data.get("panel_output_type", current.get("panel_output_type", "rpi_mfc"))).strip().lower()
    if output_type not in ("rpi_mfc", "colorlight"):
        raise ValueError("panel_output_type must be rpi_mfc or colorlight")
    clean["panel_output_type"] = output_type
    if "colorlight_receiver_model" in data:
        receiver_model = str(data["colorlight_receiver_model"]).strip().lower()
        if receiver_model not in ("5a-75b", "5a-75e"):
            raise ValueError("Unsupported Colorlight receiver model")
        clean["colorlight_receiver_model"] = receiver_model
    if "colorlight_interface" in data:
        interface = str(data["colorlight_interface"]).strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}", interface):
            raise ValueError("Invalid Colorlight network interface")
        clean["colorlight_interface"] = interface
    if "panel_scan" in data:
        scan = str(data["panel_scan"]).strip()
        supported_scans = ("1/8", "1/16") if output_type == "rpi_mfc" else ("1/4", "1/8", "1/16", "1/32", "1/64")
        if scan not in supported_scans:
            raise ValueError(f"panel_scan is not supported for {output_type}")
        clean["panel_scan"] = scan
    if "ddp_host" in data:
        clean["ddp_host"] = str(data["ddp_host"]).strip() or "127.0.0.1"
    if "color_order" in data:
        val = str(data["color_order"]).upper()
        if sorted(val) != ["B", "G", "R"]:
            raise ValueError("Invalid color order")
        clean["color_order"] = val
    if "timezone" in data:
        tz = str(data["timezone"]).strip()
        ZoneInfo(tz)  # validate
        clean["timezone"] = tz
    if "default_message_id" in data:
        clean["default_message_id"] = int(data["default_message_id"]) if data["default_message_id"] else None
    for key in ("auto_recovery_enabled", "auto_recover_renderer", "auto_recover_fppd"):
        if key in data:
            clean[key] = bool(data[key])
    db.update_settings(clean)
    engine.reload_settings()
    return get_settings()


@app.get("/api/license")
def license_status_api():
    return jsonify(license_manager.info())


@app.post("/api/license/activate")
@permission_required("display_setup")
def license_activate_api():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(license_manager.activate(str(data.get("license_key") or "")))
    except LicenseError as exc:
        return jsonify({"error": str(exc), "license": license_manager.info()}), 400


@app.post("/api/license/check")
@permission_required("display_setup")
def license_check_api():
    try:
        return jsonify(license_manager.check_now())
    except LicenseError as exc:
        return jsonify({"error": str(exc), "license": license_manager.info()}), 400


@app.post("/api/license/deactivate-local")
@permission_required("display_setup")
def license_deactivate_local_api():
    return jsonify(license_manager.deactivate_local())


@app.get("/api/components")
@permission_required("messages")
def list_components_api():
    return jsonify(db.list_components())


@app.post("/api/components")
@permission_required("messages")
def create_component_api():
    cid = db.save_component(request.get_json(force=True) or {})
    return jsonify(db.get_component(cid)), 201


@app.put("/api/components/<int:cid>")
@permission_required("messages")
def update_component_api(cid: int):
    if not db.get_component(cid):
        return jsonify({"error": "Not found"}), 404
    db.save_component(request.get_json(force=True) or {}, cid)
    return jsonify(db.get_component(cid))


@app.delete("/api/components/<int:cid>")
@permission_required("messages")
def delete_component_api(cid: int):
    db.delete_component(cid)
    return jsonify({"ok": True})


@app.get("/api/messages")
@permission_required("messages")
def list_messages_api():
    return jsonify(db.list_messages())


@app.post("/api/messages")
@permission_required("messages")
def create_message_api():
    mid = db.save_message(request.get_json(force=True) or {})
    db.save_message_version(mid, str(g.current_user.get("display_name") or g.current_user.get("username") or ""))
    return jsonify(db.get_message(mid)), 201


@app.get("/api/messages/<int:mid>")
@permission_required("messages")
def get_message_api(mid: int):
    msg = db.get_message(mid)
    return (jsonify(msg), 200) if msg else (jsonify({"error": "Not found"}), 404)


@app.put("/api/messages/<int:mid>")
@permission_required("messages")
def update_message_api(mid: int):
    if not db.get_message(mid):
        return jsonify({"error": "Not found"}), 404
    db.save_message(request.get_json(force=True) or {}, mid)
    db.save_message_version(mid, str(g.current_user.get("display_name") or g.current_user.get("username") or ""))
    return jsonify(db.get_message(mid))


@app.delete("/api/messages/<int:mid>")
@permission_required("messages")
def delete_message_api(mid: int):
    db.delete_message(mid)
    return jsonify({"ok": True})



@app.get("/api/messages/<int:mid>/versions")
@permission_required("messages")
def message_versions_api(mid: int):
    if not db.get_message(mid): return jsonify({"error": "Not found"}), 404
    return jsonify(db.list_message_versions(mid))


@app.post("/api/messages/<int:mid>/versions/<int:version_id>/restore")
@permission_required("messages")
def restore_message_version_api(mid: int, version_id: int):
    if not db.get_message(mid): return jsonify({"error": "Not found"}), 404
    who = str(g.current_user.get("display_name") or g.current_user.get("username") or "")
    try: restored = db.restore_message_version(mid, version_id, who)
    except ValueError as exc: return jsonify({"error": str(exc)}), 404
    return jsonify(restored)


@app.get("/api/portable/export/<kind>/<int:object_id>")
@permission_required("messages")
def portable_export_object_api(kind: str, object_id: int):
    if kind not in {"message", "component"}: return jsonify({"error": "Unsupported export type"}), 400
    try: path, filename = _portable_package(kind, object_id)
    except ValueError as exc: return jsonify({"error": str(exc)}), 404
    response = send_file(path, as_attachment=True, download_name=filename, mimetype="application/zip", max_age=0)
    response.call_on_close(lambda: path.unlink(missing_ok=True))
    return response


@app.get("/api/portable/export/playlist/<int:object_id>")
@permission_required("playlists")
def portable_export_playlist_api(object_id: int):
    try: path, filename = _portable_package("playlist", object_id)
    except ValueError as exc: return jsonify({"error": str(exc)}), 404
    response = send_file(path, as_attachment=True, download_name=filename, mimetype="application/zip", max_age=0)
    response.call_on_close(lambda: path.unlink(missing_ok=True))
    return response


@app.get("/api/portable/export/configuration")
@permission_required("backup")
def portable_export_configuration_api():
    path, filename = _portable_package("configuration", None)
    response = send_file(path, as_attachment=True, download_name=filename, mimetype="application/zip", max_age=0)
    response.call_on_close(lambda: path.unlink(missing_ok=True))
    return response


@app.post("/api/portable/import")
def portable_import_api():
    if "file" not in request.files: return jsonify({"error": "No portable ZIP supplied"}), 400
    upload = request.files["file"]
    fd, tmp_name = tempfile.mkstemp(prefix="pimatrix-import-", suffix=".zip", dir=str(DATA_DIR)); os.close(fd)
    tmp = Path(tmp_name)
    try:
        upload.save(tmp)
        manifest, zf = _portable_inspect(tmp)
        try:
            kind = str(manifest.get("kind") or "")
            need = "backup" if kind == "configuration" else ("playlists" if kind == "playlist" else "messages")
            if not _permission_map(g.current_user).get(need, False): return jsonify({"error": f"{need.replace('_',' ').title()} permission required"}), 403
            mapping = _portable_install_uploads(zf, manifest)
        finally: zf.close()
        who = str(g.current_user.get("display_name") or g.current_user.get("username") or "")
        result = _portable_import_payload(manifest, mapping, who)
        return jsonify({"ok": True, **result})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        tmp.unlink(missing_ok=True)


@app.post("/api/messages/<int:mid>/show")
def show_message_api(mid: int):
    if not db.get_message(mid):
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    engine.show_target("message", mid, float(data.get("duration", 0) or 0))
    return jsonify({"ok": True})


@app.get("/api/playlists")
@permission_required("playlists")
def list_playlists_api():
    return jsonify(db.list_playlists())


@app.post("/api/playlists")
@permission_required("playlists")
def create_playlist_api():
    pid = db.save_playlist(request.get_json(force=True) or {})
    return jsonify(db.get_playlist(pid)), 201


@app.put("/api/playlists/<int:pid>")
@permission_required("playlists")
def update_playlist_api(pid: int):
    if not db.get_playlist(pid):
        return jsonify({"error": "Not found"}), 404
    db.save_playlist(request.get_json(force=True) or {}, pid)
    return jsonify(db.get_playlist(pid))


@app.delete("/api/playlists/<int:pid>")
@permission_required("playlists")
def delete_playlist_api(pid: int):
    db.delete_playlist(pid)
    return jsonify({"ok": True})


@app.post("/api/playlists/<int:pid>/show")
@permission_required("playlists")
def show_playlist_api(pid: int):
    if not db.get_playlist(pid):
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    engine.show_target("playlist", pid, float(data.get("duration", 0) or 0))
    return jsonify({"ok": True})


@app.get("/api/schedules")
@permission_required("schedules")
def list_schedules_api():
    return jsonify(db.list_schedules())


@app.post("/api/schedules")
@permission_required("schedules")
def create_schedule_api():
    sid = db.save_schedule(request.get_json(force=True) or {})
    return jsonify(db.get_schedule(sid)), 201


@app.put("/api/schedules/<int:sid>")
@permission_required("schedules")
def update_schedule_api(sid: int):
    if not db.get_schedule(sid):
        return jsonify({"error": "Not found"}), 404
    db.save_schedule(request.get_json(force=True) or {}, sid)
    return jsonify(db.get_schedule(sid))


@app.delete("/api/schedules/<int:sid>")
@permission_required("schedules")
def delete_schedule_api(sid: int):
    db.delete_schedule(sid)
    return jsonify({"ok": True})


@app.get("/api/conditional-rules")
@permission_required("schedules")
def list_conditional_rules_api():
    rules=db.list_conditional_rules(); runtime={int(x.get("id")):x for x in engine.conditional_status()}
    for rule in rules: rule["runtime"]=runtime.get(int(rule["id"]),{})
    return jsonify(rules)

@app.post("/api/conditional-rules")
@permission_required("schedules")
def create_conditional_rule_api():
    rid=db.save_conditional_rule(request.get_json(force=True) or {})
    engine._automation_cache_at=0.0
    return jsonify(db.get_conditional_rule(rid)),201

@app.put("/api/conditional-rules/<int:rid>")
@permission_required("schedules")
def update_conditional_rule_api(rid:int):
    if not db.get_conditional_rule(rid): return jsonify({"error":"Not found"}),404
    db.save_conditional_rule(request.get_json(force=True) or {},rid); engine._automation_cache_at=0.0
    return jsonify(db.get_conditional_rule(rid))

@app.delete("/api/conditional-rules/<int:rid>")
@permission_required("schedules")
def delete_conditional_rule_api(rid:int):
    db.delete_conditional_rule(rid); engine._automation_cache_at=0.0
    return jsonify({"ok":True})

@app.get("/api/brightness-schedules")
@permission_required("schedules")
def list_brightness_schedules_api(): return jsonify(db.list_brightness_schedules())

@app.post("/api/brightness-schedules")
@permission_required("schedules")
def create_brightness_schedule_api():
    bid=db.save_brightness_schedule(request.get_json(force=True) or {}); engine._brightness_cache_at=0.0
    return jsonify(db.get_brightness_schedule(bid)),201

@app.put("/api/brightness-schedules/<int:bid>")
@permission_required("schedules")
def update_brightness_schedule_api(bid:int):
    if not db.get_brightness_schedule(bid): return jsonify({"error":"Not found"}),404
    db.save_brightness_schedule(request.get_json(force=True) or {},bid); engine._brightness_cache_at=0.0
    return jsonify(db.get_brightness_schedule(bid))

@app.delete("/api/brightness-schedules/<int:bid>")
@permission_required("schedules")
def delete_brightness_schedule_api(bid:int):
    db.delete_brightness_schedule(bid); engine._brightness_cache_at=0.0
    return jsonify({"ok":True})

@app.put("/api/operations/settings")
@permission_required("schedules")
def operations_settings_api():
    data=request.get_json(force=True) or {}; clean={}
    if "emergency_message_id" in data:
        mid=int(data.get("emergency_message_id") or 0)
        if mid and not db.get_message(mid): raise ValueError("Emergency message not found")
        clean["emergency_message_id"]=mid or None
    db.update_settings(clean); engine.reload_settings()
    return jsonify({"emergency_message_id":db.get_settings().get("emergency_message_id")})

@app.post("/api/emergency/activate")
def emergency_activate_api():
    data=request.get_json(silent=True) or {}; mid=int(data.get("message_id") or 0) or None
    engine.activate_emergency(mid); return jsonify({"ok":True,"status":engine.status()})

@app.post("/api/emergency/clear")
def emergency_clear_api():
    engine.clear_emergency(); return jsonify({"ok":True,"status":engine.status()})

@app.post("/api/show/blank")
def show_blank_api():
    engine.show_blank(); return jsonify({"ok":True})

@app.post("/api/brightness/override")
def brightness_override_api():
    data=request.get_json(force=True) or {}
    value=data.get("brightness")
    engine.set_brightness_override(None if value is None or value=="" else int(value))
    return jsonify({"ok":True,"brightness":engine.status().get("brightness")})


@app.get("/api/gpio-controls")
@permission_required("display_setup")
def gpio_controls_api():
    return jsonify(gpio_controls.status())


@app.put("/api/gpio-controls")
@permission_required("display_setup")
def gpio_controls_update_api():
    data=request.get_json(force=True) or {}
    enabled=bool(data.get("enabled",False))
    inputs=normalise_gpio_inputs(data.get("inputs"))
    # Store only the user-editable fields. The physical rPi-MFC connector/pin
    # mapping is fixed in gpio_controls.py and cannot be changed from the browser.
    stored=[{k:item[k] for k in ("id","enabled","action","contact_type","emergency_behaviour","debounce_ms")} for item in inputs]
    db.update_settings({"gpio_controls_enabled":enabled,"gpio_inputs":stored})
    gpio_controls.reload()
    return jsonify(gpio_controls.status())


@app.post("/api/gpio-controls/<key>/test")
@permission_required("display_setup")
def gpio_controls_test_api(key: str):
    gpio_controls.test_action(key)
    return jsonify({"ok":True,"status":gpio_controls.status(),"display":engine.status()})


@app.post("/api/show/clear")
def clear_show_api():
    engine.clear_manual()
    return jsonify({"ok": True})


@app.post("/api/test-pattern")
def test_pattern_api():
    data = request.get_json(force=True) or {}
    engine.test_pattern(str(data.get("kind", "grid")), float(data.get("duration", 30)))
    return jsonify({"ok": True})


@app.get("/api/preview.png")
def preview_png_api():
    scale = max(1, min(16, int(request.args.get("scale", 6))))
    return Response(engine.preview_png(scale), mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/render-preview")
@permission_required("messages")
def render_preview_api():
    msg = request.get_json(force=True) or {}
    s = db.get_settings()
    physical_w = int(s["panel_width"]) * int(s["panels_across"])
    physical_h = int(s["panel_height"]) * int(s["panels_down"])
    rotation = int(s.get("display_rotation", 0)) % 360
    if rotation in (90, 270):
        w, h = physical_h, physical_w
    else:
        w, h = physical_w, physical_h
    try:
        tz = ZoneInfo(str(s.get("timezone") or "Europe/London"))
    except Exception:
        tz = ZoneInfo("Europe/London")
    im = render_message(msg, w, h, float(request.args.get("elapsed", 0) or 0), datetime.now(tz), str(UPLOAD_DIR / "fonts"))
    if rotation == 90:
        im = im.transpose(Image.Transpose.ROTATE_270)
    elif rotation == 180:
        im = im.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        im = im.transpose(Image.Transpose.ROTATE_90)
    scale = max(1, min(16, int(request.args.get("scale", 6))))
    if scale > 1:
        im = im.resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/fonts")
@permission_required("messages")
def fonts_api():
    return jsonify(list_fonts(str(UPLOAD_DIR / "fonts")))


@app.get("/api/assets")
@permission_required("messages")
def assets_api():
    out = []
    for p in sorted((UPLOAD_DIR / "images").iterdir()):
        if p.is_file() and p.suffix.lower().lstrip(".") in IMAGE_EXTENSIONS:
            animated = False
            frames = 1
            try:
                with Image.open(p) as im:
                    animated = bool(getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1)
                    frames = int(getattr(im, "n_frames", 1) or 1)
            except Exception:
                pass
            out.append({"name": p.name, "path": str(p), "url": f"/uploads/images/{p.name}", "animated": animated, "frames": frames})
    return jsonify(out)


@app.get("/api/videos")
@permission_required("messages")
def videos_api():
    out = []
    root = UPLOAD_DIR / "videos"
    for folder in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda x: x.name.lower()):
        meta_path = folder / "metadata.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        except Exception:
            meta = {}
        frame_count = int(meta.get("frames") or len(list(folder.glob("frame-*.png"))))
        out.append({
            "name": str(meta.get("name") or folder.name),
            "path": str(folder),
            "fps": float(meta.get("fps") or 12),
            "frames": frame_count,
            "duration": float(meta.get("duration") or (frame_count / max(0.1, float(meta.get("fps") or 12)))),
            "width": int(meta.get("width") or 0),
            "height": int(meta.get("height") or 0),
        })
    return jsonify(out)


def _logical_display_size() -> tuple[int, int]:
    s = db.get_settings()
    physical_w = int(s["panel_width"]) * int(s["panels_across"])
    physical_h = int(s["panel_height"]) * int(s["panels_down"])
    if int(s.get("display_rotation", 0)) % 360 in (90, 270):
        return physical_h, physical_w
    return physical_w, physical_h


def _unique_dir(root: Path, stem: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "video"
    dest = root / safe
    n = 2
    while dest.exists():
        dest = root / f"{safe}-{n}"
        n += 1
    return dest


def _video_job_update(job_id: str, **changes) -> None:
    with VIDEO_JOBS_LOCK:
        job = VIDEO_JOBS.get(job_id)
        if not job:
            return
        job.update(changes)
        job["updated_at"] = time.time()


def _video_job_snapshot(job_id: str) -> dict | None:
    now = time.time()
    with VIDEO_JOBS_LOCK:
        # Opportunistic cleanup so completed jobs don't accumulate for the life
        # of the service.
        stale = [key for key, value in VIDEO_JOBS.items() if now - float(value.get("updated_at", now)) > VIDEO_JOB_TTL]
        for key in stale:
            VIDEO_JOBS.pop(key, None)
        job = VIDEO_JOBS.get(job_id)
        return dict(job) if job else None


def _probe_video_duration(source: Path, max_seconds: float) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return max_seconds
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(source)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15,
        )
        duration = float((result.stdout or "").strip())
        if duration > 0:
            return min(duration, max_seconds)
    except Exception:
        pass
    return max_seconds


def _process_video_source(source: Path, filename: str, fps: float, max_seconds: float, dest: Path, progress_cb=None) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is not installed. Re-run sudo ./install.sh to install video support.")

    w, h = _logical_display_size()
    expected_duration = _probe_video_duration(source, max_seconds)
    if progress_cb:
        progress_cb("processing", 3, f"Preparing {w}×{h} LED frames at {fps:g} fps")

    # Pre-decode video once. The live renderer then only opens tiny PNG frames,
    # avoiding expensive video decoding in the 25fps output loop.  FFmpeg's
    # machine-readable progress stream lets the browser show real conversion
    # progress rather than appearing to hang after the upload reaches 100%.
    vf = f"fps={fps:g},scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-t", f"{max_seconds:g}", "-vf", vf,
        "-progress", "pipe:1", "-nostats", str(dest / "frame-%06d.png"),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    last_pct = 3
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            out_seconds = None
            if key in ("out_time_us", "out_time_ms"):
                try:
                    # FFmpeg's historical out_time_ms field is actually in
                    # microseconds; out_time_us is explicit on newer builds.
                    out_seconds = max(0.0, float(value) / 1_000_000.0)
                except ValueError:
                    pass
            elif key == "out_time":
                try:
                    hh, mm, ss = value.split(":", 2)
                    out_seconds = int(hh) * 3600 + int(mm) * 60 + float(ss)
                except Exception:
                    pass
            if out_seconds is not None and expected_duration > 0:
                pct = int(min(96, max(3, round(3 + 93 * (out_seconds / expected_duration)))))
                if pct != last_pct:
                    last_pct = pct
                    if progress_cb:
                        progress_cb("processing", pct, f"Creating LED frames… {pct}%")
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        returncode = proc.wait()
    except Exception:
        proc.kill()
        proc.wait()
        raise
    if returncode != 0:
        raise RuntimeError((stderr or "FFmpeg could not decode this video").strip()[-2000:])

    if progress_cb:
        progress_cb("finalising", 97, "Finalising video…")
    frames = sorted(dest.glob("frame-*.png"))
    if not frames:
        raise RuntimeError("Video produced no frames")
    width = height = 0
    try:
        with Image.open(frames[0]) as im:
            width, height = im.size
    except Exception:
        pass
    meta = {
        "name": filename, "source": str(source), "fps": fps, "frames": len(frames),
        "duration": len(frames) / fps, "width": width, "height": height,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (dest / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    LOG.info("Processed video %s into %s frames at %.2ffps", filename, len(frames), fps)
    return {"name": filename, "path": str(dest), **meta}


def _video_worker(job_id: str, source: Path, filename: str, fps: float, max_seconds: float, dest: Path) -> None:
    try:
        def update(stage: str, progress: int, message: str) -> None:
            _video_job_update(job_id, state=stage, progress=int(progress), message=message)

        result = _process_video_source(source, filename, fps, max_seconds, dest, update)
        _video_job_update(job_id, state="complete", progress=100, message="Video ready", result=result)
    except Exception as exc:
        shutil.rmtree(dest, ignore_errors=True)
        LOG.exception("Video preprocessing failed for %s", filename)
        _video_job_update(job_id, state="failed", progress=100, message="Video processing failed", error=str(exc))


def _save_incoming_video():
    if "file" not in request.files:
        raise ValueError("No video supplied")
    upload = request.files["file"]
    filename = secure_filename(upload.filename or "")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not filename or ext not in VIDEO_EXTENSIONS:
        raise ValueError("Allowed video formats: " + ", ".join(sorted(VIDEO_EXTENSIONS)))
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is not installed. Re-run sudo ./install.sh to install video support.")

    fps = max(1.0, min(30.0, float(request.form.get("fps", 12) or 12)))
    max_seconds = max(1.0, min(600.0, float(request.form.get("max_seconds", 300) or 300)))
    source_dir = UPLOAD_DIR / "video-src"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / filename
    stem, suffix = source.stem, source.suffix
    n = 2
    while source.exists():
        source = source_dir / f"{stem}-{n}{suffix}"
        n += 1
    upload.save(source)
    dest = _unique_dir(UPLOAD_DIR / "videos", source.stem)
    dest.mkdir(parents=True, exist_ok=False)
    return source, filename, fps, max_seconds, dest


@app.post("/api/upload/video/start")
@permission_required("messages")
def upload_video_start_api():
    try:
        source, filename, fps, max_seconds, dest = _save_incoming_video()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    job_id = secrets.token_hex(12)
    now = time.time()
    with VIDEO_JOBS_LOCK:
        VIDEO_JOBS[job_id] = {
            "job_id": job_id, "state": "queued", "progress": 0,
            "message": "Video uploaded; waiting to process", "created_at": now, "updated_at": now,
        }
    threading.Thread(target=_video_worker, args=(job_id, source, filename, fps, max_seconds, dest), daemon=True, name=f"video-{job_id[:8]}").start()
    return jsonify({"job_id": job_id, "state": "queued", "progress": 0}), 202


@app.get("/api/upload/video/status/<job_id>")
@permission_required("messages")
def upload_video_status_api(job_id: str):
    if not re.fullmatch(r"[0-9a-f]{24}", job_id or ""):
        return jsonify({"error": "Invalid video job"}), 400
    job = _video_job_snapshot(job_id)
    if not job:
        return jsonify({"error": "Video job not found or expired"}), 404
    return jsonify(job)


@app.post("/api/upload/video")
@permission_required("messages")
def upload_video_api():
    """Compatibility endpoint for API users that still expect one request."""
    try:
        source, filename, fps, max_seconds, dest = _save_incoming_video()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    try:
        return jsonify(_process_video_source(source, filename, fps, max_seconds, dest))
    except Exception as exc:
        shutil.rmtree(dest, ignore_errors=True)
        LOG.exception("Video preprocessing failed for %s", filename)
        return jsonify({"error": str(exc)}), 400


def _save_upload(kind: str, allowed: set[str]):
    if "file" not in request.files:
        return jsonify({"error": "No file supplied"}), 400
    file = request.files["file"]
    filename = secure_filename(file.filename or "")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not filename or ext not in allowed:
        return jsonify({"error": f"Allowed: {', '.join(sorted(allowed))}"}), 400
    dest_dir = UPLOAD_DIR / kind
    dest = dest_dir / filename
    stem, suffix = dest.stem, dest.suffix
    n = 2
    while dest.exists():
        dest = dest_dir / f"{stem}-{n}{suffix}"
        n += 1
    file.save(dest)
    LOG.info("Uploaded %s asset %s", kind, dest.name)
    return jsonify({"name": dest.name, "path": str(dest), "url": f"/uploads/{kind}/{dest.name}"})


@app.get("/api/shaders")
@permission_required("messages")
def shaders_api():
    return jsonify(list_shader_assets(UPLOAD_DIR / "shaders", BASE_DIR / "shaders"))


@app.get("/api/shaders/status/<layer_id>")
@permission_required("messages")
def shader_status_api(layer_id: str):
    return jsonify(shader_layer_status(layer_id, str(UPLOAD_DIR / "fonts")))


@app.post("/api/upload/shader")
@permission_required("messages")
def upload_shader_api():
    if "file" not in request.files:
        return jsonify({"error": "No shader file supplied"}), 400
    file = request.files["file"]
    filename = secure_filename(file.filename or "")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not filename or ext not in SHADER_EXTENSIONS:
        return jsonify({"error": "Allowed shader files: .fs, .frag, .glsl, .json"}), 400
    dest_dir = UPLOAD_DIR / "shaders"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    stem, suffix = dest.stem, dest.suffix
    n = 2
    while dest.exists():
        dest = dest_dir / f"{stem}-{n}{suffix}"; n += 1
    file.save(dest)
    try:
        asset = shader_asset_from_path(dest, "upload:" + dest.name, "uploaded")
    except Exception as exc:
        try: dest.unlink()
        except OSError: pass
        return jsonify({"error": str(exc)}), 400
    LOG.info("Uploaded shader asset %s", dest.name)
    return jsonify(asset)


@app.post("/api/upload/image")
@permission_required("messages")
def upload_image_api():
    return _save_upload("images", IMAGE_EXTENSIONS)


@app.post("/api/upload/font")
@permission_required("messages")
def upload_font_api():
    return _save_upload("fonts", FONT_EXTENSIONS)


@app.get("/uploads/<kind>/<path:filename>")
@permission_required("messages")
def uploaded_file(kind: str, filename: str):
    if kind not in ("images", "fonts"):
        return "Not found", 404
    return send_from_directory(str(UPLOAD_DIR / kind), filename)


@app.post("/api/shutdown")
@permission_required("display_setup")
def shutdown_api():
    data = request.get_json(silent=True) or {}
    if str(data.get("confirm") or "").upper() != "SHUTDOWN":
        return jsonify({"error": "Shutdown confirmation was not supplied"}), 400
    LOG.warning("Remote shutdown requested from %s", request.remote_addr)
    try:
        if POWER_HELPER.is_file():
            cmd = ["sudo", "-n", str(POWER_HELPER)]
        else:
            # Standard FPP installs allow the fpp user to invoke system power
            # commands through sudo. This fallback keeps shutdown available
            # immediately after a browser upgrade from v0.2.7, before the
            # dedicated power helper is refreshed by a manual install or
            # a later browser upgrade.
            cmd = ["sudo", "-n", "/sbin/shutdown", "-h", "now"]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=5)
        return jsonify({"ok": True, "message": "Raspberry Pi is shutting down"}), 202
    except Exception as exc:
        LOG.exception("Unable to request shutdown")
        return jsonify({"error": str(exc)}), 500



@app.get("/api/upgrade/status")
@permission_required("upgrade")
def upgrade_status_api():
    status = _read_upgrade_status()
    return jsonify({
        "current_version": APP_VERSION,
        "helper_ready": UPGRADE_HELPER.is_file(),
        "status": status,
    })


@app.post("/api/upgrade")
@permission_required("upgrade")
def upgrade_api():
    # The Users permission and authenticated session gate protect executable
    # software uploads.  The privileged helper performs the actual install.
    if not UPGRADE_HELPER.is_file():
        return jsonify({"error": "The privileged upgrade helper is not installed. Run sudo ./install.sh once for this release."}), 503
    current_upgrade = _read_upgrade_status()
    if str(current_upgrade.get("state") or "").lower() in {"queued", "validating", "installing", "restarting"}:
        return jsonify({"error": "An upgrade is already in progress"}), 409
    if "file" not in request.files:
        return jsonify({"error": "Drop a Pi Matrix Signage release ZIP here"}), 400
    upload = request.files["file"]
    filename = secure_filename(upload.filename or "")
    if not filename.lower().endswith(".zip"):
        return jsonify({"error": "Upgrade packages must be ZIP files"}), 400
    UPGRADE_DIR.mkdir(parents=True, exist_ok=True)
    temp = UPGRADE_DIR / f"pending-{secrets.token_hex(6)}.zip"
    try:
        upload.save(temp)
        info = _inspect_upgrade_zip(temp)
        if _version_key(info["version"]) <= _version_key(APP_VERSION):
            return jsonify({"error": f"Release {info['version']} is not newer than installed version {APP_VERSION}"}), 400
        sha256 = hashlib.sha256(temp.read_bytes()).hexdigest()
        os.replace(temp, UPGRADE_PENDING)
        _write_upgrade_status({
            "state": "queued",
            "from_version": APP_VERSION,
            "to_version": info["version"],
            "message": "Release validated; waiting for updater",
            "sha256": sha256,
            "filename": filename,
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "completed_at": None,
            "rolled_back": False,
        })
        result = subprocess.run(["sudo", "-n", str(UPGRADE_HELPER)], text=True, capture_output=True, timeout=10)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "Unable to start privileged updater").strip())
        LOG.info("Browser upgrade queued: %s -> %s (%s)", APP_VERSION, info["version"], sha256[:12])
        return jsonify({"ok": True, "version": info["version"], "sha256": sha256, "message": "Upgrade accepted. The service will restart automatically."}), 202
    except Exception as exc:
        LOG.exception("Upgrade upload failed")
        try:
            if temp.exists(): temp.unlink()
        except OSError:
            pass
        return jsonify({"error": str(exc)}), 400



def _write_backup_status(value: dict | None = None, **updates) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    try:
        current = json.loads(BACKUP_STATUS.read_text(encoding="utf-8"))
        if isinstance(current, dict):
            data.update(current)
    except Exception:
        pass
    if value:
        data.update(value)
    data.update(updates)
    tmp = BACKUP_STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, BACKUP_STATUS)


def _sqlite_backup(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        raise RuntimeError("Pi Matrix Signage database was not found")
    with sqlite3.connect(str(src)) as source, sqlite3.connect(str(dst)) as target:
        source.backup(target)


def _fpp_backup_json(destination: Path) -> None:
    """Request FPP's supported full configuration backup."""
    form = urllib.parse.urlencode({"btnDownloadConfig": "1", "backuparea": "all"}).encode("ascii")
    req = urllib.request.Request(FPP_BACKUP_URL, data=form, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            raw = response.read()
    except Exception as exc:
        raise RuntimeError(f"Unable to obtain FPP configuration backup: {exc}") from exc
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(text)
    except Exception:
        first, last = text.find("{"), text.rfind("}")
        if first < 0 or last <= first:
            raise RuntimeError("FPP did not return a JSON configuration backup")
        try:
            payload = json.loads(text[first:last + 1])
        except Exception as exc:
            raise RuntimeError("FPP returned an invalid configuration backup") from exc
    if not isinstance(payload, dict) or "fpp_backup_version" not in payload:
        raise RuntimeError("FPP configuration backup was not recognised")
    destination.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def _add_tree_to_backup(zf: zipfile.ZipFile, source: Path, prefix: str, skip_names: set[str] | None = None) -> None:
    skip_names = skip_names or set()
    if not source.exists():
        return
    for root, dirs, files in os.walk(source):
        root_p = Path(root)
        dirs[:] = [d for d in dirs if d not in skip_names]
        for filename in files:
            src = root_p / filename
            if src.is_symlink() or src.name in skip_names:
                continue
            try:
                rel = src.relative_to(source).as_posix()
                zf.write(src, f"{prefix}/{rel}")
            except (PermissionError, FileNotFoundError) as exc:
                LOG.warning("Skipping unreadable backup item %s: %s", src, exc)


def _add_fpp_raw_snapshot(zf: zipfile.ZipFile) -> None:
    """Add FPP configuration/show-setup files as a recovery fallback."""
    media = Path("/home/fpp/media")
    for name in ("settings", "schedule", "timezone", "universes", "pixelnetDMX"):
        src = media / name
        if src.is_file() and not src.is_symlink():
            try:
                zf.write(src, f"fpp/raw-media/{name}")
            except (PermissionError, FileNotFoundError) as exc:
                LOG.warning("Skipping unreadable FPP backup item %s: %s", src, exc)
    for name in ("config", "playlists", "scripts", "events", "channelmemorymaps"):
        _add_tree_to_backup(zf, media / name, f"fpp/raw-media/{name}")


def _create_backup_archive_local(filename: str, reason: str = "manual") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    filename = _safe_backup_filename(filename)
    final = BACKUP_DIR / filename
    temp_root = BACKUP_DIR / f".build-{os.getpid()}-{time.time_ns()}"
    temp_root.mkdir(parents=True, exist_ok=True)
    tmp_zip = final.with_suffix(".tmp")
    try:
        fpp_json = temp_root / "fpp-backup.json"
        fpp_backup_error = None
        _write_backup_status(state="creating", operation="backup", filename=filename, message="Collecting FPP configuration…")
        try:
            _fpp_backup_json(fpp_json)
        except Exception as exc:
            fpp_backup_error = str(exc)
            LOG.warning("FPP official backup unavailable; using raw fallback: %s", exc)
        db_copy = temp_root / "signage.db"
        _write_backup_status(state="creating", operation="backup", filename=filename, message="Backing up Pi Matrix Signage database and media…")
        _sqlite_backup(DB_PATH, db_copy)
        manifest = {
            "product": "Pi Matrix Signage",
            "format": BACKUP_FORMAT,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "app_version": APP_VERSION,
            "reason": reason,
            "hostname": socket.gethostname(),
            "contents": {
                "pimatrix_database": True,
                "pimatrix_media": True,
                "users_and_permissions": True,
                "fpp_configuration": True,
                "fpp_sensitive_settings": True,
                "fpp_official_backup": fpp_json.is_file(),
                "fpp_raw_config_snapshot": True,
                "fpp_official_backup_error": fpp_backup_error,
            },
        }
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
            zf.write(db_copy, "pimatrix/data/signage.db")
            if DATA_DIR.exists():
                for src in DATA_DIR.iterdir():
                    if src.name in {"signage.db", "signage.db-wal", "signage.db-shm"}:
                        continue
                    if src.is_file() and not src.is_symlink():
                        zf.write(src, f"pimatrix/data/{src.name}")
                    elif src.is_dir():
                        _add_tree_to_backup(zf, src, f"pimatrix/data/{src.name}")
            _add_tree_to_backup(zf, UPLOAD_DIR, "pimatrix/uploads")
            if fpp_json.is_file():
                zf.write(fpp_json, "fpp/fpp-backup.json")
            if fpp_backup_error:
                zf.writestr("fpp/fpp-backup-error.txt", fpp_backup_error + "\n")
            _add_fpp_raw_snapshot(zf)
        os.replace(tmp_zip, final)
        return final
    finally:
        try:
            if tmp_zip.exists():
                tmp_zip.unlink()
        except OSError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def _backup_create_worker_local(filename: str) -> None:
    if not BACKUP_CREATE_LOCK.acquire(blocking=False):
        _write_backup_status(state="failed", operation="backup", message="Another backup creation is already running", completed_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        return
    try:
        _write_backup_status(state="creating", operation="backup", filename=filename, message="Creating full Pi Matrix Signage and FPP backup", started_at=datetime.now().astimezone().isoformat(timespec="seconds"), completed_at=None)
        out = _create_backup_archive_local(filename, "manual")
        _write_backup_status(state="success", operation="backup", filename=out.name, message="Backup created successfully", size=out.stat().st_size, completed_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        LOG.info("Full backup created: %s", out)
    except Exception as exc:
        LOG.exception("Backup creation failed")
        _write_backup_status(state="failed", operation="backup", filename=filename, message=str(exc), completed_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    finally:
        BACKUP_CREATE_LOCK.release()


def _safe_backup_filename(value: str) -> str:
    name = Path(str(value or "")).name
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,180}\.zip", name):
        raise ValueError("Invalid backup filename")
    return name


def _inspect_backup_archive(path: Path) -> dict:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError("The file is not a valid Pi Matrix Signage backup ZIP") from exc
    with zf:
        infos = zf.infolist()
        if not infos or len(infos) > 50000:
            raise ValueError("Backup ZIP contains an unreasonable number of files")
        names = set()
        total = 0
        for info in infos:
            raw = info.filename.rstrip("/") if info.is_dir() else info.filename
            if not raw or "\\" in raw or raw.startswith("/"):
                raise ValueError("Unsafe path in backup ZIP")
            pp = PurePosixPath(raw)
            if pp.is_absolute() or any(part in ("", ".", "..") for part in pp.parts):
                raise ValueError("Unsafe path in backup ZIP")
            total += int(info.file_size)
            if total > 8 * 1024 * 1024 * 1024:
                raise ValueError("Backup ZIP is too large when unpacked")
            names.add(str(pp))
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and stat.S_IFMT(mode) and not info.is_dir() and not stat.S_ISREG(mode):
                raise ValueError("Backup ZIP contains a non-regular file")
        required = {"manifest.json", "pimatrix/data/signage.db"}
        missing = required - names
        if missing:
            raise ValueError("Backup is incomplete; missing " + ", ".join(sorted(missing)))
        has_official_fpp = "fpp/fpp-backup.json" in names
        has_raw_fpp = "fpp/raw-media/settings" in names and any(n.startswith("fpp/raw-media/config/") for n in names)
        if not has_official_fpp and not has_raw_fpp:
            raise ValueError("Backup is incomplete; no usable FPP configuration snapshot was found")
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except Exception as exc:
            raise ValueError("Backup manifest is invalid") from exc
        if not isinstance(manifest, dict) or manifest.get("product") != "Pi Matrix Signage" or int(manifest.get("format") or 0) != BACKUP_FORMAT:
            raise ValueError("This backup format is not supported")
        manifest["uncompressed_bytes"] = total
        return manifest


def _read_backup_status() -> dict:
    try:
        value = json.loads(BACKUP_STATUS.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _backup_busy() -> bool:
    return str(_read_backup_status().get("state") or "").lower() in {"queued", "creating", "safety_backup", "restoring", "restoring_fpp"}


def _run_backup_helper(args: list[str]) -> None:
    if not UPGRADE_HELPER.is_file():
        raise RuntimeError("The privileged backup helper is not installed yet. Upgrade/install this release first.")
    result = subprocess.run(["sudo", "-n", str(UPGRADE_HELPER), *args], text=True, capture_output=True, timeout=12)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Unable to start backup/restore worker").strip())


def _backup_list() -> list[dict]:
    out = []
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(BACKUP_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            manifest = _inspect_backup_archive(path)
            out.append({
                "filename": path.name,
                "size": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                "created_at": manifest.get("created_at"),
                "app_version": manifest.get("app_version"),
                "reason": manifest.get("reason", "manual"),
                "hostname": manifest.get("hostname", ""),
                "contents": manifest.get("contents", {}),
            })
        except Exception as exc:
            out.append({"filename": path.name, "size": path.stat().st_size, "modified_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"), "invalid": True, "error": str(exc)})
    return out


@app.get("/api/backups")
@permission_required("backup")
def backups_api():
    return jsonify({"backups": _backup_list(), "status": _read_backup_status(), "helper_ready": UPGRADE_HELPER.is_file()})


@app.get("/api/backups/status")
@permission_required("backup")
def backup_status_api():
    return jsonify({"status": _read_backup_status(), "current_version": APP_VERSION, "helper_ready": UPGRADE_HELPER.is_file()})


@app.post("/api/backups/create")
@permission_required("backup")
def backup_create_api():
    if _backup_busy() or BACKUP_CREATE_LOCK.locked():
        return jsonify({"error": "A backup or restore is already in progress"}), 409
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"PiMatrixSignage-backup-{stamp}-v{APP_VERSION}.zip"
    _write_backup_status(state="queued", operation="backup", filename=filename, message="Backup queued; preparing Pi Matrix Signage and FPP data", started_at=datetime.now().astimezone().isoformat(timespec="seconds"), completed_at=None)
    threading.Thread(target=_backup_create_worker_local, args=(filename,), daemon=True, name="backup-create").start()
    return jsonify({"ok": True, "filename": filename, "message": "Backup creation started"}), 202


@app.get("/api/backups/<path:filename>/download")
@permission_required("backup")
def backup_download_api(filename: str):
    name = _safe_backup_filename(filename)
    path = BACKUP_DIR / name
    if not path.is_file():
        return jsonify({"error": "Backup not found"}), 404
    return send_from_directory(str(BACKUP_DIR), name, as_attachment=True, download_name=name)


@app.delete("/api/backups/<path:filename>")
@permission_required("backup")
def backup_delete_api(filename: str):
    if _backup_busy():
        return jsonify({"error": "Wait for the current backup/restore operation to finish"}), 409
    name = _safe_backup_filename(filename)
    path = BACKUP_DIR / name
    if not path.is_file():
        return jsonify({"error": "Backup not found"}), 404
    path.unlink()
    LOG.info("Backup %s deleted by %s", name, g.current_user.get("username"))
    return jsonify({"ok": True})


@app.post("/api/backups/<path:filename>/restore")
@permission_required("backup")
def backup_restore_existing_api(filename: str):
    if _backup_busy():
        return jsonify({"error": "A backup or restore is already in progress"}), 409
    name = _safe_backup_filename(filename)
    path = BACKUP_DIR / name
    if not path.is_file():
        return jsonify({"error": "Backup not found"}), 404
    _inspect_backup_archive(path)
    data = request.get_json(silent=True) or {}
    keep_network = bool(data.get("keep_network", True))
    keep_mode = bool(data.get("keep_mode", True))
    try:
        _run_backup_helper(["--backup-restore", name, "1" if keep_network else "0", "1" if keep_mode else "0"])
    except Exception as exc:
        LOG.exception("Unable to start privileged restore worker")
        return jsonify({"error": f"Unable to start restore helper: {exc}"}), 503
    LOG.warning("Restore of %s requested by %s", name, g.current_user.get("username"))
    return jsonify({"ok": True, "filename": name, "message": "Restore started"}), 202


@app.post("/api/backups/restore-upload")
@permission_required("backup")
def backup_restore_upload_api():
    if _backup_busy():
        return jsonify({"error": "A backup or restore is already in progress"}), 409
    if "file" not in request.files:
        return jsonify({"error": "Choose a Pi Matrix Signage backup ZIP"}), 400
    upload = request.files["file"]
    original = secure_filename(upload.filename or "backup.zip")
    if not original.lower().endswith(".zip"):
        return jsonify({"error": "Backup files must be ZIP files"}), 400
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = _safe_backup_filename(f"imported-{stamp}-{original}")
    temp = BACKUP_DIR / f".{name}.upload"
    final = BACKUP_DIR / name
    try:
        upload.save(temp)
        _inspect_backup_archive(temp)
        os.replace(temp, final)
        data_keep_network = str(request.form.get("keep_network", "1")) not in {"0", "false", "False"}
        data_keep_mode = str(request.form.get("keep_mode", "1")) not in {"0", "false", "False"}
        _run_backup_helper(["--backup-restore", name, "1" if data_keep_network else "0", "1" if data_keep_mode else "0"])
        LOG.warning("Uploaded restore %s requested by %s", name, g.current_user.get("username"))
        return jsonify({"ok": True, "filename": name, "message": "Backup uploaded and restore started"}), 202
    except Exception as exc:
        try:
            if temp.exists(): temp.unlink()
        except OSError:
            pass
        LOG.exception("Uploaded backup restore could not be started")
        return jsonify({"error": str(exc)}), 503

def _clean_username(value: str) -> str:
    username = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", username):
        raise ValueError("Username must be 1-64 characters using letters, numbers, dot, dash or underscore")
    return username


def _validate_new_password(value: str) -> str:
    password = str(value or "")
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    return password


def _user_payload(data: dict, existing: dict | None = None) -> dict:
    existing = existing or {}
    payload = {
        "username": _clean_username(data.get("username", existing.get("username", ""))),
        "display_name": str(data.get("display_name", existing.get("display_name", ""))).strip(),
        "is_active": bool(data.get("is_active", existing.get("is_active", True))),
        "must_change_password": bool(data.get("must_change_password", existing.get("must_change_password", False))),
    }
    for permission, column in PERMISSION_COLUMNS.items():
        payload[column] = bool(data.get(permission, data.get(column, existing.get(column, False))))
    return payload


@app.get("/api/users")
@permission_required("users")
def list_users_api():
    return jsonify(db.list_users())


@app.post("/api/users")
@permission_required("users")
def create_user_api():
    data = request.get_json(force=True) or {}
    payload = _user_payload(data)
    payload["password_hash"] = _hash_password(_validate_new_password(data.get("password", "")))
    # New accounts default to changing the administrator-assigned password at
    # first sign in unless explicitly disabled.
    payload["must_change_password"] = bool(data.get("must_change_password", True))
    uid = db.save_user(payload)
    user = db.get_user(uid) or {}
    return jsonify({k: v for k, v in user.items() if k != "password_hash"}), 201


@app.put("/api/users/<int:uid>")
@permission_required("users")
def update_user_api(uid: int):
    existing = db.get_user(uid)
    if not existing:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(force=True) or {}
    payload = _user_payload(data, existing)
    current_id = int(g.current_user["id"])
    if uid == current_id and not payload["is_active"]:
        return jsonify({"error": "You cannot disable the account you are currently using."}), 400
    removes_manager = bool(existing.get("is_active") and existing.get("can_users")) and not (payload["is_active"] and payload["can_users"])
    if removes_manager and db.active_user_manager_count(exclude_user_id=uid) < 1:
        return jsonify({"error": "At least one active user must retain Users permission."}), 400
    db.save_user(payload, uid)
    password = str(data.get("password") or "")
    if password:
        db.set_user_password(uid, _hash_password(_validate_new_password(password)),
                             must_change_password=bool(data.get("must_change_password", True)))
    user = db.get_user(uid)
    return jsonify({k: v for k, v in user.items() if k != "password_hash"})


@app.delete("/api/users/<int:uid>")
@permission_required("users")
def delete_user_api(uid: int):
    existing = db.get_user(uid)
    if not existing:
        return jsonify({"error": "Not found"}), 404
    if uid == int(g.current_user["id"]):
        return jsonify({"error": "You cannot delete the account you are currently using."}), 400
    if bool(existing.get("is_active") and existing.get("can_users")) and db.active_user_manager_count(exclude_user_id=uid) < 1:
        return jsonify({"error": "At least one active user must retain Users permission."}), 400
    db.delete_user(uid)
    return jsonify({"ok": True})


@app.get("/api/diagnostics")
@permission_required("display_setup")
def diagnostics_api():
    return jsonify(diagnostics.snapshot())


@app.post("/api/diagnostics/action")
@permission_required("display_setup")
def diagnostics_action_api():
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip().lower()
    if action == "restart-renderer":
        result = diagnostics.restart_renderer(f"Manual request by {g.current_user.get('username')}")
        return jsonify(result), (200 if result.get("ok") else 500)
    if action == "restart-fppd":
        result = diagnostics.restart_fppd(f"Manual request by {g.current_user.get('username')}")
        return jsonify(result), (200 if result.get("ok") else 500)
    if action == "clear-history":
        db.clear_recovery_events()
        LOG.info("Recovery history cleared by %s", g.current_user.get("username"))
        return jsonify({"ok": True, "message": "Recovery history cleared"})
    return jsonify({"error": "Unknown diagnostics action"}), 400


@app.get("/api/fpp-setup")
@permission_required("display_setup")
def fpp_setup_api():
    s = db.get_settings()
    w = int(s["panel_width"]) * int(s["panels_across"])
    h = int(s["panel_height"]) * int(s["panels_down"])
    output_type = str(s.get("panel_output_type") or "rpi_mfc")
    colorlight = output_type == "colorlight"
    interface = str(s.get("colorlight_interface") or "eth1")
    receiver_model = str(s.get("colorlight_receiver_model") or "5a-75b").upper()
    interface_path = Path("/sys/class/net") / interface
    if colorlight:
        notes = [
            "Leave FPP in Player or Remote mode; FPP 9.x no longer has a separate Bridge mode.",
            "Under Channel Inputs, enable E1.31/ArtNet/DDP input. DDP does not require a universe row.",
            f"Configure the Colorlight {receiver_model} receiver first with Colorlight LEDVISION/LEDSetting, including driver IC, scan rate and cabinet mapping, then save that configuration to the card.",
            f"Connect the receiver directly to the dedicated {interface} Ethernet interface. Do not share this interface with the normal LAN.",
            f"In FPP Channel Outputs, enable ColorLight 5A-75 and select {interface}.",
            f"Set the Colorlight output canvas to {w}x{h}, with FPP start channel 1 and the channel count shown here.",
            "The signage app continues to send DDP RGB data to FPP on localhost; FPP converts it to Colorlight Ethernet frames.",
            "If brightness control is inconsistent, update the receiver firmware and verify the saved receiver configuration with Colorlight's setup tool.",
        ]
    else:
        notes = [
            "Leave FPP in Player or Remote mode; FPP 9.x no longer has a separate Bridge mode.",
            "Under Channel Inputs, enable E1.31/ArtNet/DDP input. DDP does not require a universe row.",
            "Enable the LED Panel output and choose Hat/Cap/Cape for the rPI-MFC.",
            f"Choose the FPP single-panel definition matching {int(s['panel_width'])}x{int(s['panel_height'])} pixels and {s.get('panel_scan', '1/16')} scan.",
            "Set the FPP panel layout and each physical panel orientation to match your wiring.",
            "Use FPP start channel 1 and the channel count shown here.",
            "The signage app sends DDP RGB data to FPP on localhost.",
        ]
    return jsonify({
        "output_type": output_type,
        "output_label": f"Colorlight {receiver_model}" if colorlight else "Hanson rPI-MFC",
        "network_interface": interface if colorlight else None,
        "interface_present": interface_path.exists() if colorlight else None,
        "panels_across": int(s["panels_across"]),
        "panels_down": int(s["panels_down"]),
        "panel_size": f"{int(s['panel_width'])}x{int(s['panel_height'])}",
        "panel_scan": str(s.get("panel_scan") or "1/16"),
        "display_size": f"{w}x{h}",
        "start_channel": 1,
        "channel_count": w * h * 3,
        "ddp_port": int(s["ddp_port"]),
        "notes": notes,
    })


@app.errorhandler(ValueError)
def value_error(exc):
    return jsonify({"error": str(exc)}), 400


@app.errorhandler(413)
def too_large(_exc):
    return jsonify({"error": "Upload is too large for this device"}), 413


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PIMATRIX_PORT", "8090")))
    args = parser.parse_args()

    license_manager.start()
    engine.start()
    diagnostics.start()
    gpio_controls.start()
    LOG.info("Pi Matrix Signage v%s starting on %s:%s", APP_VERSION, args.host, args.port)

    def stop_handler(*_):
        gpio_controls.stop()
        license_manager.stop()
        diagnostics.stop()
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    try:
        app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    finally:
        gpio_controls.stop()
        license_manager.stop()
        diagnostics.stop()
        engine.stop()


if __name__ == "__main__":
    main()
