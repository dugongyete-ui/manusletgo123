#!/usr/bin/env python3
"""E2E driver: register/login user, create session, send chat message to the AI
agent via the backend SSE endpoint, and record every event to a JSONL file.

Mirrors what the Vue frontend does (fetchEventSource POST + SSE consumption).
State (email/password/session_id) is persisted so a later run can continue the
same conversation after a backend restart (agent history lives in MongoDB).

Usage:
    python3 e2e_driver.py [--message "text"] [--timeout 480]
                          [--new-session] [--no-send]
                          [--login EMAIL:PASSWORD]
                          [--upload PATH]...       # attach file(s) to the message

Output artifacts (JSONL event log, summary, session snapshot) are written to
E2E_OUT_DIR (default: ./out next to this script).
"""
import argparse
import json
import mimetypes
import os
import sys
import time
import uuid

import httpx

BACKEND = os.environ.get("E2E_BACKEND", "http://localhost:8000/api/v1")
OUT_DIR = os.environ.get(
    "E2E_OUT_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"),
)
STATE_FILE = os.path.join(OUT_DIR, "e2e_state.json")
EVENTS_FILE = os.path.join(OUT_DIR, "e2e_events.jsonl")
SUMMARY_FILE = os.path.join(OUT_DIR, "e2e_summary.json")
SNAPSHOT_FILE = os.path.join(OUT_DIR, "e2e_session_snapshot.json")

DEFAULT_MESSAGE = (
    "Uji semua kemampuan anda tools yang tersedia, kecuali abaikan generate image, "
    "karena belum support apikey nya, nah anda semua test kemampuan anda eksekusi "
    "secara nyata, lalu ringkas yang bermasalah, saya developer nanti saya akan fix "
    "setelah anda menguji tools kemampuan anda"
)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_token(state, login_creds=None):
    """Authenticate. With --login EMAIL:PASSWORD try that account first.

    Order: explicit --login → saved state → register a fresh user.
    Returns (access_token, email).
    """
    client = httpx.Client(timeout=30)
    if login_creds:
        email, _, password = login_creds.partition(":")
        r = client.post(
            f"{BACKEND}/auth/login",
            json={"email": email, "password": password},
        )
        if r.status_code == 200:
            data = r.json()["data"]
            state["email"], state["password"] = email, password
            save_state(state)
            return data["access_token"], email
        print(f"[driver] --login failed ({r.status_code}), falling back: {r.text[:200]}", flush=True)
    if "email" in state:
        r = client.post(
            f"{BACKEND}/auth/login",
            json={"email": state["email"], "password": state["password"]},
        )
        if r.status_code == 200:
            data = r.json()["data"]
            return data["access_token"], state["email"]
        print(f"[driver] login failed: {r.status_code} {r.text[:200]}", flush=True)
    email = f"e2e_{int(time.time())}_{uuid.uuid4().hex[:6]}@test.local"
    password = "E2eTest#2026"
    r = client.post(
        f"{BACKEND}/auth/register",
        json={"fullname": "E2E Tester", "email": email, "password": password},
    )
    r.raise_for_status()
    data = r.json()["data"]
    state["email"] = email
    state["password"] = password
    save_state(state)
    return data["access_token"], email


def upload_file(client, token, path):
    """Upload one file via POST /files (multipart) and return the attachment dict
    the chat endpoint expects ({file_id, filename, content_type, size})."""
    filename = os.path.basename(path)
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        r = client.post(
            f"{BACKEND}/files",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (filename, fh, ctype)},
        )
    r.raise_for_status()
    info = r.json()["data"]
    print(f"[driver] uploaded {filename} -> file_id={info.get('file_id')} ({info.get('size')} B, {info.get('content_type')})", flush=True)
    return {
        "file_id": info.get("file_id"),
        "filename": info.get("filename") or filename,
        "content_type": info.get("content_type") or ctype,
        "size": info.get("size"),
    }


def create_session(client, token):
    r = client.put(
        f"{BACKEND}/sessions", headers={"Authorization": f"Bearer {token}"}
    )
    r.raise_for_status()
    return r.json()["data"]["session_id"]


def stream_chat(token, session_id, message, timeout_s, events_out, attachments=None):
    """POST chat and consume the SSE stream. Returns summary info."""
    deadline = time.time() + timeout_s
    counts = {}
    tool_calls = []       # (tool_name, function_name, status)
    messages = []         # assistant/user message events (with attachments info)
    attachments_seen = [] # (message_index, [filenames]) — double-send detection
    ended_with = None
    seq = 0

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    payload = {"message": message, "timestamp": int(time.time() * 1000)}
    if attachments:
        payload["attachments"] = attachments

    with httpx.Client(timeout=httpx.Timeout(connect=15, read=timeout_s, write=30, pool=15)) as client:
        with client.stream(
            "POST",
            f"{BACKEND}/sessions/{session_id}/chat",
            headers=headers,
            json=payload,
        ) as resp:
            print(f"[driver] chat POST -> HTTP {resp.status_code}", flush=True)
            if resp.status_code != 200:
                body = resp.read()
                print(f"[driver] ERROR body: {body[:500]}", flush=True)
                return {"ended_with": "http_error", "status_code": resp.status_code}

            event_name = None
            data_lines = []
            with open(events_out, "a", encoding="utf-8") as fout:
                try:
                    for line in resp.iter_lines():
                        if time.time() > deadline:
                            ended_with = "timeout"
                            break
                        if line is None:
                            continue
                        if line.startswith(":"):        # sse ping / comment
                            continue
                        if line.startswith("event:"):
                            event_name = line[len("event:"):].strip()
                            continue
                        if line.startswith("data:"):
                            data_lines.append(line[len("data:"):].strip())
                            continue
                        if line == "":                    # end of event block
                            if event_name is None and not data_lines:
                                continue
                            raw = "\n".join(data_lines)
                            seq += 1
                            rec = {
                                "seq": seq,
                                "wall": time.time(),
                                "event": event_name,
                                "data": raw,
                            }
                            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            fout.flush()
                            counts[event_name] = counts.get(event_name, 0) + 1
                            try:
                                data = json.loads(raw) if raw else {}
                            except json.JSONDecodeError:
                                data = {"_raw": raw}

                            if event_name == "tool":
                                tool_calls.append({
                                    "tool": data.get("name"),
                                    "fn": data.get("function"),
                                    "status": data.get("status"),
                                })
                            elif event_name == "message":
                                msgs = data.get("content", "")
                                atts = data.get("attachments")
                                messages.append({
                                    "role": data.get("role"),
                                    "preview": (msgs or "")[:120],
                                    "attachments": [
                                        a.get("filename") for a in atts
                                    ] if atts else None,
                                })
                                if atts:
                                    attachments_seen.append({
                                        "seq": seq,
                                        "role": data.get("role"),
                                        "files": [a.get("filename") for a in atts],
                                    })
                            elif event_name in ("done", "error", "wait"):
                                ended_with = event_name
                                if event_name == "error":
                                    print(f"[driver] ERROR event: {data}", flush=True)
                                break
                            event_name = None
                            data_lines = []
                except httpx.ReadTimeout:
                    ended_with = "timeout"
                except Exception as exc:
                    print(f"[driver] stream exception: {exc!r}", flush=True)
                    ended_with = ended_with or "exception"

    if ended_with is None:
        ended_with = "stream_closed"
    return {
        "ended_with": ended_with,
        "event_counts": counts,
        "tool_calls": tool_calls,
        "messages": messages,
        "attachment_messages": attachments_seen,
        "total_events": seq,
    }


def fetch_session_events(token, session_id):
    """Fetch the authoritative event list persisted in MongoDB."""
    try:
        with httpx.Client(timeout=30) as client:
            r = client.get(
                f"{BACKEND}/sessions/{session_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code == 200:
                return r.json()["data"]
    except Exception as exc:
        print(f"[driver] fetch session failed: {exc!r}", flush=True)
    return None


def poll_session(token, session_id, poll_seconds, interval=10):
    """Poll GET /sessions/{id} until the task reaches a terminal status.

    Used after the SSE stream times out but the agent task keeps running
    server-side. Re-POSTing the message would re-queue it (double execution),
    so we poll the authoritative session state instead.
    Returns final session status string, or None if still running at deadline.
    """
    deadline = time.time() + poll_seconds
    last_status = None
    n_events = 0
    while time.time() < deadline:
        data = fetch_session_events(token, session_id)
        if data:
            last_status = data.get("status")
            n_events = len(data.get("events") or [])
            print(f"[driver] poll: status={last_status} events={n_events}", flush=True)
            if last_status != "running" and last_status != "pending":
                return last_status
        time.sleep(interval)
    print(f"[driver] poll deadline reached (status={last_status})", flush=True)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message", default=os.environ.get("E2E_MESSAGE", DEFAULT_MESSAGE))
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("E2E_TIMEOUT", "480")))
    ap.add_argument("--new-session", action="store_true")
    ap.add_argument("--no-send", action="store_true", help="only fetch existing session state")
    ap.add_argument("--login", default=os.environ.get("E2E_LOGIN", ""), help="EMAIL:PASSWORD — try this account first")
    ap.add_argument("--upload", action="append", default=[], help="file path to attach (repeatable)")
    ap.add_argument("--poll-after", type=float, default=float(os.environ.get("E2E_POLL_AFTER", "0")), help="after stream timeout, poll session status this many seconds (task keeps running server-side)")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    state = load_state()
    token, email = get_token(state, args.login or None)
    state["token"] = token
    print(f"[driver] authenticated as {email}", flush=True)

    # Upload attachments (if any) BEFORE creating/sending the chat message.
    chat_attachments = []
    if args.upload and not args.no_send:
        with httpx.Client(timeout=120) as client:
            for path in args.upload:
                chat_attachments.append(upload_file(client, token, path))

    if args.new_session or "session_id" not in state:
        session_id = create_session(httpx.Client(timeout=30), token)
        state["session_id"] = session_id
        save_state(state)
        print(f"[driver] created session {session_id}", flush=True)
    else:
        session_id = state["session_id"]
        print(f"[driver] reusing session {session_id}", flush=True)

    if args.no_send:
        if args.poll_after > 0:
            final = poll_session(token, session_id, args.poll_after)
            if final is None:
                sys.exit(4)  # still running
        data = fetch_session_events(token, session_id)
        if data:
            print(json.dumps({
                "session_id": session_id,
                "status": data.get("status"),
                "n_events": len(data.get("events") or []),
            }, indent=2))
        return

    t0 = time.time()
    result = stream_chat(token, session_id, args.message, args.timeout, EVENTS_FILE, chat_attachments or None)
    elapsed = time.time() - t0

    # Task still running server-side? Poll the session until it finishes
    # instead of re-POSTing (re-POST would re-queue the message).
    if result["ended_with"] == "timeout" and args.poll_after > 0:
        final = poll_session(token, session_id, args.poll_after)
        if final == "completed":
            result = dict(result, ended_with="done_after_poll")
        elif final == "waiting":
            result = dict(result, ended_with="wait_after_poll")
        # final None -> still running; keep ended_with=timeout (exit 4 below)

    # Snapshot persisted session state (status + events) for offline analysis.
    session_data = fetch_session_events(token, session_id)
    summary = {
        "session_id": session_id,
        "email": email,
        "elapsed_s": round(elapsed, 1),
        "result": result,
        "session_status": (session_data or {}).get("status"),
        "persisted_event_count": len((session_data or {}).get("events") or []),
    }
    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    if session_data:
        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)

    print("=" * 60, flush=True)
    print(f"[driver] ended_with={result['ended_with']} elapsed={elapsed:.0f}s", flush=True)
    print(f"[driver] event counts: {result['event_counts']}", flush=True)
    print(f"[driver] session status: {summary['session_status']}, persisted events: {summary['persisted_event_count']}", flush=True)
    print(f"[driver] tools called ({len(result['tool_calls'])}):", flush=True)
    for t in result["tool_calls"]:
        print(f"    - {t['tool']}/{t['fn']} [{t['status']}]", flush=True)
    print(f"[driver] messages ({len(result['messages'])}):", flush=True)
    for m in result["messages"]:
        print(f"    - [{m['role']}] {m['preview']}" + (f" ATTACHMENTS={m['attachments']}" if m["attachments"] else ""), flush=True)
    if result["attachment_messages"]:
        print("[driver] !! MESSAGES WITH ATTACHMENTS (double-send check):", flush=True)
        for a in result["attachment_messages"]:
            print(f"    - seq={a['seq']} role={a['role']} files={a['files']}", flush=True)
    print("=" * 60, flush=True)

    if result["ended_with"] == "timeout":
        # Stream timed out AND polling never saw a terminal status:
        # the task is still running server-side (exit 4 = continue later
        # with --no-send --poll-after). Without polling it's a plain timeout (2).
        sys.exit(4 if args.poll_after > 0 else 2)
    if result["ended_with"] == "error":
        sys.exit(3)


if __name__ == "__main__":
    main()
