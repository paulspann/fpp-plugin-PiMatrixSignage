from __future__ import annotations

import base64
import ctypes
import ctypes.util
import hashlib
import json
import logging
import math
import os
import queue
import re
import selectors
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image

LOG = logging.getLogger(__name__)

SHADER_EXTENSIONS = {"fs", "frag", "glsl", "json"}
_MAX_SHADER_BYTES = 2 * 1024 * 1024


def _json_comment(text: str) -> dict:
    """Extract the first ISF JSON block comment from a shader source."""
    for m in re.finditer(r"/\*\s*(\{.*?\})\s*\*/", text, flags=re.S):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _normalise_inputs(meta: dict) -> list[dict]:
    raw = meta.get("INPUTS") or meta.get("inputs") or []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("NAME") or item.get("name") or "").strip()
        typ = str(item.get("TYPE") or item.get("type") or "float").strip()
        if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        row = {
            "name": name,
            "type": typ,
            "default": item.get("DEFAULT", item.get("default")),
            "min": item.get("MIN", item.get("min")),
            "max": item.get("MAX", item.get("max")),
            "label": str(item.get("LABEL") or item.get("label") or name),
        }
        values = item.get("VALUES", item.get("values"))
        labels = item.get("LABELS", item.get("labels"))
        if isinstance(values, list):
            row["values"] = values
        if isinstance(labels, list):
            row["labels"] = labels
        out.append(row)
    return out


def read_shader_document(path: Path) -> tuple[str, dict]:
    """Return fragment source + useful metadata from .fs/.frag/.glsl or ISF JSON export."""
    if not path.is_file() or path.stat().st_size > _MAX_SHADER_BYTES:
        raise ValueError("Shader file is missing or too large")
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, Any] = {}
    source = text
    if path.suffix.lower() == ".json":
        try:
            doc = json.loads(text)
        except Exception as exc:
            raise ValueError(f"Invalid shader JSON: {exc}") from exc
        if not isinstance(doc, dict):
            raise ValueError("Shader JSON must contain an object")
        source = str(doc.get("rawFragmentSource") or doc.get("fragmentSource") or doc.get("source") or "")
        if not source.strip():
            raise ValueError("Shader JSON does not contain rawFragmentSource/fragmentSource")
        meta.update(doc)
    block = _json_comment(source)
    if block:
        # The source-side ISF metadata is authoritative for inputs; outer JSON
        # adds catalogue title/description/author information when available.
        merged = dict(meta)
        merged.update(block)
        meta = merged
    return source, meta


def shader_asset_from_path(path: Path, asset_id: str, origin: str) -> dict:
    source, meta = read_shader_document(path)
    title = str(meta.get("title") or meta.get("TITLE") or path.stem).strip() or path.stem
    description = str(meta.get("description") or meta.get("DESCRIPTION") or "").strip()
    credit = str(meta.get("CREDIT") or meta.get("credit") or meta.get("username") or "").strip()
    categories = meta.get("CATEGORIES") or meta.get("categories") or []
    if not isinstance(categories, list):
        categories = []
    inputs = _normalise_inputs(meta)
    return {
        "id": asset_id,
        "name": title,
        "filename": path.name,
        "origin": origin,
        "description": description,
        "credit": credit,
        "categories": [str(x) for x in categories],
        "inputs": inputs,
        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }


def list_shader_assets(upload_dir: Path, builtin_dir: Path) -> list[dict]:
    """List built-in and uploaded shaders. Prefer .fs over companion JSON with same stem."""
    out: list[dict] = []
    for origin, root, prefix in (("built-in", builtin_dir, "builtin:"), ("uploaded", upload_dir, "upload:")):
        if not root.exists():
            continue
        paths = [p for p in root.iterdir() if p.is_file() and p.suffix.lower().lstrip(".") in SHADER_EXTENSIONS]
        # If an .fs/.frag/.glsl and JSON share a stem, the source file is the actual
        # asset and the JSON is treated as companion/export metadata rather than a duplicate.
        source_stems = {p.stem.lower() for p in paths if p.suffix.lower() != ".json"}
        for p in sorted(paths, key=lambda x: x.name.lower()):
            if p.suffix.lower() == ".json" and p.stem.lower() in source_stems:
                continue
            try:
                out.append(shader_asset_from_path(p, prefix + p.name, origin))
            except Exception as exc:
                LOG.warning("Unable to read shader %s: %s", p, exc)
                out.append({
                    "id": prefix + p.name, "name": p.stem, "filename": p.name,
                    "origin": origin, "description": "", "credit": "", "categories": [],
                    "inputs": [], "error": str(exc),
                })
    return out


def resolve_shader_asset(asset_id: str, upload_dir: Path, builtin_dir: Path) -> tuple[str, dict]:
    asset_id = str(asset_id or "")
    if asset_id.startswith("builtin:"):
        root = builtin_dir
        name = asset_id[len("builtin:"):]
    elif asset_id.startswith("upload:"):
        root = upload_dir
        name = asset_id[len("upload:"):]
    else:
        raise ValueError("Unknown shader asset")
    if not name or Path(name).name != name:
        raise ValueError("Invalid shader asset name")
    path = root / name
    source, meta = read_shader_document(path)
    return source, {"inputs": _normalise_inputs(meta), "path": str(path)}


def shader_default_params(inputs: list[dict]) -> dict:
    out: dict[str, Any] = {}
    for item in inputs or []:
        name = str(item.get("name") or "")
        if not name:
            continue
        typ = str(item.get("type") or "float").lower()
        value = item.get("default")
        if value is None:
            if typ in ("bool", "event"):
                value = False
            elif typ in ("point2d", "point2D"):
                value = [0.0, 0.0]
            elif typ == "color":
                value = [1.0, 1.0, 1.0, 1.0]
            else:
                value = 0.0
        out[name] = value
    return out


def _uniform_glsl_type(typ: str) -> str | None:
    t = typ.lower()
    if t == "float": return "float"
    if t in ("long", "int"): return "int"
    if t in ("bool", "event"): return "bool"
    if t == "point2d": return "vec2"
    if t == "color": return "vec4"
    return None


def prepare_fragment_source(source: str, inputs: list[dict], es: bool = False) -> str:
    """Add ISF uniforms and make common ISF shaders portable.

    GLSL requires ``#extension`` directives to appear before ordinary declarations.
    ISF/Shadertoy exports often place them after a metadata comment, while Pi Matrix
    Signage needs to inject uniforms such as TIME and RENDERSIZE.  Pull extension
    directives out first and emit them at the top of the final shader.  The common
    GLES derivatives extension is unnecessary (and commonly rejected) by desktop
    OpenGL because dFdx/dFdy/fwidth are core there, so omit it on the desktop path.
    """
    src = re.sub(r"^\s*#version[^\n]*(?:\n|$)", "", source, flags=re.M)

    extension_lines: list[str] = []
    extension_re = re.compile(
        r"^\s*#extension\s+([A-Za-z0-9_]+)\s*:\s*(enable|require|warn|disable)\s*(?://.*)?$",
        flags=re.M | re.I,
    )

    def _take_extension(match: re.Match) -> str:
        ext = match.group(1)
        mode = match.group(2).lower()
        # Desktop GLSL already provides standard derivatives.  Keeping the GLES-only
        # extension there produces warnings/errors on Mesa and is not required.
        if not es and ext == "GL_OES_standard_derivatives":
            return ""
        line = f"#extension {ext} : {mode}"
        if line not in extension_lines:
            extension_lines.append(line)
        return ""

    src = extension_re.sub(_take_extension, src)
    names = [str(i.get("name") or "") for i in inputs if i.get("name")]
    uniform_lines = []
    if not re.search(r"\buniform\s+\w+\s+TIME\b", src):
        uniform_lines.append("uniform float TIME;")
    if not re.search(r"\buniform\s+\w+\s+RENDERSIZE\b", src):
        uniform_lines.append("uniform vec2 RENDERSIZE;")
    for item in inputs:
        name = str(item.get("name") or "")
        gltype = _uniform_glsl_type(str(item.get("type") or "float"))
        if not name or not gltype:
            continue
        if re.search(rf"\buniform\s+\w+\s+{re.escape(name)}\b", src):
            continue
        uniform_lines.append(f"uniform {gltype} {name};")

    # ISF files often initialise globals from TIME/RENDERSIZE/input uniforms.
    # GLSL implementations commonly require global initialisers to be constant,
    # so move those assignments to the start of main().
    dependent = {"TIME", "RENDERSIZE", *names}
    assignments: list[str] = []
    lines = src.splitlines()
    depth = 0
    out_lines: list[str] = []
    decl_re = re.compile(r"^(\s*)(float|int|bool|vec[234]|mat[234])\s+([A-Za-z_]\w*)\s*=\s*(.+);\s*$")
    for line in lines:
        m = decl_re.match(line) if depth == 0 else None
        if m and any(re.search(rf"\b{re.escape(dep)}\b", m.group(4)) for dep in dependent):
            out_lines.append(f"{m.group(1)}{m.group(2)} {m.group(3)};")
            assignments.append(f"{m.group(3)} = {m.group(4)};")
        else:
            out_lines.append(line)
        # comments are irrelevant for the simple top-level tracking needed here.
        depth += line.count("{") - line.count("}")
    src = "\n".join(out_lines)
    if assignments:
        main_re = re.compile(r"(void\s+main\s*\([^)]*\)\s*\{)")
        src, count = main_re.subn(lambda m: m.group(1) + "\n    " + "\n    ".join(assignments), src, count=1)
        if not count:
            raise ValueError("Shader does not contain a main() function")

    header = list(extension_lines)
    if es and not re.search(r"\bprecision\s+(?:lowp|mediump|highp)\s+float\s*;", src):
        header.append("precision highp float;")
    header.extend(uniform_lines)
    return "\n".join(header) + "\n" + src


class ShaderClient:
    """Non-blocking client for an isolated persistent shader-render subprocess.

    The LED renderer always receives the most recently completed frame. Heavy or
    broken shader compilation therefore cannot hold the DDP rendering loop up.
    """
    def __init__(self, upload_dir: Path, builtin_dir: Path):
        self.upload_dir = Path(upload_dir)
        self.builtin_dir = Path(builtin_dir)
        self._frames: dict[str, tuple[tuple, Image.Image]] = {}
        self._errors: dict[str, str] = {}
        self._pending: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._seq = 0
        # Per-layer performance data lets the client distinguish a slow shader
        # from a dead renderer.  Heavy Shadertoy/ISF effects can take longer to
        # compile/render on a Pi 4 than the old fixed 1.5s timeout allowed.
        self._stats: dict[str, dict] = {}
        self._adaptive_scale: dict[str, tuple[str, int, int, float]] = {}
        self._warmed_sources: set[str] = set()

    def _start_thread(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="shader-client")
        self._thread.start()

    def get_frame(self, key: str, asset_id: str, width: int, height: int, elapsed: float,
                  params: dict | None = None, fps: float = 15.0, time_scale: float = 1.0,
                  quality: str = "auto") -> Image.Image:
        width, height = max(1, int(width)), max(1, int(height))
        fps = max(1.0, min(30.0, float(fps or 15.0)))
        bucket = int(max(0.0, elapsed) * fps)
        try:
            source, meta = resolve_shader_asset(asset_id, self.upload_dir, self.builtin_dir)
        except Exception as exc:
            with self._lock:
                self._errors[key] = str(exc)
            return Image.new("RGBA", (width, height), (0, 0, 0, 0))
        input_defs = meta.get("inputs") or []
        merged = shader_default_params(input_defs)
        if isinstance(params, dict):
            merged.update(params)
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        quality = str(quality or "auto").lower()
        if quality not in ("auto", "native", "half", "quarter"):
            quality = "auto"
        sig = (source_hash, width, height,
               json.dumps(merged, sort_keys=True, separators=(",", ":"), default=str), bucket,
               round(float(time_scale), 4), quality)
        with self._lock:
            cached = self._frames.get(key)
            if cached and cached[0] == sig:
                return cached[1].copy()
            self._pending[key] = {
                "key": key, "sig": sig, "source": source, "source_hash": source_hash,
                "inputs": input_defs, "w": width, "h": height,
                "time": bucket / fps * float(time_scale), "params": merged,
                "quality": quality,
            }
            # Use a prior frame while the latest one is being generated, but
            # never reuse it after the layer has changed size.
            frame = (cached[1].copy() if cached and cached[1].size == (width, height)
                     else Image.new("RGBA", (width, height), (0, 0, 0, 0)))
            self._wake.set()
        self._start_thread()
        return frame

    def error(self, key: str) -> str:
        with self._lock:
            return self._errors.get(key, "")

    def stats(self, key: str) -> dict:
        """Return non-fatal performance information for the UI/diagnostics."""
        with self._lock:
            return dict(self._stats.get(key, {}))

    def _kill_proc(self):
        proc, self._proc = self._proc, None
        # The compiled-program cache lives in the worker, so a restarted worker
        # must be treated as cold even if this client saw the shader before.
        self._warmed_sources.clear()
        if proc:
            try: proc.kill()
            except Exception: pass
            try: proc.wait(timeout=.5)
            except Exception: pass

    def _ensure_proc(self):
        if self._proc and self._proc.poll() is None:
            return self._proc
        self._kill_proc()
        self._proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, env={**os.environ, "EGL_PLATFORM": os.environ.get("EGL_PLATFORM", "surfaceless")},
        )
        return self._proc

    def _request_once(self, item: dict, scale: float, timeout_s: float) -> tuple[Image.Image | None, str, float]:
        """Render one frame at a requested internal resolution.

        A shader may be evaluated below the physical LED resolution and then
        upscaled.  That is a useful escape hatch for expensive ray-marched
        shaders on a Pi 4 and is much better than killing the helper every
        1.5 seconds.
        """
        proc = self._ensure_proc()
        self._seq += 1
        req_id = self._seq
        rw = max(1, int(round(item["w"] * scale)))
        rh = max(1, int(round(item["h"] * scale)))
        req = {"id": req_id, "source": item["source"], "inputs": item["inputs"],
               "w": rw, "h": rh, "time": item["time"], "params": item["params"]}
        try:
            assert proc.stdin and proc.stdout
            proc.stdin.write(json.dumps(req, separators=(",", ":")) + "\n")
            proc.stdin.flush()
            sel = selectors.DefaultSelector(); sel.register(proc.stdout, selectors.EVENT_READ)
            events = sel.select(timeout=max(.5, float(timeout_s))); sel.close()
            if not events:
                self._kill_proc()
                return None, f"Shader render timed out after {timeout_s:g}s", 0.0
            line = proc.stdout.readline()
            if not line:
                self._kill_proc(); return None, "Shader renderer stopped unexpectedly", 0.0
            result = json.loads(line)
            if int(result.get("id", -1)) != req_id:
                return None, "Shader renderer protocol mismatch", 0.0
            if not result.get("ok"):
                return None, str(result.get("error") or "Shader failed"), float(result.get("render_ms") or 0.0)
            raw = base64.b64decode(result.get("rgba") or "", validate=True)
            expected = rw * rh * 4
            if len(raw) != expected:
                return None, "Shader renderer returned an invalid frame", 0.0
            im = Image.frombytes("RGBA", (rw, rh), raw)
            if (rw, rh) != (item["w"], item["h"]):
                # Bilinear upscaling preserves smooth procedural colour fields;
                # the final image is still sampled onto the physical LED grid.
                im = im.resize((item["w"], item["h"]), Image.Resampling.BILINEAR)
            return im, "", float(result.get("render_ms") or 0.0)
        except Exception as exc:
            self._kill_proc(); return None, str(exc), 0.0

    def _request(self, item: dict) -> tuple[Image.Image | None, str]:
        key = str(item.get("key") or "")
        source_hash = str(item.get("source_hash") or "")
        quality = str(item.get("quality") or "auto").lower()
        explicit = {"native": 1.0, "half": .5, "quarter": .25}
        if quality in explicit:
            scales = [explicit[quality]]
        else:
            prior = self._adaptive_scale.get(key)
            if prior and prior[:3] == (source_hash, int(item["w"]), int(item["h"])):
                preferred = float(prior[3])
                # Once Auto has learned that a shader needs a lower resolution,
                # do not waste time retrying a more expensive scale on every frame.
                scales = [preferred] + [s for s in (.5, .25) if s < preferred]
            else:
                scales = [1.0, .5, .25]

        last_error = "Shader failed"
        for scale in scales:
            # First compile gets a generous window.  Warm shaders use their last
            # measured render time to choose a timeout, capped so a pathological
            # shader cannot occupy the helper forever.
            stat = self._stats.get(key, {})
            last_ms = float(stat.get("render_ms") or 0.0)
            cold = source_hash not in self._warmed_sources
            timeout_s = 8.0 if cold else max(3.0, min(15.0, last_ms / 1000.0 * 4.0 + 1.0))
            im, error, render_ms = self._request_once(item, scale, timeout_s)
            if im is not None:
                self._warmed_sources.add(source_hash)
                if quality == "auto":
                    self._adaptive_scale[key] = (source_hash, int(item["w"]), int(item["h"]), scale)
                self._stats[key] = {
                    "render_ms": round(render_ms, 1),
                    "quality": quality,
                    "render_scale": scale,
                    "render_width": max(1, int(round(item["w"] * scale))),
                    "render_height": max(1, int(round(item["h"] * scale))),
                }
                return im, ""
            last_error = error or last_error
            # Compile/link errors are deterministic; resolution fallback cannot
            # repair them, so only timeout/worker failures try lower resolutions.
            lowered = last_error.lower()
            if quality != "auto" or ("timed out" not in lowered and "stopped unexpectedly" not in lowered):
                break
        if quality == "auto" and "timed out" in last_error.lower():
            last_error = "Shader is too slow even at adaptive 1/4 resolution (" + last_error + ")"
        return None, last_error

    def _run(self):
        while True:
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            while True:
                with self._lock:
                    if not self._pending:
                        break
                    # Render the newest request for one key. Any older request for
                    # that same layer was replaced before we got here.
                    key, item = self._pending.popitem()
                im, error = self._request(item)
                with self._lock:
                    # Don't overwrite a newer request's eventual result with a stale one.
                    if im is not None:
                        self._frames[key] = (item["sig"], im)
                        self._errors.pop(key, None)
                    elif error:
                        self._errors[key] = error
                time.sleep(0)


# ----------------------------- isolated worker -----------------------------

EGL_DEFAULT_DISPLAY = 0
EGL_NO_DISPLAY = 0
EGL_NO_CONTEXT = 0
EGL_NO_SURFACE = 0
EGL_NONE = 0x3038
EGL_RED_SIZE = 0x3024
EGL_GREEN_SIZE = 0x3023
EGL_BLUE_SIZE = 0x3022
EGL_ALPHA_SIZE = 0x3021
EGL_SURFACE_TYPE = 0x3033
EGL_PBUFFER_BIT = 0x0001
EGL_RENDERABLE_TYPE = 0x3040
EGL_OPENGL_BIT = 0x0008
EGL_OPENGL_ES2_BIT = 0x0004
EGL_WIDTH = 0x3057
EGL_HEIGHT = 0x3056
EGL_OPENGL_API = 0x30A2
EGL_OPENGL_ES_API = 0x30A0
EGL_CONTEXT_CLIENT_VERSION = 0x3098

GL_VERTEX_SHADER = 0x8B31
GL_FRAGMENT_SHADER = 0x8B30
GL_COMPILE_STATUS = 0x8B81
GL_LINK_STATUS = 0x8B82
GL_INFO_LOG_LENGTH = 0x8B84
GL_ARRAY_BUFFER = 0x8892
GL_STATIC_DRAW = 0x88E4
GL_FLOAT = 0x1406
GL_TRIANGLE_STRIP = 0x0005
GL_RGBA = 0x1908
GL_UNSIGNED_BYTE = 0x1401
GL_COLOR_BUFFER_BIT = 0x00004000


class _GLRenderer:
    def __init__(self):
        os.environ.setdefault("EGL_PLATFORM", "surfaceless")
        egl_name = ctypes.util.find_library("EGL") or "libEGL.so.1"
        self.egl = ctypes.CDLL(egl_name)
        self.gl = None
        self.is_es = False
        self.display = None; self.context = None; self.surface = None; self.config = None
        self.surface_w = 0; self.surface_h = 0
        self.programs: dict[str, tuple[int, list[dict]]] = {}
        self._setup_egl_functions()
        self._init_context()
        self._setup_gl_functions()
        self.vbo = ctypes.c_uint(0)
        self.gl.glGenBuffers(1, ctypes.byref(self.vbo))
        self.gl.glBindBuffer(GL_ARRAY_BUFFER, self.vbo.value)
        verts = (ctypes.c_float * 8)(-1,-1, 1,-1, -1,1, 1,1)
        self.gl.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(verts), ctypes.cast(verts, ctypes.c_void_p), GL_STATIC_DRAW)

    def _setup_egl_functions(self):
        E = self.egl
        E.eglGetDisplay.argtypes=[ctypes.c_void_p]; E.eglGetDisplay.restype=ctypes.c_void_p
        E.eglInitialize.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_int)];E.eglInitialize.restype=ctypes.c_uint
        E.eglBindAPI.argtypes=[ctypes.c_uint];E.eglBindAPI.restype=ctypes.c_uint
        E.eglChooseConfig.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_void_p),ctypes.c_int,ctypes.POINTER(ctypes.c_int)];E.eglChooseConfig.restype=ctypes.c_uint
        E.eglCreateContext.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int)];E.eglCreateContext.restype=ctypes.c_void_p
        E.eglCreatePbufferSurface.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int)];E.eglCreatePbufferSurface.restype=ctypes.c_void_p
        E.eglMakeCurrent.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p];E.eglMakeCurrent.restype=ctypes.c_uint
        E.eglDestroySurface.argtypes=[ctypes.c_void_p,ctypes.c_void_p];E.eglDestroySurface.restype=ctypes.c_uint

    def _choose_context(self, api: int, render_bit: int, lib_candidates: list[str], es: bool):
        E=self.egl
        if not E.eglBindAPI(api): return False
        attrs=(ctypes.c_int*13)(EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,render_bit,EGL_NONE)
        cfg=ctypes.c_void_p(); n=ctypes.c_int()
        if not E.eglChooseConfig(self.display,attrs,ctypes.byref(cfg),1,ctypes.byref(n)) or n.value<1: return False
        cattrs=(ctypes.c_int*3)(EGL_CONTEXT_CLIENT_VERSION,2,EGL_NONE) if es else (ctypes.c_int*1)(EGL_NONE)
        ctx=E.eglCreateContext(self.display,cfg,None,cattrs)
        if not ctx: return False
        lib=None
        for candidate in lib_candidates:
            try:
                lib=ctypes.CDLL(ctypes.util.find_library(candidate) or candidate);break
            except Exception: continue
        if lib is None: return False
        self.config=cfg;self.context=ctx;self.gl=lib;self.is_es=es
        return True

    def _init_context(self):
        self.display=self.egl.eglGetDisplay(ctypes.c_void_p(EGL_DEFAULT_DISPLAY))
        if not self.display: raise RuntimeError("EGL display unavailable")
        major=ctypes.c_int();minor=ctypes.c_int()
        if not self.egl.eglInitialize(self.display,ctypes.byref(major),ctypes.byref(minor)):
            raise RuntimeError("Unable to initialise EGL")
        if not self._choose_context(EGL_OPENGL_API,EGL_OPENGL_BIT,["GL","libGL.so.1"],False):
            if not self._choose_context(EGL_OPENGL_ES_API,EGL_OPENGL_ES2_BIT,["GLESv2","libGLESv2.so.2"],True):
                raise RuntimeError("No usable OpenGL/OpenGL ES shader context")
        self._ensure_surface(16,16)

    def _setup_gl_functions(self):
        G=self.gl
        # Shader/program
        G.glCreateShader.argtypes=[ctypes.c_uint];G.glCreateShader.restype=ctypes.c_uint
        G.glShaderSource.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.POINTER(ctypes.c_char_p),ctypes.POINTER(ctypes.c_int)]
        G.glCompileShader.argtypes=[ctypes.c_uint]
        G.glGetShaderiv.argtypes=[ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_int)]
        G.glGetShaderInfoLog.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.POINTER(ctypes.c_int),ctypes.c_char_p]
        G.glCreateProgram.restype=ctypes.c_uint
        G.glAttachShader.argtypes=[ctypes.c_uint,ctypes.c_uint]
        G.glBindAttribLocation.argtypes=[ctypes.c_uint,ctypes.c_uint,ctypes.c_char_p]
        G.glLinkProgram.argtypes=[ctypes.c_uint]
        G.glGetProgramiv.argtypes=[ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_int)]
        G.glGetProgramInfoLog.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.POINTER(ctypes.c_int),ctypes.c_char_p]
        G.glDeleteShader.argtypes=[ctypes.c_uint]
        G.glUseProgram.argtypes=[ctypes.c_uint]
        G.glGetUniformLocation.argtypes=[ctypes.c_uint,ctypes.c_char_p];G.glGetUniformLocation.restype=ctypes.c_int
        G.glUniform1f.argtypes=[ctypes.c_int,ctypes.c_float];G.glUniform1i.argtypes=[ctypes.c_int,ctypes.c_int]
        G.glUniform2f.argtypes=[ctypes.c_int,ctypes.c_float,ctypes.c_float]
        G.glUniform4f.argtypes=[ctypes.c_int,ctypes.c_float,ctypes.c_float,ctypes.c_float,ctypes.c_float]
        # Drawing
        G.glGenBuffers.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_uint)]
        G.glBindBuffer.argtypes=[ctypes.c_uint,ctypes.c_uint]
        G.glBufferData.argtypes=[ctypes.c_uint,ctypes.c_ssize_t,ctypes.c_void_p,ctypes.c_uint]
        G.glEnableVertexAttribArray.argtypes=[ctypes.c_uint]
        G.glVertexAttribPointer.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_uint,ctypes.c_ubyte,ctypes.c_int,ctypes.c_void_p]
        G.glViewport.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int]
        G.glClearColor.argtypes=[ctypes.c_float,ctypes.c_float,ctypes.c_float,ctypes.c_float]
        G.glClear.argtypes=[ctypes.c_uint]
        G.glDrawArrays.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_int]
        G.glReadPixels.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
        G.glFinish.argtypes=[]

    def _ensure_surface(self,w:int,h:int):
        if self.surface and w<=self.surface_w and h<=self.surface_h:
            if not self.egl.eglMakeCurrent(self.display,self.surface,self.surface,self.context):
                raise RuntimeError("Unable to activate shader context")
            return
        if self.surface:
            self.egl.eglDestroySurface(self.display,self.surface);self.surface=None
        self.surface_w=max(16,w);self.surface_h=max(16,h)
        attrs=(ctypes.c_int*5)(EGL_WIDTH,self.surface_w,EGL_HEIGHT,self.surface_h,EGL_NONE)
        self.surface=self.egl.eglCreatePbufferSurface(self.display,self.config,attrs)
        if not self.surface: raise RuntimeError("Unable to create shader surface")
        if not self.egl.eglMakeCurrent(self.display,self.surface,self.surface,self.context):
            raise RuntimeError("Unable to activate shader surface")

    def _compile(self, source:str, inputs:list[dict]) -> int:
        prepared=prepare_fragment_source(source,inputs,self.is_es)
        vertex=("attribute vec2 a_position;\nvoid main(){gl_Position=vec4(a_position,0.0,1.0);}\n")
        def shader(kind:int, text:str)->int:
            sid=self.gl.glCreateShader(kind); data=text.encode("utf-8"); ptr=ctypes.c_char_p(data)
            self.gl.glShaderSource(sid,1,ctypes.byref(ptr),None);self.gl.glCompileShader(sid)
            ok=ctypes.c_int();self.gl.glGetShaderiv(sid,GL_COMPILE_STATUS,ctypes.byref(ok))
            if not ok.value:
                ln=ctypes.c_int();self.gl.glGetShaderiv(sid,GL_INFO_LOG_LENGTH,ctypes.byref(ln));buf=ctypes.create_string_buffer(max(1,ln.value));self.gl.glGetShaderInfoLog(sid,len(buf),None,buf)
                raise RuntimeError("Shader compile error: "+buf.value.decode("utf-8","replace")[:1000])
            return sid
        vs=shader(GL_VERTEX_SHADER,vertex);fs=shader(GL_FRAGMENT_SHADER,prepared)
        prog=self.gl.glCreateProgram();self.gl.glAttachShader(prog,vs);self.gl.glAttachShader(prog,fs);self.gl.glBindAttribLocation(prog,0,b"a_position");self.gl.glLinkProgram(prog)
        ok=ctypes.c_int();self.gl.glGetProgramiv(prog,GL_LINK_STATUS,ctypes.byref(ok))
        self.gl.glDeleteShader(vs);self.gl.glDeleteShader(fs)
        if not ok.value:
            ln=ctypes.c_int();self.gl.glGetProgramiv(prog,GL_INFO_LOG_LENGTH,ctypes.byref(ln));buf=ctypes.create_string_buffer(max(1,ln.value));self.gl.glGetProgramInfoLog(prog,len(buf),None,buf)
            raise RuntimeError("Shader link error: "+buf.value.decode("utf-8","replace")[:1000])
        return prog

    def render(self, source:str, inputs:list[dict], w:int,h:int,t:float,params:dict)->bytes:
        self._ensure_surface(w,h)
        digest=hashlib.sha256(("es" if self.is_es else "gl").encode()+source.encode()).hexdigest()
        entry=self.programs.get(digest)
        if not entry:
            prog=self._compile(source,inputs);self.programs[digest]=(prog,inputs);entry=(prog,inputs)
            if len(self.programs)>32:
                # Programs are tiny relative to media assets; simply bound future cache growth.
                self.programs=dict(list(self.programs.items())[-24:])
        prog=entry[0];G=self.gl
        G.glViewport(0,0,w,h);G.glClearColor(0,0,0,0);G.glClear(GL_COLOR_BUFFER_BIT);G.glUseProgram(prog)
        def loc(name:str)->int: return G.glGetUniformLocation(prog,name.encode())
        L=loc("TIME");
        if L>=0:G.glUniform1f(L,float(t))
        L=loc("RENDERSIZE");
        if L>=0:G.glUniform2f(L,float(w),float(h))
        for item in inputs:
            name=str(item.get("name") or "");typ=str(item.get("type") or "float").lower();L=loc(name)
            if L<0:continue
            value=params.get(name,item.get("default"))
            try:
                if typ=="float":G.glUniform1f(L,float(value or 0))
                elif typ in ("long","int"):G.glUniform1i(L,int(value or 0))
                elif typ in ("bool","event"):G.glUniform1i(L,1 if bool(value) else 0)
                elif typ=="point2d":
                    v=value if isinstance(value,(list,tuple)) else [0,0];G.glUniform2f(L,float(v[0]),float(v[1]))
                elif typ=="color":
                    v=list(value) if isinstance(value,(list,tuple)) else [1,1,1,1]
                    while len(v)<4:v.append(1.0)
                    G.glUniform4f(L,*[float(x) for x in v[:4]])
            except Exception: pass
        G.glBindBuffer(GL_ARRAY_BUFFER,self.vbo.value);G.glEnableVertexAttribArray(0);G.glVertexAttribPointer(0,2,GL_FLOAT,0,0,None)
        G.glDrawArrays(GL_TRIANGLE_STRIP,0,4);G.glFinish()
        buf=(ctypes.c_ubyte*(w*h*4))();G.glReadPixels(0,0,w,h,GL_RGBA,GL_UNSIGNED_BYTE,ctypes.cast(buf,ctypes.c_void_p))
        # OpenGL's first row is the bottom row; PIL/display coordinates start at top.
        raw=bytes(buf);stride=w*4
        return b"".join(raw[y*stride:(y+1)*stride] for y in range(h-1,-1,-1))


def _worker_main():
    renderer=None
    for line in sys.stdin:
        started=time.perf_counter()
        try:
            req=json.loads(line);rid=req.get("id")
            if renderer is None: renderer=_GLRenderer()
            raw=renderer.render(str(req.get("source") or ""),list(req.get("inputs") or []),max(1,int(req.get("w") or 1)),max(1,int(req.get("h") or 1)),float(req.get("time") or 0),dict(req.get("params") or {}))
            render_ms=(time.perf_counter()-started)*1000.0
            resp={"id":rid,"ok":True,"rgba":base64.b64encode(raw).decode("ascii"),"render_ms":round(render_ms,2)}
        except Exception as exc:
            resp={"id":locals().get("rid",None),"ok":False,"error":str(exc)[:1500],
                  "render_ms":round((time.perf_counter()-started)*1000.0,2)}
        sys.stdout.write(json.dumps(resp,separators=(",",":"))+"\n");sys.stdout.flush()


if __name__ == "__main__" and "--worker" in sys.argv:
    _worker_main()
