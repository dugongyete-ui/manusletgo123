"""Unit tests for the server-side auto-bundle safety net
(`agents.auto_bundle.auto_bundle_deliverables`):

When a multi-file delivery arrives with NO archive (the model forgot to
zip, ran out of budget, or attached loose members), the server collapses
it into ONE .zip. Standalone documents (.md/.txt/...) stay as files.
Fail-open: any sandbox error returns the original list unchanged.
"""

from types import SimpleNamespace

import pytest

from app.domain.models.file import FileInfo
from app.domain.services.agents.auto_bundle import (
    auto_bundle_deliverables,
    sanitize_oversized_archives,
    split_docs_members,
    _common_parent,
)


class _FakeSandbox:
    """Sandbox stub: 'executes' the bundle script by simulating success,
    failure, or empty output, and records the command for assertions."""

    def __init__(self, user_home: str, output: str = "", success: bool = True):
        self.user_home = user_home
        self._output = output
        self._success = success
        self.commands = []

    async def exec_command(self, session_id, exec_dir, command):
        self.commands.append((session_id, exec_dir, command))
        return SimpleNamespace(
            success=self._success,
            data={"output": self._output, "returncode": 0},
        )


def fi(path: str) -> FileInfo:
    return FileInfo(file_path=path)


# ── pure helpers ─────────────────────────────────────────────────────────────


def test_split_docs_members():
    docs, members = split_docs_members([
        fi("/home/u/report.md"),
        fi("/home/u/app/index.html"),
        fi("/home/u/app/style.css"),
        fi("/home/u/notes.txt"),
    ])
    assert [a.file_path for a in docs] == [
        "/home/u/report.md", "/home/u/notes.txt",
    ]
    assert [a.file_path for a in members] == [
        "/home/u/app/index.html", "/home/u/app/style.css",
    ]


def test_common_parent_variants():
    assert _common_parent([
        "/home/u/app/index.html", "/home/u/app/style.css",
    ]) == "/home/u/app"
    # only the home shared → deeper parent does not exist
    assert _common_parent([
        "/home/u/a/index.html", "/home/u/b/style.css",
    ]) == "/home/u"
    # nothing shared
    assert _common_parent(["/tmp/x.png", "/home/u/y.png"]) is None


# ── bundling behaviour ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_project_dir_collapsed_into_single_zip():
    """The observed failure mode: 15 loose build files (maps, lockfile,
    sources) with no zip → ONE archive + zero loose members."""
    sandbox = _FakeSandbox(
        "/home/runner",
        output="BUNDLE_WROTE /home/runner/my-app.zip 6 40960",
    )
    attachments = [
        fi("/home/runner/my-app/index.html"),
        fi("/home/runner/my-app/app.js"),
        fi("/home/runner/my-app/app.js.map"),
        fi("/home/runner/my-app/types.d.ts"),
        fi("/home/runner/my-app/package-lock.json"),
        fi("/home/runner/my-app/README.md"),
    ]
    out = await auto_bundle_deliverables(sandbox, attachments)
    paths = [a.file_path for a in out]
    # README.md lives INSIDE the project dir → bundled, not delivered loose
    assert paths == ["/home/runner/my-app.zip"]
    assert "my-app" in sandbox.commands[0][2]
    assert "node_modules" in sandbox.commands[0][2]


@pytest.mark.asyncio
async def test_docs_stay_beside_the_archive():
    """Research/build mix: the .md report outside the project is never
    zipped into the bundle."""
    sandbox = _FakeSandbox(
        "/home/runner",
        output="BUNDLE_WROTE /home/runner/site.zip 2 2048",
    )
    attachments = [
        fi("/home/runner/site/index.html"),
        fi("/home/runner/site/style.css"),
        fi("/home/runner/summary_riset.md"),
    ]
    out = await auto_bundle_deliverables(sandbox, attachments)
    paths = [a.file_path for a in out]
    assert paths == ["/home/runner/site.zip", "/home/runner/summary_riset.md"]


@pytest.mark.asyncio
async def test_existing_zip_short_circuits():
    """A delivered archive leads the delivery — auto-bundle stays out."""
    sandbox = _FakeSandbox("/home/runner", output="BUNDLE_WROTE x 1 1")
    attachments = [
        fi("/home/runner/site.zip"),
        fi("/home/runner/summary.md"),
    ]
    out = await auto_bundle_deliverables(sandbox, attachments)
    assert [a.file_path for a in out] == [
        "/home/runner/site.zip", "/home/runner/summary.md",
    ]
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_single_member_not_bundled():
    """One asset (single-file deliverable) stays as-is."""
    sandbox = _FakeSandbox("/home/runner", output="BUNDLE_WROTE x 1 1")
    out = await auto_bundle_deliverables(
        sandbox, [fi("/home/runner/tool.py"), fi("/home/runner/report.md")]
    )
    assert out == [fi("/home/runner/tool.py"), fi("/home/runner/report.md")]
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_docs_only_never_bundled():
    """Pure document delivery (user: 'MD/txt tidak perlu di-zip')."""
    sandbox = _FakeSandbox("/home/runner", output="BUNDLE_WROTE x 1 1")
    out = await auto_bundle_deliverables(
        sandbox, [fi("/home/u/laporan.md"), fi("/home/u/catatan.txt")]
    )
    assert out == [fi("/home/u/laporan.md"), fi("/home/u/catatan.txt")]
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_scattered_members_flat_bundle():
    """No shared project dir → flat project.zip with collision handling."""
    sandbox = _FakeSandbox(
        "/home/runner", output="BUNDLE_WROTE /home/runner/project.zip 3 512"
    )
    out = await auto_bundle_deliverables(
        sandbox,
        [
            fi("/home/runner/app.js"),
            fi("/home/runner/src/app.js"),  # basename collision
            fi("/home/runner/style.css"),
        ],
    )
    assert [a.file_path for a in out] == ["/home/runner/project.zip"]
    cmd = sandbox.commands[0][2]
    assert "project.zip" in cmd
    assert "while arc in seen" in cmd


@pytest.mark.asyncio
async def test_exec_failure_returns_original_list():
    """Fail-open: a broken sandbox never blocks delivery."""
    sandbox = _FakeSandbox("/home/runner", output="", success=False)
    attachments = [
        fi("/home/runner/app/index.html"),
        fi("/home/runner/app/style.css"),
    ]
    out = await auto_bundle_deliverables(sandbox, attachments)
    assert out == attachments


@pytest.mark.asyncio
async def test_empty_archive_returns_original_list():
    """Zero members archived (e.g. paths don't exist) → no bundle."""
    sandbox = _FakeSandbox("/home/runner", output="BUNDLE_WROTE /home/runner/my-app.zip 0 0")
    attachments = [
        fi("/home/runner/my-app/index.html"),
        fi("/home/runner/my-app/style.css"),
    ]
    out = await auto_bundle_deliverables(sandbox, attachments)
    assert out == attachments


@pytest.mark.asyncio
async def test_exception_returns_original_list():
    """Any raised error inside the helper → original list (fail-open)."""
    class _Boom:
        user_home = "/home/runner"

        async def exec_command(self, *a, **k):
            raise RuntimeError("sandbox exploded")

    attachments = [
        fi("/home/runner/app/index.html"),
        fi("/home/runner/app/style.css"),
    ]
    out = await auto_bundle_deliverables(_Boom(), attachments)
    assert out == attachments


# ── oversized-archive sanitize (426MB-zip quota incident) ────────────────────


class _SizeFakeSandbox:
    """Returns ZIP_SIZE + member listing for inspect, REBUILT for rebuild."""

    user_home = "/home/runner"

    def __init__(self, size: int, members: str, rebuild_ok: bool = True):
        self._size = size
        self._members = members
        self._rebuild_ok = rebuild_ok
        self.commands = []

    async def exec_command(self, session_id, exec_dir, command):
        self.commands.append(command)
        if "ZIP_SIZE" in command:
            return SimpleNamespace(
                success=True,
                data={"output": f"ZIP_SIZE {self._size}\n{self._members}"},
            )
        return SimpleNamespace(
            success=True,
            data={
                "output": "REBUILT /home/runner/app-clean.zip 2048"
                if self._rebuild_ok else ""
            },
        )


@pytest.mark.asyncio
async def test_bloated_junk_zip_is_rebuilt():
    """The exact incident: 426MB zip with node_modules members → swapped
    for the clean archive."""
    sb = _SizeFakeSandbox(
        426 * 1024 * 1024,
        "chatgpt-clone/index.html\nchatgpt-clone/node_modules/x.js",
    )
    out = await sanitize_oversized_archives(sb, [fi("/home/runner/chatgpt-clone.zip")])
    assert [a.file_path for a in out] == ["/home/runner/chatgpt-clone-clean.zip"]
    assert out[0].filename == "chatgpt-clone-clean.zip"


@pytest.mark.asyncio
async def test_small_zip_untouched():
    sb = _SizeFakeSandbox(2 * 1024 * 1024, "app/index.html")
    out = await sanitize_oversized_archives(sb, [fi("/home/runner/app.zip")])
    assert [a.file_path for a in out] == ["/home/runner/app.zip"]
    assert len(sb.commands) == 1


@pytest.mark.asyncio
async def test_large_clean_zip_untouched():
    """A legitimately huge archive (video assets, no junk) passes through."""
    sb = _SizeFakeSandbox(
        90 * 1024 * 1024, "video/raw-cut.mp4\nvideo/final.mp4"
    )
    out = await sanitize_oversized_archives(sb, [fi("/home/runner/video.zip")])
    assert [a.file_path for a in out] == ["/home/runner/video.zip"]
    assert len(sb.commands) == 1


@pytest.mark.asyncio
async def test_rebuild_failure_delivers_original():
    sb = _SizeFakeSandbox(
        60 * 1024 * 1024, "app/node_modules/big.js", rebuild_ok=False
    )
    out = await sanitize_oversized_archives(sb, [fi("/home/runner/app.zip")])
    assert [a.file_path for a in out] == ["/home/runner/app.zip"]


@pytest.mark.asyncio
async def test_non_zip_attachments_untouched():
    sb = _SizeFakeSandbox(999, "")
    out = await sanitize_oversized_archives(
        sb, [fi("/home/runner/report.md"), fi("/home/runner/app/index.html")]
    )
    assert out == [fi("/home/runner/report.md"), fi("/home/runner/app/index.html")]
    assert sb.commands == []
