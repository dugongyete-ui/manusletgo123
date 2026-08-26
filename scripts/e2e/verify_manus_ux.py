"""Focused live verification of the 4 user-reported UX regressions:

1. SILENT CHAT  -> deterministic tool-progress narrations must appear
                   (MessageEvent with is_progress=true) between/inside steps.
2. SUMMARY REPEATS ON REFRESH
                 -> NO message_chunk events may be emitted anymore (fake
                    streaming removed); a refresh (GET /sessions) must show
                    the summary exactly ONCE; a reconnect replay
                    (POST /chat with event_id just before the summary) must
                    deliver the summary once with ZERO chunk events.
3. STEP TIMELINE CUT INTO PIECES
                 -> steps + narrations must be recognisable as one timeline
                    (narrations carry is_progress=true so the frontend groups
                    them into the unified StepTimeline rail).
4. EMOJIS       -> no checkmark/warning emoji in any user-facing message.

Run while the E2E stack is up (bash scripts/e2e/run_e2e.sh E2E_KEEP_ALIVE=1).
"""

import json
import os
import sys
import time
import uuid

import httpx

BACKEND = os.environ.get("E2E_BACKEND", "http://localhost:8000/api/v1")
OUT_DIR = os.environ.get(
    "E2E_OUT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
)
EMAIL = os.environ.get("E2E_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin123")

# Multi-step task (2+ steps, file writes -> narrations + timeline + summary)
MESSAGE = (
    "Buat dua file untuk saya dan WAJIB gunakan tools yang tersedia "
    "(shell untuk cek tanggal hari ini, lalu file write): "
    "(1) notulen_rapat.md berisi notulen rapat tim produk fiktif tanggal hari ini "
    "dengan 5 poin keputusan, lalu (2) tugas_tim.csv berisi 5 baris tugas dari "
    "rapat itu dengan kolom id,judul,pic,status. "
    "Jangan tanya apa pun, jangan menulis isi file sebagai teks chat — "
    "tulis lewat tool file langsung sampai selesai."
)

EMOJI_CODEPOINTS = set(
    chr(c) for c in (
        list(range(0x2705, 0x2706)) +      # check mark button
        list(range(0x26A0, 0x26A1)) +      # warning sign
        list(range(0x274C, 0x274D)) +      # cross mark
        list(range(0x1F300, 0x1FAFF + 1))  # emoji blocks
    )
)

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def login():
    client = httpx.Client(timeout=30)
    r = client.post(f"{BACKEND}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code == 200:
        return client, r.json()["data"]["access_token"]
    # register + retry (first boot on a fresh DB)
    client.post(
        f"{BACKEND}/auth/register",
        json={"fullname": "Admin", "email": EMAIL, "password": PASSWORD},
    )
    r = client.post(f"{BACKEND}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return client, r.json()["data"]["access_token"]


def parse_sse_stream(resp):
    """Yield (event_name, data_dict) tuples from an SSE response."""
    event_name, data_lines = None, []
    for line in resp.iter_lines():
        if line is None:
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
            continue
        if line == "":
            if event_name and data_lines:
                try:
                    yield event_name, json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    pass
            event_name, data_lines = None, []


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    client, token = login()
    headers = {"Authorization": f"Bearer {token}"}

    r = client.put(f"{BACKEND}/sessions", headers=headers)
    r.raise_for_status()
    session_id = r.json()["data"]["session_id"]
    print(f"[verify] session {session_id}", flush=True)

    # ── 1. Live stream: send task, collect every event ──────────────────────
    live_events = []   # (event_name, data)
    deadline = time.time() + 420
    with httpx.Client(
        timeout=httpx.Timeout(connect=15, read=420, write=30, pool=15)
    ) as sse:
        with sse.stream(
            "POST",
            f"{BACKEND}/sessions/{session_id}/chat",
            headers={**headers, "Accept": "text/event-stream"},
            json={"message": MESSAGE, "timestamp": int(time.time() * 1000)},
        ) as resp:
            print(f"[verify] chat POST -> HTTP {resp.status_code}", flush=True)
            if resp.status_code != 200:
                print(resp.read()[:500])
                sys.exit(2)
            for ev_name, data in parse_sse_stream(resp):
                live_events.append((ev_name, data))
                if ev_name in ("done", "error"):
                    break
                if time.time() > deadline:
                    break

    with open(os.path.join(OUT_DIR, "verify_live_events.json"), "w") as f:
        json.dump([{"event": n, "data": d} for n, d in live_events], f, indent=2, default=str)

    kinds = {}
    for name, _ in live_events:
        kinds[name] = kinds.get(name, 0) + 1
    print(f"[verify] event counts: {kinds}", flush=True)

    messages = [d for n, d in live_events if n == "message"]
    progress_msgs = [m for m in messages if m.get("is_progress")]
    final_msgs = [m for m in messages if m.get("is_final")]
    steps_started = [d for n, d in live_events if n == "step" and d.get("status") == "running"]

    # Check 1: chat not silent — narrations present
    check(
        "tool-progress narrations emitted (chat not silent)",
        len(progress_msgs) >= 2,
        f"{len(progress_msgs)} progress line(s): "
        + " | ".join(m.get("content", "")[:50] for m in progress_msgs[:4]),
    )
    check(
        "multi-step plan executed",
        len(steps_started) >= 2,
        f"{len(steps_started)} step(s) started",
    )

    # Check 2a: no fake streaming chunks
    check(
        "no message_chunk events (fake streaming removed)",
        kinds.get("message_chunk", 0) == 0,
        f"{kinds.get('message_chunk', 0)} chunk event(s)",
    )

    # Check 2b: summary exactly once in the live stream
    check(
        "final summary delivered exactly once",
        len(final_msgs) == 1,
        f"{len(final_msgs)} summary-size message(s)",
    )

    # Check 4: no emojis in any user-facing message
    all_texts = [m.get("content", "") for m in messages if m.get("role") == "assistant"]
    emoji_hits = [
        (t[:40], hex(ord(c))) for t in all_texts for c in t if c in EMOJI_CODEPOINTS
    ]
    check("no emoji in assistant messages", not emoji_hits, str(emoji_hits[:3]))

    # Check: acknowledgement must be clean prose (no leaked tool-call JSON)
    ack_msgs = [
        m for m in messages
        if m.get("role") == "assistant" and not m.get("is_progress")
        and not m.get("is_final")
    ]
    json_leaks = [
        m.get("content", "")[:60] for m in ack_msgs
        if '"name"' in m.get("content", "") or '"arguments"' in m.get("content", "")
        or m.get("content", "").strip().startswith("{")
    ]
    check(
        "acknowledgement is clean prose (no raw JSON tool call)",
        not json_leaks,
        f"{len(ack_msgs)} ack message(s), leaks: {json_leaks[:2]}",
    )

    # ── 2. Simulate PAGE REFRESH: GET /sessions/{id} replay ──────────────────
    r = client.get(f"{BACKEND}/sessions/{session_id}", headers=headers)
    r.raise_for_status()
    snap = r.json()["data"]
    hist_events = snap.get("events", [])
    hist_messages = [e.get("data", e) if isinstance(e, dict) else e for e in hist_events]
    # events may be wrapped as SSE event objects {event, data}
    hist_msgs = []
    for e in hist_events:
        if isinstance(e, dict):
            if e.get("event") == "message":
                hist_msgs.append(e.get("data") or {})
            elif "content" in e and "role" in e:
                hist_msgs.append(e)
    final_in_history = [m for m in hist_msgs if m.get("is_final")]
    check(
        "after refresh: summary appears exactly once in history",
        len(final_in_history) == 1,
        f"{len(final_in_history)} summary-size message(s) in replayed history",
    )
    hist_progress = [m for m in hist_msgs if m.get("is_progress")]
    check(
        "after refresh: progress narrations persisted for timeline",
        len(hist_progress) >= 2,
        f"{len(hist_progress)} narration(s) persisted with is_progress",
    )

    # ── 3. Simulate MID-SUMMARY REFRESH: reconnect from an earlier cursor ───
    # Find the live event just BEFORE the final summary message and reconnect
    # from there — this is exactly what a refresh mid-summary does.
    final_idx = None
    for i, (n, d) in enumerate(live_events):
        if n == "message" and d.get("is_final"):
            final_idx = i
            break
    if final_idx is not None and final_idx > 0:
        cursor = live_events[final_idx - 1][1].get("event_id")
        replay_events = []
        with httpx.Client(
            timeout=httpx.Timeout(connect=15, read=60, write=30, pool=15)
        ) as sse:
            with sse.stream(
                "POST",
                f"{BACKEND}/sessions/{session_id}/chat",
                headers={**headers, "Accept": "text/event-stream"},
                json={"message": "", "timestamp": int(time.time() * 1000), "event_id": cursor},
            ) as resp:
                for ev_name, data in parse_sse_stream(resp):
                    replay_events.append((ev_name, data))
                    if ev_name in ("done", "error"):
                        break
        replay_kinds = {}
        for n, _ in replay_events:
            replay_kinds[n] = replay_kinds.get(n, 0) + 1
        replay_summary = [
            d for n, d in replay_events if n == "message" and d.get("is_final")
        ]
        check(
            "mid-summary refresh reconnect: NO chunk replay",
            replay_kinds.get("message_chunk", 0) == 0,
            f"replay event kinds: {replay_kinds}",
        )
        check(
            "mid-summary refresh reconnect: summary delivered at most once",
            len(replay_summary) <= 1,
            f"{len(replay_summary)} summary message(s) in reconnect replay",
        )
    else:
        check("mid-summary refresh reconnect test ran", False, "no summary found in live stream")

    # ── Final verdict ─────────────────────────────────────────────────────────
    failed = [r for r in results if not r[1]]
    print("\n== SUMMARY ==")
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
