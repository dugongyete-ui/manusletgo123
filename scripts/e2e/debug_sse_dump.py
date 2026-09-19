#!/usr/bin/env python3
"""Debug: dump raw SSE events dari 1 turn chat (maks 25 event pertama)."""
from __future__ import annotations
import json, uuid, requests

BASE = "http://localhost:8000"
API = f"{BASE}/api/v1"
tag = uuid.uuid4().hex[:8]
email = f"smokedbg_{tag}@dzeck-test.local"
password = "SmokeTest#2026x"
s = requests.Session()
s.headers["Content-Type"] = "application/json"
s.post(f"{API}/auth/register", json={"email": email, "password": password, "fullname": f"Dbg {tag}"}, timeout=20)
r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
r.raise_for_status()
s.headers["Authorization"] = f"Bearer {r.json()['data']['access_token']}"
r = s.put(f"{API}/sessions", json={"title": f"dbg-{tag}"}, timeout=20)
r.raise_for_status()
sid = r.json()["data"]["session_id"]
print("sid:", sid)

n = 0
with s.post(f"{API}/sessions/{sid}/chat", json={"message": "Jawab satu kalimat: 2+2 berapa?", "stream": True}, timeout=120, stream=True) as resp:
    print("HTTP", resp.status_code, resp.headers.get("content-type"))
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        print("RAW:", raw[:220])
        n += 1
        if n > 25:
            break
s.delete(f"{API}/sessions/{sid}", timeout=15)
print("cleaned")
