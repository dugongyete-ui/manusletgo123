#!/usr/bin/env python3
"""
CDP Host-header proxy for E2B sandboxes.

Listens on :9222, forwards to Chrome on 127.0.0.1:8222.

Problems solved:
  1. Chrome rejects CDP HTTP requests whose Host header is not localhost/IP
     (DNS-rebinding protection added in Chrome 94+).  We rewrite the Host
     header to localhost:8222 before forwarding so Chrome accepts the request.

  2. Chrome embeds localhost:8222 in the webSocketDebuggerUrl JSON field.
     browser_use's BrowserSession reads this URL and tries to connect via
     WebSocket to ws://localhost:8222/... which is not reachable from outside
     the sandbox.  We rewrite those ws:// URLs to wss://EXTERNAL_HOST/ in
     the HTTP response bodies, and also update the Content-Length header to
     match the new (longer) body.

  3. WebSocket connections (the actual CDP communication after the initial
     HTTP handshake) are proxied transparently as a bidirectional byte stream.

External hostname discovery:
  - Pass it as argv[1]: python3 cdp_proxy.py 9222-<sandbox_id>.e2b.app
  - Or omit: the proxy learns it from the first incoming request's Host header.
"""
import asyncio
import re
import sys

CHROME_HOST = "127.0.0.1"
CHROME_PORT = 8222
PROXY_PORT  = 9222

# External hostname used for URL rewriting.  Set from argv[1] if provided;
# otherwise discovered dynamically from the first incoming Host header.
EXTERNAL_HOST: str = sys.argv[1] if len(sys.argv) > 1 else ""


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy bytes from reader to writer until EOF."""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def _rewrite_body(body: bytes, external: str) -> bytes:
    """Replace Chrome-internal ws:// URLs with the externally-reachable wss:// URL."""
    if not external:
        return body
    ext = external.encode()
    # ws://localhost:8222/... -> wss://EXTERNAL/...
    body = body.replace(b"ws://localhost:8222", b"wss://" + ext)
    # ws://localhost/... (Chrome omits port when using default HTTP port)
    body = body.replace(b"ws://localhost/", b"wss://" + ext + b"/")
    return body


def _fix_content_length(resp: bytes, new_body: bytes, old_body: bytes) -> bytes:
    """Update the Content-Length response header when body length changed."""
    if len(new_body) == len(old_body):
        return resp
    sep = resp.find(b"\r\n\r\n")
    if sep < 0:
        return resp
    headers = resp[:sep]
    headers = re.sub(
        rb"(?i)content-length:\s*\d+",
        b"Content-Length: " + str(len(new_body)).encode(),
        headers,
    )
    return headers + b"\r\n\r\n" + new_body


async def _handle(client_reader: asyncio.StreamReader,
                  client_writer: asyncio.StreamWriter) -> None:
    global EXTERNAL_HOST
    try:
        # ── Read full HTTP request headers ────────────────────────────
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = await asyncio.wait_for(client_reader.read(4096), timeout=30)
            if not chunk:
                return
            buf += chunk

        sep = buf.index(b"\r\n\r\n")
        raw_headers = buf[:sep]
        body_tail   = buf[sep + 4:]

        # ── Inspect / rewrite request headers ─────────────────────────
        is_ws = False
        new_lines: list[bytes] = []
        for line in raw_headers.split(b"\r\n"):
            if line.lower().startswith(b"host:"):
                original_host = line[5:].strip().decode(errors="replace")
                # Learn external hostname from first request if not yet known
                if not EXTERNAL_HOST and original_host and "localhost" not in original_host:
                    EXTERNAL_HOST = original_host
                    print(f"CDPproxy: learned external host={EXTERNAL_HOST}", flush=True)
                # Rewrite Host header so Chrome accepts the request
                new_lines.append(b"Host: localhost:8222")
            else:
                if b"websocket" in line.lower():
                    is_ws = True
                new_lines.append(line)

        modified_request = b"\r\n".join(new_lines) + b"\r\n\r\n"

        # ── Forward to Chrome ─────────────────────────────────────────
        chrome_reader, chrome_writer = await asyncio.wait_for(
            asyncio.open_connection(CHROME_HOST, CHROME_PORT), timeout=10
        )
        chrome_writer.write(modified_request + body_tail)
        await chrome_writer.drain()

        if is_ws:
            # Transparent bidirectional WebSocket pipe
            await asyncio.gather(
                _pipe(client_reader, chrome_writer),
                _pipe(chrome_reader, client_writer),
                return_exceptions=True,
            )
            return

        # ── HTTP response: read until Content-Length satisfied ────────
        resp = b""
        try:
            while True:
                chunk = await asyncio.wait_for(chrome_reader.read(65536), timeout=20)
                if not chunk:
                    break
                resp += chunk
                if b"\r\n\r\n" not in resp:
                    continue
                h_end = resp.index(b"\r\n\r\n")
                h_lower = resp[:h_end].lower()
                cl_idx = h_lower.find(b"content-length:")
                if cl_idx >= 0:
                    cl = int(
                        h_lower[cl_idx:].split(b"\r\n")[0]
                        .split(b":")[1]
                        .strip()
                    )
                    if len(resp) >= h_end + 4 + cl:
                        break
        except asyncio.TimeoutError:
            pass

        # ── Rewrite ws:// URLs and fix Content-Length ─────────────────
        if b"\r\n\r\n" in resp:
            h_end = resp.index(b"\r\n\r\n")
            old_body = resp[h_end + 4:]
            new_body = _rewrite_body(old_body, EXTERNAL_HOST)
            resp = _fix_content_length(resp, new_body, old_body)

        client_writer.write(resp)
        await client_writer.drain()
        try:
            chrome_writer.close()
        except Exception:
            pass

    except Exception:
        pass
    finally:
        try:
            client_writer.close()
        except Exception:
            pass


async def main() -> None:
    server = await asyncio.start_server(_handle, "0.0.0.0", PROXY_PORT)
    ext_info = EXTERNAL_HOST or "(will auto-discover from first request)"
    print(
        f"CDPproxy :9222 -> 127.0.0.1:8222  external={ext_info}",
        flush=True,
    )
    async with server:
        await server.serve_forever()


asyncio.run(main())
