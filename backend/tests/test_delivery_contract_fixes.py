"""Unit tests for the delivery-contract fixes (Task 40).

Covers the four regressions found in the live E2E run of 2026-08-31
(sessions 86bd73f5c45f40e7 / 102c30cd4e104025):

  1. file_read of ANY file (worst case: the workspace manual AGENTS.md)
     must never upload/sync/deliver — the manual leaked into a user's
     chat file list.
  2. Mid-task syncs (tool read-backs, artifact sweeps, step attachments)
     upload as CANDIDATES only (add_to_session=False): the session's
     visible file list gets files ONLY at the final summary. Before, the
     user saw every intermediate html/css/js file next to the zip.
  3. Protected delivery paths — {home}/project (manual) and {home}/upload
     (user's own uploads) — are refused by _sync_file_to_storage even
     when called directly.
  4. Cross-session delivery ledger: an automatic sweep skips candidates
     whose exact (user, path, size) another session already delivered;
     explicit model attachments are never blocked by the sweep filter.

And the positive path:
  5. The final-summary attach point links uploaded candidates into the
     session file list exactly once (replacing a stale same-path entry).
"""

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.domain.services.agents.delivery_ledger as delivery_ledger
from app.domain.models.event import MessageEvent, ToolEvent, ToolStatus
from app.domain.models.file import FileInfo
from app.domain.services.agent_task_runner import AgentTaskRunner


HOME = "/home/z/sandbox/users/u1"


def make_runner() -> AgentTaskRunner:
    """AgentTaskRunner skeleton — no settings, no real sandboxes."""
    runner = AgentTaskRunner.__new__(AgentTaskRunner)
    runner._session_id = "s1"
    runner._agent_id = "a1"
    runner._user_id = "u1"
    runner._sandbox = SimpleNamespace(
        user_home=HOME,
        file_read=AsyncMock(),
        file_download=AsyncMock(),
        exec_command=AsyncMock(),
    )
    runner._session_repository = MagicMock()
    runner._session_repository.get_file_by_path = AsyncMock(return_value=None)
    runner._session_repository.add_file = AsyncMock()
    runner._session_repository.remove_file = AsyncMock()
    runner._file_storage = MagicMock()
    runner._file_storage.upload_file = AsyncMock(
        return_value=FileInfo(file_id="fid-1", filename="x", size=10)
    )
    runner._file_old_by_call = {}
    runner._file_storage.delete_file = AsyncMock()
    return runner


def zip_bytes(name="x.zip", content=b"PK-zip"):
    return io.BytesIO(content)


# ── 1. file_read never syncs (manual leak fix) ─────────────────────────────

@pytest.mark.asyncio
async def test_file_read_event_never_syncs(tmp_path):
    """The model reading AGENTS.md (or any file) must not trigger an
    upload — only WRITE functions sync, and only as candidates."""
    runner = make_runner()
    sync_calls = []

    async def fake_sync(path, *, add_to_session=True):
        sync_calls.append((path, add_to_session))
        return None

    runner._sync_file_to_storage = fake_sync
    runner._sandbox.file_read = AsyncMock(
        return_value=SimpleNamespace(
            success=True, data={"content": "# manual body"}
        )
    )

    ev = ToolEvent(
        status=ToolStatus.CALLED,
        tool_call_id="t1",
        tool_name="file",
        function_name="file_read",
        function_args={"file": f"{HOME}/project/AGENTS.md"},
        function_result=SimpleNamespace(success=True, data={}),
    )
    await runner._handle_tool_event(ev)

    assert sync_calls == []  # reads never sync — the AGENTS.md leak fix
    assert ev.tool_content is not None  # content preview still works


@pytest.mark.asyncio
async def test_file_write_event_syncs_as_candidate_only(tmp_path):
    """file_write uploads the new version but must NOT add it to the
    session file list — the final summary decides visibility."""
    runner = make_runner()
    runner._sandbox.file_download = AsyncMock(return_value=io.BytesIO(b"body"))

    ev = ToolEvent(
        status=ToolStatus.CALLED,
        tool_call_id="t2",
        tool_name="file",
        function_name="file_write",
        function_args={"file": f"{HOME}/site/index.html"},
        function_result=SimpleNamespace(success=True, data={}),
    )
    runner._sandbox.file_read = AsyncMock(
        return_value=SimpleNamespace(success=True, data={"content": "<html/>"})
    )
    info = await runner._handle_tool_event(ev)

    assert info is not None  # tracked for the final merge
    runner._session_repository.add_file.assert_not_awaited()  # candidate only
    runner._session_repository.get_file_by_path.assert_not_awaited()


# ── 3. protected delivery paths ────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        f"{HOME}/project/AGENTS.md",
        f"{HOME}/project/WORKFLOW.md",
        f"{HOME}/project/skills/webdev-fullstack/SKILL.md",
        f"{HOME}/project",
        f"{HOME}/upload/foto-user.png",
    ],
)
async def test_protected_paths_refused(path):
    runner = make_runner()
    info = await runner._sync_file_to_storage(path)
    assert info is None
    runner._file_storage.upload_file.assert_not_awaited()
    runner._session_repository.add_file.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        f"{HOME}/project/kopi-senja/index.html",       # build subfolder
        f"{HOME}/project/kopi-senja/assets/logo.png",  # nested build file
        f"{HOME}/project/kopi-senja.zip",              # the archive itself
        f"{HOME}/project/report.md",                   # task doc (not manual set)
    ],
)
async def test_build_outputs_inside_project_are_deliverable(path):
    """Builds live in project/<app-name>/ — those MUST sync (guard does not
    over-block the new workspace layout)."""
    runner = make_runner()
    runner._sandbox.file_download = AsyncMock(return_value=io.BytesIO(b"data"))
    info = await runner._sync_file_to_storage(path)
    assert info is not None
    assert info.file_path == path


@pytest.mark.asyncio
async def test_normal_path_still_syncs():
    """A genuine build output is not blocked by the zone guards."""
    runner = make_runner()
    runner._sandbox.file_download = AsyncMock(return_value=io.BytesIO(b"html"))
    info = await runner._sync_file_to_storage(f"{HOME}/kopi-senja/index.html")
    assert info is not None
    assert info.file_path == f"{HOME}/kopi-senja/index.html"


@pytest.mark.asyncio
async def test_sandbox_without_user_home_has_no_guard():
    """Provider without a user_home concept (None) — guard is a no-op."""
    runner = make_runner()
    runner._sandbox.user_home = None
    runner._sandbox.file_download = AsyncMock(return_value=io.BytesIO(b"x"))
    info = await runner._sync_file_to_storage("/tmp/anything.txt")
    assert info is not None


# ── 3b. scan: manual root skipped, build subfolders scanned ────────────────

@pytest.mark.asyncio
async def test_scan_skips_manual_root_but_scans_build_subfolders():
    """The manual marker (AGENTS.md + skills) makes the scan skip the
    manual's own files and skills/**, while build subfolders inside
    project/ and task documents at project/ root are still found."""
    runner = make_runner()
    runner._sandbox.file_list = AsyncMock(
        side_effect=lambda path: SimpleNamespace(
            success=True,
            data={"entries": {
                f"{HOME}": [
                    {"name": "project", "type": "dir"},
                ],
                f"{HOME}/project": [
                    {"name": "AGENTS.md", "type": "file", "size": 2210},
                    {"name": "WORKFLOW.md", "type": "file", "size": 900},
                    {"name": "skills", "type": "dir"},
                    {"name": "report.md", "type": "file", "size": 50},
                    {"name": "kopi-senja", "type": "dir"},
                    {"name": "kopi-senja.zip", "type": "file", "size": 3141},
                ],
                f"{HOME}/project/kopi-senja": [
                    {"name": "index.html", "type": "file", "size": 2949},
                ],
            }.get(path)},
        )
    )

    found = await runner._scan_user_home_files()

    assert f"{HOME}/project/kopi-senja/index.html" in found
    assert f"{HOME}/project/kopi-senja.zip" in found
    assert f"{HOME}/project/report.md" in found      # task document kept
    assert f"{HOME}/project/AGENTS.md" not in found  # manual never scanned
    assert f"{HOME}/project/WORKFLOW.md" not in found
    assert not any(p.startswith(f"{HOME}/project/skills/") for p in found)


# ── 2. sweep = candidates only ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_uploads_candidates_without_session_link():
    runner = make_runner()
    runner._sandbox.file_download = AsyncMock(return_value=io.BytesIO(b"body"))
    runner._sandbox.file_list = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            data={"entries": [
                {"name": "site", "type": "dir"},
                {"name": "index.html", "type": "file", "size": 4},
            ]},
        )
    )

    baseline = {}  # everything is "new"
    files_written: list = []
    pending: set = set()
    await runner._sync_run_artifacts(baseline, files_written, pending)

    assert files_written, "sweep must track the found file"
    runner._session_repository.add_file.assert_not_awaited()


# ── 4. cross-session ledger ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ledger_blocks_sweep_re_delivery():
    """File already delivered by ANOTHER session (same user+path+size) is
    skipped by the automatic sweep — the hello.txt double-send incident."""
    runner = make_runner()
    runner._sandbox.file_download = AsyncMock(return_value=io.BytesIO(b"body"))
    runner._sandbox.file_list = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            data={"entries": [
                {"name": "hello.txt", "type": "file", "size": 15},
            ]},
        )
    )
    delivery_ledger.reset()
    delivery_ledger.mark("u1", f"{HOME}/hello.txt", 15)

    files_written: list = []
    await runner._sync_run_artifacts({}, files_written, set())

    assert files_written == []  # blocked by ledger
    runner._file_storage.upload_file.assert_not_awaited()
    delivery_ledger.reset()


@pytest.mark.asyncio
async def test_ledger_allows_new_version_of_same_path():
    """Same path but different size = genuinely updated file → delivered."""
    runner = make_runner()
    runner._sandbox.file_download = AsyncMock(return_value=io.BytesIO(b"body2"))
    runner._sandbox.file_list = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            data={"entries": [
                {"name": "kopi.zip", "type": "file", "size": 6629},
            ]},
        )
    )
    delivery_ledger.reset()
    delivery_ledger.mark("u1", f"{HOME}/kopi.zip", 4494)  # older version

    files_written: list = []
    await runner._sync_run_artifacts({}, files_written, set())
    assert files_written, "new version must pass the ledger"
    delivery_ledger.reset()


def test_ledger_ttl_expiry(monkeypatch):
    delivery_ledger.reset()
    delivery_ledger.mark("u", "/p", 1)
    assert delivery_ledger.seen("u", "/p", 1)
    # Simulate time passing beyond TTL.
    past = delivery_ledger._ledger[(("u"), "/p", 1)] - (49 * 3600)
    delivery_ledger._ledger[("u", "/p", 1)] = past
    assert not delivery_ledger.seen("u", "/p", 1)
    delivery_ledger.reset()


# ── 5. final attach point links candidates into the session ────────────────

@pytest.mark.asyncio
async def test_final_message_links_uploaded_candidate():
    runner = make_runner()
    candidate = FileInfo(
        file_id="fid-9", filename="kopi-senja-website.zip",
        file_path=f"{HOME}/kopi-senja-website.zip", size=3141,
    )
    ev = MessageEvent(
        role="assistant", message="selesai", is_final=True,
        attachments=[candidate],
    )
    await runner._sync_message_attachments_to_storage(ev)
    runner._session_repository.add_file.assert_awaited_once()
    # No re-upload: the candidate already carries a file_id.
    runner._file_storage.upload_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_message_replaces_stale_same_path_entry():
    """The model rewrote a file already delivered in an earlier turn of
    this session: the old entry is removed, the new one added — never
    both."""
    runner = make_runner()
    runner._session_repository.get_file_by_path = AsyncMock(
        return_value=FileInfo(
            file_id="fid-old", filename="index.html",
            file_path=f"{HOME}/site/index.html", size=1,
        )
    )
    fresh = FileInfo(
        file_id="fid-new", filename="index.html",
        file_path=f"{HOME}/site/index.html", size=2,
    )
    ev = MessageEvent(role="assistant", message="revisi", is_final=True,
                      attachments=[fresh])
    await runner._sync_message_attachments_to_storage(ev)
    runner._session_repository.remove_file.assert_awaited_once_with("s1", "fid-old")
    runner._session_repository.add_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_final_message_uploads_unsynced_attachment():
    """Attachment without file_id (model listed a shell-made path) is
    uploaded AND linked in one step."""
    runner = make_runner()
    runner._sandbox.file_download = AsyncMock(return_value=io.BytesIO(b"pptx"))
    ev = MessageEvent(
        role="assistant", message="slide siap", is_final=True,
        attachments=[FileInfo(filename="deck.pptx",
                              file_path=f"{HOME}/deck.pptx", size=100)],
    )
    await runner._sync_message_attachments_to_storage(ev)
    runner._file_storage.upload_file.assert_awaited_once()
    runner._session_repository.add_file.assert_awaited_once()
    assert ev.attachments and ev.attachments[0].file_id
