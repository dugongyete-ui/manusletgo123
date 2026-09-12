"""Share API states (P0) — live-server tests.

The share page must NEVER show a blank screen; the API contract behind it:
- valid share id            → 200 with events (auth-free)
- invalid / unshared id     → clean 404 JSON (not 500, not HTML)
- shared files for bad id   → clean 404 (regression: used to raise
                              RuntimeError → 500 "Internal server error")
- valid session, no events  → 200 with an empty event list (the frontend
                              renders the empty state from this)

Run against a live backend:
  TEST_API_BASE_URL=http://localhost:3000/api/v1 pytest tests/test_share_api_states.py
"""

import uuid

import pytest
import requests
from conftest import BASE_URL


def _share_url(base, session_id):
    return f"{base}/sessions/shared/{session_id}"


def test_shared_session_roundtrip(authenticated_headers):
    """Share a session → public GET works WITHOUT any auth header."""
    base = BASE_URL
    s = requests.put(f"{base}/sessions", headers=authenticated_headers)
    assert s.status_code == 200, s.text
    session_id = s.json()["data"]["session_id"]

    # Before sharing: publicly invisible (this is the "share ID valid but not
    # shared" branch → 404).
    r = requests.get(_share_url(base, session_id))
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == 404
    assert body["data"] is None

    # Share it.
    sh = requests.post(f"{base}/sessions/{session_id}/share",
                       headers=authenticated_headers)
    assert sh.status_code == 200, sh.text
    assert sh.json()["data"]["is_shared"] is True

    # Public GET (no auth): 200 with a parseable event list.
    r = requests.get(_share_url(base, session_id))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["session_id"] == session_id
    assert isinstance(data["events"], list)
    assert data["is_shared"] is True


def test_invalid_share_id_returns_clean_404():
    """Garbage share id → friendly 404 JSON, never 500/blank."""
    base = BASE_URL
    r = requests.get(_share_url(base, f"bogus-{uuid.uuid4().hex}"))
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == 404
    assert isinstance(body["msg"], str) and body["msg"]
    assert body["data"] is None


def test_unshare_hides_public_access(authenticated_headers):
    base = BASE_URL
    s = requests.put(f"{base}/sessions", headers=authenticated_headers)
    session_id = s.json()["data"]["session_id"]
    requests.post(f"{base}/sessions/{session_id}/share",
                  headers=authenticated_headers)
    r = requests.get(_share_url(base, session_id))
    assert r.status_code == 200

    un = requests.delete(f"{base}/sessions/{session_id}/share",
                         headers=authenticated_headers)
    assert un.status_code == 200
    assert un.json()["data"]["is_shared"] is False

    r = requests.get(_share_url(base, session_id))
    assert r.status_code == 404


def test_shared_files_invalid_id_is_404_not_500():
    """Regression (fixed): get_shared_session_files raised RuntimeError → 500.
    The share-page file panel must receive a clean 404 instead."""
    base = BASE_URL
    r = requests.get(f"{base}/sessions/bogus-{uuid.uuid4().hex}/share/files")
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["code"] == 404
    assert body["data"] is None


def test_shared_session_without_events_is_200_empty_list(authenticated_headers):
    """Freshly shared session has zero events — the API must still return
    200 + empty list (frontend empty state relies on this, not on an error)."""
    base = BASE_URL
    s = requests.put(f"{base}/sessions", headers=authenticated_headers)
    session_id = s.json()["data"]["session_id"]
    requests.post(f"{base}/sessions/{session_id}/share",
                  headers=authenticated_headers)
    r = requests.get(_share_url(base, session_id))
    assert r.status_code == 200
    assert r.json()["data"]["events"] == []
