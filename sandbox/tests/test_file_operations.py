"""
Tests for the REAL filesystem operations added to the sandbox file API:
- /api/v1/file/list   (was always empty — Pattern C)
- /api/v1/file/copy   (was a silent stub — Pattern B)
- /api/v1/file/move   (was a silent stub — Pattern B)
- /api/v1/file/delete (was a silent stub — Pattern B)
- /api/v1/file/write  append-mode integrity (was silently truncated)
- /api/v1/file/replace on a >10KB file (was silently truncated by max_length)

These tests exercise the sandbox API over HTTP (same as test_api_file.py).
"""
import pytest
import os
import tempfile
import requests
from conftest import BASE_URL
import logging

logger = logging.getLogger(__name__)

WORK_DIR = tempfile.mkdtemp(prefix="sandbox_file_ops_test_")


def _write(path: str, content: str, append: bool = False) -> dict:
    resp = requests.post(
        f"{BASE_URL}/api/v1/file/write",
        json={"file": path, "content": content, "append": append},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _read(path: str, max_length=None) -> dict:
    # Always send the max_length key — an explicit null disables truncation,
    # while omitting the key would fall back to the server default (10000).
    payload = {"file": path, "max_length": max_length}
    resp = requests.post(f"{BASE_URL}/api/v1/file/read", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _exists_on_disk(path: str) -> bool:
    return os.path.exists(path)


@pytest.mark.file_api
def test_list_dir_returns_real_entries(client):
    """file_list_dir must return the actual directory contents (was always empty)."""
    dir_path = os.path.join(WORK_DIR, "listme")
    os.makedirs(dir_path, exist_ok=True)
    _write(os.path.join(dir_path, "a.txt"), "alpha")
    _write(os.path.join(dir_path, "b.txt"), "beta")
    os.makedirs(os.path.join(dir_path, "subdir"), exist_ok=True)

    resp = client.post(f"{BASE_URL}/api/v1/file/list", json={"path": dir_path})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True

    entries = data["data"]["entries"]
    names = {e["name"]: e for e in entries}
    assert "a.txt" in names, f"a.txt missing from listing: {names}"
    assert "b.txt" in names, f"b.txt missing from listing: {names}"
    assert "subdir" in names, f"subdir missing from listing: {names}"
    assert names["a.txt"]["type"] == "file"
    assert names["a.txt"]["size"] == len("alpha")
    assert names["subdir"]["type"] == "dir"


@pytest.mark.file_api
def test_copy_actually_copies(client):
    """file_copy must create the destination on disk (was fake success)."""
    src = os.path.join(WORK_DIR, "src_copy.txt")
    dst = os.path.join(WORK_DIR, "dst_copy.txt")
    _write(src, "COPY_ME_123")

    resp = client.post(
        f"{BASE_URL}/api/v1/file/copy",
        json={"source": src, "destination": dst},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    # The critical assertion: the file REALLY exists now.
    assert _exists_on_disk(dst), "copy reported success but destination missing"
    read_back = _read(dst)["data"]["content"]
    assert read_back == "COPY_ME_123"


@pytest.mark.file_api
def test_copy_missing_source_fails(client):
    """copy of a nonexistent source must NOT report success."""
    resp = client.post(
        f"{BASE_URL}/api/v1/file/copy",
        json={
            "source": os.path.join(WORK_DIR, "nope_missing.txt"),
            "destination": os.path.join(WORK_DIR, "nope_dst.txt"),
        },
    )
    data = resp.json()
    assert data["success"] is False, "copy of missing source must fail"


@pytest.mark.file_api
def test_move_actually_moves(client):
    """file_move must rename on disk (was fake success)."""
    src = os.path.join(WORK_DIR, "before_move.txt")
    dst = os.path.join(WORK_DIR, "after_move.txt")
    _write(src, "MOVE_ME")

    resp = client.post(
        f"{BASE_URL}/api/v1/file/move",
        json={"source": src, "destination": dst},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    assert _exists_on_disk(dst), "move reported success but destination missing"
    assert not _exists_on_disk(src), "move reported success but source still present"
    assert _read(dst)["data"]["content"] == "MOVE_ME"


@pytest.mark.file_api
def test_delete_actually_deletes(client):
    """file_delete must remove the path from disk (was fake success)."""
    target = os.path.join(WORK_DIR, "to_delete.txt")
    _write(target, "DELETE_ME")

    resp = client.post(f"{BASE_URL}/api/v1/file/delete", json={"path": target})
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    assert not _exists_on_disk(target), "delete reported success but file still exists"


@pytest.mark.file_api
def test_write_append_large_content_integrity(client):
    """Large append writes must land on disk IN FULL (was truncated silently)."""
    target = os.path.join(WORK_DIR, "append_large.txt")
    if _exists_on_disk(target):
        os.remove(target)

    chunk = "X" * 1024  # 1 KB
    for i in range(15):  # 15 × 1 KB = ~15 KB total, well past the old failure point
        resp = _write(target, f"CHUNK_{i:02d}:" + chunk + "\n", append=(i > 0))
        assert resp["success"] is True
        assert resp["data"]["bytes_written"] == len(f"CHUNK_{i:02d}:" + chunk + "\n")

    actual_size = os.path.getsize(target)
    expected = sum(
        len(f"CHUNK_{i:02d}:" + chunk + "\n") for i in range(15)
    )
    assert actual_size == expected, (
        f"append integrity broken: expected {expected} bytes on disk, found {actual_size}"
    )


@pytest.mark.file_api
def test_str_replace_on_large_file_not_truncated(client):
    """str_replace on a >10 KB file must preserve the whole file.

    Previously read_file's default max_length=10000 truncated the content
    before replacement, destroying everything past the first 10 KB.
    """
    target = os.path.join(WORK_DIR, "large_replace.txt")
    head = "NEEDLE_TO_REPLACE and then padding follows:\n"
    filler = "Y" * 12000  # > 10 KB of filler AFTER the needle
    _write(target, head + filler)

    resp = client.post(
        f"{BASE_URL}/api/v1/file/replace",
        json={"file": target, "old_str": "NEEDLE_TO_REPLACE", "new_str": "REPLACED_OK"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["replaced_count"] == 1

    content = _read(target, max_length=None)["data"]["content"]
    assert "REPLACED_OK" in content
    # The filler beyond 10 KB must still be present (no silent truncation).
    assert content.count("Y") >= 12000, (
        f"file was truncated by str_replace: only {content.count('Y')} filler chars remain"
    )
