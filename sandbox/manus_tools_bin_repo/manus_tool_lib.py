#!/usr/bin/env python3
"""Shared implementation library for the 16 manus-* shell tools.

Every executable in this directory:
  - accepts argv ONLY (never a shell command string),
  - operates inside the sandbox user home (bounded working directory),
  - prints a single structured JSON object on stdout:
      {"ok": true, "tool": "...", "data": {...}}
      {"ok": false, "tool": "...", "error": {"code": "...", "message": "..."}},
  - exits 0 on handled outcomes (including structured errors) and 2 on
    internal crashes (so the executor can distinguish the two),
  - never prints secrets.

The backend ManusShellExecutor allowlists these absolute paths, quotes every
argv token itself (shell=False equivalent), wraps the call in coreutils
`timeout`, and bounds/redacts output.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

MAX_OUTPUT_CHARS = 200_000
MANUS_DIR = ".manus"


# ── output helpers ───────────────────────────────────────────────────────────
def emit_ok(tool: str, data: dict) -> int:
    print(json.dumps({"ok": True, "tool": tool, "data": data},
                     ensure_ascii=False)[:MAX_OUTPUT_CHARS])
    return 0


def emit_err(tool: str, code: str, message: str, **extra) -> int:
    payload = {"ok": False, "tool": tool,
               "error": {"code": code, "message": message}}
    payload["error"].update(extra)
    print(json.dumps(payload, ensure_ascii=False)[:MAX_OUTPUT_CHARS])
    return 0


def crash_guard(tool_name: str):
    """Return a main() wrapper: turn unexpected exceptions into exit 2."""
    def _wrap(fn):
        def run(argv):
            try:
                return fn(argv)
            except SystemExit:
                raise
            except BrokenPipeError:
                return 0
            except FileNotFoundError as exc:
                print(json.dumps({
                    "ok": False, "tool": tool_name,
                    "error": {"code": "NOT_FOUND", "message": str(exc)[:300]},
                }, ensure_ascii=False))
                return 2
            except PermissionError as exc:
                print(json.dumps({
                    "ok": False, "tool": tool_name,
                    "error": {"code": "PERMISSION_DENIED", "message": str(exc)[:300]},
                }, ensure_ascii=False))
                return 2
            except ValueError as exc:
                print(json.dumps({
                    "ok": False, "tool": tool_name,
                    "error": {"code": "VALIDATION_ERROR", "message": str(exc)[:300]},
                }, ensure_ascii=False))
                return 2
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({
                    "ok": False, "tool": tool_name,
                    "error": {"code": "INTERNAL_ERROR", "message": str(exc)[:500]},
                }, ensure_ascii=False))
                return 2
        return run
    return _wrap


def _require_file(argv: list, index: int, exts: tuple = ()) -> Path:
    if len(argv) <= index:
        raise ValueError(f"missing required argument #{index + 1}")
    p = Path(argv[index]).expanduser()
    if not p.is_absolute():
        raise ValueError(f"path must be absolute: {p}")
    if exts and p.suffix.lower() not in exts:
        raise ValueError(f"expected one of {exts}, got {p.suffix}")
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    return p


# ── 1. manus-md-to-pdf ───────────────────────────────────────────────────────
def md_to_pdf(argv: list) -> int:
    tool = "manus-md-to-pdf"
    src = _require_file(argv, 0, (".md", ".markdown"))
    out = Path(argv[1] if len(argv) > 1 else str(src.with_suffix(".pdf")))
    if not out.is_absolute():
        raise ValueError(f"output path must be absolute: {out}")

    import markdown as _markdown
    from xml.sax.saxutils import escape as _esc
    from html.parser import HTMLParser
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Preformatted)

    text = src.read_text(encoding="utf-8", errors="replace")
    html = _markdown.markdown(text, extensions=["tables", "fenced_code"])

    class _P(HTMLParser):
        """Tiny top-level tag walker — enough for platypus conversion."""

        def __init__(self):
            super().__init__()
            self.items = []
            self._buf = []
            self._tag = None

        def handle_starttag(self, tag, attrs):
            if tag in ("p", "h1", "h2", "h3", "h4", "li", "pre", "blockquote"):
                self._tag = tag
                self._buf = []

        def handle_endtag(self, tag):
            if self._tag == tag:
                content = " ".join("".join(self._buf).split())
                if content:
                    self.items.append((tag, content))
                self._tag = None

        def handle_data(self, data):
            if self._tag:
                self._buf.append(data)

    parser = _P()
    parser.feed(html)
    doc = SimpleDocTemplate(str(out), pagesize=A4)
    styles = getSampleStyleSheet()
    flow = []
    for tag, content in parser.items:
        if tag == "pre":
            flow.append(Preformatted(content, styles["Code"]))
        elif tag.startswith("h"):
            flow.append(Paragraph(
                _esc(content),
                styles["Title" if tag == "h1" else "Heading2"]))
        else:
            flow.append(Paragraph(_esc(content), styles["BodyText"]))
        flow.append(Spacer(1, 6))
    if not flow:
        flow.append(Paragraph(_esc(text[:2000]), styles["BodyText"]))
    doc.build(flow)
    return emit_ok(tool, {"input": str(src), "output": str(out),
                          "bytes": out.stat().st_size})


# ── 2. manus-analyze-pptx ────────────────────────────────────────────────────
def analyze_pptx(argv: list) -> int:
    tool = "manus-analyze-pptx"
    src = _require_file(argv, 0, (".pptx",))
    from pptx import Presentation
    prs = Presentation(str(src))
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                t = shape.text_frame.text.strip()
                if t:
                    texts.append(t[:500])
        slides.append({"slide": i, "texts": texts[:10]})
    return emit_ok(tool, {"file": str(src), "slide_count": len(prs.slides),
                          "slides": slides[:50]})


# ── 3. manus-analyze-video ───────────────────────────────────────────────────
def analyze_video(argv: list) -> int:
    tool = "manus-analyze-video"
    if shutil.which("ffprobe") is None:
        return emit_err(tool, "CAPABILITY_UNAVAILABLE", "ffprobe not installed")
    src = _require_file(argv, 0)
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(src)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return emit_err(tool, "EXECUTION_ERROR", out.stderr[:400])
    info = json.loads(out.stdout or "{}")
    fmt = info.get("format", {})
    return emit_ok(tool, {
        "file": str(src),
        "duration_seconds": float(fmt.get("duration", 0) or 0),
        "size_bytes": int(fmt.get("size", 0) or 0),
        "streams": [
            {"type": s.get("codec_type"), "codec": s.get("codec_name"),
             "width": s.get("width"), "height": s.get("height")}
            for s in info.get("streams", [])[:8]
        ],
    })


# ── 4. manus-render-diagram ──────────────────────────────────────────────────
def render_diagram(argv: list) -> int:
    tool = "manus-render-diagram"
    if shutil.which("dot") is None:
        return emit_err(tool, "CAPABILITY_UNAVAILABLE",
                        "graphviz (dot) not installed")
    src = _require_file(argv, 0)
    out = Path(argv[1] if len(argv) > 1 else str(src.with_suffix(".png")))
    fmt = out.suffix.lower().lstrip(".") or "png"
    cmd = ["dot", f"-T{fmt}", str(src), "-o", str(out)]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if run.returncode != 0:
        return emit_err(tool, "EXECUTION_ERROR", run.stderr[:400])
    return emit_ok(tool, {"input": str(src), "output": str(out),
                          "format": fmt, "bytes": out.stat().st_size})


# ── 5. manus-upload-file ─────────────────────────────────────────────────────
def upload_file(argv: list) -> int:
    tool = "manus-upload-file"
    if not argv:
        return emit_err(tool, "VALIDATION_ERROR",
                        "usage: manus-upload-file <abs-path> [--name NAME]")
    src = _require_file(argv, 0)
    name = src.name
    if "--name" in argv:
        i = argv.index("--name")
        if len(argv) > i + 1:
            name = argv[i + 1]
    digest = hashlib.sha256()
    with src.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    delivery = Path(MANUS_DIR) / "delivery"
    delivery.mkdir(parents=True, exist_ok=True)
    manifest = delivery / "manifest.json"
    entries = []
    if manifest.exists():
        try:
            entries = json.loads(manifest.read_text())
        except Exception:
            entries = []
    entry = {"name": name, "path": str(src),
             "size_bytes": src.stat().st_size, "sha256": digest.hexdigest(),
             "registered_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    entries = [e for e in entries if e["path"] != str(src)] + [entry]
    manifest.write_text(json.dumps(entries[-100:], indent=1))
    return emit_ok(tool, {
        "file": entry,
        "message": "File registered for delivery — attach it via "
                   "message_notify_user to send it to the user.",
    })


# ── 6. manus-webdev-logs ─────────────────────────────────────────────────────
def webdev_logs(argv: list) -> int:
    tool = "manus-webdev-logs"
    n = 80
    if argv and argv[0].isdigit():
        n = int(argv[0])
    for c in (Path("server.log"), Path("webdev/server.log"),
              Path(".manus/webdev/server.log")):
        if c.exists():
            lines = c.read_text(errors="replace").splitlines()[-n:]
            return emit_ok(tool, {"log": str(c), "lines": lines})
    return emit_err(tool, "NOT_FOUND", "no server.log found (start a server first)")


# ── 7. manus-config ──────────────────────────────────────────────────────────
def config(argv: list) -> int:
    tool = "manus-config"
    cfg = Path(MANUS_DIR) / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
        except Exception:
            data = {}
    action = argv[0] if argv else "list"
    if action == "list":
        return emit_ok(tool, {"config": data})
    if action == "get":
        if len(argv) < 2:
            return emit_err(tool, "VALIDATION_ERROR", "usage: manus-config get <key>")
        return emit_ok(tool, {"key": argv[1], "value": data.get(argv[1])})
    if action == "set":
        if len(argv) < 3:
            return emit_err(tool, "VALIDATION_ERROR",
                            "usage: manus-config set <key> <value>")
        data[argv[1]] = argv[2]
        cfg.write_text(json.dumps(data, indent=1))
        return emit_ok(tool, {"key": argv[1], "value": argv[2], "saved": True})
    return emit_err(tool, "VALIDATION_ERROR", f"unknown action '{action}'")


# ── 8. manus-heartbeat ───────────────────────────────────────────────────────
def heartbeat(argv: list) -> int:
    tool = "manus-heartbeat"
    hb = Path(MANUS_DIR) / "heartbeat.json"
    hb.parent.mkdir(parents=True, exist_ok=True)
    state = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "epoch": int(time.time()), "pid": os.getpid(),
             "service": argv[0] if argv else "default", "status": "alive"}
    hb.write_text(json.dumps(state, indent=1))
    return emit_ok(tool, state)


# ── 9. manus-channel ─────────────────────────────────────────────────────────
def channel(argv: list) -> int:
    tool = "manus-channel"
    ch = Path(MANUS_DIR) / "channel"
    ch.mkdir(parents=True, exist_ok=True)
    action = argv[0] if argv else "read"
    if action == "send":
        if len(argv) < 3:
            return emit_err(tool, "VALIDATION_ERROR",
                            "usage: manus-channel send <channel> <message>")
        box = ch / f"{argv[1]}.jsonl"
        with box.open("a") as f:
            f.write(json.dumps({
                "from": os.environ.get("MANUS_AGENT", "agent"),
                "message": argv[2][:2000],
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, ensure_ascii=False) + "\n")
        return emit_ok(tool, {"channel": argv[1], "sent": True})
    if action == "read":
        box = ch / f"{argv[1] if len(argv) > 1 else 'default'}.jsonl"
        if not box.exists():
            return emit_ok(tool, {"channel": box.stem, "messages": []})
        msgs = [json.loads(l) for l in box.read_text().splitlines() if l.strip()]
        return emit_ok(tool, {"channel": box.stem, "messages": msgs[-50:]})
    if action == "list":
        return emit_ok(tool, {"channels": [p.stem for p in ch.glob("*.jsonl")]})
    return emit_err(tool, "VALIDATION_ERROR", f"unknown action '{action}'")


# ── 10. manus-export-slides ──────────────────────────────────────────────────
def export_slides(argv: list) -> int:
    tool = "manus-export-slides"
    src = _require_file(argv, 0, (".md",))
    out = Path(argv[1] if len(argv) > 1 else str(src.with_suffix(".pdf")))
    text = src.read_text(encoding="utf-8", errors="replace")
    slides = [s.strip() for s in text.split("\n---\n") if s.strip()]
    parts = [f"# Slide {i}\n\n{s}" for i, s in enumerate(slides, 1)]
    tmp_md = Path(f"{src}.export.tmp.md")
    tmp_md.write_text("\n\n".join(parts))
    try:
        rc = md_to_pdf([str(tmp_md), str(out)])
    finally:
        tmp_md.unlink(missing_ok=True)
    if rc == 0:
        return emit_ok(tool, {"input": str(src), "output": str(out),
                              "slides": len(slides), "bytes": out.stat().st_size})
    return rc


# ── 11. manus-speech-to-text ─────────────────────────────────────────────────
def speech_to_text(argv: list) -> int:
    tool = "manus-speech-to-text"
    if shutil.which("whisper") is None:
        return emit_err(tool, "CAPABILITY_UNAVAILABLE",
                        "no local speech-to-text engine (whisper) installed "
                        "in this sandbox")
    src = _require_file(argv, 0)
    out = subprocess.run(["whisper", "--output_format", "txt", str(src)],
                         capture_output=True, text=True, timeout=300)
    return emit_ok(tool, {"file": str(src), "text": out.stdout[:8000]})


# ── 12. manus-token-local-proxy ──────────────────────────────────────────────
def token_local_proxy(argv: list) -> int:
    tool = "manus-token-local-proxy"
    usage = Path(MANUS_DIR) / "usage.json"
    action = argv[0] if argv else "stats"
    if action == "record":
        if len(argv) < 3:
            return emit_err(tool, "VALIDATION_ERROR",
                            "usage: manus-token-local-proxy record <tool> <tokens>")
        data = json.loads(usage.read_text()) if usage.exists() else {"calls": []}
        data["calls"] = (data.get("calls") or [])[-500:]
        data["calls"].append({"tool": argv[1], "tokens": int(argv[2]),
                              "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        usage.write_text(json.dumps(data))
        return emit_ok(tool, {"recorded": True})
    data = json.loads(usage.read_text()) if usage.exists() else {"calls": []}
    calls = data.get("calls") or []
    total = sum(c.get("tokens", 0) for c in calls)
    return emit_ok(tool, {"total_tokens": total, "calls": len(calls),
                          "recent": calls[-10:]})


# ── 13. manus-mcp-cli ────────────────────────────────────────────────────────
def mcp_cli(argv: list) -> int:
    tool = "manus-mcp-cli"
    return emit_err(
        tool, "ROUTE_VIA_MCP",
        "MCP tools must be called through the MCP transport (the agent's "
        "native tool-call path), not from the shell. Call the tool directly "
        "by name; manus-mcp-cli exists only as the allowlisted documentation "
        "entry point.",
    )


# ── 14/15. manus-touchpoint / -fuse ─────────────────────────────────────────
def touchpoint(argv: list) -> int:
    tool = "manus-touchpoint"
    return emit_err(
        tool, "CAPABILITY_UNAVAILABLE",
        "live browser takeover (VNC touchpoint) is disabled in this "
        "deployment; browser_* tools operate the sandbox Chrome directly "
        "via CDP",
    )


def touchpoint_fuse(argv: list) -> int:
    return emit_err(
        "manus-touchpoint-fuse", "CAPABILITY_UNAVAILABLE",
        "VNC touchpoint fuse is disabled in this deployment",
    )


# ── 16. manus-tools (meta: self-test / list / validate-argv) ────────────────
def manus_tools(argv: list) -> int:
    tool = "manus-tools"
    action = argv[0] if argv else "list"
    if action == "list":
        bins = sorted(p.name for p in Path(__file__).parent.glob("manus-*")
                      if p.is_file() and os.access(p, os.X_OK))
        return emit_ok(tool, {"binaries": bins, "count": len(bins)})
    if action == "self-test":
        expected = [
            "manus-analyze-pptx", "manus-analyze-video", "manus-channel",
            "manus-config", "manus-export-slides", "manus-heartbeat",
            "manus-mcp-cli", "manus-md-to-pdf", "manus-render-diagram",
            "manus-speech-to-text", "manus-token-local-proxy", "manus-tools",
            "manus-touchpoint", "manus-touchpoint-fuse", "manus-upload-file",
            "manus-webdev-logs",
        ]
        parent = Path(__file__).parent
        results = {name: (parent / name).exists()
                   and os.access(parent / name, os.X_OK)
                   for name in expected}
        ok = all(results.values())
        return emit_ok(tool, {"self_test": "pass" if ok else "fail",
                              "binaries": results})
    if action == "validate-argv":
        return emit_ok(tool, {"argv": argv[1:], "count": max(0, len(argv) - 1)})
    return emit_err(tool, "VALIDATION_ERROR", f"unknown action '{action}'")
