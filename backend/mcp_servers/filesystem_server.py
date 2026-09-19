#!/usr/bin/env python3
"""Bundled Dzeck MCP filesystem server (stdio transport).

A self-contained MCP server that guarantees MCP is ACTIVE in every
deployment environment (Replit / E2B runtime / z.ai container) without any
npm download or external service. Launched by the backend's MCP bootstrap
(``app/domain/services/mcp/environment.py``) through the user's mcp.json.

Security model (mirrors the sandbox isolation guarantees):
- Every path operation is confined to ``DZECK_MCP_USER_ROOT`` (the per-user
  home root the sandbox uses). Anything outside is refused.
- Paths listed in ``DZECK_MCP_PROTECTED`` (comma-separated) are refused —
  the host project source is never reachable through MCP.
- Symlinks are resolved before the boundary check, so escaping via a link
  is not possible.
- ``http_get`` is text-only, size-capped, and refuses private/loopback
  addresses to prevent SSRF into the host network.

Tools exposed (MCP namespaced by the client as ``mcp_dzeck-fs_*``):
- list_dir / read_text_file / write_text_file / create_directory
- search_files / get_system_info / http_get
"""

from __future__ import annotations

import os
import platform
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

USER_ROOT = Path(os.environ.get("DZECK_MCP_USER_ROOT", "/tmp/dzeck-mcp-home")).resolve()
PROTECTED = [
    Path(p).resolve()
    for p in os.environ.get("DZECK_MCP_PROTECTED", "").split(",")
    if p.strip()
]
MAX_BYTES = int(os.environ.get("DZECK_MCP_MAX_BYTES", "2000000") or "2000000")

mcp = FastMCP("dzeck-fs")


class PathDenied(Exception):
    """Raised when a path escapes the user root or hits a protected path."""


def _check(path: Path) -> Path:
    """Resolve ``path`` and enforce the user-root / protected-path boundary."""
    resolved = (USER_ROOT / path if not path.is_absolute() else path).resolve()
    if resolved == USER_ROOT or resolved.is_relative_to(USER_ROOT):
        for protected in PROTECTED:
            if resolved == protected or resolved.is_relative_to(protected):
                raise PathDenied(f"Protected path: {resolved}")
        return resolved
    raise PathDenied(f"Outside the allowed user root: {resolved}")


@mcp.tool()
def list_dir(path: str = ".") -> str:
    """List a directory inside the user home root.

    Returns one entry per line as ``<type> <size> <name>`` (type: dir|file).
    """
    target = _check(Path(path))
    if not target.exists():
        return f"NOT FOUND: {path}"
    if not target.is_dir():
        return f"NOT A DIRECTORY: {path}"
    lines: List[str] = []
    for entry in sorted(target.iterdir(), key=lambda p: p.name)[:500]:
        kind = "dir" if entry.is_dir() else "file"
        try:
            size = entry.stat().st_size if kind == "file" else ""
        except OSError:
            size = "?"
        lines.append(f"{kind}\t{size}\t{entry.name}")
    return "\n".join(lines) or "(empty directory)"


@mcp.tool()
def read_text_file(path: str, max_bytes: int = 200000) -> str:
    """Read a UTF-8 text file (head-capped at ``max_bytes``)."""
    target = _check(Path(path))
    if not target.is_file():
        return f"NOT FOUND: {path}"
    size = target.stat().st_size
    with open(target, "r", encoding="utf-8", errors="replace") as fh:
        data = fh.read(min(max_bytes, MAX_BYTES))
    if size > min(max_bytes, MAX_BYTES):
        data += f"\n... [truncated {size - min(max_bytes, MAX_BYTES)} of {size} bytes]"
    return data


@mcp.tool()
def write_text_file(path: str, content: str) -> str:
    """Write (or overwrite) a UTF-8 text file inside the user home root.

    Parent directories are created automatically. Hard-capped at
    ``DZECK_MCP_MAX_BYTES``.
    """
    payload = content.encode("utf-8")
    if len(payload) > MAX_BYTES:
        return f"ERROR: content too large ({len(payload)} > {MAX_BYTES} bytes)"
    target = _check(Path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return f"WROTE {len(payload)} bytes to {target}"


@mcp.tool()
def create_directory(path: str) -> str:
    """Create a directory (including parents) inside the user home root."""
    target = _check(Path(path))
    target.mkdir(parents=True, exist_ok=True)
    return f"CREATED {target}"


@mcp.tool()
def search_files(root: str, pattern: str, max_results: int = 50) -> str:
    """Recursively search file NAMES containing ``pattern`` (case-insensitive)."""
    base = _check(Path(root if root else "."))
    if not base.is_dir():
        return f"NOT A DIRECTORY: {root}"
    needle = pattern.lower()
    hits: List[str] = []
    for current, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if needle in name.lower():
                hits.append(str(Path(current) / name))
                if len(hits) >= max(1, min(max_results, 200)):
                    return "\n".join(hits)
    return "\n".join(hits) or "(no matches)"


@mcp.tool()
def get_system_info() -> str:
    """Return basic host information for the MCP server environment."""
    return (
        f"environment={os.environ.get('DZECK_MCP_ENV', 'unknown')}\n"
        f"platform={platform.system()} {platform.release()}\n"
        f"python={sys.version.split()[0]}\n"
        f"user_root={USER_ROOT}\n"
        f"protected_paths={len(PROTECTED)} configured\n"
        f"hostname={socket.gethostname()}\n"
        f"time={datetime.now().isoformat(timespec='seconds')}"
    )


@mcp.tool()
def http_get(url: str, max_bytes: int = 100000) -> str:
    """Fetch a public URL as text (SSRF-guarded, size-capped).

    Refuses loopback/private/link-local hosts. Returns the first
    ``max_bytes`` of the body with a status header line.
    """
    from urllib.parse import urlparse
    import httpx

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "ERROR: only http/https URLs are allowed"
    host = parsed.hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        return f"ERROR: DNS resolution failed for {host}: {exc}"
    for info in infos:
        ip = info[4][0]
        if ip == "::1" or ip.startswith(("127.", "10.", "192.168.", "169.254.", "fc", "fd")):
            return f"ERROR: private/loopback address refused: {ip}"
        if ip.startswith("172."):
            second = int(ip.split(".")[1])
            if 16 <= second <= 31:
                return f"ERROR: private address refused: {ip}"
    cap = max(1000, min(max_bytes, MAX_BYTES))
    try:
        resp = httpx.get(url, timeout=15.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        return f"ERROR: request failed: {exc}"
    body = resp.text[:cap]
    header = f"status={resp.status_code} content_type={resp.headers.get('content-type','')} url={resp.url}"
    if len(resp.text) > cap:
        body += f"\n... [truncated, full length {len(resp.text)} chars]"
    return header + "\n\n" + body


if __name__ == "__main__":
    mcp.run()
