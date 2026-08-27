"""Unit tests for attachment path normalization.

Regression (session 5e7888777d4b4c03): the model called message_notify_user
with attachments='["/home/z/users/x/kopi_senja.zip"]' — a JSON-encoded list
as a plain string. The deferral code stored the whole blob as one "path",
which failed every sync and the zip silently disappeared from delivery.
"""

from app.domain.services.agents.attachment_paths import normalize_attachment_paths


def test_json_encoded_string_expands():
    raw = '["/home/z/users/x/kopi_senja.zip"]'
    assert normalize_attachment_paths(raw) == ["/home/z/users/x/kopi_senja.zip"]


def test_json_encoded_string_multiple_paths():
    raw = '["/home/runner/a.zip", "/home/runner/b.md"]'
    assert normalize_attachment_paths(raw) == [
        "/home/runner/a.zip",
        "/home/runner/b.md",
    ]


def test_single_path_string():
    assert normalize_attachment_paths("/home/runner/report.md") == [
        "/home/runner/report.md"
    ]


def test_list_with_mixed_entries():
    raw = ["/home/runner/a.zip", '["/home/runner/b.md"]', "/home/runner/c.txt"]
    assert normalize_attachment_paths(raw) == [
        "/home/runner/a.zip",
        "/home/runner/b.md",
        "/home/runner/c.txt",
    ]


def test_quoted_path_stripped():
    assert normalize_attachment_paths('"/home/runner/a.md"') == [
        "/home/runner/a.md"
    ]
    assert normalize_attachment_paths("'/home/runner/a.md'") == [
        "/home/runner/a.md"
    ]


def test_junk_dropped():
    # no absolute path → dropped, not crashing
    assert normalize_attachment_paths("not a path") == []
    assert normalize_attachment_paths(["", None, 42, "kopi_senja.zip"]) == []
    assert normalize_attachment_paths(None) == []
    assert normalize_attachment_paths([]) == []


def test_dedup_preserves_order():
    raw = ["/home/a.zip", "/home/b.md", "/home/a.zip"]
    assert normalize_attachment_paths(raw) == ["/home/a.zip", "/home/b.md"]


def test_relative_path_with_tilde():
    assert normalize_attachment_paths("~/notes.md") == ["~/notes.md"]


def test_broken_json_string_falls_back_to_drop():
    # starts like JSON but is not valid → not a path → dropped
    assert normalize_attachment_paths('["/broken...') == []
