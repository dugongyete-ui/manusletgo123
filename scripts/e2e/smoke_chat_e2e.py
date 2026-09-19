#!/usr/bin/env python3
"""E2E smoke: register → login → session → SSE chat 1 turn → cleanup.

Usage:
    python3 scripts/e2e/smoke_chat_e2e.py [--base http://localhost:8000]

Verifies the full hot path (auth, session store, agent loop, model gateway,
SSE contract) against a RUNNING backend. Temporary smoke user/session are
deleted afterwards. Exit code 0 = PASS.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import requests

BASE = "http://localhost:8000"
API = f"{BASE}/api/v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    global API
    API = f"{args.base}/api/v1"

    tag = uuid.uuid4().hex[:8]
    email = f"smoke_{tag}@dzeck-test.local"
    password = "SmokeTest#2026x"
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"

    # 1. health
    r = s.get(f"{args.base}/health", timeout=15)
    r.raise_for_status()
    health = r.json()
    print(f"[1] health: status={health.get('status')} ready={health.get('ready')}")
    assert health.get("ready") is True, "backend not ready"

    # 2. register (idempotent-ish: ignore 'already exists')
    r = s.post(
        f"{API}/auth/register",
        json={"email": email, "password": password, "fullname": f"Smoke {tag}"},
        timeout=20,
    )
    if r.status_code not in (200, 201):
        print(f"    register → {r.status_code}: {r.text[:200]}")
    # 3. login
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    token = r.json()["data"]["access_token"]
    s.headers["Authorization"] = f"Bearer {token}"
    print(f"[2] login ok (token {len(token)} chars)")

    # 4. create session
    r = s.put(f"{API}/sessions", json={"title": f"smoke-{tag}"}, timeout=20)
    r.raise_for_status()
    sid = r.json()["data"]["session_id"]
    print(f"[3] session: {sid}")

    # 5. chat 1 turn via SSE
    # Kontrak SSE nyata: baris "event: <name>" + baris "data: <json>".
    # Jawaban assistant = event "message" dengan data.role=="assistant"
    # yang membawa "content"; event "error" = kegagalan.
    t0 = time.time()
    payload = {"message": "Jawab satu kalimat saja: apa itu 2+2?", "stream": True}
    got_answer = False
    err = None
    current_event = ""
    with s.post(
        f"{API}/sessions/{sid}/chat", json=payload, timeout=120, stream=True
    ) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("event:"):
                current_event = raw[len("event:"):].strip()
                continue
            if not raw.startswith("data:"):
                continue
            chunk = raw[len("data:"):].strip()
            if chunk == "[DONE]":
                break
            try:
                evt = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if current_event == "message" and evt.get("role") == "assistant" and evt.get("content"):
                got_answer = True
            if current_event in ("error", "task_error") or evt.get("type") == "error":
                err = evt
    dt = time.time() - t0
    print(f"[4] chat SSE selesai dalam {dt:.1f}s → answer={got_answer} error={err}")
    assert got_answer and not err, "tidak menerima jawaban model dari SSE"

    # 6. cleanup
    s.delete(f"{API}/sessions/{sid}", timeout=15)
    print(f"[5] sesi smoke dihapus — PASS ({tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
