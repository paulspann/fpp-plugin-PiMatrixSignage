from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import colorsys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import random
import hashlib
from functools import lru_cache
from collections import deque
import threading
import time
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence, ImageFilter, ImageChops

from ddp import DDPSender
from shader_support import ShaderClient

LOG = logging.getLogger(__name__)

DIRECTIONS = {
    "static", "left", "right", "up", "down",
    "up-left", "up-right", "down-left", "down-right",
}


def _hex_color(value: str, default: str = "#ffffff") -> tuple[int, int, int]:
    try:
        v = (value or default).strip().lstrip("#")
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        if len(v) != 6:
            raise ValueError
        return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return _hex_color(default, "#ffffff") if value != default else (255, 255, 255)


def _token_text(text: str, now: datetime) -> str:
    replacements = {
        "{TIME}": now.strftime("%H:%M"),
        "{TIME_SECONDS}": now.strftime("%H:%M:%S"),
        "{TIME_12}": now.strftime("%I:%M %p").lstrip("0"),
        "{DATE}": now.strftime("%d/%m/%Y"),
        "{DATE_SHORT}": now.strftime("%d/%m/%y"),
        "{DATE_LONG}": now.strftime("%d %B %Y"),
        "{DAY}": now.strftime("%A"),
        "{DAY_SHORT}": now.strftime("%a"),
        "{MONTH}": now.strftime("%B"),
        "{YEAR}": now.strftime("%Y"),
        "{DATETIME}": now.strftime("%d/%m/%Y %H:%M"),
    }
    out = text or ""
    for key, value in replacements.items():
        out = out.replace(key, value)
    return out


_FONT_LIST_CACHE: dict[str, tuple[float, list[dict]]] = {}
_IMAGE_CACHE: dict[str, tuple[float, list[Image.Image], list[int]]] = {}
_VIDEO_META_CACHE: dict[str, tuple[float, dict]] = {}
_VIDEO_FRAME_CACHE: dict[tuple[str, int], Image.Image] = {}
_TEXT_LAYER_CACHE: dict[str, Image.Image] = {}
_CLOUD_POSITION_CACHE: dict[tuple, tuple[int, int, int, int]] = {}
_CLOUD_PLAYBACK_STATE: dict[tuple[str, str], tuple[float, str]] = {}
_CLOUD_CACHE_LOCK = threading.RLock()
_LIVE_DATA_CACHE: dict[str, dict] = {}
_LIVE_DATA_LOCK = threading.RLock()
_SHADER_CLIENTS: dict[str, ShaderClient] = {}
_SHADER_CLIENTS_LOCK = threading.RLock()


def _shader_client(upload_fonts_dir: str) -> ShaderClient:
    upload_root = Path(upload_fonts_dir).parent
    key = str(upload_root.resolve()) if upload_root.exists() else str(upload_root)
    with _SHADER_CLIENTS_LOCK:
        client = _SHADER_CLIENTS.get(key)
        if client is None:
            client = ShaderClient(upload_root / "shaders", Path(__file__).resolve().parent / "shaders")
            _SHADER_CLIENTS[key] = client
        return client



def list_fonts(upload_fonts_dir: str) -> list[dict]:
    # Font discovery is expensive on a Pi. Cache it and invalidate when the upload directory changes.
    upload_root = Path(upload_fonts_dir)
    try:
        stamp = upload_root.stat().st_mtime if upload_root.exists() else 0.0
    except OSError:
        stamp = 0.0
    cache_key = str(upload_root.resolve()) if upload_root.exists() else str(upload_root)
    cached = _FONT_LIST_CACHE.get(cache_key)
    if cached and cached[0] == stamp:
        return cached[1]

    candidates: list[Path] = []
    for root in (Path("/usr/share/fonts"), upload_root):
        if root.exists():
            candidates.extend(root.rglob("*.ttf"))
            candidates.extend(root.rglob("*.otf"))
    seen = set()
    out = []
    for path in sorted(candidates, key=lambda p: p.name.lower()):
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": path.stem, "path": str(path)})
    _FONT_LIST_CACHE[cache_key] = (stamp, out)
    return out


def _find_font(font_value: str, upload_fonts_dir: str) -> str | None:
    if font_value and os.path.isfile(font_value):
        return font_value
    fonts = list_fonts(upload_fonts_dir)
    if font_value:
        wanted = font_value.lower()
        for f in fonts:
            if f["name"].lower() == wanted or os.path.basename(f["path"]).lower() == wanted:
                return f["path"]
    preferred = ["DejaVuSans-Bold", "DejaVuSans", "LiberationSans-Bold", "LiberationSans"]
    for name in preferred:
        for f in fonts:
            if f["name"] == name:
                return f["path"]
    return fonts[0]["path"] if fonts else None


@lru_cache(maxsize=512)
def _load_font_path(path: str, size: int):
    return ImageFont.truetype(path, size=max(1, int(size)))


def _load_font(font_value: str, size: int, upload_fonts_dir: str):
    path = _find_font(font_value, upload_fonts_dir)
    if path:
        try:
            return _load_font_path(path, max(1, int(size)))
        except Exception:
            pass
    return ImageFont.load_default()


def _fit_font(text: str, target_w: int, target_h: int, font_value: str, upload_fonts_dir: str, stroke: int = 0):
    if not text:
        return _load_font(font_value, max(5, target_h // 2), upload_fonts_dir)
    lo, hi = 5, max(6, min(256, target_h * 3))
    probe = Image.new("RGB", (4, 4))
    draw = ImageDraw.Draw(probe)
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(font_value, mid, upload_fonts_dir)
        box = draw.multiline_textbbox((0, 0), text, font=font, spacing=max(1, mid // 8), stroke_width=stroke)
        w, h = box[2] - box[0], box[3] - box[1]
        if w <= max(1, target_w) and h <= max(1, target_h):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return _load_font(font_value, best, upload_fonts_dir)


def _load_image(path: str, elapsed: float, speed: float = 1.0, loop: bool = True) -> Image.Image | None:
    """Load static or animated images (GIF/WebP/APNG) with playback controls."""
    if not path or not os.path.isfile(path):
        return None
    try:
        stamp = os.path.getmtime(path)
        cached = _IMAGE_CACHE.get(path)
        if not cached or cached[0] != stamp:
            with Image.open(path) as src:
                frames: list[Image.Image] = []
                durations: list[int] = []
                if getattr(src, "is_animated", False) and getattr(src, "n_frames", 1) > 1:
                    for frame in ImageSequence.Iterator(src):
                        frames.append(frame.convert("RGBA").copy())
                        durations.append(max(20, int(frame.info.get("duration", src.info.get("duration", 100)))))
                else:
                    frames = [src.convert("RGBA").copy()]
                    durations = [1000]
            cached = (stamp, frames, durations)
            _IMAGE_CACHE[path] = cached
            if len(_IMAGE_CACHE) > 32:
                for key in list(_IMAGE_CACHE)[:-24]:
                    _IMAGE_CACHE.pop(key, None)
        _, frames, durations = cached
        if len(frames) == 1:
            return frames[0]
        total = max(1, sum(durations))
        t_raw = max(0, int(float(elapsed) * max(0.01, float(speed or 1.0)) * 1000))
        if loop:
            t = t_raw % total
        else:
            t = min(total - 1, t_raw)
        acc = 0
        idx = 0
        for idx, duration in enumerate(durations):
            acc += duration
            if t < acc:
                break
        return frames[idx]
    except Exception:
        LOG.exception("Unable to load image %s", path)
        return None


def _load_video_frame(path: str, elapsed: float, speed: float = 1.0, loop: bool = True) -> Image.Image | None:
    """Load one pre-decoded PNG frame from a video asset directory."""
    if not path or not os.path.isdir(path):
        return None
    try:
        meta_path = os.path.join(path, "metadata.json")
        stamp = os.path.getmtime(meta_path) if os.path.isfile(meta_path) else os.path.getmtime(path)
        cached = _VIDEO_META_CACHE.get(path)
        if not cached or cached[0] != stamp:
            meta = {}
            if os.path.isfile(meta_path):
                try:
                    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            frames = int(meta.get("frames") or len(list(Path(path).glob("frame-*.png"))))
            meta["frames"] = frames
            meta["fps"] = max(0.1, float(meta.get("fps") or 12.0))
            cached = (stamp, meta)
            _VIDEO_META_CACHE[path] = cached
        meta = cached[1]
        count = max(0, int(meta.get("frames") or 0))
        if count <= 0:
            return None
        fps = max(0.1, float(meta.get("fps") or 12.0)) * max(0.01, float(speed or 1.0))
        raw_index = max(0, int(float(elapsed) * fps))
        index = (raw_index % count) if loop else min(count - 1, raw_index)
        key = (path, index)
        frame = _VIDEO_FRAME_CACHE.get(key)
        if frame is None:
            frame_path = os.path.join(path, f"frame-{index + 1:06d}.png")
            with Image.open(frame_path) as im:
                frame = im.convert("RGBA").copy()
            _VIDEO_FRAME_CACHE[key] = frame
            if len(_VIDEO_FRAME_CACHE) > 96:
                for old in list(_VIDEO_FRAME_CACHE)[:-72]:
                    _VIDEO_FRAME_CACHE.pop(old, None)
        return frame
    except Exception:
        LOG.exception("Unable to load video frame %s", path)
        return None




def _live_fetch_async(key: str, ttl: float, fetcher, placeholder: str = "Loading…",
                      error_value: str = "Data unavailable", fetch_timeout: float = 12.0) -> str:
    """Return cached live data immediately and refresh stale values off-thread.

    Network access must never block the LED output thread.  A generation token
    plus a watchdog prevents a DNS/socket call which never returns from leaving
    a live widget stuck on ``Loading…`` forever.
    """
    now_m = time.monotonic()
    timeout_s = max(3.0, float(fetch_timeout or 12.0))
    with _LIVE_DATA_LOCK:
        entry = _LIVE_DATA_CACHE.setdefault(key, {
            "value": placeholder, "fetched": 0.0, "fetching": False, "error": "",
            "started": 0.0, "generation": 0,
        })

        # A Python DNS lookup can outlive urllib's socket timeout on some Pi/FPP
        # network configurations.  Expire an in-flight refresh from the render
        # thread rather than allowing the placeholder to persist indefinitely.
        if entry.get("fetching") and (now_m - float(entry.get("started") or now_m)) >= timeout_s:
            entry["generation"] = int(entry.get("generation") or 0) + 1
            entry["fetching"] = False
            entry["fetched"] = now_m
            entry["error"] = f"Live data request timed out after {timeout_s:g}s"
            if not entry.get("value") or entry.get("value") == placeholder:
                entry["value"] = error_value
            LOG.warning("Live data refresh timed out for %s after %.1fs", key, timeout_s)

        fetched_at = float(entry.get("fetched") or 0.0)
        # A new entry has never been fetched and must refresh immediately,
        # including during the first cache-TTL seconds after a system boot.
        stale = fetched_at <= 0.0 or (now_m - fetched_at) >= max(5.0, float(ttl or 60.0))
        if stale and not entry.get("fetching"):
            generation = int(entry.get("generation") or 0) + 1
            entry.update(fetching=True, started=now_m, generation=generation)

            def worker(my_generation=generation):
                try:
                    value = str(fetcher())
                    with _LIVE_DATA_LOCK:
                        e = _LIVE_DATA_CACHE.setdefault(key, {})
                        # Ignore a late result from a request that the watchdog
                        # has already expired and superseded.
                        if int(e.get("generation") or 0) != my_generation:
                            return
                        e.update(value=value, fetched=time.monotonic(), fetching=False,
                                 started=0.0, error="")
                except Exception as exc:
                    LOG.warning("Live data refresh failed for %s: %s", key, exc)
                    with _LIVE_DATA_LOCK:
                        e = _LIVE_DATA_CACHE.setdefault(key, {})
                        if int(e.get("generation") or 0) != my_generation:
                            return
                        # Keep a prior successful value on transient failures.
                        if not e.get("value") or e.get("value") == placeholder:
                            e["value"] = error_value
                        e.update(fetched=time.monotonic(), fetching=False, started=0.0, error=str(exc))

            threading.Thread(target=worker, name="PiMatrixLiveData", daemon=True).start()
        return str(entry.get("value") or placeholder)


def live_data_diagnostics() -> dict:
    """Small, thread-safe health summary for live widgets."""
    now_m = time.monotonic()
    with _LIVE_DATA_LOCK:
        entries = []
        for key, raw in _LIVE_DATA_CACHE.items():
            fetched = float(raw.get("fetched") or 0.0)
            started = float(raw.get("started") or 0.0)
            entries.append({
                "key": str(key),
                "fetching": bool(raw.get("fetching")),
                "age_seconds": None if fetched <= 0 else max(0.0, now_m - fetched),
                "fetch_seconds": None if not raw.get("fetching") or started <= 0 else max(0.0, now_m - started),
                "error": str(raw.get("error") or ""),
                "value": str(raw.get("value") or "")[:120],
            })
        errors = sum(1 for e in entries if e["error"])
        fetching = sum(1 for e in entries if e["fetching"])
        return {"count": len(entries), "errors": errors, "fetching": fetching, "entries": entries[-20:]}


def _http_text(url: str, timeout: float = 5.0, max_bytes: int = 1_000_000) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Live-data URL must be http:// or https://")
    req = urllib.request.Request(
        parsed.geturl(), headers={"User-Agent": "PiMatrixSignage/0.3 (+LED signage)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("Live-data response is too large")
    return raw.decode("utf-8", "replace")


def _json_path(value, path: str):
    current = value
    for part in [x for x in str(path or "").strip().split(".") if x != ""]:
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(part)
    return current


def _weather_code_label(code: int) -> str:
    # Compact WMO descriptions chosen for small LED signs.
    if code == 0: return "Clear"
    if code == 1: return "Mostly clear"
    if code == 2: return "Partly cloudy"
    if code == 3: return "Cloudy"
    if code in (45, 48): return "Fog"
    if code in (51, 53, 55, 56, 57): return "Drizzle"
    if code in (61, 63, 65, 66, 67): return "Rain"
    if code in (71, 73, 75, 77): return "Snow"
    if code in (80, 81, 82): return "Showers"
    if code in (85, 86): return "Snow showers"
    if code in (95, 96, 99): return "Thunder"
    return "Weather"


def _weather_visual_category(code: int) -> str:
    if code == 0: return "clear"
    if code in (1, 2): return "partly-cloudy"
    if code == 3: return "cloudy"
    if code in (45, 48): return "fog"
    if code in (51, 53, 55, 56, 57): return "drizzle"
    if code in (61, 63, 65, 66, 67): return "rain"
    if code in (71, 73, 75, 77): return "snow"
    if code in (80, 81, 82): return "showers"
    if code in (85, 86): return "snow-showers"
    if code in (95, 96, 99): return "thunder"
    return "cloudy"


def _wind_direction_label(value) -> str:
    try:
        deg = float(value) % 360.0
    except Exception:
        return "?"
    points = ("N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW")
    return points[int((deg + 11.25) // 22.5) % 16]


def _weather_number(value, decimals: int = 0) -> str:
    try:
        n = float(value)
        if not math.isfinite(n): raise ValueError
        if decimals <= 0: return str(int(round(n)))
        out = f"{n:.{decimals}f}"
        return out.rstrip("0").rstrip(".")
    except Exception:
        return "?"


def _weather_current(layer: dict) -> dict:
    """Return cached current weather without ever blocking the render thread."""
    lat = float(layer.get("weather_lat") or 0.0)
    lon = float(layer.get("weather_lon") or 0.0)
    refresh = max(60.0, float(layer.get("refresh_seconds") or 600.0))
    temp_unit = "fahrenheit" if str(layer.get("weather_temp_unit") or "c").lower() == "f" else "celsius"
    wind_pref = str(layer.get("weather_wind_unit") or "mph").lower()
    wind_unit = "kmh" if wind_pref in ("kmh", "km/h", "kph") else "mph"
    key = f"weather-data:{lat:.5f}:{lon:.5f}:{temp_unit}:{wind_unit}"

    def fetch():
        q = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon,
            "current": ",".join((
                "temperature_2m", "apparent_temperature", "relative_humidity_2m",
                "precipitation", "rain", "showers", "snowfall", "weather_code",
                "cloud_cover", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "is_day"
            )),
            "temperature_unit": temp_unit,
            "wind_speed_unit": wind_unit,
            "precipitation_unit": "mm",
            "timezone": "auto",
        })
        payload = json.loads(_http_text("https://api.open-meteo.com/v1/forecast?" + q))
        cur = payload.get("current") or {}
        code = int(cur.get("weather_code", -1) if cur.get("weather_code") is not None else -1)
        data = {
            "status": "ok", "code": code, "condition": _weather_code_label(code),
            "category": _weather_visual_category(code),
            "temp": cur.get("temperature_2m"), "feels": cur.get("apparent_temperature"),
            "humidity": cur.get("relative_humidity_2m"), "precip": cur.get("precipitation"),
            "rain": cur.get("rain"), "showers": cur.get("showers"), "snow": cur.get("snowfall"),
            "cloud": cur.get("cloud_cover"), "wind": cur.get("wind_speed_10m"),
            "wind_direction": cur.get("wind_direction_10m"), "gust": cur.get("wind_gusts_10m"),
            "is_day": bool(int(cur.get("is_day", 1) if cur.get("is_day") is not None else 1)),
            "temp_unit": "°F" if temp_unit == "fahrenheit" else "°C",
            "wind_unit": "km/h" if wind_unit == "kmh" else "mph",
        }
        data["wind_compass"] = _wind_direction_label(data.get("wind_direction"))
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)

    raw = _live_fetch_async(
        key, refresh, fetch,
        placeholder='{"status":"loading"}', error_value='{"status":"error"}'
    )
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"status": "error"}
    except Exception:
        return {"status": "error"}


def _weather_template_text(layer: dict, data: dict) -> str:
    status = str(data.get("status") or "error")
    if status == "loading": return "Loading…"
    if status != "ok": return "Weather unavailable"
    template = str(layer.get("weather_template") or "{TEMP}{TEMP_UNIT} {CONDITION}")
    values = {
        "TEMP": _weather_number(data.get("temp"), 1),
        "TEMP_UNIT": str(data.get("temp_unit") or "°C"),
        "FEELS": _weather_number(data.get("feels"), 1),
        "CONDITION": str(data.get("condition") or "Weather"),
        "WIND": _weather_number(data.get("wind"), 1),
        "WIND_UNIT": str(data.get("wind_unit") or "mph"),
        "WIND_DIR": str(data.get("wind_compass") or "?"),
        "WIND_DEG": _weather_number(data.get("wind_direction"), 0),
        "GUST": _weather_number(data.get("gust"), 1),
        "HUMIDITY": _weather_number(data.get("humidity"), 0),
        "PRECIP": _weather_number(data.get("precip"), 1),
        "RAIN": _weather_number(data.get("rain"), 1),
        "SHOWERS": _weather_number(data.get("showers"), 1),
        "SNOW": _weather_number(data.get("snow"), 1),
        "CLOUD": _weather_number(data.get("cloud"), 0),
        "CODE": str(data.get("code", "?")),
    }
    value = template
    for key, replacement in values.items():
        value = value.replace("{" + key + "}", replacement)
    return value


def _widget_text(layer: dict, now: datetime) -> str:
    kind = str(layer.get("widget_type") or "clock").lower()
    prefix = str(layer.get("widget_prefix") or "")
    suffix = str(layer.get("widget_suffix") or "")
    if kind == "clock":
        fmt = str(layer.get("widget_format") or "%H:%M")
        try: value = now.strftime(fmt)
        except Exception: value = now.strftime("%H:%M")
        return prefix + value + suffix
    if kind == "date":
        fmt = str(layer.get("widget_format") or "%d/%m/%Y")
        try: value = now.strftime(fmt)
        except Exception: value = now.strftime("%d/%m/%Y")
        return prefix + value + suffix
    if kind == "countdown":
        raw = str(layer.get("countdown_target") or "").strip()
        try:
            target = datetime.fromisoformat(raw)
            if target.tzinfo is None:
                target = target.replace(tzinfo=now.tzinfo)
            seconds = max(0, int((target - now).total_seconds()))
            days, rem = divmod(seconds, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, secs = divmod(rem, 60)
            template = str(layer.get("countdown_format") or "{D}d {HH}:{MM}:{SS}")
            value = (template.replace("{D}", str(days)).replace("{HH}", f"{hours:02d}")
                     .replace("{H}", str(hours)).replace("{MM}", f"{minutes:02d}")
                     .replace("{M}", str(minutes)).replace("{SS}", f"{secs:02d}")
                     .replace("{S}", str(secs)))
        except Exception:
            value = "Set countdown"
        return prefix + value + suffix
    if kind == "weather":
        return prefix + _weather_template_text(layer, _weather_current(layer)) + suffix
    if kind == "json":
        url = str(layer.get("data_url") or "").strip()
        path = str(layer.get("json_path") or "").strip()
        refresh = max(5.0, float(layer.get("refresh_seconds") or 60.0))
        if not url:
            return prefix + "Set JSON URL" + suffix
        key = f"json:{url}:{path}"
        def fetch():
            payload = json.loads(_http_text(url))
            value = _json_path(payload, path) if path else payload
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            return value
        return prefix + _live_fetch_async(key, refresh, fetch) + suffix
    if kind == "rss":
        url = str(layer.get("data_url") or "").strip()
        refresh = max(30.0, float(layer.get("refresh_seconds") or 300.0))
        item_index = max(0, int(layer.get("rss_item") or 0))
        if not url:
            return prefix + "Set RSS URL" + suffix
        key = f"rss:{url}:{item_index}"
        def fetch():
            root = ET.fromstring(_http_text(url))
            titles = []
            for item in root.findall(".//item"):
                title = item.findtext("title")
                if title: titles.append(title.strip())
            if not titles:
                # Atom feeds
                for entry in root.findall(".//{*}entry"):
                    title = entry.findtext("{*}title")
                    if title: titles.append(title.strip())
            if not titles:
                return "No feed items"
            return titles[item_index % len(titles)]
        return prefix + _live_fetch_async(key, refresh, fetch) + suffix
    return prefix + "Widget" + suffix


def _transform_text(text: str, mode: str) -> str:
    mode = str(mode or "none").lower()
    if mode == "upper": return text.upper()
    if mode == "lower": return text.lower()
    if mode == "title": return text.title()
    return text


def _live_weather_shader_params(config: dict, params: dict) -> dict:
    """Overlay Sky Weather uniforms with cached Open-Meteo conditions."""
    out = dict(params or {})
    if not bool(config.get("shader_live_weather")):
        return out
    weather_config = {
        "weather_lat": config.get("shader_weather_lat", 53.55),
        "weather_lon": config.get("shader_weather_lon", -2.52),
        "weather_temp_unit": "c",
        "weather_wind_unit": "mph",
        "refresh_seconds": config.get("shader_weather_refresh", 600),
    }
    data = _weather_current(weather_config)
    if data.get("status") != "ok":
        return out
    category = str(data.get("category") or "cloudy")
    weather_mode = {
        "clear": 0, "partly-cloudy": 1, "cloudy": 2, "fog": 2,
        "drizzle": 3, "rain": 3, "showers": 3, "snow": 4, "snow-showers": 4,
        "thunder": 5,
    }.get(category, 2)
    wind = max(0.0, float(data.get("wind") or 0.0))
    wind_degrees = float(data.get("wind_direction") or 0.0) % 360.0
    cloud = max(0.0, min(100.0, float(data.get("cloud") or 0.0))) / 100.0
    precip = max(0.0, float(data.get("precip") or 0.0))
    out.update({
        "Weather": weather_mode,
        "SkyPhase": 0 if bool(data.get("is_day", True)) else 2,
        "CloudCover": cloud,
        "Speed": max(0.05, min(4.0, 0.05 + wind / 8.0)),
        "WindDirection": 0 if 180.0 <= wind_degrees < 360.0 else 1,
        "PrecipIntensity": max(0.0, min(1.0, precip / 5.0)) if weather_mode < 3 else max(0.25, min(1.0, precip / 5.0)),
    })
    return out


def _random_reveal_text(layer: dict, text: str, elapsed: float) -> str:
    """Reveal characters in-place in a stable random order over effect_period seconds."""
    delay = max(0.0, float(layer.get("delay", 0) or 0))
    local = max(0.0, float(elapsed) - delay)
    duration = max(0.1, float(layer.get("effect_period", 1.0) or 1.0))
    if local >= duration:
        return text
    revealable = [i for i, ch in enumerate(text) if ch not in ("\r", "\n") and not ch.isspace()]
    if not revealable:
        return text
    visible = int((local / duration) * len(revealable))
    if visible <= 0:
        revealed = set()
    elif visible >= len(revealable):
        return text
    else:
        seed = f"{layer.get('id','')}|{layer.get('name','')}|{text}"
        order = revealable[:]
        random.Random(seed).shuffle(order)
        revealed = set(order[:visible])
    chars = []
    for i, ch in enumerate(text):
        if ch in ("\r", "\n") or ch.isspace() or i in revealed:
            chars.append(ch)
        else:
            chars.append(" ")
    return "".join(chars)


def _sequenced_text_layer(layer: dict, elapsed: float, scene_duration: float) -> tuple[dict, float]:
    """Select one explicit non-empty text line for this point on the scene timeline.

    The sequence spans the layer's usable time: after its Start delay and, when
    configured, up to Exit after.  Child text animations receive time relative
    to the selected slot so typewriter/random-reveal/split-flap restart for each
    new line. Existing multiline layers remain unchanged unless line_display is
    explicitly set to ``sequence``.
    """
    if str(layer.get("type") or "text") != "text" or str(layer.get("line_display") or "together") != "sequence":
        return layer, elapsed
    raw = str(layer.get("text") or "")
    lines = [line for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    if len(lines) <= 1:
        return layer, elapsed
    delay = max(0.0, float(layer.get("delay", 0) or 0))
    usable = max(0.001, float(scene_duration) - delay)
    exit_after = max(0.0, float(layer.get("exit_after", 0) or 0))
    if exit_after > 0:
        usable = max(0.001, min(usable, exit_after))
    local = max(0.0, float(elapsed) - delay)
    slot = usable / len(lines)
    index = min(len(lines) - 1, max(0, int(local / max(0.001, slot))))
    slot_elapsed = max(0.0, local - index * slot)
    child = dict(layer)
    child["text"] = lines[index]
    child["delay"] = 0
    child["_line_sequence_index"] = index
    child["_line_sequence_count"] = len(lines)
    child["_line_sequence_slot"] = slot
    # Keep the complete sequence context on the transient child.  The split-flap
    # renderer uses this to model one fixed bank of physical character cells: a
    # new line starts from the previous line instead of appearing from nowhere,
    # and cells no longer used by the new line can genuinely flap to blank.
    child["_line_sequence_lines"] = lines
    child["_line_sequence_previous_text"] = lines[index - 1] if index > 0 else ""
    return child, slot_elapsed


def _layer_text_value(layer: dict, now: datetime, elapsed: float) -> str:
    if str(layer.get("type") or "text") == "widget":
        text = _widget_text(layer, now)
    else:
        text = _token_text(str(layer.get("text") or ""), now)
    text = _transform_text(text, str(layer.get("text_transform") or "none"))
    animation = str(layer.get("animation") or "static")
    if animation == "typewriter":
        delay = max(0.0, float(layer.get("delay", 0) or 0))
        local = max(0.0, float(elapsed) - delay)
        cps = max(0.1, float(layer.get("typewriter_speed", 12) or 12))
        text = text[:max(0, int(local * cps))]
    elif animation == "random-reveal":
        text = _random_reveal_text(layer, text, elapsed)
    return text


def _contain(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    if size[0] <= 0 or size[1] <= 0:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    copy = im.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    return copy


def _cover(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(im, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _align_pos(container: int, item: int, mode: str, pad: int) -> int:
    if mode in ("left", "top"):
        return pad
    if mode in ("right", "bottom"):
        return container - item - pad
    return (container - item) // 2



@lru_cache(maxsize=64)
def _gradient_background_cached(width: int, height: int, mode: str, c1: tuple[int, int, int], c2: tuple[int, int, int]) -> Image.Image:
    """Small-matrix-friendly two-colour gradient, cached because it is normally static."""
    im = Image.new("RGB", (width, height), c1)
    px = im.load()
    horizontal = mode == "gradient-h"
    span = max(1, (width - 1) if horizontal else (height - 1))
    for y in range(height):
        for x in range(width):
            pos = x if horizontal else y
            t = pos / span
            px[x, y] = tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))
    return im


def _gradient_background(width: int, height: int, mode: str, c1: tuple[int, int, int], c2: tuple[int, int, int]) -> Image.Image:
    return _gradient_background_cached(width, height, mode, c1, c2).copy()


def _wrap_text_pixels(text: str, font, max_width: int, draw: ImageDraw.ImageDraw, stroke: int = 0,
                      break_long_words: bool = True) -> str:
    """Wrap text by rendered pixel width while preserving explicit newlines."""
    max_width = max(1, int(max_width))
    paragraphs = str(text or "").split("\n")
    out: list[str] = []
    for paragraph in paragraphs:
        if paragraph == "":
            out.append("")
            continue
        words = paragraph.split(" ")
        line = ""
        for word in words:
            trial = word if not line else f"{line} {word}"
            box = draw.textbbox((0, 0), trial or " ", font=font, stroke_width=stroke)
            if box[2] - box[0] <= max_width:
                line = trial
                continue
            if line:
                out.append(line)
                line = ""
            if not break_long_words:
                line = word
                continue
            # Normal text layers may split a single over-wide word to avoid clipping.
            chunk = ""
            for ch in word:
                trial_chunk = chunk + ch
                cb = draw.textbbox((0, 0), trial_chunk, font=font, stroke_width=stroke)
                if chunk and cb[2] - cb[0] > max_width:
                    out.append(chunk)
                    chunk = ch
                else:
                    chunk = trial_chunk
            line = chunk
        out.append(line)
    return "\n".join(out)


def _text_metrics(text: str, font, width: int, wrap: bool, align: str, spacing: int, stroke: int,
                  break_long_words: bool = True):
    probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    laid_out = _wrap_text_pixels(text, font, width, draw, stroke, break_long_words) if wrap else text
    raw = draw.multiline_textbbox((0, 0), laid_out or " ", font=font, spacing=spacing, align=align, stroke_width=stroke)
    box = (math.floor(raw[0]), math.floor(raw[1]), math.ceil(raw[2]), math.ceil(raw[3]))
    return laid_out, box


def _fit_layer_font(text: str, target_w: int, target_h: int, font_value: str, upload_fonts_dir: str,
                    wrap: bool, align: str, spacing_ratio: float, stroke: int, max_size: int = 512,
                    break_long_words: bool = True):
    minimum = 4 if break_long_words else 1
    lo, hi, best = minimum, max(minimum + 1, min(max_size, max(target_h * 4, 16))), minimum
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(font_value, mid, upload_fonts_dir)
        spacing = max(0, int(round(mid * spacing_ratio)))
        _, box = _text_metrics(text, font, target_w, wrap, align, spacing, stroke, break_long_words)
        if box[2] - box[0] <= target_w and box[3] - box[1] <= target_h:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return _load_font(font_value, best, upload_fonts_dir), best




# Built-in 5x7 LED alphabet. It is stored as pixel patterns in the application
# rather than as an external font file, so it is always available on FPP.
_LED5X7 = {
    " ": ("00000",)*7,
    "A": ("01110","10001","10001","11111","10001","10001","10001"),
    "B": ("11110","10001","10001","11110","10001","10001","11110"),
    "C": ("01111","10000","10000","10000","10000","10000","01111"),
    "D": ("11110","10001","10001","10001","10001","10001","11110"),
    "E": ("11111","10000","10000","11110","10000","10000","11111"),
    "F": ("11111","10000","10000","11110","10000","10000","10000"),
    "G": ("01111","10000","10000","10111","10001","10001","01111"),
    "H": ("10001","10001","10001","11111","10001","10001","10001"),
    "I": ("11111","00100","00100","00100","00100","00100","11111"),
    "J": ("00111","00010","00010","00010","10010","10010","01100"),
    "K": ("10001","10010","10100","11000","10100","10010","10001"),
    "L": ("10000","10000","10000","10000","10000","10000","11111"),
    "M": ("10001","11011","10101","10101","10001","10001","10001"),
    "N": ("10001","11001","10101","10011","10001","10001","10001"),
    "O": ("01110","10001","10001","10001","10001","10001","01110"),
    "P": ("11110","10001","10001","11110","10000","10000","10000"),
    "Q": ("01110","10001","10001","10001","10101","10010","01101"),
    "R": ("11110","10001","10001","11110","10100","10010","10001"),
    "S": ("01111","10000","10000","01110","00001","00001","11110"),
    "T": ("11111","00100","00100","00100","00100","00100","00100"),
    "U": ("10001","10001","10001","10001","10001","10001","01110"),
    "V": ("10001","10001","10001","10001","10001","01010","00100"),
    "W": ("10001","10001","10001","10101","10101","10101","01010"),
    "X": ("10001","10001","01010","00100","01010","10001","10001"),
    "Y": ("10001","10001","01010","00100","00100","00100","00100"),
    "Z": ("11111","00001","00010","00100","01000","10000","11111"),
    "0": ("01110","10001","10011","10101","11001","10001","01110"),
    "1": ("00100","01100","00100","00100","00100","00100","01110"),
    "2": ("01110","10001","00001","00010","00100","01000","11111"),
    "3": ("11110","00001","00001","01110","00001","00001","11110"),
    "4": ("00010","00110","01010","10010","11111","00010","00010"),
    "5": ("11111","10000","10000","11110","00001","00001","11110"),
    "6": ("01110","10000","10000","11110","10001","10001","01110"),
    "7": ("11111","00001","00010","00100","01000","01000","01000"),
    "8": ("01110","10001","10001","01110","10001","10001","01110"),
    "9": ("01110","10001","10001","01111","00001","00001","01110"),
    ".": ("00000","00000","00000","00000","00000","00110","00110"),
    ",": ("00000","00000","00000","00000","00110","00110","00100"),
    ":": ("00000","00110","00110","00000","00110","00110","00000"),
    ";": ("00000","00110","00110","00000","00110","00110","00100"),
    "!": ("00100","00100","00100","00100","00100","00000","00100"),
    "?": ("01110","10001","00001","00010","00100","00000","00100"),
    "-": ("00000","00000","00000","11111","00000","00000","00000"),
    "_": ("00000","00000","00000","00000","00000","00000","11111"),
    "/": ("00001","00010","00010","00100","01000","01000","10000"),
    "\\": ("10000","01000","01000","00100","00010","00010","00001"),
    "(": ("00010","00100","01000","01000","01000","00100","00010"),
    ")": ("01000","00100","00010","00010","00010","00100","01000"),
    "[": ("01110","01000","01000","01000","01000","01000","01110"),
    "]": ("01110","00010","00010","00010","00010","00010","01110"),
    "+": ("00000","00100","00100","11111","00100","00100","00000"),
    "=": ("00000","11111","00000","11111","00000","00000","00000"),
    "*": ("00000","10101","01110","11111","01110","10101","00000"),
    "#": ("01010","01010","11111","01010","11111","01010","01010"),
    "%": ("11001","11010","00100","01000","10110","00110","00000"),
    "&": ("01100","10010","10100","01000","10101","10010","01101"),
    "@": ("01110","10001","10111","10101","10111","10000","01110"),
    "'": ("00100","00100","00000","00000","00000","00000","00000"),
    '"': ("01010","01010","00000","00000","00000","00000","00000"),
    "£": ("00110","01001","01000","11100","01000","01000","11111"),
    "°": ("01100","10010","01100","00000","00000","00000","00000"),
}


def _pixel_sharpen_rgba(im: Image.Image, grid: int = 1, bold: bool = False) -> Image.Image:
    """Remove anti-aliased edge pixels and optionally coarsen to larger square pixels."""
    work = im.convert("RGBA")
    if bold:
        thick = Image.new("RGBA", work.size, (0, 0, 0, 0))
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            thick.alpha_composite(work, (dx, dy))
        work = thick
    alpha = work.getchannel("A").point(lambda value: 255 if value >= 112 else 0)
    work.putalpha(alpha)
    grid = max(1, min(8, int(grid or 1)))
    if grid > 1:
        sw = max(1, math.ceil(work.width / grid))
        sh = max(1, math.ceil(work.height / grid))
        small = work.resize((sw, sh), Image.Resampling.NEAREST)
        work = small.resize((work.width, work.height), Image.Resampling.NEAREST)
        alpha = work.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
        work.putalpha(alpha)
    return work


def _render_ttf_sprite(text: str, font, fill: tuple[int, int, int], outline: tuple[int, int, int],
                       stroke: int, spacing: int, align: str, render_mode: str = "smooth",
                       pixel_scale: int = 1, pixel_bold: bool = False, letter_spacing: int = 0) -> Image.Image:
    """Render a tight RGBA text sprite, optionally with hard pixel edges and tracking."""
    text = text or " "
    letter_spacing = max(0, min(8, int(letter_spacing or 0)))
    probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(probe)
    if letter_spacing == 0:
        raw = pdraw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align=align, stroke_width=stroke)
        box = (math.floor(raw[0]), math.floor(raw[1]), math.ceil(raw[2]), math.ceil(raw[3]))
        im = Image.new("RGBA", (max(1, box[2]-box[0]), max(1, box[3]-box[1])), (0, 0, 0, 0))
        ImageDraw.Draw(im).multiline_text((-box[0], -box[1]), text, font=font, fill=(*fill,255),
                                          spacing=spacing, align=align, stroke_width=stroke,
                                          stroke_fill=(*outline,255))
    else:
        lines = text.split("\n") or [""]
        rendered = []
        max_w = 1
        for line in lines:
            sample = line or " "
            lb = pdraw.textbbox((0, 0), sample, font=font, stroke_width=stroke)
            line_h = max(1, math.ceil(lb[3]) - math.floor(lb[1]))
            advances = [max(1, int(math.ceil(pdraw.textlength(ch, font=font)))) for ch in sample]
            line_w = max(1, sum(advances) + letter_spacing * max(0, len(sample)-1) + stroke * 2 + 2)
            lim = Image.new("RGBA", (line_w, line_h), (0,0,0,0))
            ld = ImageDraw.Draw(lim)
            x = stroke + 1
            baseline_y = -math.floor(lb[1])
            for ch, adv in zip(sample, advances):
                ld.text((x, baseline_y), ch, font=font, fill=(*fill,255), stroke_width=stroke,
                        stroke_fill=(*outline,255))
                x += adv + letter_spacing
            rendered.append(lim)
            max_w = max(max_w, lim.width)
        total_h = sum(x.height for x in rendered) + spacing * max(0, len(rendered)-1)
        im = Image.new("RGBA", (max_w, max(1,total_h)), (0,0,0,0))
        y = 0
        for line_im in rendered:
            if align == "right": x = max_w - line_im.width
            elif align == "center": x = (max_w - line_im.width)//2
            else: x = 0
            im.alpha_composite(line_im, (x,y)); y += line_im.height + spacing
    if render_mode == "pixel":
        im = _pixel_sharpen_rgba(im, pixel_scale, pixel_bold)
    return im


# A genuinely compact 3x5 face used by the small LED modes.  Keeping an
# independent glyph table avoids the fuzzy/awkward look that comes from merely
# squeezing the 5x7 alphabet down to a different aspect ratio.
_LED3X5 = {
    " ": ("000","000","000","000","000"),
    "A": ("010","101","111","101","101"), "B": ("110","101","110","101","110"),
    "C": ("011","100","100","100","011"), "D": ("110","101","101","101","110"),
    "E": ("111","100","110","100","111"), "F": ("111","100","110","100","100"),
    "G": ("011","100","101","101","011"), "H": ("101","101","111","101","101"),
    "I": ("111","010","010","010","111"), "J": ("001","001","001","101","010"),
    "K": ("101","101","110","101","101"), "L": ("100","100","100","100","111"),
    "M": ("101","111","111","101","101"), "N": ("101","111","111","111","101"),
    "O": ("010","101","101","101","010"), "P": ("110","101","110","100","100"),
    "Q": ("010","101","101","011","001"), "R": ("110","101","110","101","101"),
    "S": ("011","100","010","001","110"), "T": ("111","010","010","010","010"),
    "U": ("101","101","101","101","111"), "V": ("101","101","101","101","010"),
    "W": ("101","101","111","111","101"), "X": ("101","101","010","101","101"),
    "Y": ("101","101","010","010","010"), "Z": ("111","001","010","100","111"),
    "0": ("111","101","101","101","111"), "1": ("010","110","010","010","111"),
    "2": ("110","001","010","100","111"), "3": ("110","001","010","001","110"),
    "4": ("101","101","111","001","001"), "5": ("111","100","110","001","110"),
    "6": ("011","100","111","101","111"), "7": ("111","001","010","010","010"),
    "8": ("111","101","111","101","111"), "9": ("111","101","111","001","110"),
    ".": ("000","000","000","000","010"), ",": ("000","000","000","010","100"),
    ":": ("000","010","000","010","000"), ";": ("000","010","000","010","100"),
    "-": ("000","000","111","000","000"), "+": ("000","010","111","010","000"),
    "/": ("001","001","010","100","100"), "\\": ("100","100","010","001","001"),
    "!": ("010","010","010","000","010"), "?": ("110","001","010","000","010"),
    "'": ("010","010","000","000","000"), '"': ("101","101","000","000","000"),
    "(": ("001","010","010","010","001"), ")": ("100","010","010","010","100"),
    "=": ("000","111","000","111","000"), "_": ("000","000","000","000","111"),
    "%": ("101","001","010","100","101"), "£": ("011","010","111","010","111"),
    "?": ("110","001","010","000","010"),
}


def _led_pattern(ch: str) -> tuple[str, ...]:
    if ch in _LED5X7:
        return _LED5X7[ch]
    up = ch.upper()
    return _LED5X7.get(up, _LED5X7["?"])


def _led3_pattern(ch: str) -> tuple[str, ...]:
    if ch in _LED3X5:
        return _LED3X5[ch]
    return _LED3X5.get(ch.upper(), _LED3X5["?"])


def _seven_segment_pattern(ch: str) -> tuple[str, ...]:
    """Return a true 5x7 seven-segment glyph for digits/clock punctuation."""
    segs = {
        "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
        "5": "acdfg", "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg",
        "-": "g", " ": "",
    }
    if ch == ":":
        return ("00000","00100","00100","00000","00100","00100","00000")
    if ch == ".":
        return ("00000","00000","00000","00000","00000","00100","00100")
    active = set(segs.get(ch, ""))
    grid = [["0"]*5 for _ in range(7)]
    def h(y):
        for x in range(1,4): grid[y][x] = "1"
    def v(x,y0,y1):
        for y in range(y0,y1+1): grid[y][x] = "1"
    if "a" in active: h(0)
    if "g" in active: h(3)
    if "d" in active: h(6)
    if "f" in active: v(0,1,2)
    if "b" in active: v(4,1,2)
    if "e" in active: v(0,4,5)
    if "c" in active: v(4,4,5)
    if ch not in segs and ch not in ":.":
        return _led_pattern(ch)
    return tuple("".join(row) for row in grid)


def _led_wrap(text: str, max_chars: int, break_long_words: bool = True) -> str:
    if max_chars <= 0:
        return text
    out: list[str] = []
    for paragraph in (text or "").split("\n"):
        if not paragraph:
            out.append(""); continue
        words = paragraph.split(" ")
        line = ""
        for word in words:
            trial = word if not line else f"{line} {word}"
            if len(trial) <= max_chars:
                line = trial
            else:
                if line: out.append(line)
                while break_long_words and len(word) > max_chars:
                    out.append(word[:max_chars]); word = word[max_chars:]
                line = word
        out.append(line)
    return "\n".join(out)


def _led_dimensions(text: str, scale: int, letter_spacing: int, bold: bool, line_gap: int = 1) -> tuple[int,int]:
    lines = (text or " ").split("\n")
    gap = max(0, 1 + letter_spacing)
    glyph_w = 5 + (1 if bold else 0)
    widths = []
    for line in lines:
        n = max(1, len(line))
        widths.append((n * glyph_w + max(0,n-1)*gap) * scale)
    h = (len(lines)*7 + max(0,len(lines)-1)*line_gap) * scale
    return max(1,max(widths, default=1)), max(1,h)


def _render_led5x7_sprite(text: str, max_w: int, max_h: int, color: tuple[int,int,int],
                          outline: tuple[int,int,int], stroke: int, scale: int, auto_fit: bool,
                          wrap: bool, align: str, pixel_bold: bool, letter_spacing: int,
                          line_gap: int = 1) -> Image.Image:
    max_w, max_h = max(1,int(max_w)), max(1,int(max_h))
    letter_spacing = max(0,min(8,int(letter_spacing or 0)))
    requested = max(1,min(8,int(scale or 1)))
    candidates = range(8,0,-1) if auto_fit else (requested,)
    chosen_text, chosen_scale = text or " ", requested
    for sc in candidates:
        glyph_w = 5 + (1 if pixel_bold else 0)
        per_char = (glyph_w + 1 + letter_spacing) * sc
        chars = max(1, (max_w + sc*(1+letter_spacing)) // max(1,per_char))
        laid = _led_wrap(text or " ", chars) if wrap else (text or " ")
        w,h = _led_dimensions(laid, sc, letter_spacing, pixel_bold, line_gap)
        if (not auto_fit) or (w <= max_w and h <= max_h):
            chosen_text, chosen_scale = laid, sc
            break
    w,h = _led_dimensions(chosen_text, chosen_scale, letter_spacing, pixel_bold, line_gap)
    mask = Image.new("L", (w,h), 0)
    md = ImageDraw.Draw(mask)
    glyph_w = 5 + (1 if pixel_bold else 0)
    gap = max(0,1+letter_spacing)
    lines = chosen_text.split("\n")
    y_cell = 0
    for line in lines:
        line_w = (max(1,len(line))*glyph_w + max(0,len(line)-1)*gap) * chosen_scale
        if align == "right": x0 = w-line_w
        elif align == "center": x0 = (w-line_w)//2
        else: x0 = 0
        x_cell = x0 // chosen_scale
        for ch in (line or " "):
            pat = _led_pattern(ch)
            for gy,row in enumerate(pat):
                for gx,on in enumerate(row):
                    if on == "1":
                        for bx in range(1 + (1 if pixel_bold else 0)):
                            xx=(x_cell+gx+bx)*chosen_scale; yy=(y_cell+gy)*chosen_scale
                            md.rectangle((xx,yy,xx+chosen_scale-1,yy+chosen_scale-1), fill=255)
            x_cell += glyph_w + gap
        y_cell += 7 + line_gap
    out = Image.new("RGBA", mask.size, (0,0,0,0))
    if stroke > 0:
        radius=max(1,int(stroke)); size=radius*2+1
        om = mask.filter(ImageFilter.MaxFilter(size))
        ol = Image.new("RGBA", mask.size, (*outline,255)); out.alpha_composite(Image.composite(ol, Image.new("RGBA",mask.size,(0,0,0,0)), om))
    fg=Image.new("RGBA",mask.size,(*color,255)); out.alpha_composite(Image.composite(fg,Image.new("RGBA",mask.size,(0,0,0,0)),mask))
    return out



_LED_FONT_SPECS = {
    "led3x5": (3, 5, "3x5"),
    "led4x6": (4, 6, "3x5"),
    "led5x7": (5, 7, "5x7"),
    "led6x8": (6, 8, "5x7"),
    "led7x9": (7, 9, "5x7"),
    "led8x8": (8, 8, "5x7"),
    "led8x12": (8, 12, "5x7"),
    "led8x16": (8, 16, "5x7"),
    "led-condensed": (3, 7, "3x5"),
    "led-bold": (6, 8, "5x7"),
    "led-digital": (5, 7, "seven"),
    "led-scoreboard": (7, 9, "seven"),
    "led-dot": (5, 7, "5x7"),
}


def _is_led_mode(mode: str) -> bool:
    return str(mode or "").lower() in _LED_FONT_SPECS


def _is_crisp_mode(mode: str) -> bool:
    return str(mode or "").lower() == "pixel" or _is_led_mode(mode)


def _glyph_for_led_mode(ch: str, source: str) -> tuple[str, ...]:
    if source == "3x5": return _led3_pattern(ch)
    if source == "seven": return _seven_segment_pattern(ch)
    return _led_pattern(ch)


def _scale_pattern(pattern: tuple[str, ...], target_w: int, target_h: int) -> tuple[str, ...]:
    src_h=max(1,len(pattern)); src_w=max(1,max((len(r) for r in pattern), default=1))
    rows=[]
    for ty in range(target_h):
        sy=min(src_h-1,int(ty*src_h/target_h)); row=[]
        for tx in range(target_w):
            sx=min(src_w-1,int(tx*src_w/target_w)); rr=pattern[sy]
            row.append("1" if sx < len(rr) and rr[sx] == "1" else "0")
        rows.append("".join(row))
    return tuple(rows)


def _render_led_sprite(text: str, max_w: int, max_h: int, color: tuple[int, int, int],
                       outline: tuple[int, int, int], stroke: int, scale: int, auto_fit: bool,
                       wrap: bool, align: str, pixel_bold: bool, letter_spacing: int,
                       line_gap: int, mode: str = "led5x7", break_long_words: bool = True) -> Image.Image:
    """Render the embedded LED font family directly onto an integer LED grid.

    v0.4 uses independent compact and seven-segment source alphabets rather than
    just stretching the 5x7 sprite.  Every output pixel is fully on/off before
    colouring, so these faces stay razor-sharp on P5/P10 matrices.
    """
    mode=str(mode or "led5x7").lower(); gw,gh,source=_LED_FONT_SPECS.get(mode,(5,7,"5x7"))
    bold=bool(pixel_bold or mode=="led-bold")
    max_w,max_h=max(1,int(max_w)),max(1,int(max_h)); letter_spacing=max(0,min(8,int(letter_spacing or 0)))
    requested=max(1,min(8,int(scale or 1)))

    def layout(sc:int):
        char_gap=max(1,1+letter_spacing)
        cell_w=gw+(1 if bold else 0)
        per=(cell_w+char_gap)*sc
        max_chars=max(1,(max_w+char_gap*sc)//max(1,per))
        laid=_led_wrap(text or " ",max_chars,break_long_words) if wrap else (text or " ")
        lines=laid.split("\n")
        widths=[]
        for line in lines:
            n=max(1,len(line)); widths.append((n*cell_w+max(0,n-1)*char_gap)*sc)
        hh=(len(lines)*gh+max(0,len(lines)-1)*max(0,line_gap))*sc
        return laid,max(1,max(widths,default=1)),max(1,hh)

    chosen=requested; laid,w,h=layout(chosen)
    if auto_fit:
        for sc in range(8,0,-1):
            trial,tw,th=layout(sc)
            if tw<=max_w and th<=max_h:
                chosen,laid,w,h=sc,trial,tw,th;break

    mask=Image.new("L",(w,h),0); md=ImageDraw.Draw(mask); gap=max(1,1+letter_spacing)
    ycell=0
    for line in laid.split("\n"):
        cell_w=gw+(1 if bold else 0); line_w=(max(1,len(line))*cell_w+max(0,len(line)-1)*gap)*chosen
        xcell=(w-line_w)//chosen if align=="right" else ((w-line_w)//2//chosen if align=="center" else 0)
        for ch in (line or " "):
            pat=_scale_pattern(_glyph_for_led_mode(ch,source),gw,gh)
            for gy,row in enumerate(pat):
                for gx,on in enumerate(row):
                    if on=="1":
                        xx=(xcell+gx)*chosen; yy=(ycell+gy)*chosen
                        md.rectangle((xx,yy,xx+chosen-1,yy+chosen-1),fill=255)
                        if bold:
                            bx=xx+chosen
                            if bx<w: md.rectangle((bx,yy,bx+chosen-1,yy+chosen-1),fill=255)
            xcell += cell_w+gap
        ycell += gh+max(0,line_gap)
    out=Image.new("RGBA",mask.size,(0,0,0,0))
    if stroke>0:
        radius=max(1,int(stroke)); om=mask.filter(ImageFilter.MaxFilter(radius*2+1))
        ol=Image.new("RGBA",mask.size,(*outline,255)); out.alpha_composite(Image.composite(ol,Image.new("RGBA",mask.size,(0,0,0,0)),om))
    fg=Image.new("RGBA",mask.size,(*color,255)); out.alpha_composite(Image.composite(fg,Image.new("RGBA",mask.size,(0,0,0,0)),mask))
    return out


def _word_colour_ranges(alpha: Image.Image, text: str) -> list[tuple[int, int, int]]:
    """Map laid-out words to their real ink spans instead of equal-width slices."""
    w, h = alpha.size
    pixels = alpha.load()
    active_rows = [any(pixels[x, y] > 0 for x in range(w)) for y in range(h)]
    text_lines = [line for line in str(text or "").split("\n") if line.strip()]
    ink_rows = [y for y, active in enumerate(active_rows) if active]
    if not ink_rows:
        return []
    first_row, last_row = ink_rows[0], ink_rows[-1] + 1
    vertical_gaps = []
    gap_start = None
    for y in range(first_row, last_row + 1):
        blank = y == last_row or not active_rows[y]
        if blank and gap_start is None:
            gap_start = y
        elif not blank and gap_start is not None:
            vertical_gaps.append((gap_start, y)); gap_start = None
    line_cuts = sorted(
        ((a + b) // 2 for a, b in sorted(vertical_gaps, key=lambda gap: gap[1] - gap[0], reverse=True)[:max(0, len(text_lines) - 1)])
    )
    row_boundaries = [first_row, *line_cuts, last_row]
    row_bands = list(zip(row_boundaries, row_boundaries[1:]))
    ranges = []
    palette_index = 0
    for band_index, (top, bottom) in enumerate(row_bands):
        line = text_lines[band_index] if band_index < len(text_lines) else ""
        word_count = max(1, len(re.findall(r"\S+", line)))
        active_cols = [any(pixels[x, y] > 0 for y in range(top, bottom)) for x in range(w)]
        ink = [x for x, active in enumerate(active_cols) if active]
        if not ink:
            continue
        first, last = ink[0], ink[-1] + 1
        gaps = []
        gap_start = None
        for x in range(first, last + 1):
            blank = x == last or not active_cols[x]
            if blank and gap_start is None:
                gap_start = x
            elif not blank and gap_start is not None:
                gaps.append((gap_start, x)); gap_start = None
        separators = sorted(gaps, key=lambda gap: (gap[1] - gap[0], -gap[0]), reverse=True)[:max(0, word_count - 1)]
        cuts = sorted((a + b) // 2 for a, b in separators)
        boundaries = [first, *cuts, last]
        for index in range(len(boundaries) - 1):
            ranges.append((boundaries[index], boundaries[index + 1], palette_index))
            palette_index += 1
    return ranges


def _apply_sprite_color_effect(sprite: Image.Image, layer: dict, elapsed: float,
                               laid_out_text: str | None = None) -> Image.Image:
    mode = str(layer.get("color_effect") or "none").lower()
    if mode == "none":
        return sprite
    work = sprite.convert("RGBA").copy()
    alpha = work.getchannel("A")
    w, h = work.size
    c1 = _hex_color(str(layer.get("color") or "#ffffff"), "#ffffff")
    c2 = _hex_color(str(layer.get("color2") or "#00ffff"), "#00ffff")
    speed = float(layer.get("color_speed", 0.15) or 0.15)
    rgb = Image.new("RGB", (w, h), c1)
    px = rgb.load()
    if mode == "gradient":
        span = max(1, w - 1)
        for x in range(w):
            t = x / span
            col = tuple(int(round(a + (b-a)*t)) for a,b in zip(c1,c2))
            for y in range(h): px[x,y] = col
    elif mode == "wave":
        # A moving two-colour sine wave remains legible on very small matrices
        # because it changes colour without moving the glyph geometry.
        span = max(1, w - 1)
        phase = elapsed * speed * math.tau
        for x in range(w):
            t = 0.5 + 0.5 * math.sin((x / span) * math.tau * 1.35 - phase)
            col = tuple(int(round(a + (b-a)*t)) for a,b in zip(c1,c2))
            for y in range(h): px[x,y] = col
    elif mode in ("rainbow", "cycle", "wave"):
        base_hue = (elapsed * speed) % 1.0
        if mode == "cycle":
            r,g,b = (v/255 for v in c1)
            h0,s0,v0 = colorsys.rgb_to_hsv(r,g,b)
            rr,gg,bb = colorsys.hsv_to_rgb((h0+base_hue)%1.0, max(.55,s0), max(.3,v0))
            col = (int(rr*255),int(gg*255),int(bb*255))
            rgb.paste(col, (0,0,w,h))
        else:
            span=max(1,w)
            for x in range(w):
                rr,gg,bb=colorsys.hsv_to_rgb((base_hue+x/span)%1.0,1.0,1.0)
                col=(int(rr*255),int(gg*255),int(bb*255))
                for y in range(h): px[x,y]=col
    elif mode in ("characters", "words"):
        raw_palette = str(layer.get("color_palette") or "").strip()
        palette = []
        for raw in raw_palette.split(","):
            raw = raw.strip()
            if raw:
                palette.append(_hex_color(raw, "#ffffff"))
        if not palette:
            palette = [c1, c2]
        text = str(laid_out_text if laid_out_text is not None else layer.get("text") or "")
        if mode == "words":
            for left, right, index in _word_colour_ranges(alpha, text):
                col = palette[index % len(palette)]
                for x in range(left, right):
                    for y in range(h):
                        px[x, y] = col
        else:
            units = list(text.replace("\n", ""))
            count = max(1, len(units))
            for x in range(w):
                idx = min(count - 1, int(x / max(1, w) * count))
                col = palette[idx % len(palette)]
                for y in range(h): px[x,y] = col
    rgba = rgb.convert("RGBA")
    rgba.putalpha(alpha)
    return rgba


def _with_glow(sprite: Image.Image, layer: dict) -> Image.Image:
    radius = max(0, min(12, int(round(float(layer.get("glow", 0) or 0)))))
    if radius <= 0:
        return sprite
    pad = radius * 2
    out = Image.new("RGBA", (sprite.width + pad*2, sprite.height + pad*2), (0,0,0,0))
    mask = Image.new("L", out.size, 0)
    mask.paste(sprite.getchannel("A"), (pad,pad))
    blur = mask.filter(ImageFilter.GaussianBlur(radius=max(.5, radius*.7)))
    glow_color = _hex_color(str(layer.get("glow_color") or layer.get("color") or "#ffffff"), "#ffffff")
    glow = Image.new("RGBA", out.size, (*glow_color, 0)); glow.putalpha(blur)
    out.alpha_composite(glow)
    out.alpha_composite(sprite, (pad,pad))
    return out


def _triangle_wave(distance: float, travel: float) -> float:
    if travel <= 0:
        return 0.0
    phase = distance % (travel * 2.0)
    return phase if phase <= travel else (travel * 2.0 - phase)


def _layer_motion(layer: dict, x: int, y: int, w: int, h: int, canvas_w: int, canvas_h: int, elapsed: float) -> tuple[int, int, float, bool]:
    animation = str(layer.get("animation") or "static")
    speed = max(0.0, float(layer.get("speed", 30) or 0))
    period = max(0.1, float(layer.get("effect_period", 1.0) or 1.0))
    delay = max(0.0, float(layer.get("delay", 0.0) or 0.0))
    local = elapsed - delay
    if local < 0:
        return x, y, 1.0, False
    alpha = 1.0
    visible = True
    if animation == "scroll-left":
        x = int(canvas_w - ((local * speed) % max(1.0, canvas_w + w)))
    elif animation == "scroll-right":
        x = int(-w + ((local * speed) % max(1.0, canvas_w + w)))
    elif animation == "scroll-up":
        y = int(canvas_h - ((local * speed) % max(1.0, canvas_h + h)))
    elif animation == "scroll-down":
        y = int(-h + ((local * speed) % max(1.0, canvas_h + h)))
    elif animation == "bounce-horizontal":
        x = int(_triangle_wave(local * speed, max(0, canvas_w - w)))
    elif animation == "bounce-vertical":
        y = int(_triangle_wave(local * speed, max(0, canvas_h - h)))
    elif animation == "blink":
        duty = max(0.05, min(0.95, float(layer.get("blink_duty", 0.5) or 0.5)))
        visible = (local % period) < period * duty
    elif animation == "pulse":
        # 0.25..1.0 keeps text readable even at the bottom of the pulse.
        alpha = 0.625 + 0.375 * math.sin((local / period) * math.tau - math.pi / 2)
    return x, y, max(0.0, min(1.0, alpha)), visible


def _apply_opacity(im: Image.Image, opacity: float) -> Image.Image:
    opacity = max(0.0, min(1.0, opacity))
    if opacity >= 0.999:
        return im
    out = im.copy()
    a = out.getchannel("A").point(lambda v: int(v * opacity))
    out.putalpha(a)
    return out


def _transition_ease(t: float) -> float:
    """Smooth cubic easing used for layer entrance/exit transitions."""
    t = max(0.0, min(1.0, float(t)))
    return 1.0 - (1.0 - t) ** 3


def _layer_transition_phase(layer: dict, elapsed: float, forced_exit_elapsed: float | None = None) -> tuple[str, float, bool, bool]:
    """Return (effect, progress, entering, visible) for a Designer layer.

    Entrance/exit effects are intentionally separate from the layer's normal
    animation (scroll, bounce, blink, pulse).  This allows combinations such as
    slide-in -> scrolling ticker -> fade-out.  Exit timing is measured from the
    layer start after ``delay``; an ``exit_after`` value of zero means stay on.

    ``forced_exit_elapsed`` is used by the playback engine when a message change
    has been requested.  If this layer has an exit effect, that effect starts
    immediately and takes precedence over its normal entrance/exit timeline.
    """
    if str(layer.get("type") or "text") not in ("text", "cloud-text", "image", "video", "widget", "icon", "shader"):
        return "none", 1.0, True, True

    if forced_exit_elapsed is not None:
        exit_effect = str(layer.get("exit_effect") or "none").lower()
        if exit_effect != "none":
            exit_duration = max(0.05, float(layer.get("exit_duration", 0.5) or 0.5))
            forced = max(0.0, float(forced_exit_elapsed))
            if forced >= exit_duration:
                return exit_effect, 1.0, False, False
            return exit_effect, _transition_ease(forced / exit_duration), False, True

    delay = max(0.0, float(layer.get("delay", 0.0) or 0.0))
    local = elapsed - delay
    if local < 0:
        return "none", 0.0, True, False

    entrance = str(layer.get("entrance_effect") or "none").lower()
    entrance_duration = max(0.05, float(layer.get("entrance_duration", 0.5) or 0.5))
    if entrance != "none" and local < entrance_duration:
        return entrance, _transition_ease(local / entrance_duration), True, True

    exit_effect = str(layer.get("exit_effect") or "none").lower()
    exit_after = max(0.0, float(layer.get("exit_after", 0.0) or 0.0))
    exit_duration = max(0.05, float(layer.get("exit_duration", 0.5) or 0.5))
    if exit_effect != "none" and exit_after > 0:
        # Never start the exit before a configured entrance has completed.
        exit_start = max(exit_after, entrance_duration if entrance != "none" else 0.0)
        if local >= exit_start + exit_duration:
            return exit_effect, 1.0, False, False
        if local >= exit_start:
            return exit_effect, _transition_ease((local - exit_start) / exit_duration), False, True

    return "none", 1.0, True, True


def _apply_layer_transition(viewport: Image.Image, layer: dict, elapsed: float, crisp: bool = False, forced_exit_elapsed: float | None = None) -> tuple[Image.Image, bool]:
    """Apply a contained entrance/exit effect to a fixed W x H layer viewport.

    The returned image always has the same dimensions as ``viewport``.  Slide,
    wipe and zoom effects therefore cannot escape the enclosing Designer box.
    """
    effect, progress, entering, visible = _layer_transition_phase(layer, elapsed, forced_exit_elapsed)
    if not visible:
        return Image.new("RGBA", viewport.size, (0, 0, 0, 0)), False
    if effect == "none":
        return viewport, True

    w, h = viewport.size
    p = max(0.0, min(1.0, progress))
    amount = p if entering else (1.0 - p)

    if effect == "fade":
        return _apply_opacity(viewport, amount), True

    if effect.startswith("slide-"):
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if effect == "slide-left":
            dx = int(round(-w * (1.0 - p))) if entering else int(round(-w * p)); dy = 0
        elif effect == "slide-right":
            dx = int(round(w * (1.0 - p))) if entering else int(round(w * p)); dy = 0
        elif effect == "slide-up":
            dx = 0; dy = int(round(-h * (1.0 - p))) if entering else int(round(-h * p))
        else:  # slide-down
            dx = 0; dy = int(round(h * (1.0 - p))) if entering else int(round(h * p))
        out.alpha_composite(viewport, (dx, dy))
        return out, True

    if effect.startswith("wipe-"):
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if effect == "wipe-left":
            keep = max(0, min(w, int(round(w * amount))))
            if keep: out.alpha_composite(viewport.crop((0, 0, keep, h)), (0, 0))
        elif effect == "wipe-right":
            keep = max(0, min(w, int(round(w * amount))))
            if keep: out.alpha_composite(viewport.crop((w - keep, 0, w, h)), (w - keep, 0))
        elif effect == "wipe-up":
            keep = max(0, min(h, int(round(h * amount))))
            if keep: out.alpha_composite(viewport.crop((0, 0, w, keep)), (0, 0))
        else:  # wipe-down
            keep = max(0, min(h, int(round(h * amount))))
            if keep: out.alpha_composite(viewport.crop((0, h - keep, w, h)), (0, h - keep))
        return out, True

    if effect in ("columns","rows","spiral","center-out","random-leds"):
        return _apply_pixel_transition_rgba(viewport, effect, amount), True

    if effect == "zoom":
        scale = max(0.05, amount)
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        resample = Image.Resampling.NEAREST if crisp else Image.Resampling.BICUBIC
        scaled = viewport.resize((nw, nh), resample)
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.alpha_composite(scaled, ((w - nw) // 2, (h - nh) // 2))
        return out, True

    return viewport, True


def _split_flap_fake_char(layer: dict, text: str, index: int, target: str, cycle: int, previous: str = "") -> str:
    """Choose a stable fake flap character matching the target's broad type."""
    if target.isspace() or target in ("\r", "\n"):
        return target
    if target.isdigit():
        pool = "0123456789"
    elif target.isalpha():
        pool = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if target.isupper() else "abcdefghijklmnopqrstuvwxyz"
    else:
        # Punctuation is much clearer if it stays put while the alphanumeric
        # flaps around it move (especially ':' in times and '/' in dates).
        return target
    choices = [ch for ch in pool if ch != target and ch != previous] or [ch for ch in pool if ch != target] or [target]
    seed = f"{layer.get('id','')}|{layer.get('name','')}|{text}|{index}|{cycle}"
    return choices[random.Random(seed).randrange(len(choices))]


def _split_flap_sequence(layer: dict, text: str, index: int, target: str, cycles: int) -> list[str]:
    seq: list[str] = []
    previous = ""
    for cycle in range(cycles):
        ch = _split_flap_fake_char(layer, text, index, target, cycle, previous)
        seq.append(ch)
        previous = ch
    seq.append(target)
    return seq


def _split_flap_fixed_row(text: str, columns: int, align: str) -> str:
    """Place one sequential line into a fixed bank of split-flap cells."""
    value = str(text or "")
    columns = max(1, int(columns or 1))
    if len(value) >= columns:
        return value[:columns]
    spare = columns - len(value)
    if align == "right":
        return " " * spare + value
    if align == "center":
        left = spare // 2
        return " " * left + value + " " * (spare - left)
    return value + " " * spare


def _split_flap_transition_sequence(layer: dict, text: str, index: int, source: str, target: str, cycles: int) -> list[str]:
    """Build a physical-cell transition from the previous character to the next.

    Sequential departure-board lines must not discard the old cell contents at a
    slot boundary.  The old glyph is the first flap state.  When the destination
    is blank, fake glyphs use the old glyph's alphabet/number family and the final
    flap lands on a genuinely transparent blank cell.
    """
    if source == target:
        return [target]
    seq = [source]
    previous = source
    fake_basis = target if not target.isspace() else source
    for cycle in range(max(0, int(cycles))):
        ch = _split_flap_fake_char(layer, text, index, fake_basis, cycle, previous)
        # Punctuation deliberately does not cycle.  Avoid filling the sequence
        # with duplicate stages while still allowing the final turn to blank.
        if ch != previous and ch != target:
            seq.append(ch)
            previous = ch
    if seq[-1] != target:
        seq.append(target)
    return seq


def _split_flap_cell(src: Image.Image, dst: Image.Image, phase: float, crisp: bool) -> Image.Image:
    """Approximate a mechanical split-flap rotation inside one fixed character cell.

    On the first half of the turn the old top half collapses into the centre
    seam.  On the second half the new lower half unfolds from that seam.  This
    deliberately uses very few visual cues so it remains legible on a 16/32 px
    high HUB75 display.
    """
    w, h = src.size
    if dst.size != src.size:
        dst = dst.resize(src.size, Image.Resampling.NEAREST if crisp else Image.Resampling.BICUBIC)
    if w <= 0 or h <= 1:
        return dst.copy() if phase >= 0.5 else src.copy()
    p = max(0.0, min(1.0, float(phase)))
    mid = max(1, h // 2)
    lower_h = h - mid
    resample = Image.Resampling.NEAREST if crisp else Image.Resampling.BICUBIC
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    if p < 0.5:
        # The old lower half remains visible while the upper flap rotates down.
        if lower_h > 0:
            out.alpha_composite(src.crop((0, mid, w, h)), (0, mid))
        frac = 1.0 - p * 2.0
        sh = max(0, int(round(mid * frac)))
        if sh > 0:
            top = src.crop((0, 0, w, mid)).resize((w, sh), resample)
            out.alpha_composite(top, (0, mid - sh))
    else:
        # Once the flap crosses the centre, the new upper half is exposed and
        # its lower half unfolds downwards.
        out.alpha_composite(dst.crop((0, 0, w, mid)), (0, 0))
        frac = (p - 0.5) * 2.0
        sh = max(0, int(round(lower_h * frac)))
        if sh > 0 and lower_h > 0:
            bottom = dst.crop((0, mid, w, h)).resize((w, sh), resample)
            out.alpha_composite(bottom, (0, mid))

    # A one-pixel dark hinge line, but only where glyph ink exists.  It never
    # paints a black rectangle over layers behind transparent text.
    seam_y = min(h - 1, mid)
    alpha = out.getchannel("A").crop((0, seam_y, w, seam_y + 1)).point(lambda a: int(a * 0.72))
    if alpha.getbbox():
        seam = Image.new("RGBA", (w, 1), (0, 0, 0, 0))
        seam.putalpha(alpha)
        out.alpha_composite(seam, (0, seam_y))
    return out


def _split_flap_text_layout(layer: dict, text: str, box_w: int, box_h: int, sy: float, upload_fonts_dir: str):
    """Return fixed-cell layout data and a layer override for split-flap glyphs."""
    pad = max(0, int(round(float(layer.get("padding", 0) or 0) * sy)))
    inner_w, inner_h = max(1, box_w - pad * 2), max(1, box_h - pad * 2)
    lines = str(text or " ").split("\n") or [" "]
    max_cols = max(1, max((len(line) for line in lines), default=1))
    line_count = max(1, len(lines))
    align = str(layer.get("align") or "center")
    if align not in ("left", "center", "right"):
        align = "center"
    valign = str(layer.get("valign") or "middle")
    if valign not in ("top", "middle", "bottom"):
        valign = "middle"
    render_mode = str(layer.get("render_mode") or "smooth").lower()
    if render_mode not in ("smooth", "pixel") and not _is_led_mode(render_mode):
        render_mode = "smooth"
    board_style = str(layer.get("flap_board_style") or "none").lower()
    mechanical_cells = board_style != "none"
    letter_spacing = max(0, min(8, int(layer.get("letter_spacing", 0) or 0)))
    spacing_ratio = max(0.0, min(1.0, float(layer.get("line_spacing", 0.12) or 0.0)))
    auto_fit = bool(layer.get("auto_fit", False)) or str(layer.get("overflow") or "manual").lower() == "shrink"
    child_override: dict = {"auto_fit": False, "wrap": False, "overflow": "manual", "padding": 0,
                            "align": "center", "valign": "middle", "animation": "static",
                            "text_transform": "none"}

    if _is_led_mode(render_mode):
        gw, gh, _source = _LED_FONT_SPECS.get(render_mode, (5, 7, "5x7"))
        bold = bool(layer.get("pixel_bold", False) or render_mode == "led-bold")
        gap_units = max(1, 1 + letter_spacing)
        line_gap_units = max(1, int(round(1 + spacing_ratio * 4)))
        requested = max(1, min(8, int(layer.get("pixel_scale", 1) or 1)))
        candidates = range(8, 0, -1) if auto_fit else (requested,)
        chosen = requested
        for scale in candidates:
            # A mechanical casing must surround the glyph, not share its pixels.
            # Reserve a transparent module gap, a one-pixel frame, and at least
            # one *clear* LED pixel between the frame and the illuminated glyph.
            # At scale=1 this deliberately makes a 5x7 glyph sit inside an
            # 11x13-ish physical module instead of the old 8x9 box whose border
            # could land directly on the first/last glyph column.
            configured_gap = max(0, min(3, int(layer.get("flap_cell_gap", 1) or 0)))
            module_gap = max(1, configured_gap) if board_style in ("departure", "airport") else configured_gap
            requested_case_padding = max(1, min(6, int(layer.get("flap_case_padding", 2) or 2)))
            face_padding = max(2, scale, requested_case_padding) if mechanical_cells else 0
            content_inset = module_gap + face_padding if mechanical_cells else 0
            glyph_w = max(1, (gw + (1 if bold else 0)) * scale)
            glyph_h = max(1, gh * scale)
            cell_w = max(1, glyph_w + content_inset * 2) if mechanical_cells else max(1, (gw + (1 if bold else 0) + gap_units) * scale)
            cell_h = max(1, glyph_h + content_inset * 2)
            line_gap = line_gap_units * scale
            board_w = max_cols * cell_w
            board_h = line_count * cell_h + max(0, line_count - 1) * line_gap
            chosen = scale
            if not auto_fit or (board_w <= inner_w and board_h <= inner_h):
                break
        configured_gap = max(0, min(3, int(layer.get("flap_cell_gap", 1) or 0)))
        module_gap = max(1, configured_gap) if board_style in ("departure", "airport") else configured_gap
        requested_case_padding = max(1, min(6, int(layer.get("flap_case_padding", 2) or 2)))
        face_padding = max(2, chosen, requested_case_padding) if mechanical_cells else 0
        content_inset = module_gap + face_padding if mechanical_cells else 0
        glyph_w = max(1, (gw + (1 if bold else 0)) * chosen)
        glyph_h = max(1, gh * chosen)
        cell_w = max(1, glyph_w + content_inset * 2) if mechanical_cells else max(1, (gw + (1 if bold else 0) + gap_units) * chosen)
        cell_h = max(1, glyph_h + content_inset * 2)
        line_gap = line_gap_units * chosen
        child_override.update({"render_mode": render_mode, "pixel_scale": chosen, "letter_spacing": 0,
                               "_flap_content_inset_x": content_inset, "_flap_content_inset_y": content_inset})
    else:
        stroke = max(0, int(round(float(layer.get("outline_width", 0) or 0) * sy)))
        base_size = max(4, int(round(float(layer.get("font_size", 18) or 18) * sy)))
        placeholder = "\n".join("M" * max(1, len(line)) for line in lines)
        if auto_fit:
            font, chosen_size = _fit_layer_font(placeholder, inner_w, inner_h, str(layer.get("font") or ""),
                                                 upload_fonts_dir, False, "left", spacing_ratio, stroke)
        else:
            chosen_size = base_size
            font = _load_font(str(layer.get("font") or ""), chosen_size, upload_fonts_dir)

        def metrics(font_obj, size: int):
            widths, heights = [], []
            for probe_ch in ("M", "W", "8", "0"):
                probe = _render_ttf_sprite(probe_ch, font_obj, (255,255,255), (0,0,0), stroke, 0, "center",
                                           render_mode, max(1, min(8, int(layer.get("pixel_scale", 1) or 1))),
                                           bool(layer.get("pixel_bold", False)), 0)
                widths.append(probe.width); heights.append(probe.height)
            gap = max(1, letter_spacing + 1)
            configured_gap = max(0, min(3, int(layer.get("flap_cell_gap", 1) or 0)))
            module_gap = max(1, configured_gap) if board_style in ("departure", "airport") else configured_gap
            # Smooth/pixel TTF gets the same physical rule: frame + visible air
            # around the glyph.  Use a modest font-relative inset, but never less
            # than two real output pixels inside the module gap.
            requested_case_padding = max(1, min(6, int(layer.get("flap_case_padding", 2) or 2)))
            face_padding = max(2, requested_case_padding, int(round(size * .12))) if mechanical_cells else 0
            content_inset = module_gap + face_padding if mechanical_cells else 0
            return (max(widths, default=max(1, size // 2)) + gap + content_inset * 2,
                    max(heights, default=max(1, size)) + content_inset * 2,
                    max(0, int(round(size * spacing_ratio))), content_inset)

        cell_w, cell_h, line_gap, content_inset = metrics(font, chosen_size)
        if auto_fit:
            while chosen_size > 4 and (max_cols * cell_w > inner_w or line_count * cell_h + max(0, line_count - 1) * line_gap > inner_h):
                chosen_size -= 1
                font = _load_font(str(layer.get("font") or ""), chosen_size, upload_fonts_dir)
                cell_w, cell_h, line_gap, content_inset = metrics(font, chosen_size)
        child_override.update({"font_size": chosen_size / max(0.0001, sy), "render_mode": render_mode,
                               "letter_spacing": 0, "_flap_content_inset_x": content_inset,
                               "_flap_content_inset_y": content_inset})

    board_h = line_count * cell_h + max(0, line_count - 1) * line_gap
    board_y = pad + _align_pos(inner_h, board_h, valign, 0)
    return lines, pad, inner_w, board_y, cell_w, cell_h, line_gap, align, child_override


def _composite_cell_clipped(base: Image.Image, overlay: Image.Image, x: int, y: int) -> None:
    bx0, by0 = max(0, x), max(0, y)
    bx1, by1 = min(base.width, x + overlay.width), min(base.height, y + overlay.height)
    if bx1 <= bx0 or by1 <= by0:
        return
    ox0, oy0 = bx0 - x, by0 - y
    base.alpha_composite(overlay.crop((ox0, oy0, ox0 + bx1 - bx0, oy0 + by1 - by0)), (bx0, by0))


def _render_split_flap_text(layer: dict, box_w: int, box_h: int, sy: float, elapsed: float,
                            now: datetime, upload_fonts_dir: str) -> Image.Image:
    transform = str(layer.get("text_transform") or "none")
    target = _transform_text(_token_text(str(layer.get("text") or ""), now), transform)
    delay = max(0.0, float(layer.get("delay", 0) or 0))
    local = max(0.0, float(elapsed) - delay)
    duration = max(0.1, float(layer.get("effect_period", 1.0) or 1.0))
    cycles = max(1, min(12, int(layer.get("flap_cycles", 4) or 4)))
    stagger = max(0.0, min(0.5, float(layer.get("flap_stagger", 0.06) or 0.0)))
    order = str(layer.get("flap_order") or "left").lower()
    align = str(layer.get("align") or "center")
    if align not in ("left", "center", "right"):
        align = "center"

    # Sequential multiline split-flap text is one physical board, not a series
    # of independently sized text sprites.  Work out the widest transformed line
    # and pad both the old and new line into that same fixed bank of cells.
    sequence_raw = layer.get("_line_sequence_lines")
    sequential = isinstance(sequence_raw, list) and len(sequence_raw) > 1
    previous_lines: list[str] | None = None
    if sequential:
        sequence_text = [
            _transform_text(_token_text(str(line or ""), now), transform)
            for line in sequence_raw
        ]
        board_cols = max(1, max((len(line) for line in sequence_text), default=1))
        previous = _transform_text(
            _token_text(str(layer.get("_line_sequence_previous_text") or ""), now), transform
        )
        target = _split_flap_fixed_row(target, board_cols, align)
        previous = _split_flap_fixed_row(previous, board_cols, align)
        previous_lines = [previous]

    if not target:
        child = dict(layer); child.update(animation="static", text=target)
        return _render_scene_text(child, box_w, box_h, sy, elapsed, now, upload_fonts_dir)

    lines, pad, inner_w, board_y, cell_w, cell_h, line_gap, align, child_override = _split_flap_text_layout(
        layer, target, box_w, box_h, sy, upload_fonts_dir
    )
    out = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))

    if previous_lines is None:
        # Original single-line/together behaviour: only visible destination cells
        # participate, and each one begins on its deterministic fake character.
        positions = [(li, ci, ch) for li, line in enumerate(lines) for ci, ch in enumerate(line)
                     if not ch.isspace() and ch not in ("\r", "\n")]
    else:
        # Fixed sequential board: every cell whose state changes participates,
        # including old visible cells whose destination is now a blank flap.
        positions = []
        for li, line in enumerate(lines):
            previous_line = previous_lines[li] if li < len(previous_lines) else " " * len(line)
            for ci, ch in enumerate(line):
                src_ch = previous_line[ci] if ci < len(previous_line) else " "
                if src_ch != ch:
                    positions.append((li, ci, ch))

    ordered = list(positions)
    if order == "right":
        ordered.reverse()
    elif order == "random":
        random.Random(f"{layer.get('id','')}|{layer.get('name','')}|{target}|flap-order").shuffle(ordered)
    rank = {(li, ci): idx for idx, (li, ci, _ch) in enumerate(ordered)}
    max_delay = min(stagger * max(0, len(ordered) - 1), duration * 0.68)
    actual_stagger = max_delay / max(1, len(ordered) - 1)
    flip_window = max(0.12, duration - max_delay)
    crisp = _is_crisp_mode(str(child_override.get("render_mode") or layer.get("render_mode") or "smooth"))
    flat_index = 0

    def render_char(ch: str) -> Image.Image:
        child = dict(layer)
        child.update(child_override)
        inset_x = max(0, int(child.pop("_flap_content_inset_x", 0) or 0))
        inset_y = max(0, int(child.pop("_flap_content_inset_y", 0) or 0))
        child.update(text=ch, animation="static", delay=0, entrance_effect="none", exit_effect="none")
        # Render the glyph into the flap's *inner face*, then place that inside
        # the physical module.  This guarantees the frame cannot ever be hidden
        # underneath the first/last glyph column, even with the 5x7 LED font.
        inner_char_w = max(1, cell_w - inset_x * 2)
        inner_char_h = max(1, cell_h - inset_y * 2)
        glyph = _render_scene_text(child, inner_char_w, inner_char_h, sy, elapsed, now, upload_fonts_dir)
        if inset_x <= 0 and inset_y <= 0:
            return glyph
        framed = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
        framed.alpha_composite(glyph, (inset_x, inset_y))
        return framed

    for li, line in enumerate(lines):
        line_w = max(1, len(line) * cell_w)
        line_x = pad + _align_pos(inner_w, line_w, align, 0)
        y = board_y + li * (cell_h + line_gap)
        previous_line = previous_lines[li] if previous_lines is not None and li < len(previous_lines) else None
        for ci, target_ch in enumerate(line):
            x = line_x + ci * cell_w
            source_ch = previous_line[ci] if previous_line is not None and ci < len(previous_line) else None
            board_cell = _split_flap_board_cell(layer, cell_w, cell_h)
            board_overlay = _split_flap_board_overlay(layer, cell_w, cell_h)
            if board_cell is not None:
                _composite_cell_clipped(out, board_cell, x, y)

            if previous_line is not None:
                if source_ch == target_ch:
                    if not target_ch.isspace():
                        _composite_cell_clipped(out, render_char(target_ch), x, y)
                    if board_overlay is not None:
                        _composite_cell_clipped(out, board_overlay, x, y)
                    flat_index += 1
                    continue
                seq = _split_flap_transition_sequence(layer, target, flat_index, source_ch or " ", target_ch, cycles)
                char_local = local - rank.get((li, ci), 0) * actual_stagger
                stage_count = max(1, len(seq) - 1)
                if char_local <= 0:
                    src_ch = dst_ch = seq[0]; phase = 0.0
                elif char_local >= flip_window:
                    src_ch = dst_ch = target_ch; phase = 1.0
                else:
                    scaled = max(0.0, min(float(stage_count) - 1e-9, char_local / flip_window * stage_count))
                    stage = min(stage_count - 1, int(scaled))
                    phase = scaled - stage
                    src_ch, dst_ch = seq[stage], seq[stage + 1]
            else:
                if target_ch.isspace():
                    if board_overlay is not None:
                        _composite_cell_clipped(out, board_overlay, x, y)
                    flat_index += 1
                    continue
                seq = _split_flap_sequence(layer, target, flat_index, target_ch, cycles)
                char_local = local - rank.get((li, ci), 0) * actual_stagger
                if char_local <= 0:
                    src_ch = dst_ch = seq[0]; phase = 0.0
                elif char_local >= flip_window:
                    src_ch = dst_ch = target_ch; phase = 1.0
                else:
                    scaled = max(0.0, min(float(cycles) - 1e-9, char_local / flip_window * cycles))
                    stage = min(cycles - 1, int(scaled))
                    phase = scaled - stage
                    src_ch, dst_ch = seq[stage], seq[stage + 1]

            # A destination/source space still owns a real fixed cell.  Rendering
            # it yields transparent ink, allowing _split_flap_cell() to visibly
            # fold the previous glyph away instead of dropping it between frames.
            src = render_char(src_ch)
            cell = src if src_ch == dst_ch else _split_flap_cell(src, render_char(dst_ch), phase, crisp)
            _composite_cell_clipped(out, cell, x, y)
            if board_overlay is not None:
                _composite_cell_clipped(out, board_overlay, x, y)
            flat_index += 1
    return out



def _split_flap_board_cell(layer: dict, cell_w: int, cell_h: int) -> Image.Image | None:
    """Return a crisp low-resolution mechanical split-flap cell background.

    The built-in presets deliberately use much stronger face/border contrast than
    a desktop UI would need.  On a real P5/P10 matrix subtle charcoal-on-black
    detail disappears, so each physical module gets a clear one-LED frame, a
    separate upper/lower flap face and a hard centre hinge.
    """
    style = str(layer.get("flap_board_style") or "none").lower()
    if style == "none":
        return None

    if style == "departure":
        top, bottom = (24, 27, 24), (9, 10, 9)
        border, seam, hinge = (92, 98, 92), (0, 0, 0), (142, 148, 138)
    elif style == "airport":
        top, bottom = (12, 38, 68), (5, 19, 37)
        border, seam, hinge = (58, 103, 143), (0, 5, 12), (111, 158, 196)
    else:
        bg = _hex_color(str(layer.get("flap_bg_color") or "#171717"), "#171717")
        border = _hex_color(str(layer.get("flap_border_color") or "#454545"), "#454545")
        seam = _hex_color(str(layer.get("flap_seam_color") or "#000000"), "#000000")
        # Custom keeps the chosen colour but still gets two distinguishable flap
        # faces.  The shift is intentionally tiny and deterministic.
        top = tuple(min(255, c + 7) for c in bg)
        bottom = tuple(max(0, c - 7) for c in bg)
        hinge = border

    configured_gap = max(0, min(3, int(layer.get("flap_cell_gap", 1) or 0)))
    # The two named board presets should always read as separate modules.  A zero
    # gap makes adjacent borders merge into one grid line on a low-resolution LED
    # matrix, which is exactly what made the original black preset look too faint.
    gap = max(1, configured_gap) if style in ("departure", "airport") else configured_gap

    im = Image.new("RGBA", (max(1, cell_w), max(1, cell_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    x0 = y0 = gap
    x1 = max(x0, cell_w - 1 - gap)
    y1 = max(y0, cell_h - 1 - gap)

    # Strong one-pixel physical frame.
    draw.rectangle((x0, y0, x1, y1), fill=(*bottom, 255), outline=(*border, 255))
    if x1 - x0 >= 2 and y1 - y0 >= 2:
        ix0, ix1 = x0 + 1, x1 - 1
        iy0, iy1 = y0 + 1, y1 - 1
        seam_y = (y0 + y1) // 2
        # Separate upper and lower flap faces.
        if seam_y - 1 >= iy0:
            draw.rectangle((ix0, iy0, ix1, seam_y - 1), fill=(*top, 255))
        if seam_y + 1 <= iy1:
            draw.rectangle((ix0, seam_y + 1, ix1, iy1), fill=(*bottom, 255))
        # Hard centre split plus two tiny hinge/pivot pixels.
        draw.line((x0 + 1, seam_y, x1 - 1, seam_y), fill=(*seam, 255), width=1)
        if x1 - x0 >= 5:
            draw.point((x0 + 1, seam_y), fill=(*hinge, 255))
            draw.point((x1 - 1, seam_y), fill=(*hinge, 255))
    elif y1 - y0 >= 3:
        seam_y = (y0 + y1) // 2
        draw.line((x0, seam_y, x1, seam_y), fill=(*seam, 255), width=1)
    return im


def _split_flap_board_overlay(layer: dict, cell_w: int, cell_h: int) -> Image.Image | None:
    """Return the centre split/hinge drawn above the flap glyph.

    A real split-flap character is physically cut at the hinge, so the seam must
    cross the illuminated glyph too.  Drawing it only into the background makes
    it disappear behind white text and the effect reads as an ordinary boxed
    font rather than a mechanical flap.
    """
    style = str(layer.get("flap_board_style") or "none").lower()
    if style == "none":
        return None
    if style == "departure":
        seam, hinge = (0, 0, 0), (142, 148, 138)
    elif style == "airport":
        seam, hinge = (0, 5, 12), (111, 158, 196)
    else:
        seam = _hex_color(str(layer.get("flap_seam_color") or "#000000"), "#000000")
        hinge = _hex_color(str(layer.get("flap_border_color") or "#454545"), "#454545")
    configured_gap = max(0, min(3, int(layer.get("flap_cell_gap", 1) or 0)))
    gap = max(1, configured_gap) if style in ("departure", "airport") else configured_gap
    x0 = y0 = gap
    x1 = max(x0, cell_w - 1 - gap)
    y1 = max(y0, cell_h - 1 - gap)
    if y1 - y0 < 3:
        return None
    seam_y = (y0 + y1) // 2
    im = Image.new("RGBA", (max(1, cell_w), max(1, cell_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    sx0, sx1 = min(x1, x0 + 1), max(x0, x1 - 1)
    draw.line((sx0, seam_y, sx1, seam_y), fill=(*seam, 255), width=1)
    if x1 - x0 >= 5:
        draw.point((sx0, seam_y), fill=(*hinge, 255))
        draw.point((sx1, seam_y), fill=(*hinge, 255))
    return im


def _animation_progress(layer: dict, elapsed: float) -> tuple[float, float, float]:
    delay=max(0.0,float(layer.get("delay",0) or 0)); local=max(0.0,float(elapsed)-delay)
    duration=max(0.1,float(layer.get("effect_period",1.0) or 1.0))
    return local,duration,max(0.0,min(1.0,local/duration))


def _stable_pixel_rank(x: int, y: int, seed: int = 0) -> int:
    return ((x*1973 + y*9277 + x*y*26699 + seed*811) ^ (x<<5) ^ (y<<3)) & 1023


def _apply_text_post_effect(im: Image.Image, layer: dict, elapsed: float) -> Image.Image:
    """Cheap LED-resolution effects applied after normal text rasterisation."""
    animation=str(layer.get("animation") or "static").lower()
    if animation not in ("pixel-assemble","pixel-dissolve","neon-flicker","glitch"):
        return im
    local,duration,p=_animation_progress(layer,elapsed)
    if animation in ("pixel-assemble","pixel-dissolve"):
        amount=p if animation=="pixel-assemble" else abs(1.0-2.0*((local/duration)%1.0))
        src=im.convert("RGBA"); alpha=src.getchannel("A"); a=alpha.load(); seed=int(hashlib.sha1(str(layer.get("id") or "text").encode()).hexdigest()[:4],16)
        threshold=int(max(0.0,min(1.0,amount))*1024)
        for y in range(src.height):
            for x in range(src.width):
                if a[x,y] and _stable_pixel_rank(x,y,seed)>=threshold: a[x,y]=0
        src.putalpha(alpha); return src
    if animation=="neon-flicker":
        if local>=duration: return im
        # Deliberately irregular startup sequence: failed strikes, brief full light,
        # then a final stable ignition. Seeded so preview and live output agree.
        seq=(0.0,.92,.12,1.0,.25,.82,.05,1.0,.42,.96,.18,1.0)
        idx=min(len(seq)-1,int((local/duration)*len(seq)))
        level=seq[idx]
        seed=int(hashlib.sha1(f"{layer.get('id','')}|neon".encode()).hexdigest()[:4],16)
        jitter=((seed+idx*37)%17)/100.0
        return _apply_opacity(im,max(0.0,min(1.0,level-jitter)))
    # Glitch: most of each period is stable; a short burst shifts horizontal LED
    # bands and adds a restrained one-pixel RGB split.
    phase=(local/duration)%1.0
    if phase<.72: return im
    strength=max(1,min(12,int(round(float(layer.get("effect_amount",2) or 2)))))
    src=im.convert("RGBA"); out=Image.new("RGBA",src.size,(0,0,0,0)); band=max(1,src.height//6)
    seed=int((local/duration)*19)+int(hashlib.sha1(str(layer.get("id") or "").encode()).hexdigest()[:4],16)
    rng=random.Random(seed)
    for y in range(0,src.height,band):
        dy=min(src.height,y+band); shift=rng.randint(-strength,strength)
        _composite_cell_clipped(out,src.crop((0,y,src.width,dy)),shift,y)
    if strength>=2:
        a=out.getchannel("A"); r,g,b,_=out.split()
        ghost=Image.new("RGBA",out.size,(0,0,0,0)); ghost.putalpha(a.point(lambda v:int(v*.28)))
        red=Image.merge("RGBA",(r,Image.new("L",out.size,0),Image.new("L",out.size,0),ghost.getchannel("A")))
        blue=Image.merge("RGBA",(Image.new("L",out.size,0),Image.new("L",out.size,0),b,ghost.getchannel("A")))
        _composite_cell_clipped(out,red,1,0); _composite_cell_clipped(out,blue,-1,0)
    return out


def _fixed_character_rows(layer: dict, text: str, box_w: int, box_h: int, sy: float, upload_fonts_dir: str):
    return _split_flap_text_layout(layer,text or " ",box_w,box_h,sy,upload_fonts_dir)


def _render_character_wave_text(layer: dict, box_w: int, box_h: int, sy: float, elapsed: float,
                                now: datetime, upload_fonts_dir: str) -> Image.Image:
    text=_layer_text_value(dict(layer,animation="static"),now,elapsed)
    lines,pad,inner_w,board_y,cell_w,cell_h,line_gap,align,child_override=_fixed_character_rows(layer,text,box_w,box_h,sy,upload_fonts_dir)
    out=Image.new("RGBA",(box_w,box_h),(0,0,0,0)); local,duration,_p=_animation_progress(layer,elapsed)
    amp=max(1,min(12,int(round(float(layer.get("effect_amount",2) or 2)*sy))))
    stagger=max(0.0,min(.5,float(layer.get("effect_stagger",.08) or .08)))
    idx=0
    for li,line in enumerate(lines):
        line_w=max(1,len(line)*cell_w); line_x=pad+_align_pos(inner_w,line_w,align,0); base_y=board_y+li*(cell_h+line_gap)
        for ci,ch in enumerate(line):
            if not ch.isspace():
                child=dict(layer);child.update(child_override);child.update(text=ch,animation="static",delay=0,entrance_effect="none",exit_effect="none")
                glyph=_render_scene_text(child,cell_w,cell_h,sy,elapsed,now,upload_fonts_dir)
                offset=int(round(math.sin((local/duration)*math.tau-idx*stagger*math.tau)*amp))
                _composite_cell_clipped(out,glyph,line_x+ci*cell_w,base_y+offset)
            idx+=1
    return out


def _render_rolling_digits_text(layer: dict, box_w: int, box_h: int, sy: float, elapsed: float,
                                now: datetime, upload_fonts_dir: str) -> Image.Image:
    transform=str(layer.get("text_transform") or "none")
    is_widget=str(layer.get("type") or "text")=="widget"
    raw_target=_widget_text(layer,now) if is_widget else _token_text(str(layer.get("text") or ""),now)
    target=_transform_text(raw_target,transform)
    previous_sequence=layer.get("_line_sequence_previous_text")
    local,duration,p=_animation_progress(layer,elapsed)
    if previous_sequence is not None:
        source=_transform_text(_token_text(str(previous_sequence or ""),now),transform); progress=p
    else:
        raw_source=_widget_text(layer,now-timedelta(seconds=1)) if is_widget else _token_text(str(layer.get("text") or ""),now-timedelta(seconds=1))
        source=_transform_text(raw_source,transform)
        # Dynamic clocks/countdowns roll at the second boundary. Static numeric text
        # gets one useful roll-in at layer start instead of doing nothing forever.
        if source==target:
            source="".join(str((int(ch)-1)%10) if ch.isdigit() else ch for ch in target); progress=p
        else:
            progress=min(1.0,(now.microsecond/1_000_000.0)/max(.05,min(duration,.95)))
    cols=max(1,len(source),len(target)); align=str(layer.get("align") or "center")
    source=_split_flap_fixed_row(source,cols,align); target=_split_flap_fixed_row(target,cols,align)
    lines,pad,inner_w,board_y,cell_w,cell_h,line_gap,align,child_override=_fixed_character_rows(layer,target,box_w,box_h,sy,upload_fonts_dir)
    out=Image.new("RGBA",(box_w,box_h),(0,0,0,0)); line=lines[0] if lines else target
    line_x=pad+_align_pos(inner_w,max(1,len(line)*cell_w),align,0)
    def glyph(ch: str)->Image.Image:
        child=dict(layer);child.update(child_override);child.update(text=ch,animation="static",delay=0,entrance_effect="none",exit_effect="none")
        return _render_scene_text(child,cell_w,cell_h,sy,elapsed,now,upload_fonts_dir)
    for ci,dst in enumerate(target):
        src=source[ci] if ci<len(source) else " "; x=line_x+ci*cell_w
        if src==dst or not (src.isdigit() or dst.isdigit()):
            if not dst.isspace(): _composite_cell_clipped(out,glyph(dst),x,board_y)
            continue
        old=glyph(src); new=glyph(dst); shift=int(round(cell_h*progress)); cell=Image.new("RGBA",(cell_w,cell_h),(0,0,0,0))
        _composite_cell_clipped(cell,old,0,-shift); _composite_cell_clipped(cell,new,0,cell_h-shift)
        _composite_cell_clipped(out,cell,x,board_y)
    return out


def _render_scene_text(layer: dict, box_w: int, box_h: int, sy: float, elapsed: float, now: datetime, upload_fonts_dir: str) -> Image.Image:
    animation = str(layer.get("animation") or "static")
    if animation == "split-flap" and str(layer.get("type") or "text") == "text":
        return _render_split_flap_text(layer, box_w, box_h, sy, elapsed, now, upload_fonts_dir)
    if animation == "character-wave" and str(layer.get("type") or "text") == "text":
        return _render_character_wave_text(layer, box_w, box_h, sy, elapsed, now, upload_fonts_dir)
    if animation == "rolling-digits" and str(layer.get("type") or "text") in ("text", "widget"):
        return _render_rolling_digits_text(layer, box_w, box_h, sy, elapsed, now, upload_fonts_dir)
    text = _layer_text_value(layer, now, elapsed)
    cache_fields = {k: layer.get(k) for k in (
        "font", "font_size", "auto_fit", "wrap", "color", "outline_color", "outline_width",
        "padding", "align", "valign", "line_spacing", "shadow_color", "shadow_x", "shadow_y",
        "render_mode", "pixel_scale", "pixel_bold", "letter_spacing", "text_transform",
        "overflow", "break_long_words", "color_effect", "color2", "color_speed", "color_palette", "glow", "glow_color",
        "animation", "effect_period", "effect_amount", "effect_stagger"
    )}
    animated_color = str(layer.get("color_effect") or "none").lower() in ("rainbow", "cycle", "wave")
    animated_post = animation in ("pixel-assemble","pixel-dissolve","neon-flicker","glitch")
    cache_key = json.dumps([box_w, box_h, round(sy, 5), text, cache_fields, round(elapsed, 2) if (animated_color or animated_post) else 0], sort_keys=True, default=str)
    cached = _TEXT_LAYER_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()

    pad = max(0, int(round(float(layer.get("padding", 0) or 0) * sy)))
    inner_w, inner_h = max(1, box_w - pad * 2), max(1, box_h - pad * 2)
    font_size = max(4, int(round(float(layer.get("font_size", 18) or 18) * sy)))
    stroke = max(0, int(round(float(layer.get("outline_width", 0) or 0) * sy)))
    align = str(layer.get("align") or "center")
    if align not in ("left", "center", "right"):
        align = "center"
    valign = str(layer.get("valign") or "middle")
    if valign not in ("top", "middle", "bottom"):
        valign = "middle"
    overflow = str(layer.get("overflow") or "manual").lower()
    wrap = bool(layer.get("wrap", False)) or overflow == "wrap"
    break_long_words = bool(layer.get("break_long_words", True))
    auto_fit = bool(layer.get("auto_fit", False)) or overflow == "shrink"
    if overflow in ("clip", "marquee"): wrap = False
    spacing_ratio = max(0.0, min(1.0, float(layer.get("line_spacing", 0.12) or 0.0)))
    render_mode = str(layer.get("render_mode") or "smooth").lower()
    if render_mode not in ("smooth", "pixel") and not _is_led_mode(render_mode):
        render_mode = "smooth"
    pixel_scale = max(1, min(8, int(layer.get("pixel_scale", 1) or 1)))
    pixel_bold = bool(layer.get("pixel_bold", False))
    letter_spacing = max(0, min(8, int(layer.get("letter_spacing", 0) or 0)))
    color = _hex_color(str(layer.get("color") or "#ffffff"), "#ffffff")
    outline = _hex_color(str(layer.get("outline_color") or "#000000"), "#000000")
    shadow_x = int(round(float(layer.get("shadow_x", 0) or 0) * sy))
    shadow_y = int(round(float(layer.get("shadow_y", 0) or 0) * sy))
    needs_shadow = bool(shadow_x or shadow_y)
    shadow_body = None

    if _is_led_mode(render_mode):
        line_gap = max(1, int(round(1 + spacing_ratio * 4)))
        sprite = _render_led_sprite(
            text, inner_w, inner_h, color, outline, stroke, pixel_scale,
            auto_fit, wrap, align, pixel_bold, letter_spacing, line_gap, render_mode, break_long_words
        )
        if needs_shadow:
            # The shadow follows the original glyph body, not the already-outlined
            # sprite.  This makes Outline=1 + Shadow=(1,1) remain a genuinely
            # one-pixel offset instead of visually compounding into a 2-3px halo.
            shadow_body = _render_led_sprite(
                text, inner_w, inner_h, color, outline, 0, pixel_scale,
                auto_fit, wrap, align, pixel_bold, letter_spacing, line_gap, render_mode, break_long_words
            )
    else:
        if auto_fit:
            font, font_size = _fit_layer_font(text, inner_w, inner_h, str(layer.get("font") or ""), upload_fonts_dir,
                                              wrap, align, spacing_ratio, stroke, break_long_words=break_long_words)
        else:
            font = _load_font(str(layer.get("font") or ""), font_size, upload_fonts_dir)
        spacing = max(0, int(round(font_size * spacing_ratio)))
        probe = ImageDraw.Draw(Image.new("RGBA", (4,4), (0,0,0,0)))
        laid_out = _wrap_text_pixels(text, font, inner_w, probe, stroke, break_long_words) if wrap else text
        sprite = _render_ttf_sprite(laid_out, font, color, outline, stroke, spacing, align,
                                    render_mode, pixel_scale, pixel_bold, letter_spacing)
        if needs_shadow:
            shadow_body = _render_ttf_sprite(laid_out, font, color, outline, 0, spacing, align,
                                             render_mode, pixel_scale, pixel_bold, letter_spacing)

    sprite = _apply_sprite_color_effect(sprite, layer, elapsed, locals().get("laid_out", text))
    sprite = _with_glow(sprite, layer)
    tw, th = sprite.size
    tx = pad + _align_pos(inner_w, tw, align, 0)
    ty = pad + _align_pos(inner_h, th, valign, 0)
    im = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    shadow_color = _hex_color(str(layer.get("shadow_color") or "#000000"), "#000000")
    if needs_shadow and shadow_body is not None:
        # Centre the un-outlined body inside the outlined sprite.  Pillow grows
        # TTF bounding boxes symmetrically for stroke_width, so this preserves
        # the glyph's original baseline while keeping the requested offset exact.
        body_dx = (sprite.width - shadow_body.width) // 2
        body_dy = (sprite.height - shadow_body.height) // 2
        alpha = shadow_body.getchannel("A")
        shadow = Image.new("RGBA", shadow_body.size, (*shadow_color,255))
        shadow.putalpha(alpha)
        im.alpha_composite(shadow, (tx + body_dx + shadow_x, ty + body_dy + shadow_y))
    im.alpha_composite(sprite, (tx,ty))
    im = _apply_text_post_effect(im, layer, elapsed)

    _TEXT_LAYER_CACHE[cache_key] = im.copy()
    if len(_TEXT_LAYER_CACHE) > 256:
        for key in list(_TEXT_LAYER_CACHE)[:-192]:
            _TEXT_LAYER_CACHE.pop(key, None)
    return im


def _render_scene_text_scroll_content(layer: dict, box_w: int, box_h: int, sy: float, elapsed: float, now: datetime,
                                      upload_fonts_dir: str, axis: str) -> Image.Image:
    """Render the *whole* text item for a Designer scrolling layer.

    The layer's W/H rectangle is a viewport.  The text itself is deliberately
    allowed to be wider/taller than that viewport, then the scroll compositor
    clips it to the layer rectangle.  This prevents a ticker from leaking into
    neighbouring areas of the sign while still allowing the complete message
    to pass through the viewport.
    """
    text = _layer_text_value(layer, now, elapsed)
    axis = "y" if axis == "y" else "x"
    cache_fields = {k: layer.get(k) for k in (
        "font", "font_size", "auto_fit", "wrap", "color", "outline_color", "outline_width",
        "padding", "align", "valign", "line_spacing", "shadow_color", "shadow_x", "shadow_y",
        "render_mode", "pixel_scale", "pixel_bold", "letter_spacing", "text_transform",
        "overflow", "color_effect", "color2", "color_speed", "color_palette", "glow", "glow_color"
    )}
    animated_color = str(layer.get("color_effect") or "none").lower() in ("rainbow", "cycle")
    cache_key = json.dumps(["scroll-content", axis, box_w, box_h, round(sy, 5), text, cache_fields, round(elapsed, 2) if animated_color else 0],
                           sort_keys=True, default=str)
    cached = _TEXT_LAYER_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()

    pad = max(0, int(round(float(layer.get("padding", 0) or 0) * sy)))
    inner_w, inner_h = max(1, box_w - pad * 2), max(1, box_h - pad * 2)
    font_size = max(4, int(round(float(layer.get("font_size", 18) or 18) * sy)))
    stroke = max(0, int(round(float(layer.get("outline_width", 0) or 0) * sy)))
    align = str(layer.get("align") or "center")
    if align not in ("left", "center", "right"):
        align = "center"
    overflow = str(layer.get("overflow") or "manual").lower()
    wrap = bool(layer.get("wrap", False)) or overflow == "wrap"
    auto_fit = bool(layer.get("auto_fit", False)) or overflow == "shrink"
    if overflow in ("clip", "marquee"): wrap = False
    spacing_ratio = max(0.0, min(1.0, float(layer.get("line_spacing", 0.12) or 0.0)))
    render_mode = str(layer.get("render_mode") or "smooth").lower()
    if render_mode not in ("smooth", "pixel") and not _is_led_mode(render_mode):
        render_mode = "smooth"
    pixel_scale = max(1, min(8, int(layer.get("pixel_scale", 1) or 1)))
    pixel_bold = bool(layer.get("pixel_bold", False))
    letter_spacing = max(0, min(8, int(layer.get("letter_spacing", 0) or 0)))
    color = _hex_color(str(layer.get("color") or "#ffffff"), "#ffffff")
    outline = _hex_color(str(layer.get("outline_color") or "#000000"), "#000000")
    shadow_x = int(round(float(layer.get("shadow_x", 0) or 0) * sy))
    shadow_y = int(round(float(layer.get("shadow_y", 0) or 0) * sy))
    needs_shadow = bool(shadow_x or shadow_y)
    shadow_body = None

    # Horizontal tickers should preserve their natural width.  Vertical
    # scrollers preserve natural height but may still wrap to the layer width.
    if _is_led_mode(render_mode):
        requested_scale = pixel_scale
        if auto_fit:
            if axis == "x":
                # Auto-fit to height only; fitting width would defeat scrolling.
                for sc in range(8, 0, -1):
                    _, hh = _led_dimensions(text or " ", sc, letter_spacing, pixel_bold,
                                             max(1, int(round(1 + spacing_ratio * 4))))
                    if hh <= inner_h:
                        requested_scale = sc
                        break
            else:
                # For a vertical crawl, fit the line width, not the total height.
                for sc in range(8, 0, -1):
                    laid = _led_wrap(text or " ", max(1, inner_w // max(1, (6 + letter_spacing) * sc))) if wrap else (text or " ")
                    ww, _ = _led_dimensions(laid, sc, letter_spacing, pixel_bold,
                                             max(1, int(round(1 + spacing_ratio * 4))))
                    if ww <= inner_w:
                        requested_scale = sc
                        break
        line_gap = max(1, int(round(1 + spacing_ratio * 4)))
        if axis == "x":
            sprite = _render_led_sprite(
                text, 65535, inner_h, color, outline, stroke, requested_scale,
                False, False, align, pixel_bold, letter_spacing, line_gap, render_mode
            )
            if needs_shadow:
                shadow_body = _render_led_sprite(
                    text, 65535, inner_h, color, outline, 0, requested_scale,
                    False, False, align, pixel_bold, letter_spacing, line_gap, render_mode
                )
        else:
            # Give the renderer a very tall area so wrapped content is not clipped.
            sprite = _render_led_sprite(
                text, inner_w, 65535, color, outline, stroke, requested_scale,
                False, wrap, align, pixel_bold, letter_spacing, line_gap, render_mode
            )
            if needs_shadow:
                shadow_body = _render_led_sprite(
                    text, inner_w, 65535, color, outline, 0, requested_scale,
                    False, wrap, align, pixel_bold, letter_spacing, line_gap, render_mode
                )
    else:
        if auto_fit:
            if axis == "x":
                font, font_size = _fit_layer_font(text, 32768, inner_h, str(layer.get("font") or ""),
                                                  upload_fonts_dir, False, align, spacing_ratio, stroke)
            else:
                font, font_size = _fit_layer_font(text, inner_w, 32768, str(layer.get("font") or ""),
                                                  upload_fonts_dir, wrap, align, spacing_ratio, stroke)
        else:
            font = _load_font(str(layer.get("font") or ""), font_size, upload_fonts_dir)
        spacing = max(0, int(round(font_size * spacing_ratio)))
        probe = ImageDraw.Draw(Image.new("RGBA", (4, 4), (0, 0, 0, 0)))
        laid_out = _wrap_text_pixels(text, font, inner_w, probe, stroke) if (axis == "y" and wrap) else text
        sprite = _render_ttf_sprite(laid_out, font, color, outline, stroke, spacing, align,
                                    render_mode, pixel_scale, pixel_bold, letter_spacing)
        if needs_shadow:
            shadow_body = _render_ttf_sprite(laid_out, font, color, outline, 0, spacing, align,
                                             render_mode, pixel_scale, pixel_bold, letter_spacing)

    # Keep the shadow as part of the moving item instead of letting it escape the
    # clipping viewport independently.
    shadow_color = _hex_color(str(layer.get("shadow_color") or "#000000"), "#000000")
    if needs_shadow and shadow_body is not None:
        body_dx = (sprite.width - shadow_body.width) // 2
        body_dy = (sprite.height - shadow_body.height) // 2
        shadow_left = body_dx + shadow_x
        shadow_top = body_dy + shadow_y
        min_x = min(0, shadow_left)
        min_y = min(0, shadow_top)
        max_x = max(sprite.width, shadow_left + shadow_body.width)
        max_y = max(sprite.height, shadow_top + shadow_body.height)
        out = Image.new("RGBA", (max_x - min_x, max_y - min_y), (0, 0, 0, 0))
        alpha = shadow_body.getchannel("A")
        shadow = Image.new("RGBA", shadow_body.size, (*shadow_color, 255)); shadow.putalpha(alpha)
        out.alpha_composite(shadow, (shadow_left - min_x, shadow_top - min_y))
        out.alpha_composite(sprite, (-min_x, -min_y))
        sprite = out

    sprite = _apply_sprite_color_effect(sprite, layer, elapsed)
    sprite = _with_glow(sprite, layer)
    _TEXT_LAYER_CACHE[cache_key] = sprite.copy()
    if len(_TEXT_LAYER_CACHE) > 256:
        for key in list(_TEXT_LAYER_CACHE)[:-192]:
            _TEXT_LAYER_CACHE.pop(key, None)
    return sprite


def _render_scroll_viewport(layer: dict, content: Image.Image, box_w: int, box_h: int, sy: float,
                            elapsed: float, direction: str) -> tuple[Image.Image, bool]:
    """Move content *inside* a fixed layer rectangle and clip at its edges."""
    viewport = Image.new("RGBA", (max(1, box_w), max(1, box_h)), (0, 0, 0, 0))
    speed = max(0.0, float(layer.get("speed", 30) or 0))
    delay = max(0.0, float(layer.get("delay", 0.0) or 0.0))
    local = elapsed - delay
    if local < 0:
        return viewport, False

    is_text = str(layer.get("type") or "text") in ("text", "cloud-text", "widget")
    pad = max(0, int(round(float(layer.get("padding", 0) or 0) * sy))) if is_text else 0
    left, top = pad, pad
    inner_w, inner_h = max(1, box_w - pad * 2), max(1, box_h - pad * 2)
    align = str(layer.get("align") or "center") if is_text else "center"
    valign = str(layer.get("valign") or "middle") if is_text else "middle"

    if direction in ("scroll-left", "scroll-right"):
        travel = inner_w + content.width
        phase = (local * speed) % max(1.0, float(travel))
        if direction == "scroll-left":
            cx = left + int(inner_w - phase)
        else:
            cx = left + int(-content.width + phase)
        cy = top + _align_pos(inner_h, content.height, valign, 0)
    else:
        travel = inner_h + content.height
        phase = (local * speed) % max(1.0, float(travel))
        if direction == "scroll-up":
            cy = top + int(inner_h - phase)
        else:
            cy = top + int(-content.height + phase)
        cx = left + _align_pos(inner_w, content.width, align, 0)

    # Composite onto an inner transparent viewport first so padding is also a
    # clipping boundary. Then put that viewport into the full layer rectangle.
    inner = Image.new("RGBA", (inner_w, inner_h), (0, 0, 0, 0))
    inner.alpha_composite(content, (cx - left, cy - top))
    viewport.alpha_composite(inner, (left, top))
    return viewport, True



def _crop_visible_rgba(im: Image.Image) -> Image.Image:
    """Crop transparent margins from an RGBA layer without losing visible pixels."""
    rgba = im.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if not bbox:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    return rgba.crop(bbox)


def _render_bounce_viewport(layer: dict, content: Image.Image, box_w: int, box_h: int, sy: float,
                            elapsed: float, direction: str) -> tuple[Image.Image, bool]:
    """Bounce visible content inside a fixed layer viewport.

    The layer's x/y/w/h never move.  Only the visible content moves inside that
    rectangle, and all compositing is clipped to the viewport (and text
    padding).  This prevents bounce animations from leaking over adjacent
    Designer regions.
    """
    viewport = Image.new("RGBA", (max(1, box_w), max(1, box_h)), (0, 0, 0, 0))
    speed = max(0.0, float(layer.get("speed", 30) or 0))
    delay = max(0.0, float(layer.get("delay", 0.0) or 0.0))
    local = elapsed - delay
    if local < 0:
        return viewport, False

    is_text = str(layer.get("type") or "text") in ("text", "cloud-text", "widget")
    pad = max(0, int(round(float(layer.get("padding", 0) or 0) * sy))) if is_text else 0
    inner_w, inner_h = max(1, box_w - pad * 2), max(1, box_h - pad * 2)
    align = str(layer.get("align") or "center") if is_text else "center"
    valign = str(layer.get("valign") or "middle") if is_text else "middle"

    sprite = _crop_visible_rgba(content)
    if direction == "bounce-horizontal":
        travel = max(0, inner_w - sprite.width)
        cx = int(round(_triangle_wave(local * speed, travel)))
        cy = _align_pos(inner_h, sprite.height, valign, 0)
    else:
        travel = max(0, inner_h - sprite.height)
        cy = int(round(_triangle_wave(local * speed, travel)))
        cx = _align_pos(inner_w, sprite.width, align, 0)

    # The inner surface is the hard clipping window.  Pillow's alpha_composite
    # clips automatically when the sprite is partly outside it (e.g. a rotated
    # or oversized item), so no pixel can escape the defined layer box.
    inner = Image.new("RGBA", (inner_w, inner_h), (0, 0, 0, 0))
    inner.alpha_composite(sprite, (cx, cy))
    viewport.alpha_composite(inner, (pad, pad))
    return viewport, True

def _render_scene_image(layer: dict, box_w: int, box_h: int, elapsed: float) -> Image.Image:
    src = _load_image(
        str(layer.get("image_path") or ""), elapsed,
        float(layer.get("media_speed", 1.0) or 1.0), bool(layer.get("media_loop", True))
    )
    if src is None:
        # Visible placeholder in preview/output makes a missing asset obvious without crashing the renderer.
        im = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, max(0, box_w - 1), max(0, box_h - 1)), outline=(120, 120, 120, 180))
        d.line((0, 0, max(0, box_w - 1), max(0, box_h - 1)), fill=(120, 120, 120, 180))
        d.line((max(0, box_w - 1), 0, 0, max(0, box_h - 1)), fill=(120, 120, 120, 180))
        return im
    fit = str(layer.get("fit") or "contain")
    if fit == "cover":
        return _cover(src, (box_w, box_h)).convert("RGBA")
    if fit == "stretch":
        return src.resize((box_w, box_h), Image.Resampling.LANCZOS).convert("RGBA")
    contained = _contain(src, (box_w, box_h)).convert("RGBA")
    out = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    out.alpha_composite(contained, ((box_w - contained.width) // 2, (box_h - contained.height) // 2))
    return out


def _render_scene_video(layer: dict, box_w: int, box_h: int, elapsed: float) -> Image.Image:
    src = _load_video_frame(
        str(layer.get("video_path") or ""), elapsed,
        float(layer.get("media_speed", 1.0) or 1.0), bool(layer.get("media_loop", True))
    )
    if src is None:
        im = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, max(0, box_w-1), max(0, box_h-1)), outline=(150,80,80,220))
        d.text((2,2), "VIDEO", fill=(200,120,120,255), font=ImageFont.load_default())
        return im
    fit = str(layer.get("fit") or "contain")
    if fit == "cover": return _cover(src, (box_w, box_h)).convert("RGBA")
    if fit == "stretch": return src.resize((box_w, box_h), Image.Resampling.LANCZOS).convert("RGBA")
    contained = _contain(src, (box_w, box_h)).convert("RGBA")
    out = Image.new("RGBA", (box_w, box_h), (0,0,0,0))
    out.alpha_composite(contained, ((box_w-contained.width)//2, (box_h-contained.height)//2))
    return out


def _render_analog_clock(layer: dict, box_w: int, box_h: int, now: datetime) -> Image.Image:
    """Render a crisp analogue clock directly into the layer viewport."""
    w,h=max(1,int(box_w)),max(1,int(box_h))
    im=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(im)
    cx=(w-1)/2.0; cy=(h-1)/2.0; r=max(2.0,min(w,h)/2.0-1.0)
    face=_hex_color(str(layer.get("clock_face_color") or "#000000"),"#000000")
    ring=_hex_color(str(layer.get("clock_ring_color") or layer.get("color") or "#ffffff"),"#ffffff")
    tick=_hex_color(str(layer.get("clock_tick_color") or ring),"#ffffff")
    hourc=_hex_color(str(layer.get("clock_hour_color") or ring),"#ffffff")
    minc=_hex_color(str(layer.get("clock_minute_color") or ring),"#ffffff")
    secc=_hex_color(str(layer.get("clock_second_color") or "#ff3030"),"#ff3030")
    fill_face=bool(layer.get("clock_fill_face",False)); show_seconds=bool(layer.get("clock_show_seconds",True))
    show_quarters=bool(layer.get("clock_show_quarters",True))
    bbox=(int(round(cx-r)),int(round(cy-r)),int(round(cx+r)),int(round(cy+r)))
    if fill_face: d.ellipse(bbox,fill=(*face,255),outline=(*ring,255),width=1)
    else: d.ellipse(bbox,outline=(*ring,255),width=1)
    # Minute ticks, with stronger quarter-hour marks. Integer endpoints make the
    # clock look clean on a 32-pixel-high matrix.
    for i in range(60):
        if i%5 and min(w,h)<24: continue
        ang=math.radians(i*6-90); major=(i%15==0)
        if not show_quarters and major: major=False
        inner=r-(3 if major else (2 if i%5==0 else 1))
        x1=int(round(cx+math.cos(ang)*inner)); y1=int(round(cy+math.sin(ang)*inner))
        x2=int(round(cx+math.cos(ang)*(r-1))); y2=int(round(cy+math.sin(ang)*(r-1)))
        d.line((x1,y1,x2,y2),fill=(*tick,255),width=1)
    hour=(now.hour%12)+now.minute/60.0+now.second/3600.0
    minute=now.minute+now.second/60.0
    second=now.second+now.microsecond/1_000_000.0
    def hand(value,units,length,color,width=1):
        ang=math.radians(value*(360.0/units)-90)
        x=int(round(cx+math.cos(ang)*r*length)); y=int(round(cy+math.sin(ang)*r*length))
        d.line((int(round(cx)),int(round(cy)),x,y),fill=(*color,255),width=max(1,width))
    hand(hour,12,.48,hourc,2 if min(w,h)>=28 else 1)
    hand(minute,60,.72,minc,1)
    if show_seconds: hand(second,60,.82,secc,1)
    d.point((int(round(cx)),int(round(cy))),fill=(*ring,255))
    return im


def _render_scene_shape(layer: dict, box_w: int, box_h: int, sy: float) -> Image.Image:
    im = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fill = _hex_color(str(layer.get("fill") or "#2255aa"), "#2255aa")
    border = _hex_color(str(layer.get("border_color") or "#ffffff"), "#ffffff")
    bw = max(0, int(round(float(layer.get("border_width", 0) or 0) * sy)))
    shape = str(layer.get("shape") or "rectangle")
    xy = (0, 0, max(0, box_w - 1), max(0, box_h - 1))
    kwargs = {"fill": (*fill, 255)}
    if bw:
        kwargs.update({"outline": (*border, 255), "width": bw})
    if shape == "ellipse":
        d.ellipse(xy, **kwargs)
    else:
        radius = max(0, int(round(float(layer.get("radius", 0) or 0) * sy)))
        if shape == "rounded" or radius:
            d.rounded_rectangle(xy, radius=min(radius, max(0, min(box_w, box_h) // 2)), **kwargs)
        else:
            d.rectangle(xy, **kwargs)
    return im



def _draw_builtin_icon(name: str, box_w: int, box_h: int, color: tuple[int,int,int],
                       color2: tuple[int,int,int], phase: float = 0.0) -> Image.Image:
    """Draw one of the built-in signage pictograms directly at LED resolution.

    The artwork deliberately uses Pillow primitives on the final pixel grid rather
    than SVG/TTF glyphs.  That makes every edge deterministic and crisp on P5/P10
    matrices and keeps the icon library self-contained.
    """
    w,h=max(1,int(box_w)),max(1,int(box_h)); im=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(im)
    fg=(*color,255); accent=(*color2,255); m=max(1,min(w,h)); lw=max(1,int(round(m/11)))
    X=lambda v:int(round((w-1)*v/31.0)); Y=lambda v:int(round((h-1)*v/31.0))
    P=lambda pts:[(X(x),Y(y)) for x,y in pts]
    name=str(name or "info").lower()

    if name.startswith("arrow-"):
        if name=="arrow-left": pts=[(3,16),(15,4),(15,11),(29,11),(29,21),(15,21),(15,28)]
        elif name=="arrow-up": pts=[(16,3),(28,15),(21,15),(21,29),(11,29),(11,15),(4,15)]
        elif name=="arrow-down": pts=[(16,29),(28,17),(21,17),(21,3),(11,3),(11,17),(4,17)]
        else: pts=[(29,16),(17,4),(17,11),(3,11),(3,21),(17,21),(17,28)]
        d.polygon(P(pts),fill=fg)
    elif name=="warning":
        d.polygon(P([(16,2),(30,28),(2,28)]),outline=fg,width=lw)
        d.line((X(16),Y(9),X(16),Y(19)),fill=fg,width=lw)
        r=max(1,lw//2);d.ellipse((X(16)-r,Y(23)-r,X(16)+r,Y(23)+r),fill=fg)
    elif name=="info":
        d.ellipse((X(3),Y(3),X(28),Y(28)),outline=fg,width=lw)
        r=max(1,lw);d.ellipse((X(16)-r,Y(8)-r,X(16)+r,Y(8)+r),fill=fg)
        d.line((X(16),Y(13),X(16),Y(23)),fill=fg,width=lw)
    elif name=="wheelchair":
        d.ellipse((X(12),Y(2),X(18),Y(8)),fill=fg)
        d.line(P([(14,9),(13,18),(21,18),(25,25)]),fill=fg,width=lw)
        d.line(P([(14,12),(21,13)]),fill=fg,width=lw)
        d.ellipse((X(5),Y(14),X(22),Y(30)),outline=fg,width=lw)
    elif name=="toilet":
        # Two universally recognisable person silhouettes rather than letters.
        for cx in (10,22): d.ellipse((X(cx-2),Y(3),X(cx+2),Y(7)),fill=fg)
        d.line((X(10),Y(9),X(10),Y(20)),fill=fg,width=lw);d.line((X(22),Y(9),X(22),Y(20)),fill=fg,width=lw)
        d.line(P([(6,12),(10,9),(14,12)]),fill=fg,width=lw);d.line(P([(18,12),(22,9),(26,12)]),fill=fg,width=lw)
        d.line(P([(10,20),(7,29)]),fill=fg,width=lw);d.line(P([(10,20),(13,29)]),fill=fg,width=lw)
        d.polygon(P([(18,20),(22,9),(26,20)]),outline=fg)
        d.line(P([(22,20),(19,29)]),fill=fg,width=lw);d.line(P([(22,20),(25,29)]),fill=fg,width=lw)
    elif name=="parking":
        d.rounded_rectangle((X(2),Y(2),X(29),Y(29)),radius=max(1,m//8),outline=fg,width=lw)
        d.line((X(11),Y(24),X(11),Y(8)),fill=fg,width=lw)
        d.line((X(11),Y(8),X(19),Y(8)),fill=fg,width=lw)
        d.arc((X(14),Y(8),X(24),Y(18)),start=270,end=90,fill=fg,width=lw)
        d.line((X(19),Y(18),X(11),Y(18)),fill=fg,width=lw)
    elif name=="wifi":
        active=3 if phase<=0 else max(1,min(3,1+int(phase*3)%3))
        boxes=[(5,9,27,27),(9,14,23,27),(13,20,19,27)]
        for i,b in enumerate(boxes):
            c=fg if (phase<=0 or i>=3-active) else accent
            d.arc((X(b[0]),Y(b[1]),X(b[2]),Y(b[3])),start=205,end=335,fill=c,width=lw)
        d.ellipse((X(14),Y(25),X(18),Y(29)),fill=fg)
    elif name=="phone":
        # Chunky handset silhouette that survives very small matrices.
        pts=[(7,4),(12,3),(15,9),(12,12),(15,18),(20,21),(23,18),(29,21),(28,26),(24,29),(17,27),(10,22),(5,15),(3,8)]
        d.polygon(P(pts),fill=fg)
    elif name=="tick":
        d.line(P([(4,17),(12,25),(28,7)]),fill=fg,width=max(lw,2))
    elif name=="cross":
        d.line(P([(6,6),(26,26)]),fill=fg,width=max(lw,2));d.line(P([(26,6),(6,26)]),fill=fg,width=max(lw,2))
    elif name=="heart":
        d.polygon(P([(16,29),(4,18),(3,10),(7,5),(12,5),(16,9),(20,5),(25,5),(29,10),(28,18)]),fill=fg)
    elif name=="smile":
        d.ellipse((X(3),Y(3),X(28),Y(28)),outline=fg,width=lw)
        er=max(1,lw//2);d.ellipse((X(11)-er,Y(12)-er,X(11)+er,Y(12)+er),fill=fg);d.ellipse((X(21)-er,Y(12)-er,X(21)+er,Y(12)+er),fill=fg)
        d.arc((X(9),Y(11),X(23),Y(24)),start=25,end=155,fill=fg,width=lw)
    elif name=="walking":
        swing=math.sin(float(phase)*math.tau)*5.0
        d.ellipse((X(13),Y(2),X(19),Y(8)),fill=fg)
        d.line((X(16),Y(9),X(15),Y(19)),fill=fg,width=lw)
        d.line((X(15),Y(13),X(8+swing),Y(17)),fill=fg,width=lw);d.line((X(15),Y(13),X(23-swing),Y(10)),fill=fg,width=lw)
        d.line((X(15),Y(19),X(8-swing),Y(29)),fill=fg,width=lw);d.line((X(15),Y(19),X(24+swing),Y(27)),fill=fg,width=lw)
    elif name=="bell":
        d.arc((X(7),Y(5),X(25),Y(25)),start=190,end=350,fill=fg,width=lw)
        d.line(P([(8,17),(6,24),(26,24),(24,17)]),fill=fg,width=lw)
        d.ellipse((X(14),Y(25),X(18),Y(29)),fill=fg)
    elif name=="star":
        pts=[]
        for i in range(10):
            a=math.radians(-90+i*36);r=14 if i%2==0 else 6
            pts.append((16+math.cos(a)*r,16+math.sin(a)*r))
        d.polygon([(X(x),Y(y)) for x,y in pts],fill=fg)
    elif name=="gift":
        d.rectangle((X(5),Y(12),X(27),Y(28)),outline=fg,width=lw);d.line((X(16),Y(12),X(16),Y(28)),fill=fg,width=lw);d.line((X(5),Y(17),X(27),Y(17)),fill=fg,width=lw)
        d.arc((X(7),Y(3),X(16),Y(14)),start=180,end=360,fill=fg,width=lw);d.arc((X(16),Y(3),X(25),Y(14)),start=180,end=360,fill=fg,width=lw)
    elif name=="snowflake":
        cx,cy=X(16),Y(16);r=max(4,int(m*.42))
        for deg in (0,60,120):
            a=math.radians(deg);dx=int(round(math.cos(a)*r));dy=int(round(math.sin(a)*r));d.line((cx-dx,cy-dy,cx+dx,cy+dy),fill=fg,width=lw)
    elif name=="sale-tag":
        d.polygon(P([(3,8),(18,3),(29,14),(15,28),(3,16)]),outline=fg,width=lw)
        d.ellipse((X(7),Y(10),X(10),Y(13)),fill=fg)
        d.ellipse((X(13),Y(10),X(17),Y(14)),outline=fg,width=max(1,lw//2));d.ellipse((X(20),Y(18),X(24),Y(22)),outline=fg,width=max(1,lw//2));d.line(P([(14,22),(23,10)]),fill=fg,width=max(1,lw//2))
    elif name=="queue":
        for cx,cy,scale in ((8,15,.72),(16,12,1.0),(25,16,.65)):
            rr=max(1,int(m*.09*scale));d.ellipse((X(cx)-rr,Y(cy-7)-rr,X(cx)+rr,Y(cy-7)+rr),fill=fg)
            d.line((X(cx),Y(cy-3),X(cx),Y(cy+7)),fill=fg,width=lw);d.line(P([(cx,cy+2),(cx-4*scale,cy+10)]),fill=fg,width=lw);d.line(P([(cx,cy+2),(cx+4*scale,cy+10)]),fill=fg,width=lw)
    else:
        d.rectangle((X(5),Y(5),X(26),Y(26)),outline=fg,width=lw);d.line(P([(8,8),(24,24)]),fill=fg,width=lw)
    return im


def _icon_scale_center(im: Image.Image, scale: float) -> Image.Image:
    w,h=im.size;scale=max(.08,min(1.5,float(scale)));nw=max(1,int(round(w*scale)));nh=max(1,int(round(h*scale)))
    small=im.resize((nw,nh),Image.Resampling.NEAREST);out=Image.new("RGBA",(w,h),(0,0,0,0));out.alpha_composite(small,((w-nw)//2,(h-nh)//2));return out


def _render_scene_icon(layer: dict, box_w: int, box_h: int, elapsed: float) -> Image.Image:
    w,h=max(1,int(box_w)),max(1,int(box_h));name=str(layer.get("icon_name") or "info").lower()
    c1=_hex_color(str(layer.get("icon_color") or layer.get("color") or "#ffffff"),"#ffffff")
    c2=_hex_color(str(layer.get("icon_color2") or "#31506a"),"#31506a")
    effect=str(layer.get("icon_effect") or "none").lower();period=max(.15,float(layer.get("icon_period",1.0) or 1.0));phase=(max(0.0,elapsed)/period)%1.0

    # Chase is purpose-built for direction arrows: three compact arrows light in
    # sequence while the layer itself can still be static, scrolling or bouncing.
    if effect=="chase" and name in ("arrow-left","arrow-right","arrow-up","arrow-down"):
        out=Image.new("RGBA",(w,h),(0,0,0,0));active=int(phase*3)%3
        horizontal=name in ("arrow-left","arrow-right")
        for i in range(3):
            idx=(2-i) if name in ("arrow-left","arrow-up") else i
            bright=(idx==active); col=c1 if bright else c2
            if horizontal:
                x0=int(round(i*w/3));x1=int(round((i+1)*w/3));part=_draw_builtin_icon(name,max(1,x1-x0),h,col,c2,phase);out.alpha_composite(part,(x0,0))
            else:
                y0=int(round(i*h/3));y1=int(round((i+1)*h/3));part=_draw_builtin_icon(name,w,max(1,y1-y0),col,c2,phase);out.alpha_composite(part,(0,y0))
        return out

    native_phase=phase if effect=="native" else 0.0
    im=_draw_builtin_icon(name,w,h,c1,c2,native_phase)
    if effect=="flash":
        return im if phase<.55 else Image.new("RGBA",(w,h),(0,0,0,0))
    if effect=="pulse" or (effect=="native" and name=="heart"):
        scale=.72+.28*(.5+.5*math.sin(phase*math.tau-math.pi/2));return _icon_scale_center(im,scale)
    if effect=="spin":
        return im.rotate(-phase*360.0,resample=Image.Resampling.NEAREST,expand=False)
    if effect=="wiggle" or (effect=="native" and name=="bell"):
        ang=math.sin(phase*math.tau)*14.0;return im.rotate(-ang,resample=Image.Resampling.NEAREST,expand=False)
    # Walking and Wi-Fi use their own phase in the primitive drawing routine.
    return im



def _weather_draw_sun(out: Image.Image, cx: int, cy: int, radius: int, phase: float, colour=(255, 205, 40)):
    draw = ImageDraw.Draw(out)
    radius = max(2, int(radius)); ray0 = radius + 2; ray1 = radius + 5
    width = max(1, radius // 4)
    angle_offset = phase * math.tau * 0.18
    for i in range(8):
        a = angle_offset + i * math.tau / 8.0
        x0 = int(round(cx + math.cos(a) * ray0)); y0 = int(round(cy + math.sin(a) * ray0))
        x1 = int(round(cx + math.cos(a) * ray1)); y1 = int(round(cy + math.sin(a) * ray1))
        draw.line((x0, y0, x1, y1), fill=(*colour, 255), width=width)
    draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=(*colour, 255))


def _weather_draw_cloud(out: Image.Image, x: int, y: int, w: int, h: int, colour=(205, 220, 230)):
    draw = ImageDraw.Draw(out); w=max(8,int(w));h=max(5,int(h))
    base_y=y+max(2,h//2); r1=max(2,h//3); r2=max(3,h//2)
    draw.ellipse((x+w//7-r1,base_y-r1,x+w//7+r1,base_y+r1),fill=(*colour,255))
    draw.ellipse((x+w//2-r2,base_y-r2-1,x+w//2+r2,base_y+r2-1),fill=(*colour,255))
    draw.ellipse((x+5*w//6-r1,base_y-r1,x+5*w//6+r1,base_y+r1),fill=(*colour,255))
    draw.rectangle((x+w//7,base_y-r1//2,x+5*w//6,base_y+r1),fill=(*colour,255))


def _weather_wind_motion(wind_speed=0.0, wind_direction=None, wind_unit: str = "mph") -> tuple[float, float]:
    """Return a compact LED-animation velocity (vx, vy) in pixels/second.

    Open-Meteo reports the meteorological direction the wind is *from*.  The
    animation moves weather features towards the opposite direction.  Vertical
    movement is deliberately damped because the icon is normally only 16-32
    pixels high, while the horizontal component remains obvious enough to read
    as drifting rather than bouncing.
    """
    try:
        speed=max(0.0,float(wind_speed or 0.0))
    except Exception:
        speed=0.0
    unit=str(wind_unit or "mph").lower()
    mph=speed/1.609344 if unit in ("km/h","kmh","kph") else speed
    # Almost still below ~1mph, gently progressive through normal UK winds,
    # capped so a storm does not turn a 32px icon into an unreadable blur.
    pxps=0.04 if mph < 0.5 else min(4.5, 0.16 + mph * 0.11)
    try:
        from_deg=float(wind_direction if wind_direction is not None else 270.0) % 360.0
    except Exception:
        from_deg=270.0
    toward=math.radians((from_deg + 180.0) % 360.0)
    vx=pxps * math.sin(toward)
    vy=-pxps * math.cos(toward) * 0.22
    return vx,vy


def _weather_wrapped_x(elapsed: float, start_x: float, vx: float, canvas_w: int, object_w: int) -> tuple[int, int, int]:
    """Continuous one-way drift with wrap-around, never a reversing bounce."""
    span=max(1.0,float(canvas_w + object_w + 2))
    x=((float(start_x) + max(0.0,float(elapsed))*float(vx) + object_w + 1) % span) - object_w - 1
    base=int(round(x))
    return base, int(round(x-span)), int(round(x+span))


def _weather_draw_wrapped_cloud(out: Image.Image, start_x: float, y: int, cw: int, ch: int,
                                elapsed: float, vx: float, colour) -> None:
    for x in _weather_wrapped_x(elapsed,start_x,vx,out.size[0],cw):
        if x < out.size[0] and x+cw >= 0:
            _weather_draw_cloud(out,x,y,cw,ch,colour)


def _weather_draw_icon(category: str, width: int, height: int, elapsed: float, is_day: bool = True,
                       animate: bool = True, wind_speed: float = 0.0, wind_direction=None,
                       wind_unit: str = "mph") -> Image.Image:
    """Draw a compact weather pictogram whose motion follows the live weather.

    Clouds and fog drift continuously and wrap rather than bouncing.  Wind
    speed controls the travel speed, while meteorological wind direction sets
    the motion direction.  Rain/snow inherit the same horizontal wind vector.
    """
    w,h=max(1,int(width)),max(1,int(height));out=Image.new("RGBA",(w,h),(0,0,0,0))
    elapsed=max(0.0,float(elapsed)); phase=((elapsed/1.6)%1.0) if animate else 0.0
    category=str(category or "cloudy").lower(); pad=max(1,min(w,h)//16)
    cloud=(205,220,230); dark_cloud=(145,165,180); sun=(255,205,40); rain=(70,170,255); snow=(245,250,255); fog=(165,185,195); lightning=(255,220,40)
    cx=w//2; size=min(w,h)
    vx,vy=_weather_wind_motion(wind_speed,wind_direction,wind_unit) if animate else (0.0,0.0)

    if category=="clear":
        if is_day:
            _weather_draw_sun(out,cx,h//2,max(2,size//6),phase,sun)
        else:
            d=ImageDraw.Draw(out);r=max(3,size//5);d.ellipse((cx-r,h//2-r,cx+r,h//2+r),fill=(190,215,255,255));d.ellipse((cx-r//3,h//2-r,cx+r+1,h//2+r-1),fill=(0,0,0,0))
            for sx,sy in ((pad+2,pad+2),(w-pad-3,pad+5)):
                d.point((sx,sy),fill=(255,255,220,255))
                if size>=20:d.point((sx+1,sy),fill=(255,255,220,255))
        return out

    cloud_y=max(1,h//5)
    cloud_h=max(5,h//3)
    cloud_w=max(8,3*w//4)

    if category=="partly-cloudy":
        # Sun/moon remains a stable reference while the cloud travels past it.
        if is_day:_weather_draw_sun(out,max(4,w//3),max(5,h//3),max(2,size//8),phase,sun)
        else:
            d=ImageDraw.Draw(out);r=max(2,size//8);d.ellipse((w//3-r,h//3-r,w//3+r,h//3+r),fill=(190,215,255,255))
        y=max(1,h//3 + int(round(vy*.35)))
        _weather_draw_wrapped_cloud(out,w//5,y,cloud_w,cloud_h,elapsed,vx,cloud)
        return out

    if category=="fog":
        # Multiple independently moving mist bands feel more natural than a
        # cloud bouncing over static lines.  Slightly different speeds create
        # parallax while all bands still honour the real wind direction.
        draw=ImageDraw.Draw(out)
        base_y=max(3,h//4)
        lengths=(max(7,w-5),max(6,w-10),max(8,w-7),max(5,w-14))
        factors=(.55,.8,1.0,.68)
        for i,(length,factor) in enumerate(zip(lengths,factors)):
            yy=min(h-2,base_y-7+i*3)
            band_vx=vx*factor
            for x in _weather_wrapped_x(elapsed,2+i*3,band_vx,w,length):
                if x<w and x+length>=0:
                    draw.line((x,yy,x+length,yy),fill=(*fog,255),width=1 if size<24 else 2)
        return out

    # Cloud-bearing weather.  A second, subtler cloud on overcast conditions
    # adds depth and makes stronger wind visibly more dynamic without bouncing.
    cloud_colour=dark_cloud if category=="thunder" else cloud
    _weather_draw_wrapped_cloud(out,w//8,cloud_y,cloud_w,cloud_h,elapsed,vx,cloud_colour)
    if category=="cloudy" and w>=20:
        small_w=max(8,int(cloud_w*.60)); small_h=max(5,int(cloud_h*.72))
        _weather_draw_wrapped_cloud(out,w//2,max(0,cloud_y-2),small_w,small_h,elapsed,vx*.68,(175,195,208))

    draw=ImageDraw.Draw(out)
    cloud_bottom=max(h//2,cloud_y+cloud_h)
    wind_slant=max(-5.0,min(5.0,vx*1.7))

    if category in ("drizzle","rain","showers"):
        count=4 if w>=22 else 3 if w>=16 else 2
        span=max(4,h-cloud_bottom-1)
        fall_px=2.2 if category=="drizzle" else (5.0 if category=="showers" else 3.5)
        # Vertical speed is mainly gravity; wind adds a small storm intensity cue.
        fall_px += min(2.0,abs(vx)*.35)
        for i in range(count):
            local=(elapsed*fall_px + i*span/max(1,count)) % span if animate else i*span/max(1,count)
            y=cloud_bottom+int(local)
            base_x=(i+1)*w/(count+1)
            x=int(round((base_x + elapsed*vx*.8 + local*wind_slant*.22) % max(1,w)))
            length=1 if category=="drizzle" else max(2,h//9)
            dx=int(round(wind_slant*.35))
            draw.line((x,y,max(0,min(w-1,x+dx)),min(h-1,y+length)),fill=(*rain,255),width=1)
    elif category in ("snow","snow-showers"):
        count=4 if w>=22 else 3
        span=max(4,h-cloud_bottom-1)
        fall_px=1.15 if category=="snow-showers" else .72
        for i in range(count):
            local=(elapsed*fall_px*4 + i*span/max(1,count)) % span if animate else i*span/max(1,count)
            y=cloud_bottom+int(local)
            flutter=math.sin((elapsed*.75+i*.37)*math.tau)*1.4 if animate else 0.0
            x=int(round(((i+1)*w/(count+1) + elapsed*vx*.9 + flutter) % max(1,w)))
            x=max(1,min(w-2,x)); y=max(1,min(h-2,y))
            draw.point((x,y),fill=(*snow,255))
            if size>=20:
                draw.point((x-1,y),fill=(*snow,255));draw.point((x+1,y),fill=(*snow,255));draw.point((x,y-1),fill=(*snow,255));draw.point((x,y+1),fill=(*snow,255))
    elif category=="thunder":
        # Two short deterministic flashes in a ~2.8s cycle look less mechanical.
        flash=(elapsed%2.8)
        if (not animate) or flash<.13 or (.29<flash<.36):
            x=cx;y=cloud_bottom;bolt=[(x-1,y),(x+2,y),(x,y+max(2,h//8)),(x+3,y+max(2,h//8)),(x-2,min(h-2,y+max(5,h//4)))]
            draw.line(bolt,fill=(*lightning,255),width=max(1,size//18),joint="curve")
    return out

def _weather_detail_text(layer: dict, data: dict, elapsed: float = 0.0) -> tuple[str, str]:
    """Return main/detail lines for the animated weather layout."""
    unit=str(data.get("temp_unit") or "°C"); wind_unit=str(data.get("wind_unit") or "mph")
    temp=f"{_weather_number(data.get('temp'),1)}{unit}"
    main=temp
    if bool(layer.get("weather_show_condition", True)):
        main += " " + str(data.get("condition") or "Weather")
    details=[]
    if bool(layer.get("weather_show_feels", True)):
        details.append(f"Feels {_weather_number(data.get('feels'),1)}{unit}")
    if bool(layer.get("weather_show_wind", True)):
        details.append(f"{data.get('wind_compass') or '?'} {_weather_number(data.get('wind'),1)}{wind_unit}")
    if bool(layer.get("weather_show_gusts", False)):
        details.append(f"Gust {_weather_number(data.get('gust'),1)}{wind_unit}")
    if bool(layer.get("weather_show_humidity", False)):
        details.append(f"RH {_weather_number(data.get('humidity'),0)}%")
    if bool(layer.get("weather_show_precip", False)):
        details.append(f"Rain {_weather_number(data.get('precip'),1)}mm")
    if bool(layer.get("weather_cycle_details", True)) and len(details) > 2:
        period=max(1.0,float(layer.get("weather_detail_period",2.5) or 2.5)); start=int(max(0.0,elapsed)/period)%len(details)
        details=[details[start],details[(start+1)%len(details)]]
    return main, "  ·  ".join(details)


def _render_weather_widget(layer: dict, box_w: int, box_h: int, sy: float, elapsed: float,
                           now: datetime, upload_fonts_dir: str) -> Image.Image:
    w,h=max(1,int(box_w)),max(1,int(box_h)); data=_weather_current(layer)
    if str(data.get("status") or "error") != "ok":
        text="Loading…" if data.get("status")=="loading" else "Weather unavailable"
        child=dict(layer);child.update(type="text",text=text,auto_fit=True,wrap=False,animation="static",padding=0)
        return _render_scene_text(child,w,h,sy,elapsed,now,upload_fonts_dir)

    show_icon=bool(layer.get("weather_show_icon",True)); animated=bool(layer.get("weather_animate_icon",True))
    icon_w=0
    out=Image.new("RGBA",(w,h),(0,0,0,0))
    if show_icon and w>=12 and h>=10:
        icon_w=min(h,max(12,min(h,int(round(w*.28)))))
        icon=_weather_draw_icon(
            str(data.get("category") or "cloudy"), icon_w, h, elapsed,
            bool(data.get("is_day",True)), animated,
            data.get("wind") or 0.0, data.get("wind_direction"), str(data.get("wind_unit") or "mph")
        )
        out.alpha_composite(icon,(0,0))
    text_x=icon_w+(1 if icon_w else 0); text_w=max(1,w-text_x)
    main,detail=_weather_detail_text(layer,data,elapsed)
    text=main+("\n"+detail if detail and h>=14 else "")
    child=dict(layer);child.update(type="text",text=text,auto_fit=True,wrap=False,animation="static",padding=0,align="left" if icon_w else str(layer.get("align") or "center"),valign="middle",line_spacing=0)
    rendered=_render_scene_text(child,text_w,h,sy,elapsed,now,upload_fonts_dir)
    out.alpha_composite(rendered,(text_x,0))
    return out


def _cloud_text_entries(layer: dict) -> list[str]:
    raw = layer.get("cloud_text_items")
    values = raw if isinstance(raw, list) else str(raw or "").splitlines()
    entries = []
    seen = set()
    for value in values:
        phrase = str(value).strip()
        key = " ".join(phrase.casefold().split())
        if phrase and key not in seen:
            seen.add(key)
            entries.append(phrase)
        if len(entries) >= 200:
            break
    return entries


def _cloud_text_sequence(entry_count: int, through_occurrence: int, layer_key: str,
                         playback_seed: str, visible_limit: int) -> list[int]:
    """Build shuffled rounds without repeating an entry still in the visible window."""
    if entry_count <= 0 or through_occurrence < 0:
        return []
    window = max(1, min(entry_count, visible_limit))
    sequence: list[int] = []
    round_index = 0
    while len(sequence) <= through_occurrence:
        candidates = list(range(entry_count))
        seed = int.from_bytes(hashlib.sha256(
            f"{layer_key}:{playback_seed}:{round_index}:order".encode()
        ).digest()[:8], "big")
        random.Random(seed).shuffle(candidates)
        while candidates:
            recent_count = window - 1
            recent = set(sequence[-recent_count:]) if recent_count else set()
            choice = next((value for value in candidates if value not in recent), candidates[0])
            sequence.append(choice)
            candidates.remove(choice)
        round_index += 1
    return sequence


def _cloud_playback_seed(layer_key: str, elapsed: float, now: datetime) -> str:
    """Return a stable seed for one playback and replace it when time restarts."""
    context = "live" if threading.current_thread().name == "PiMatrixRenderer" else "preview"
    state_key = (context, layer_key)
    with _CLOUD_CACHE_LOCK:
        previous = _CLOUD_PLAYBACK_STATE.get(state_key)
        if previous is None or elapsed + 0.05 < previous[0]:
            seed = f"{now.timestamp():.6f}:{random.SystemRandom().getrandbits(64)}"
        else:
            seed = previous[1]
        _CLOUD_PLAYBACK_STATE[state_key] = (elapsed, seed)
        return f"{context}:{seed}"


def _cloud_position_is_clear(x: int, y: int, sprite_w: int, sprite_h: int, gap: int,
                             occupied: list[tuple[int, int, int, int]]) -> bool:
    left, top, right, bottom = x - gap, y - gap, x + sprite_w + gap, y + sprite_h + gap
    return all(right <= ox0 or left >= ox1 or bottom <= oy0 or top >= oy1
               for ox0, oy0, ox1, oy1 in occupied)


def _cloud_random_position(sprite_w: int, sprite_h: int, box_w: int, box_h: int, gap: int,
                           occupied: list[tuple[int, int, int, int]], rng: random.Random) -> tuple[int, int] | None:
    """Choose an in-bounds random position which does not collide with visible text."""
    min_x = min(max(0, gap), max(0, box_w - sprite_w))
    min_y = min(max(0, gap), max(0, box_h - sprite_h))
    max_x = max(min_x, box_w - sprite_w - gap)
    max_y = max(min_y, box_h - sprite_h - gap)

    # Random attempts produce the normal layout.  The exhaustive pass is only
    # a safety net for crowded layers and starts at a randomized offset.
    for _ in range(384):
        x, y = rng.randint(min_x, max_x), rng.randint(min_y, max_y)
        if _cloud_position_is_clear(x, y, sprite_w, sprite_h, gap, occupied):
            return x, y
    width_count, height_count = max_x - min_x + 1, max_y - min_y + 1
    total = width_count * height_count
    start = rng.randrange(total) if total else 0
    for offset in range(total):
        index = (start + offset) % total
        x, y = min_x + index % width_count, min_y + index // width_count
        if _cloud_position_is_clear(x, y, sprite_w, sprite_h, gap, occupied):
            return x, y
    return None


def _render_cloud_text(layer: dict, box_w: int, box_h: int, sy: float, elapsed: float,
                       now: datetime, upload_fonts_dir: str) -> Image.Image:
    """Render timed phrases at collision-free random positions across the layer."""
    out = Image.new("RGBA", (max(1, box_w), max(1, box_h)), (0, 0, 0, 0))
    entries = _cloud_text_entries(layer)
    if not entries:
        return out
    visible_for = max(0.5, float(layer.get("cloud_visible_for", 4.0) or 4.0))
    max_visible = max(1, min(12, int(layer.get("cloud_max_visible", 3) or 3)))
    unique_visible = min(max_visible, len(entries))
    interval = max(0.1, float(layer.get("cloud_interval", 1.5) or 1.5), visible_for / unique_visible)
    fade_in = max(0.2, min(visible_for, float(layer.get("cloud_fade_in", 0.6) or 0.0)))
    fade_out = max(0.2, min(visible_for, float(layer.get("cloud_fade_out", 0.8) or 0.0)))
    if fade_in + fade_out > visible_for * 0.9:
        scale = visible_for * 0.9 / (fade_in + fade_out)
        fade_in, fade_out = fade_in * scale, fade_out * scale
    gap = max(0, int(round(float(layer.get("cloud_gap", 2) or 0) * sy)))
    cols = max(1, min(max_visible, int(math.ceil(math.sqrt(max_visible * box_w / max(1, box_h))))))
    rows = max(1, int(math.ceil(max_visible / cols)))
    # These limits control phrase size only. Positioning uses the whole layer,
    # avoiding the visibly column-based layout used by the first implementation.
    available_w = max(1, box_w // cols - gap * 2)
    available_h = max(1, box_h // max(2, rows) - gap * 2)
    layer_key = str(layer.get("id") or "cloud-text")
    playback_epoch = _cloud_playback_seed(layer_key, max(0.0, elapsed), now)
    latest = int(math.floor(max(0.0, elapsed) / interval))
    sequence = _cloud_text_sequence(len(entries), latest, layer_key, playback_epoch, unique_visible)
    palette = [x.strip() for x in str(layer.get("cloud_palette") or "").split(",") if x.strip()]
    active = []
    for occurrence in range(max(0, latest - unique_visible + 1), latest + 1):
        age = elapsed - occurrence * interval
        if age < 0.0 or age >= visible_for:
            continue
        active.append((occurrence, age, _token_text(entries[sequence[occurrence]], now)))
    sprites = []
    for occurrence, age, phrase in active:
        seed = int.from_bytes(hashlib.sha256(f"{layer_key}:{playback_epoch}:{occurrence}:position".encode()).digest()[:8], "big")
        rng = random.Random(seed)
        colour = str(layer.get("color") or "#ffffff")
        if str(layer.get("cloud_color_mode") or "solid") == "palette" and palette:
            colour = palette[rng.randrange(len(palette))]
        child = dict(layer)
        child.update({
            "text": phrase, "color": colour, "auto_fit": True, "wrap": True,
            "overflow": "shrink", "break_long_words": False,
            "align": "center", "valign": "middle", "padding": 0,
            "font": layer.get("cloud_font", layer.get("font", "")),
            "font_size": layer.get("cloud_font_size", layer.get("font_size", 18)),
            "render_mode": layer.get("cloud_render_mode", layer.get("render_mode", "pixel")),
            "outline_width": 0, "shadow_x": 0, "shadow_y": 0, "glow": 0, "color_effect": "none",
        })
        tile = _render_scene_text(child, available_w, available_h, sy, elapsed, now, upload_fonts_dir)
        bounds = tile.getchannel("A").getbbox()
        if not bounds:
            continue
        sprite = tile.crop(bounds)
        opacity = 1.0
        if fade_in > 0.0 and age < fade_in:
            opacity = min(opacity, age / fade_in)
        remaining = visible_for - age
        if fade_out > 0.0 and remaining < fade_out:
            opacity = min(opacity, remaining / fade_out)
        if opacity < 1.0:
            sprite.putalpha(sprite.getchannel("A").point(lambda value: int(value * max(0.0, opacity))))
        sprites.append((occurrence, sprite, rng))

    occupied: list[tuple[int, int, int, int]] = []
    for occurrence, sprite, rng in sprites:
        cache_key = (playback_epoch, layer_key, occurrence, box_w, box_h, gap)
        with _CLOUD_CACHE_LOCK:
            cached_position = _CLOUD_POSITION_CACHE.get(cache_key)
        position = None
        if cached_position is not None:
            px, py, cached_w, cached_h = cached_position
            if (sprite.width, sprite.height) != (cached_w, cached_h):
                crisp = _is_crisp_mode(str(layer.get("cloud_render_mode") or "pixel"))
                sprite = sprite.resize((cached_w, cached_h), Image.Resampling.NEAREST if crisp else Image.Resampling.LANCZOS)
            if _cloud_position_is_clear(px, py, sprite.width, sprite.height, gap, occupied):
                position = (px, py)
        if position is None:
            position = _cloud_random_position(sprite.width, sprite.height, box_w, box_h, gap, occupied, rng)
            # A random earlier phrase may divide a crowded layer awkwardly.
            # Shrink only the new arrival until it fits; existing phrases never move.
            if position is None:
                original = sprite
                crisp = _is_crisp_mode(str(layer.get("cloud_render_mode") or "pixel"))
                for scale in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3):
                    size = (max(1, int(round(original.width * scale))), max(1, int(round(original.height * scale))))
                    sprite = original.resize(size, Image.Resampling.NEAREST if crisp else Image.Resampling.LANCZOS)
                    position = _cloud_random_position(sprite.width, sprite.height, box_w, box_h, gap, occupied, rng)
                    if position is not None:
                        break
            if position is not None:
                with _CLOUD_CACHE_LOCK:
                    _CLOUD_POSITION_CACHE[cache_key] = (position[0], position[1], sprite.width, sprite.height)
                    if len(_CLOUD_POSITION_CACHE) > 4096:
                        for old_key in list(_CLOUD_POSITION_CACHE)[:-3072]:
                            _CLOUD_POSITION_CACHE.pop(old_key, None)
        if position is None:
            continue
        px, py = position
        occupied.append((px, py, px + sprite.width, py + sprite.height))
        out.alpha_composite(sprite, (px, py))
    return out


def shader_layer_status(layer_id: str, upload_fonts_dir: str) -> dict:
    """Return non-fatal shader helper errors for browser preview/live rendering."""
    client = _shader_client(upload_fonts_dir)
    lid = str(layer_id or "")
    return {
        "preview_error": client.error(f"preview:{lid}"),
        "live_error": client.error(f"live:{lid}"),
        "preview_stats": client.stats(f"preview:{lid}"),
        "live_stats": client.stats(f"live:{lid}"),
    }


def _render_scene_shader(layer: dict, w: int, h: int, elapsed: float, upload_fonts_dir: str) -> Image.Image:
    asset_id = str(layer.get("shader_id") or "")
    if not asset_id:
        return Image.new("RGBA", (max(1,w), max(1,h)), (0,0,0,0))
    params = layer.get("shader_params") if isinstance(layer.get("shader_params"), dict) else {}
    if asset_id == "builtin:Sky-Weather.fs":
        params = _live_weather_shader_params(layer, params)
    fps = max(1.0, min(30.0, float(layer.get("shader_fps", 15) or 15)))
    _time_scale = layer.get("shader_time_scale", 1.0)
    time_scale = float(1.0 if _time_scale is None else _time_scale)
    # Keep the live LED renderer and browser/editor preview on independent
    # shader caches. Otherwise scrubbing the Designer timeline could briefly
    # feed preview-time frames into the physical display for the same layer ID.
    context = "live" if threading.current_thread().name == "PiMatrixRenderer" else "preview"
    layer_key = str(layer.get("id") or f"{asset_id}:{w}x{h}")
    key = f"{context}:{layer_key}"
    quality = str(layer.get("shader_quality") or "auto")
    return _shader_client(upload_fonts_dir).get_frame(key, asset_id, w, h, elapsed, params, fps, time_scale, quality)


def _render_scene_background_shader(bg: dict, w: int, h: int, elapsed: float, upload_fonts_dir: str) -> Image.Image:
    """Render a shader as the scene's true canvas background.

    Background shaders have an independent live/preview cache from shader layers,
    so timeline scrubbing never disturbs the physical display.
    """
    asset_id = str(bg.get("shader_id") or "")
    if not asset_id:
        return Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    params = bg.get("shader_params") if isinstance(bg.get("shader_params"), dict) else {}
    if asset_id == "builtin:Sky-Weather.fs":
        params = _live_weather_shader_params(bg, params)
    fps = max(1.0, min(30.0, float(bg.get("shader_fps", 15) or 15)))
    raw_scale = bg.get("shader_time_scale", 1.0)
    time_scale = float(1.0 if raw_scale is None else raw_scale)
    quality = str(bg.get("shader_quality") or "auto")
    context = "live" if threading.current_thread().name == "PiMatrixRenderer" else "preview"
    key = f"{context}:__background__"
    return _shader_client(upload_fonts_dir).get_frame(key, asset_id, w, h, elapsed, params, fps, time_scale, quality)


def _render_layer_content(layer: dict, ltype: str, w: int, h: int, sy: float, elapsed: float,
                          now: datetime, upload_fonts_dir: str, scroll_axis: str | None = None) -> Image.Image:
    if ltype == "widget" and str(layer.get("widget_type") or "clock") == "analog-clock":
        return _render_analog_clock(layer, w, h, now)
    if ltype == "widget" and str(layer.get("widget_type") or "clock") == "weather" and str(layer.get("weather_display") or "text") != "text":
        return _render_weather_widget(layer, w, h, sy, elapsed, now, upload_fonts_dir)
    if ltype == "cloud-text":
        return _render_cloud_text(layer, w, h, sy, elapsed, now, upload_fonts_dir)
    if ltype in ("text", "widget"):
        if scroll_axis:
            return _render_scene_text_scroll_content(layer, w, h, sy, elapsed, now, upload_fonts_dir, scroll_axis)
        return _render_scene_text(layer, w, h, sy, elapsed, now, upload_fonts_dir)
    if ltype == "image":
        return _render_scene_image(layer, w, h, elapsed)
    if ltype == "video":
        return _render_scene_video(layer, w, h, elapsed)
    if ltype == "shape":
        return _render_scene_shape(layer, w, h, sy)
    if ltype == "icon":
        return _render_scene_icon(layer, w, h, elapsed)
    if ltype == "shader":
        return _render_scene_shader(layer, w, h, elapsed, upload_fonts_dir)
    return _render_scene_text(layer, w, h, sy, elapsed, now, upload_fonts_dir)



@lru_cache(maxsize=96)
def _pixel_transition_rank_mask(effect: str, w: int, h: int) -> Image.Image:
    """Precompute an 8-bit reveal order so per-frame transitions stay cheap on Pi."""
    effect=str(effect or "").lower();w=max(1,int(w));h=max(1,int(h));im=Image.new("L",(w,h),255);px=im.load()
    cx=(w-1)*.5;cy=(h-1)*.5;maxd=max(1.0,math.hypot(cx,cy))
    for y in range(h):
        for x in range(w):
            if effect=="columns": rank=x/max(1,w-1)
            elif effect=="rows": rank=y/max(1,h-1)
            elif effect=="center-out": rank=math.hypot(x-cx,y-cy)/maxd
            elif effect=="spiral":
                dx=x-cx;dy=y-cy;rad=math.hypot(dx,dy)/maxd;ang=(math.atan2(dy,dx)+math.pi)/math.tau
                rank=min(1.0,rad*.72+((ang+rad*1.7)%1.0)*.28)
            else: rank=_stable_pixel_rank(x,y,29)/1023.0
            px[x,y]=max(0,min(255,int(round(rank*255))))
    return im


def _pixel_transition_mask(effect: str, w: int, h: int, amount: float) -> Image.Image:
    amount=max(0.0,min(1.0,float(amount)))
    if amount<=0: return Image.new("L",(w,h),0)
    if amount>=1: return Image.new("L",(w,h),255)
    threshold=max(0,min(255,int(round(amount*255))))
    rank=_pixel_transition_rank_mask(effect,w,h)
    return rank.point([255 if i<=threshold else 0 for i in range(256)])


def _pixel_transition_visible(effect: str, x: int, y: int, w: int, h: int, amount: float) -> bool:
    """Compatibility/testing helper backed by the cached transition order map."""
    return _pixel_transition_mask(effect,w,h,amount).getpixel((x,y))>0


def _apply_pixel_transition_rgba(viewport: Image.Image, effect: str, amount: float) -> Image.Image:
    src=viewport.convert("RGBA");mask=_pixel_transition_mask(effect,*src.size,amount)
    alpha=ImageChops.multiply(src.getchannel("A"),mask)
    src.putalpha(alpha);return src


def _apply_pixel_transition_rgb(im: Image.Image, effect: str, amount: float) -> Image.Image:
    src=im.convert("RGB");mask=_pixel_transition_mask(effect,*src.size,amount)
    return Image.composite(src,Image.new("RGB",src.size,(0,0,0)),mask)



def _apply_scene_transition(im: Image.Image, scene: dict, elapsed: float,
                            forced_exit_elapsed: float | None = None) -> Image.Image:
    """Apply a whole-scene entrance or forced exit transition.

    This sits outside layer transitions.  It allows a finished composition to
    wipe/push/dissolve as one scene while every individual layer keeps its own
    animation and clipping rules.
    """
    entering = forced_exit_elapsed is None
    prefix = "transition_in" if entering else "transition_out"
    effect = str(scene.get(prefix) or "none").lower()
    if effect == "none":
        return im
    duration = max(0.05, float(scene.get(prefix + "_duration", 0.6) or 0.6))
    clock = max(0.0, float(elapsed if entering else forced_exit_elapsed or 0.0))
    p = _transition_ease(min(1.0, clock / duration))
    amount = p if entering else 1.0 - p
    if entering and clock >= duration:
        return im
    if not entering and clock >= duration:
        return Image.new("RGB", im.size, (0,0,0))

    w,h=im.size
    black=Image.new("RGB", (w,h), (0,0,0))
    if effect in ("fade", "crossfade"):
        return Image.blend(black, im, max(0.0,min(1.0,amount)))
    if effect.startswith("wipe-"):
        out=black.copy()
        if effect=="wipe-left":
            keep=max(0,min(w,int(round(w*amount))))
            if keep: out.paste(im.crop((0,0,keep,h)),(0,0))
        elif effect=="wipe-right":
            keep=max(0,min(w,int(round(w*amount))))
            if keep: out.paste(im.crop((w-keep,0,w,h)),(w-keep,0))
        elif effect=="wipe-up":
            keep=max(0,min(h,int(round(h*amount))))
            if keep: out.paste(im.crop((0,0,w,keep)),(0,0))
        else:
            keep=max(0,min(h,int(round(h*amount))))
            if keep: out.paste(im.crop((0,h-keep,w,h)),(0,h-keep))
        return out
    if effect.startswith("push-") or effect.startswith("roll-"):
        out=black.copy()
        is_roll=effect.startswith("roll-")
        direction=effect.split("-",1)[1]
        if direction=="left": dx=int(round((-w*(1-p)) if entering else (-w*p)));dy=0
        elif direction=="right": dx=int(round((w*(1-p)) if entering else (w*p)));dy=0
        elif direction=="up": dx=0;dy=int(round((-h*(1-p)) if entering else (-h*p)))
        else: dx=0;dy=int(round((h*(1-p)) if entering else (h*p)))
        out.paste(im,(dx,dy))
        if is_roll:
            if dx<0: out.paste(im,(dx+w,dy))
            elif dx>0: out.paste(im,(dx-w,dy))
            elif dy<0: out.paste(im,(dx,dy+h))
            elif dy>0: out.paste(im,(dx,dy-h))
        return out
    if effect in ("columns","rows","spiral","center-out","random-leds"):
        return _apply_pixel_transition_rgb(im, effect, amount)
    if effect == "zoom":
        scale=max(.04, amount)
        nw,nh=max(1,int(round(w*scale))),max(1,int(round(h*scale)))
        scaled=im.resize((nw,nh),Image.Resampling.NEAREST)
        out=black.copy();out.paste(scaled,((w-nw)//2,(h-nh)//2));return out
    if effect in ("dissolve", "pixel-scatter"):
        # Stable pseudo-random order based only on coordinates; no flicker from
        # re-randomising each frame.
        src=im.load();out=black.copy();dst=out.load();threshold=int(amount*1024)
        for y in range(h):
            for x in range(w):
                v=((x*1973 + y*9277 + x*y*26699) ^ (x<<5) ^ (y<<3)) & 1023
                if v < threshold: dst[x,y]=src[x,y]
        return out
    if effect == "blinds":
        out=black.copy();stripes=max(2,min(16,w//8 or 2));sw=max(1,math.ceil(w/stripes));visible=max(0,int(round(sw*amount)))
        for i in range(stripes):
            x=i*sw
            if x>=w:break
            out.paste(im.crop((x,0,min(w,x+visible),h)),(x,0))
        return out
    if effect == "checker":
        out=black.copy();cell=max(2,min(8,max(2,min(w,h)//4)));stage=int(amount*16)
        for y in range(0,h,cell):
            for x in range(0,w,cell):
                order=((x//cell)*5+(y//cell)*3)%16
                if order<stage:
                    out.paste(im.crop((x,y,min(w,x+cell),min(h,y+cell))),(x,y))
        return out
    return im


def _scene_zone_rect(scene: dict, layer: dict, sx: float, sy: float) -> tuple[int,int,int,int] | None:
    zid=str(layer.get("zone_id") or "")
    if not zid: return None
    zones=scene.get("zones",[])
    if not isinstance(zones,list): return None
    for z in zones:
        if isinstance(z,dict) and str(z.get("id") or "")==zid:
            x=int(round(float(z.get("x",0) or 0)*sx)); y=int(round(float(z.get("y",0) or 0)*sy))
            w=max(1,int(round(float(z.get("w",1) or 1)*sx))); h=max(1,int(round(float(z.get("h",1) or 1)*sy)))
            return (x,y,x+w,y+h)
    return None


def _alpha_composite_clipped(base: Image.Image, overlay: Image.Image, x: int, y: int,
                             clip: tuple[int,int,int,int] | None = None) -> None:
    """Composite overlay but hard-clip it to an optional scene-zone rectangle."""
    if clip is None:
        base.alpha_composite(overlay,(x,y)); return
    cx0,cy0,cx1,cy1=clip
    ox0=max(0,cx0-x); oy0=max(0,cy0-y); ox1=min(overlay.width,cx1-x); oy1=min(overlay.height,cy1-y)
    if ox1<=ox0 or oy1<=oy0: return
    part=overlay.crop((ox0,oy0,ox1,oy1)); base.alpha_composite(part,(x+ox0,y+oy0))


def render_scene(scene: dict, width: int, height: int, elapsed: float, now: datetime,
                 upload_fonts_dir: str, forced_exit_elapsed: float | None = None,
                 skip_scene_transition: bool = False) -> Image.Image:
    width, height = max(1, int(width)), max(1, int(height))
    design_w = max(1, int(scene.get("design_width") or width))
    design_h = max(1, int(scene.get("design_height") or height))
    sx, sy = width / design_w, height / design_h
    bg = scene.get("background") if isinstance(scene.get("background"), dict) else {}
    mode = str(bg.get("mode") or "solid")
    c1 = _hex_color(str(bg.get("color1") or "#000000"), "#000000")
    c2 = _hex_color(str(bg.get("color2") or c1), "#000000")
    if mode == "shader" and str(bg.get("shader_id") or ""):
        # Start with Colour 1 as a safe fallback while the asynchronous shader
        # compiles/renders, and underneath any transparent shader pixels.
        fallback = Image.new("RGBA", (width, height), (*c1, 255))
        shader_bg = _render_scene_background_shader(bg, width, height, elapsed, upload_fonts_dir)
        base = Image.alpha_composite(fallback, shader_bg)
    elif mode in ("gradient-h", "gradient-v"):
        base = _gradient_background(width, height, mode, c1, c2).convert("RGBA")
    else:
        base = Image.new("RGBA", (width, height), (*c1, 255))

    layers = scene.get("layers", [])
    if not isinstance(layers, list): layers = []
    sorted_layers = sorted((x for x in layers if isinstance(x, dict)), key=lambda x: int(x.get("z",0) or 0))
    for layer in sorted_layers:
        if not bool(layer.get("enabled", True)): continue
        x = int(round(float(layer.get("x",0) or 0)*sx))
        y = int(round(float(layer.get("y",0) or 0)*sy))
        w = max(1,int(round(float(layer.get("w",design_w) or design_w)*sx)))
        h = max(1,int(round(float(layer.get("h",design_h) or design_h)*sy)))
        ltype = str(layer.get("type") or "text")
        scene_duration = max(0.25, float(scene.get("duration", 10) or 10))
        content_layer, content_elapsed = _sequenced_text_layer(layer, elapsed, scene_duration)
        text_render_mode = content_layer.get("cloud_render_mode") if ltype == "cloud-text" else content_layer.get("render_mode")
        layer_is_crisp = (ltype == "icon") or (ltype in ("text", "cloud-text", "widget") and _is_crisp_mode(str(text_render_mode or "smooth")))
        zone_clip = _scene_zone_rect(scene, layer, sx, sy)
        animation = str(layer.get("animation") or "static")

        # Auto marquee only moves when the natural content is too large for the
        # layer.  Short text remains static and aligned normally.
        if animation == "auto-marquee" and ltype in ("text","widget"):
            content = _render_layer_content(content_layer,ltype,w,h,sy,content_elapsed,now,upload_fonts_dir,"x")
            pad=max(0,int(round(float(layer.get("padding",0) or 0)*sy)))
            if content.width > max(1,w-pad*2):
                animation="scroll-left"
            else:
                animation="static"

        if animation in ("scroll-left","scroll-right","scroll-up","scroll-down"):
            axis="x" if animation in ("scroll-left","scroll-right") else "y"
            content=_render_layer_content(content_layer,ltype,w,h,sy,content_elapsed,now,upload_fonts_dir,axis)
            rotation=int(round(float(layer.get("rotation",0) or 0)))%360
            if rotation:
                crisp=layer_is_crisp
                content=content.rotate(-rotation,expand=True,resample=Image.Resampling.NEAREST if crisp else Image.Resampling.BICUBIC)
            viewport,visible=_render_scroll_viewport(content_layer,content,w,h,sy,content_elapsed,animation)
            if not visible: continue
            crisp=layer_is_crisp
            viewport,visible=_apply_layer_transition(viewport,layer,elapsed,crisp,forced_exit_elapsed)
            if not visible: continue
            opacity=max(0.0,min(1.0,float(layer.get("opacity",100) or 0)/100.0))
            _alpha_composite_clipped(base,_apply_opacity(viewport,opacity),x,y,zone_clip);continue

        if animation in ("bounce-horizontal","bounce-vertical"):
            content=_render_layer_content(content_layer,ltype,w,h,sy,content_elapsed,now,upload_fonts_dir)
            rotation=int(round(float(layer.get("rotation",0) or 0)))%360
            if rotation:
                crisp=layer_is_crisp
                content=content.rotate(-rotation,expand=True,resample=Image.Resampling.NEAREST if crisp else Image.Resampling.BICUBIC)
            viewport,visible=_render_bounce_viewport(content_layer,content,w,h,sy,content_elapsed,animation)
            if not visible: continue
            crisp=layer_is_crisp
            viewport,visible=_apply_layer_transition(viewport,layer,elapsed,crisp,forced_exit_elapsed)
            if not visible: continue
            opacity=max(0.0,min(1.0,float(layer.get("opacity",100) or 0)/100.0))
            _alpha_composite_clipped(base,_apply_opacity(viewport,opacity),x,y,zone_clip);continue

        lim=_render_layer_content(content_layer,ltype,w,h,sy,content_elapsed,now,upload_fonts_dir)
        if ltype not in ("text","widget") and animation in ("pixel-assemble","pixel-dissolve","neon-flicker","glitch"):
            lim=_apply_text_post_effect(lim,content_layer,content_elapsed)
        rotation=int(round(float(layer.get("rotation",0) or 0)))%360
        if rotation:
            crisp=layer_is_crisp
            lim=lim.rotate(-rotation,expand=True,resample=Image.Resampling.NEAREST if crisp else Image.Resampling.BICUBIC)
            x-=(lim.width-w)//2;y-=(lim.height-h)//2;w,h=lim.width,lim.height
        x,y,effect_alpha,visible=_layer_motion(layer,x,y,w,h,width,height,elapsed)
        if not visible: continue
        has_transition=(ltype in ("text","cloud-text","image","video","widget","icon","shader") and
                        (str(layer.get("entrance_effect") or "none")!="none" or str(layer.get("exit_effect") or "none")!="none"))
        if has_transition:
            orig_x=int(round(float(layer.get("x",0) or 0)*sx));orig_y=int(round(float(layer.get("y",0) or 0)*sy))
            orig_w=max(1,int(round(float(layer.get("w",design_w) or design_w)*sx)));orig_h=max(1,int(round(float(layer.get("h",design_h) or design_h)*sy)))
            viewport=Image.new("RGBA",(orig_w,orig_h),(0,0,0,0));viewport.alpha_composite(lim,((orig_w-lim.width)//2,(orig_h-lim.height)//2))
            crisp=layer_is_crisp
            viewport,visible=_apply_layer_transition(viewport,layer,elapsed,crisp,forced_exit_elapsed)
            if not visible: continue
            opacity=max(0.0,min(1.0,float(layer.get("opacity",100) or 0)/100.0))*effect_alpha
            _alpha_composite_clipped(base,_apply_opacity(viewport,opacity),orig_x,orig_y,zone_clip)
        else:
            opacity=max(0.0,min(1.0,float(layer.get("opacity",100) or 0)/100.0))*effect_alpha
            _alpha_composite_clipped(base,_apply_opacity(lim,opacity),x,y,zone_clip)

    composed=base.convert("RGB")
    return _apply_scene_transition(composed, scene, elapsed, forced_exit_elapsed)


def render_message(message: dict, width: int, height: int, elapsed: float, now: datetime, upload_fonts_dir: str, forced_exit_elapsed: float | None = None, skip_scene_transition: bool = False) -> Image.Image:
    width, height = max(1, int(width)), max(1, int(height))
    if str(message.get("editor_mode") or "quick") == "designer" and message.get("scene_json"):
        try:
            scene = json.loads(str(message.get("scene_json") or "{}"))
            if isinstance(scene, dict):
                return render_scene(scene, width, height, elapsed, now, upload_fonts_dir, forced_exit_elapsed, skip_scene_transition)
        except Exception:
            LOG.exception("Unable to render designer scene for message %s", message.get("id"))

    bg = _hex_color(message.get("background_color"), "#000000")
    base = Image.new("RGB", (width, height), bg)
    pad = max(0, int(message.get("padding", 1) or 0))
    image_mode = message.get("image_mode", "none")
    source_image = _load_image(message.get("image_path", ""), elapsed)

    if source_image is not None and image_mode in ("background-cover", "background-contain"):
        if image_mode == "background-cover":
            bgim = _cover(source_image, (width, height))
        else:
            bgim = Image.new("RGBA", (width, height), (*bg, 255))
            contained = _contain(source_image, (max(1, width - 2 * pad), max(1, height - 2 * pad)))
            bgim.alpha_composite(contained, ((width - contained.width) // 2, (height - contained.height) // 2))
        base.paste(bgim.convert("RGB"), (0, 0))

    text = _token_text(message.get("text", ""), now)
    font_size = max(5, int(message.get("font_size", 18) or 18))
    stroke = max(0, int(message.get("outline_width", 0) or 0))
    available_w, available_h = max(1, width - 2 * pad), max(1, height - 2 * pad)
    text_color = _hex_color(message.get("text_color"), "#ffffff")
    outline_color = _hex_color(message.get("outline_color"), "#000000")
    render_mode = str(message.get("render_mode") or "smooth").lower()
    if render_mode not in ("smooth", "pixel") and not _is_led_mode(render_mode):
        render_mode = "smooth"
    pixel_scale = max(1, min(8, int(message.get("pixel_scale", 1) or 1)))
    pixel_bold = bool(message.get("pixel_bold", False))
    letter_spacing = max(0, min(8, int(message.get("letter_spacing", 0) or 0)))
    align = message.get("align", "center")
    if align not in ("left", "center", "right"):
        align = "center"

    text_sprite = None
    if text:
        if _is_led_mode(render_mode):
            text_sprite = _render_led_sprite(
                text, available_w, available_h, text_color, outline_color, stroke,
                pixel_scale, bool(message.get("auto_fit")), False, align, pixel_bold,
                letter_spacing, 1, render_mode
            )
        else:
            if message.get("auto_fit"):
                font = _fit_font(text, available_w, available_h, message.get("font", ""), upload_fonts_dir, stroke)
                actual_size = max(5, int(getattr(font, "size", font_size) or font_size))
            else:
                font = _load_font(message.get("font", ""), font_size, upload_fonts_dir)
                actual_size = font_size
            text_sprite = _render_ttf_sprite(
                text, font, text_color, outline_color, stroke, max(1, actual_size // 8), align,
                render_mode, pixel_scale, pixel_bold, letter_spacing
            )

    tw = text_sprite.width if text_sprite is not None else 0
    th = text_sprite.height if text_sprite is not None else 0

    logo = None
    if source_image is not None and image_mode in ("logo-left", "logo-right", "logo-center"):
        logo_max_h = max(1, available_h)
        logo_max_w = max(1, available_w // 2 if text else available_w)
        scale = float(message.get("image_scale", 1.0) or 1.0)
        logo = _contain(source_image, (max(1, int(logo_max_w * scale)), max(1, int(logo_max_h * scale))))

    gap = max(1, pad + 1)
    if logo is not None and image_mode in ("logo-left", "logo-right"):
        content_w = logo.width + (gap if text_sprite is not None else 0) + tw
        content_h = max(logo.height, th)
    elif logo is not None and image_mode == "logo-center" and text_sprite is None:
        content_w, content_h = logo.width, logo.height
    else:
        content_w, content_h = max(1, tw), max(1, th)

    content = Image.new("RGBA", (max(1,int(content_w)), max(1,int(content_h))), (0, 0, 0, 0))
    if logo is not None and image_mode == "logo-left":
        content.alpha_composite(logo, (0, (content.height - logo.height) // 2))
        if text_sprite is not None:
            content.alpha_composite(text_sprite, (logo.width + gap, (content.height - text_sprite.height)//2))
    elif logo is not None and image_mode == "logo-right":
        if text_sprite is not None:
            content.alpha_composite(text_sprite, (0, (content.height - text_sprite.height)//2))
        content.alpha_composite(logo, ((tw + gap) if text_sprite is not None else 0, (content.height - logo.height) // 2))
    elif logo is not None and image_mode == "logo-center" and text_sprite is None:
        content.alpha_composite(logo, (0, 0))
    else:
        if text_sprite is not None:
            content.alpha_composite(text_sprite, ((content.width-text_sprite.width)//2, (content.height-text_sprite.height)//2))
        if logo is not None and image_mode == "logo-center":
            content.alpha_composite(logo, ((content.width - logo.width) // 2, (content.height - logo.height) // 2))

    direction = message.get("direction", "left")
    if direction not in DIRECTIONS:
        direction = "left"
    speed = max(0.1, float(message.get("speed", 30) or 30))
    valign = message.get("valign", "middle")
    static_x = _align_pos(width, content.width, align, pad)
    static_y = _align_pos(height, content.height, valign, pad)

    if direction == "static":
        x, y = static_x, static_y
    else:
        travel_x = width + content.width
        travel_y = height + content.height
        px = (elapsed * speed) % max(1.0, float(travel_x))
        py = (elapsed * speed) % max(1.0, float(travel_y))
        x, y = static_x, static_y
        if "left" in direction:
            x = int(width - px)
        elif "right" in direction:
            x = int(-content.width + px)
        if "up" in direction:
            y = int(height - py)
        elif "down" in direction:
            y = int(-content.height + py)

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layer.alpha_composite(content, (x, y))
    return Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")

def render_test_pattern(kind: str, width: int, height: int, now: datetime) -> Image.Image:
    kind = kind or "grid"
    if kind in ("red", "green", "blue", "white", "black"):
        colors = {
            "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
            "white": (255, 255, 255), "black": (0, 0, 0),
        }
        return Image.new("RGB", (width, height), colors[kind])
    im = Image.new("RGB", (width, height), (0, 0, 0))
    d = ImageDraw.Draw(im)
    if kind == "checker":
        size = 4
        for y in range(0, height, size):
            for x in range(0, width, size):
                if ((x // size) + (y // size)) % 2 == 0:
                    d.rectangle((x, y, min(width - 1, x + size - 1), min(height - 1, y + size - 1)), fill=(255, 255, 255))
    else:
        for x in range(0, width, 8):
            d.line((x, 0, x, height - 1), fill=(80, 80, 80))
        for y in range(0, height, 8):
            d.line((0, y, width - 1, y), fill=(80, 80, 80))
        d.rectangle((0, 0, width - 1, height - 1), outline=(255, 255, 255))
        d.line((0, 0, width - 1, height - 1), fill=(255, 0, 0))
        d.line((width - 1, 0, 0, height - 1), fill=(0, 255, 0))
    return im


def _message_scene(scene_message: dict | None) -> dict:
    if not scene_message or str(scene_message.get("editor_mode") or "quick") != "designer":
        return {}
    try:
        scene=json.loads(str(scene_message.get("scene_json") or "{}"))
        return scene if isinstance(scene,dict) else {}
    except Exception:
        return {}


def _message_scene_transition(message: dict | None, which: str) -> tuple[str,float]:
    scene=_message_scene(message)
    key="transition_in" if which=="in" else "transition_out"
    effect=str(scene.get(key) or "none").lower()
    try: duration=max(.05,float(scene.get(key+"_duration",.6) or .6))
    except Exception: duration=.6
    return effect,duration


def _message_exit_duration(message: dict | None) -> float:
    """Longest configured scene/layer exit duration used before a message cut."""
    scene=_message_scene(message)
    if not scene:
        return 0.0
    duration=0.0
    effect,scene_duration=_message_scene_transition(message,"out")
    if effect!="none": duration=max(duration,scene_duration)
    layers=scene.get("layers",[]) if isinstance(scene,dict) else []
    if not isinstance(layers,list): return duration
    for layer in layers:
        if not isinstance(layer,dict) or not bool(layer.get("enabled",True)): continue
        if str(layer.get("type") or "text") not in ("text","cloud-text","image","video","widget","icon","shader"): continue
        if str(layer.get("exit_effect") or "none").lower()=="none": continue
        try: duration=max(duration,max(.05,float(layer.get("exit_duration",.5) or .5)))
        except Exception: duration=max(duration,.5)
    return duration


def _compare_condition(actual, operator: str, expected: str) -> bool:
    op=str(operator or "eq").lower()
    if op in ("contains","not_contains"):
        result=str(expected or "").casefold() in str(actual if actual is not None else "").casefold()
        return (not result) if op=="not_contains" else result
    if op in ("eq","neq"):
        try:
            a=float(actual); b=float(expected); result=math.isfinite(a) and math.isfinite(b) and abs(a-b)<1e-9
        except Exception:
            result=str(actual if actual is not None else "").strip().casefold()==str(expected or "").strip().casefold()
        return (not result) if op=="neq" else result
    try:
        a=float(actual); b=float(expected)
        if not (math.isfinite(a) and math.isfinite(b)): return False
    except Exception:
        return False
    return {"gt":a>b,"gte":a>=b,"lt":a<b,"lte":a<=b}.get(op,False)


def _condition_value(rule: dict) -> tuple[object | None, str]:
    ctype=str(rule.get("condition_type") or "").lower()
    cfg=rule.get("config") if isinstance(rule.get("config"),dict) else {}
    if ctype.startswith("weather_"):
        layer={
            "weather_lat":cfg.get("lat",0), "weather_lon":cfg.get("lon",0),
            "weather_temp_unit":cfg.get("temp_unit","c"), "weather_wind_unit":cfg.get("wind_unit","mph"),
            "refresh_seconds":cfg.get("refresh_seconds",300),
        }
        data=_weather_current(layer)
        if data.get("status")!="ok": return None, "Weather loading/unavailable"
        field={
            "weather_temp":"temp","weather_feels":"feels","weather_wind":"wind",
            "weather_gust":"gust","weather_humidity":"humidity",
            "weather_condition":"category",
        }.get(ctype)
        value=data.get(field) if field else None
        if ctype=="weather_condition":
            detail=f"{data.get('condition') or value}"
        else:
            unit=data.get("temp_unit") if ctype in ("weather_temp","weather_feels") else ("%" if ctype=="weather_humidity" else data.get("wind_unit"))
            detail=f"{value if value is not None else '?'}{unit or ''}"
        return value,detail
    if ctype=="json":
        url=str(cfg.get("url") or "").strip(); path=str(cfg.get("path") or "").strip(); refresh=max(5.0,float(cfg.get("refresh_seconds") or 60))
        if not url: return None,"JSON URL not set"
        key=f"condition-json:{url}:{path}"
        def fetch():
            payload=json.loads(_http_text(url))
            value=_json_path(payload,path) if path else payload
            if isinstance(value,(dict,list)): return json.dumps(value,separators=(",",":"),ensure_ascii=False)
            return str(value)
        raw=_live_fetch_async(key,refresh,fetch,placeholder="__LOADING__",error_value="__ERROR__")
        if raw in ("__LOADING__","__ERROR__"): return None,"JSON loading/unavailable"
        return raw,str(raw)[:80]
    return None,"Unsupported condition"


def _schedule_matches(s: dict, now: datetime) -> bool:
    if not s.get("enabled"):
        return False
    try:
        days = {int(v) for v in str(s.get("days", "0,1,2,3,4,5,6")).split(",") if v != ""}
    except Exception:
        days = set(range(7))
    if now.weekday() not in days:
        return False
    today = now.date()
    try:
        if s.get("start_date") and today < date.fromisoformat(s["start_date"]):
            return False
        if s.get("end_date") and today > date.fromisoformat(s["end_date"]):
            return False
    except Exception:
        return False
    current = now.strftime("%H:%M")
    start = s.get("start_time") or "00:00"
    end = s.get("end_time") or "23:59"
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end  # overnight window


def _schedule_next_start(s: dict, now: datetime) -> datetime | None:
    """Return the next configured start for a timed schedule after ``now``.

    This uses the same weekday/date fields as :func:`_schedule_matches`.  The
    search jumps straight to a future start_date when one exists, then needs
    at most one week to find the next enabled weekday.
    """
    if not s.get("enabled"):
        return None
    try:
        days = {int(v) for v in str(s.get("days", "0,1,2,3,4,5,6")).split(",") if v != ""}
        days = {v for v in days if 0 <= v <= 6}
    except Exception:
        days = set(range(7))
    if not days:
        return None
    try:
        start_clock = datetime.strptime(str(s.get("start_time") or "00:00"), "%H:%M").time()
        first_day = now.date()
        if s.get("start_date"):
            first_day = max(first_day, date.fromisoformat(str(s["start_date"])))
        last_day = date.fromisoformat(str(s["end_date"])) if s.get("end_date") else None
    except Exception:
        return None
    if last_day is not None and first_day > last_day:
        return None
    for offset in range(8):
        day = first_day + timedelta(days=offset)
        if last_day is not None and day > last_day:
            return None
        if day.weekday() not in days:
            continue
        candidate = datetime.combine(day, start_clock)
        if now.tzinfo is not None:
            candidate = candidate.replace(tzinfo=now.tzinfo)
        if candidate > now:
            return candidate
    return None


def _schedule_occurrence_end(s: dict, start_at: datetime) -> datetime:
    """Return the configured end clock for a schedule occurrence."""
    try:
        end_clock = datetime.strptime(str(s.get("end_time") or "23:59"), "%H:%M").time()
    except Exception:
        end_clock = datetime.strptime("23:59", "%H:%M").time()
    end_at = datetime.combine(start_at.date(), end_clock)
    if start_at.tzinfo is not None:
        end_at = end_at.replace(tzinfo=start_at.tzinfo)
    if str(s.get("end_time") or "23:59") < str(s.get("start_time") or "00:00"):
        end_at += timedelta(days=1)
    return end_at


@dataclass
class ActiveTarget:
    target_type: str
    target_id: int
    source: str
    activated_monotonic: float


@dataclass
class MessageTransition:
    started_monotonic: float
    duration: float
    outgoing_message: dict
    outgoing_elapsed: float
    outgoing_target: ActiveTarget | None
    incoming_message: dict | None = None
    incoming_target: ActiveTarget | None = None
    crossfade: bool = False


class RendererEngine:
    def __init__(self, db, data_dir: str, upload_dir: str, license_checker=None):
        self.db = db
        self.data_dir = data_dir
        self.upload_dir = upload_dir
        self._license_checker = license_checker
        self.font_dir = os.path.join(upload_dir, "fonts")
        self.image_dir = os.path.join(upload_dir, "images")
        self._lock = threading.RLock()
        self._preview = Image.new("RGB", (64, 32), (0, 0, 0))
        self._running = False
        self._thread: threading.Thread | None = None
        self._settings = self.db.get_settings()
        self._ddp = DDPSender(self._settings["ddp_host"], self._settings["ddp_port"], self._settings["ddp_offset"])
        self._active: ActiveTarget | None = None
        self._display_message_id: int | None = None
        self._display_message: dict | None = None
        self._display_elapsed: float = 0.0
        self._transition: MessageTransition | None = None
        self._manual: ActiveTarget | None = None
        self._manual_until: float | None = None
        self._test_pattern: str | None = None
        self._test_until: float | None = None
        self.last_error = ""
        self.frames_sent = 0
        self.last_frame_at = 0.0
        self.frame_failures = 0
        self.slow_frames = 0
        self.dropped_frames = 0
        self.last_frame_duration_ms = 0.0
        self.renderer_restarts = 0
        self._frame_times = deque(maxlen=240)
        self._emergency: ActiveTarget | None = None
        self._brightness_override: int | None = None
        self._effective_brightness_value = int(self._settings.get("brightness", 60))
        self._effective_brightness_source = "default"
        self._condition_runtime: dict[int, dict] = {}
        self._automation_cache_at = 0.0
        self._automation_candidates: list[tuple[int,int,str,int,str]] = []
        self._brightness_cache_at = 0.0
        self._brightness_cache: tuple[int,str] | None = None

    def start(self):
        if self._running and self._thread and self._thread.is_alive():
            return
        # A stopped renderer closes its UDP socket. Recreate it before starting again.
        if getattr(self._ddp, "sock", None) is None or getattr(self._ddp.sock, "_closed", False):
            self._ddp = DDPSender(self._settings["ddp_host"], self._settings["ddp_port"], self._settings["ddp_offset"])
        self._running = True
        self._thread = threading.Thread(target=self._run, name="PiMatrixRenderer", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._ddp.close()

    def restart(self) -> bool:
        """Restart only the LED renderer thread without disturbing the web UI."""
        self._running = False
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.5)
        if thread and thread.is_alive():
            LOG.error("Renderer watchdog could not stop the existing renderer thread")
            return False
        try:
            self._ddp.close()
        except Exception:
            pass
        with self._lock:
            self._settings = self.db.get_settings()
            self._ddp = DDPSender(self._settings["ddp_host"], self._settings["ddp_port"], self._settings["ddp_offset"])
            self.last_error = ""
            self.renderer_restarts += 1
        self._running = True
        self._thread = threading.Thread(target=self._run, name="PiMatrixRenderer", daemon=True)
        self._thread.start()
        return True

    def reload_settings(self):
        with self._lock:
            self._settings = self.db.get_settings()
            self._ddp.update_target(self._settings["ddp_host"], self._settings["ddp_port"], self._settings["ddp_offset"])

    def show_target(self, target_type: str, target_id: int, duration: float = 0):
        if target_type not in ("message", "playlist"):
            raise ValueError("Invalid target type")
        with self._lock:
            mono = time.monotonic()
            hold = 0.0
            if float(duration) > 0:
                # A timed manual override should receive its full requested
                # on-screen duration *after* the outgoing message has exited.
                # If an exit is already underway, only add the remaining time.
                if self._transition is not None:
                    hold = max(0.0, self._transition.duration - (mono - self._transition.started_monotonic))
                elif self._display_message is not None:
                    visual_change = True
                    if target_type == "message" and self._display_message_id == int(target_id):
                        visual_change = False
                    if visual_change:
                        hold = _message_exit_duration(self._display_message)
            self._manual = ActiveTarget(target_type, int(target_id), "manual", mono)
            self._manual_until = mono + hold + float(duration) if float(duration) > 0 else None
            self._test_pattern = None

    def activate_emergency(self, message_id: int | None = None, source: str = "emergency"):
        with self._lock:
            mid=int(message_id or self._settings.get("emergency_message_id") or 0)
            if mid<=0 or not self.db.get_message(mid):
                raise ValueError("No emergency message is configured")
            self._emergency=ActiveTarget("message",mid,str(source or "emergency"),time.monotonic())
            self._test_pattern=None; self._test_until=None

    def clear_emergency(self, source: str | None = None):
        with self._lock:
            if source is not None and self._emergency is not None and self._emergency.source != source:
                return False
            self._emergency=None
            return True

    def step_message(self, delta: int):
        with self._lock:
            messages=[m for m in self.db.list_messages() if m.get("enabled")]
            if not messages:
                raise ValueError("No enabled messages are available")
            current=self._display_message_id
            idx=next((i for i,m in enumerate(messages) if int(m.get("id") or 0)==int(current or 0)),-1)
            idx=(idx+int(delta))%len(messages)
            target=int(messages[idx]["id"])
        self.show_target("message",target)
        return target

    def cycle_brightness_override(self):
        with self._lock:
            cycle=[10,25,50,75,100,None]
            current=self._brightness_override
            try: idx=cycle.index(current)
            except ValueError: idx=-1
            self._brightness_override=cycle[(idx+1)%len(cycle)]
            return self._brightness_override

    def show_blank(self):
        with self._lock:
            mono=time.monotonic(); hold=_message_exit_duration(self._display_message) if self._display_message is not None else 0.0
            self._manual=ActiveTarget("blank",0,"manual",mono)
            self._manual_until=None
            self._test_pattern=None; self._test_until=None

    def set_brightness_override(self, value: int | None):
        with self._lock:
            self._brightness_override=None if value is None else max(0,min(100,int(value)))

    def conditional_status(self) -> list[dict]:
        with self._lock:
            return [dict({"id":rid},**{k:v for k,v in data.items() if k not in ("first_true",)}) for rid,data in sorted(self._condition_runtime.items())]

    def clear_manual(self):
        with self._lock:
            self._manual = None
            self._manual_until = None
            self._test_pattern = None
            self._test_until = None

    def test_pattern(self, kind: str, duration: float = 30):
        with self._lock:
            if self._emergency is not None:
                raise ValueError("End Emergency mode before running a panel test")
            self._test_pattern = kind
            self._test_until = time.monotonic() + max(1.0, float(duration)) if duration else None

    def preview_png(self, scale: int = 6) -> bytes:
        with self._lock:
            im = self._preview.copy()
        if scale > 1:
            im = im.resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _physical_size(self) -> tuple[int, int]:
        s = self._settings
        return (
            max(1, int(s["panel_width"]) * int(s["panels_across"])),
            max(1, int(s["panel_height"]) * int(s["panels_down"])),
        )

    def _evaluate_automation(self, now: datetime, mono: float) -> list[tuple[int,int,str,int,str]]:
        if mono-self._automation_cache_at < 2.0:
            return list(self._automation_candidates)
        candidates=[]
        for sch in self.db.list_schedules():
            if _schedule_matches(sch,now):
                candidates.append((int(sch.get("priority",0)),int(sch.get("id",0)),str(sch.get("target_type")),int(sch.get("target_id")),f"schedule:{sch.get('id')}"))
        rules=self.db.list_conditional_rules()
        valid_ids={int(r["id"]) for r in rules}
        for stale in list(self._condition_runtime):
            if stale not in valid_ids: self._condition_runtime.pop(stale,None)
        for rule in rules:
            rid=int(rule["id"]); rt=self._condition_runtime.setdefault(rid,{"matching":False,"eligible":False,"detail":"Not evaluated","value":None,"first_true":None})
            if not rule.get("enabled"):
                rt.update(matching=False,eligible=False,detail="Disabled",value=None,first_true=None); continue
            try:
                actual,detail=_condition_value(rule)
                matching=actual is not None and _compare_condition(actual,rule.get("operator"),rule.get("compare_value"))
            except Exception as exc:
                actual=None; detail=f"Condition error: {exc}"; matching=False
            if matching:
                if rt.get("first_true") is None: rt["first_true"]=mono
            else:
                rt["first_true"]=None
            true_for=max(0.0,float(rule.get("true_for_seconds",0) or 0))
            eligible=matching and rt.get("first_true") is not None and mono-float(rt["first_true"])>=true_for
            held=False
            active_same=bool(self._active and self._active.source==f"condition:{rid}")
            if active_same and not eligible:
                hold=max(0.0,float(rule.get("minimum_hold_seconds",0) or 0))
                held=(mono-self._active.activated_monotonic)<hold
            rt.update(matching=matching,eligible=eligible or held,detail=(detail+(" · minimum hold" if held else "")),value=actual,last_checked=time.time())
            if eligible or held:
                candidates.append((int(rule.get("priority",0)),rid,str(rule.get("target_type")),int(rule.get("target_id")),f"condition:{rid}"))
        candidates.sort(key=lambda x:(x[0],x[1]),reverse=True)
        self._automation_candidates=list(candidates); self._automation_cache_at=mono
        return candidates

    def _resolve_target(self, now: datetime) -> ActiveTarget | None:
        mono = time.monotonic()
        if self._license_checker is not None:
            try:
                if not bool(self._license_checker()):
                    return None
            except Exception:
                return None
        if self._emergency is not None:
            return self._emergency
        if self._manual is not None:
            if self._manual_until is None or mono < self._manual_until:
                return self._manual
            self._manual = None; self._manual_until = None
        candidates=self._evaluate_automation(now,mono)
        if candidates:
            _priority,_id,target_type,target_id,source=candidates[0]
            if self._active and (self._active.target_type,self._active.target_id,self._active.source)==(target_type,target_id,source):
                return self._active
            return ActiveTarget(target_type,target_id,source,mono)
        default_id = self._settings.get("default_message_id")
        if default_id:
            key=("message",int(default_id),"default")
            if self._active and (self._active.target_type,self._active.target_id,self._active.source)==key: return self._active
            return ActiveTarget(key[0],key[1],key[2],mono)
        return None

    def _next_timed_schedule(self, now: datetime) -> dict | None:
        candidates: list[tuple[datetime, int, int, dict]] = []
        for schedule in self.db.list_schedules():
            start_at = _schedule_next_start(schedule, now)
            if start_at is None:
                continue
            candidates.append((start_at, -int(schedule.get("priority", 0)), -int(schedule.get("id", 0)), schedule))
        if not candidates:
            return None
        start_at, _priority_key, _id_key, schedule = min(candidates, key=lambda item: (item[0], item[1], item[2]))
        target_type = str(schedule.get("target_type") or "message")
        target_id = int(schedule.get("target_id") or 0)
        target = self.db.get_playlist(target_id) if target_type == "playlist" else self.db.get_message(target_id)
        end_at = _schedule_occurrence_end(schedule, start_at)
        delta_days = (start_at.date() - now.date()).days
        day_label = "Today" if delta_days == 0 else "Tomorrow" if delta_days == 1 else start_at.strftime("%a %d %b")
        overnight = end_at.date() != start_at.date()
        return {
            "id": int(schedule.get("id") or 0),
            "name": str(schedule.get("name") or "Schedule"),
            "target_type": target_type,
            "target_id": target_id,
            "target_name": str((target or {}).get("name") or f"{target_type.title()} #{target_id}"),
            "target_available": bool(target),
            "priority": int(schedule.get("priority") or 0),
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "start_label": f"{day_label} at {start_at.strftime('%H:%M')}",
            "window_label": f"{start_at.strftime('%H:%M')}–{end_at.strftime('%H:%M')}{' next day' if overnight else ''}",
            "timezone": str(getattr(now.tzinfo, "key", "") or self._settings.get("timezone") or "Europe/London"),
        }

    def _effective_brightness(self, now: datetime, mono: float) -> tuple[int,str]:
        if self._brightness_override is not None:
            result=(int(self._brightness_override),"remote override")
        elif self._brightness_cache is not None and mono-self._brightness_cache_at<2.0:
            result=self._brightness_cache
        else:
            matches=[]
            for item in self.db.list_brightness_schedules():
                probe={"enabled":item.get("enabled"),"days":item.get("days"),"start_time":item.get("start_time"),"end_time":item.get("end_time"),"start_date":"","end_date":""}
                if _schedule_matches(probe,now): matches.append(item)
            if matches:
                matches.sort(key=lambda x:(int(x.get("priority",0)),int(x.get("id",0))),reverse=True); chosen=matches[0]
                result=(max(0,min(100,int(chosen.get("brightness",60)))),f"schedule:{chosen.get('id')} {chosen.get('name')}")
            else:
                result=(max(0,min(100,int(self._settings.get("brightness",60)))),"default")
            self._brightness_cache=result; self._brightness_cache_at=mono
        self._effective_brightness_value,self._effective_brightness_source=result
        return result

    def _message_for_target(self, target: ActiveTarget, mono: float) -> tuple[dict | None, float, str]:
        elapsed = max(0.0, mono - target.activated_monotonic)
        if target.target_type == "blank":
            return None, elapsed, ""
        if target.target_type == "message":
            return self.db.get_message(target.target_id), elapsed, ""
        playlist = self.db.get_playlist(target.target_id)
        if not playlist or not playlist.get("items"):
            return None, elapsed, ""
        total = sum(max(0.5, float(i.get("duration", 10))) for i in playlist["items"])
        cursor = elapsed % max(0.5, total)
        acc = 0.0
        for item in playlist["items"]:
            duration = max(0.5, float(item.get("duration", 10)))
            if cursor < acc + duration:
                return self.db.get_message(int(item["message_id"])), cursor - acc, playlist.get("name", "")
            acc += duration
        item = playlist["items"][-1]
        return self.db.get_message(int(item["message_id"])), 0.0, playlist.get("name", "")

    def status(self) -> dict:
        with self._lock:
            active = self._active
            manual = self._manual
            width, height = self._physical_size()
            try:
                tz = ZoneInfo(str(self._settings.get("timezone") or "Europe/London"))
            except Exception:
                tz = ZoneInfo("Europe/London")
            now = datetime.now(tz)
            next_schedule = self._next_timed_schedule(now)
            return {
                "running": self._running,
                "width": width,
                "height": height,
                "active": None if not active else {
                    "type": active.target_type, "id": active.target_id, "source": active.source,
                },
                "manual": None if not manual else {"type": manual.target_type, "id": manual.target_id},
                "emergency": None if not self._emergency else {"type": self._emergency.target_type, "id": self._emergency.target_id, "source": self._emergency.source},
                "brightness": {"effective": self._effective_brightness_value, "source": self._effective_brightness_source, "override": self._brightness_override},
                "next_schedule": next_schedule,
                "transition": None if not self._transition else {
                    "outgoing_message_id": self._transition.outgoing_message.get("id"),
                    "duration": self._transition.duration,
                    "remaining": max(0.0, self._transition.duration - (time.monotonic() - self._transition.started_monotonic)),
                },
                "test_pattern": self._test_pattern,
                "frames_sent": self.frames_sent,
                "last_frame_at": self.last_frame_at,
                "last_error": self.last_error,
                "actual_fps": self._actual_fps(),
                "frame_failures": self.frame_failures,
                "slow_frames": self.slow_frames,
                "dropped_frames": self.dropped_frames,
                "last_frame_duration_ms": round(self.last_frame_duration_ms, 2),
                "renderer_restarts": self.renderer_restarts,
                "thread_alive": bool(self._thread and self._thread.is_alive()),
            }

    def _actual_fps(self) -> float:
        now_m = time.monotonic()
        recent = [t for t in self._frame_times if now_m - t <= 3.0]
        if len(recent) < 2:
            return 0.0
        span = recent[-1] - recent[0]
        return round((len(recent) - 1) / span, 2) if span > 0 else 0.0

    def _apply_output_transform(self, im: Image.Image, brightness: int | None = None) -> Image.Image:
        s = self._settings
        brightness = max(0, min(100, int(s.get("brightness", 100) if brightness is None else brightness)))
        if brightness < 100:
            lut = [min(255, int(v * brightness / 100.0)) for v in range(256)]
            r, g, b = im.split()
            im = Image.merge("RGB", (r.point(lut), g.point(lut), b.point(lut)))
        order = str(s.get("color_order", "RGB")).upper()
        if order != "RGB" and sorted(order) == ["B", "G", "R"]:
            ch = dict(zip("RGB", im.split()))
            im = Image.merge("RGB", tuple(ch[c] for c in order))
        return im

    def _run(self):
        last_settings_refresh = 0.0
        while self._running:
            loop_start = time.monotonic()
            try:
                if loop_start - last_settings_refresh > 2.0:
                    self.reload_settings()
                    last_settings_refresh = loop_start
                s = self._settings
                fps = max(1, min(60, int(s.get("frame_rate", 25))))
                physical_w, physical_h = self._physical_size()
                rotation = int(s.get("display_rotation", 0)) % 360
                if rotation in (90, 270):
                    logical_w, logical_h = physical_h, physical_w
                else:
                    logical_w, logical_h = physical_w, physical_h
                try:
                    tz = ZoneInfo(str(s.get("timezone") or "Europe/London"))
                except Exception:
                    tz = ZoneInfo("Europe/London")
                now = datetime.now(tz)
                effective_brightness,_brightness_source = self._effective_brightness(now, loop_start)

                if self._test_pattern is not None and self._emergency is None:
                    if self._test_until is not None and loop_start >= self._test_until:
                        self._test_pattern = None
                        self._test_until = None
                    else:
                        im = render_test_pattern(self._test_pattern, logical_w, logical_h, now)
                        target = None
                if self._test_pattern is None or self._emergency is not None:
                    # Resolve what *wants* to be on screen, but do not cut to it
                    # until any configured exit on the currently displayed
                    # message has completed.  This applies to manual changes,
                    # schedules/defaults, override expiry and playlist item
                    # boundaries.
                    desired_target = self._resolve_target(now)
                    if desired_target:
                        desired_msg, desired_elapsed, _playlist_name = self._message_for_target(desired_target, loop_start)
                    else:
                        desired_msg, desired_elapsed = None, 0.0
                    if not (desired_msg and desired_msg.get("enabled")):
                        desired_msg = None
                    desired_id = int(desired_msg["id"]) if desired_msg and desired_msg.get("id") is not None else None

                    transition = self._transition
                    if transition is not None:
                        exit_elapsed = max(0.0, loop_start - transition.started_monotonic)
                        if exit_elapsed < transition.duration:
                            msg = transition.outgoing_message
                            elapsed = transition.outgoing_elapsed + exit_elapsed
                            if transition.crossfade and transition.incoming_message is not None:
                                outgoing = render_message(
                                    msg, logical_w, logical_h, elapsed, now, self.font_dir,
                                    forced_exit_elapsed=exit_elapsed, skip_scene_transition=True,
                                )
                                incoming = render_message(
                                    transition.incoming_message, logical_w, logical_h, exit_elapsed, now, self.font_dir,
                                    skip_scene_transition=True,
                                )
                                p = _transition_ease(exit_elapsed / max(.05, transition.duration))
                                im = Image.blend(outgoing, incoming, max(0.0, min(1.0, p)))
                            else:
                                # The outgoing message owns the display until its
                                # longest configured layer/scene exit has finished.
                                im = render_message(
                                    msg, logical_w, logical_h, elapsed, now, self.font_dir,
                                    forced_exit_elapsed=exit_elapsed,
                                )
                        else:
                            outgoing_target = transition.outgoing_target
                            transition_duration = transition.duration
                            crossfade_finished = transition.crossfade
                            incoming_snapshot = transition.incoming_message
                            incoming_target_snapshot = transition.incoming_target
                            self._transition = None

                            if crossfade_finished and incoming_target_snapshot is not None:
                                desired_target = incoming_target_snapshot

                            # If this was simply the next item in the same
                            # playlist, pause the playlist clock while a non-overlapping
                            # exit ran. Crossfades deliberately count as incoming scene time.
                            same_playlist = bool(
                                desired_target and outgoing_target and
                                desired_target.target_type == "playlist" and
                                outgoing_target.target_type == "playlist" and
                                desired_target.target_id == outgoing_target.target_id and
                                desired_target.source == outgoing_target.source
                            )
                            if same_playlist and not crossfade_finished:
                                desired_target.activated_monotonic += transition_duration
                            elif crossfade_finished and desired_target is not None:
                                desired_target = ActiveTarget(
                                    desired_target.target_type, desired_target.target_id, desired_target.source,
                                    transition.started_monotonic,
                                )
                                if desired_target.source == "manual" and self._manual is not None:
                                    self._manual = desired_target
                            elif desired_target is not None:
                                # A different target starts when the outgoing
                                # exit actually completes, not when it was first
                                # requested.
                                desired_target = ActiveTarget(
                                    desired_target.target_type, desired_target.target_id,
                                    desired_target.source, loop_start,
                                )
                                if desired_target.source == "manual" and self._manual is not None:
                                    self._manual = desired_target

                            self._active = desired_target
                            if desired_target:
                                desired_msg, desired_elapsed, _playlist_name = self._message_for_target(desired_target, loop_start)
                            else:
                                desired_msg, desired_elapsed = None, 0.0
                            if not (desired_msg and desired_msg.get("enabled")):
                                desired_msg = None
                            desired_id = int(desired_msg["id"]) if desired_msg and desired_msg.get("id") is not None else None
                            self._display_message_id = desired_id
                            self._display_message = desired_msg
                            self._display_elapsed = desired_elapsed
                            if desired_msg:
                                im = render_message(desired_msg, logical_w, logical_h, desired_elapsed, now, self.font_dir)
                            else:
                                im = Image.new("RGB", (logical_w, logical_h), (0, 0, 0))
                    else:
                        current_id = self._display_message_id
                        if current_id is not None and desired_id != current_id and self._display_message is not None:
                            exit_duration = _message_exit_duration(self._display_message)
                            out_effect, out_scene_duration = _message_scene_transition(self._display_message, "out")
                            in_effect, in_scene_duration = _message_scene_transition(desired_msg, "in")
                            crossfade = (out_effect == "crossfade" or in_effect == "crossfade") and desired_msg is not None
                            transition_duration = max(exit_duration, in_scene_duration if crossfade else 0.0)
                            if transition_duration > 0:
                                self._transition = MessageTransition(
                                    started_monotonic=loop_start,
                                    duration=transition_duration,
                                    outgoing_message=dict(self._display_message),
                                    outgoing_elapsed=self._display_elapsed,
                                    outgoing_target=self._active,
                                    incoming_message=dict(desired_msg) if desired_msg is not None else None,
                                    incoming_target=desired_target,
                                    crossfade=crossfade,
                                )
                                # Keep the current active target/status until the
                                # physical exit has actually completed.
                                im = render_message(
                                    self._display_message, logical_w, logical_h,
                                    self._display_elapsed, now, self.font_dir,
                                    forced_exit_elapsed=0.0,
                                )
                            else:
                                self._active = desired_target
                                self._display_message_id = desired_id
                                self._display_message = desired_msg
                                self._display_elapsed = desired_elapsed
                                if desired_msg:
                                    im = render_message(desired_msg, logical_w, logical_h, desired_elapsed, now, self.font_dir)
                                else:
                                    im = Image.new("RGB", (logical_w, logical_h), (0, 0, 0))
                        else:
                            # Initial display, blank->message, or the same
                            # message continuing/restarting under another source.
                            self._active = desired_target
                            self._display_message_id = desired_id
                            self._display_message = desired_msg
                            self._display_elapsed = desired_elapsed
                            if desired_msg:
                                im = render_message(desired_msg, logical_w, logical_h, desired_elapsed, now, self.font_dir)
                            else:
                                im = Image.new("RGB", (logical_w, logical_h), (0, 0, 0))

                if rotation == 90:
                    im = im.transpose(Image.Transpose.ROTATE_270)
                elif rotation == 180:
                    im = im.transpose(Image.Transpose.ROTATE_180)
                elif rotation == 270:
                    im = im.transpose(Image.Transpose.ROTATE_90)
                if im.size != (physical_w, physical_h):
                    im = im.resize((physical_w, physical_h), Image.Resampling.NEAREST)

                output = self._apply_output_transform(im, effective_brightness)
                self._ddp.send(output.tobytes())
                finished = time.monotonic()
                frame_duration = max(0.0, finished - loop_start)
                budget = 1.0 / max(1, fps)
                with self._lock:
                    self._preview = im.copy()
                    self.frames_sent += 1
                    self.last_frame_at = time.time()
                    self.last_error = ""
                    self.last_frame_duration_ms = frame_duration * 1000.0
                    self._frame_times.append(finished)
                    if frame_duration > budget * 1.15:
                        self.slow_frames += 1
                        self.dropped_frames += max(1, int(frame_duration / budget) - 1)
            except Exception as exc:
                LOG.exception("Renderer frame failed")
                with self._lock:
                    self.last_error = str(exc)
                    self.frame_failures += 1
                fps = 10

            delay = max(0.0, (1.0 / fps) - (time.monotonic() - loop_start))
            time.sleep(delay)
