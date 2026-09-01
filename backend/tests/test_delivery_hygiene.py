"""Unit tests for the delivery hygiene nets (hard junk + zip-fold).

Pins the live incident (session fbfcb72d): a build delivered as
project.zip + 14 loose cards (template scrap, dist/ outputs, server.pid,
server.log, 200KB package-lock.json). The nets must produce ONE archive
+ at most standalone documents.
"""

from pathlib import Path
from zipfile import ZipFile

import pytest

from app.domain.models.file import FileInfo
from app.domain.services.agents.delivery_hygiene import (
    drop_junk_attachments,
    fold_loose_files_into_archive,
    is_junk_path,
)


def fi(path: str) -> FileInfo:
    return FileInfo(file_path=path, filename=path.rsplit("/", 1)[-1])


# ── is_junk_path ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/home/u/app/server.pid",
    "/home/u/app/server.log",
    "/home/u/app/package-lock.json",
    "/home/u/app/pnpm-lock.yaml",
    "/home/u/app/yarn.lock",
    "/home/u/app/.env",
    "/home/u/app/.env.production",
    "/home/u/app/__pycache__/main.pyc",
    "/home/u/app/node_modules/vite/package.json",
    "/home/u/app/.git/config",
    "/home/u/app/main.tsbuildinfo",
    "/home/u/app/build.tmp",
])
def test_junk_detected(path: str) -> None:
    assert is_junk_path(path) is True


@pytest.mark.parametrize("path", [
    "/home/u/app/index.html",
    "/home/u/app/style.css",
    "/home/u/app/main.ts",
    "/home/u/app/.env.example",   # template, safe deliverable
    "/home/u/app/README.md",
    "/home/u/app/schema.prisma",
    "/home/u/app/kopi.png",
])
def test_clean_paths_kept(path: str) -> None:
    assert is_junk_path(path) is False


# ── drop_junk_attachments ───────────────────────────────────────────────────

def test_drop_junk_from_incident_list() -> None:
    """The exact live incident: junk cards must vanish, real files stay."""
    attachments = [
        fi("/home/u/project.zip"),
        fi("/home/u/simple-chatgpt-clone/README.md"),
        fi("/home/u/simple-chatgpt-clone/client/src/counter.ts"),
        fi("/home/u/server.pid"),
        fi("/home/u/server.log"),
        fi("/home/u/simple-chatgpt-clone/package-lock.json"),
        fi("/home/u/simple-chatgpt-clone/client/dist/index.js"),
    ]
    kept = drop_junk_attachments(attachments)
    kept_paths = [a.file_path for a in kept]
    assert "/home/u/server.pid" not in kept_paths
    assert "/home/u/server.log" not in kept_paths
    assert "/home/u/simple-chatgpt-clone/package-lock.json" not in kept_paths
    assert "/home/u/project.zip" in kept_paths
    assert "/home/u/simple-chatgpt-clone/client/src/counter.ts" in kept_paths
    # dist/ build outputs are NOT hard junk — the fold net handles them.
    assert "/home/u/simple-chatgpt-clone/client/dist/index.js" in kept_paths


def test_drop_junk_never_raises() -> None:
    weird = [FileInfo(file_path=None, filename="x")]
    assert drop_junk_attachments(weird) == weird


# ── fold_loose_files_into_archive ───────────────────────────────────────────

class FakeSandbox:
    """Executes the fold script LOCALLY (same filesystem), like the real
    sandbox exec_command would in-sandbox."""

    def __init__(self, root: Path, user_home: str = None):
        self.root = root
        self.user_home = user_home or str(root)

    async def exec_command(self, session_id: str, exec_dir: str, command: str):
        import shlex as _shlex

        class R:
            success = True
            data = {"output": ""}
            message = ""

        # command = python3 -c '<script>'
        script = _shlex.split(command)[2]
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(script, {"__name__": "__main__"})
        r = R()
        r.data = {"output": buf.getvalue()}
        return r


def _make_tree(tmp_path: Path) -> FakeSandbox:
    (tmp_path / "project.zip").write_bytes(b"")  # replaced below
    # Build a REAL zip first so the fold appends into a valid archive.
    with ZipFile(tmp_path / "project.zip", "w") as z:
        z.writestr("App.tsx", "export default () => null;")
        z.writestr("index.ts", "console.log(1);")
    for rel in ("client/src/counter.ts", "client/src/main.ts", "README.md"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"// {rel}")
    return FakeSandbox(tmp_path)


@pytest.mark.asyncio
async def test_fold_collapses_loose_into_zip(tmp_path: Path) -> None:
    sandbox = _make_tree(tmp_path)
    attachments = [
        fi(str(tmp_path / "project.zip")),
        fi(str(tmp_path / "README.md")),              # doc → stays loose
        fi(str(tmp_path / "client/src/counter.ts")),  # non-doc → folded
        fi(str(tmp_path / "client/src/main.ts")),     # non-doc → folded
    ]
    kept = await fold_loose_files_into_archive(sandbox, attachments)
    kept_paths = [a.file_path for a in kept]
    assert kept_paths == [
        str(tmp_path / "project.zip"),
        str(tmp_path / "README.md"),
    ]
    # The folded files must be INSIDE the archive now (nothing lost) —
    # WITH their folder structure (flat basenames scattered the archive
    # in the live incident).
    with ZipFile(tmp_path / "project.zip") as z:
        names = z.namelist()
    assert "client/src/counter.ts" in names
    assert "client/src/main.ts" in names
    assert "App.tsx" in names  # original member untouched


@pytest.mark.asyncio
async def test_fold_no_zip_is_noop(tmp_path: Path) -> None:
    sandbox = _make_tree(tmp_path)
    attachments = [
        fi(str(tmp_path / "README.md")),
        fi(str(tmp_path / "client/src/counter.ts")),
    ]
    kept = await fold_loose_files_into_archive(sandbox, attachments)
    assert len(kept) == 2  # unchanged


@pytest.mark.asyncio
async def test_fold_only_docs_is_noop(tmp_path: Path) -> None:
    sandbox = _make_tree(tmp_path)
    attachments = [
        fi(str(tmp_path / "project.zip")),
        fi(str(tmp_path / "README.md")),
    ]
    kept = await fold_loose_files_into_archive(sandbox, attachments)
    assert [a.file_path for a in kept] == [
        str(tmp_path / "project.zip"),
        str(tmp_path / "README.md"),
    ]


@pytest.mark.asyncio
async def test_fold_basename_collision_is_safe(tmp_path: Path) -> None:
    """Two index.html at different paths fold STRUCTURED — distinct
    arcnames, no clobbering, no flat dump (live incident: favicon_1.svg)."""
    with ZipFile(tmp_path / "site.zip", "w") as z:
        z.writestr("index.html", "original")
    for rel in ("a/index.html", "b/index.html"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"// {rel}")
    sandbox = FakeSandbox(tmp_path)
    attachments = [
        fi(str(tmp_path / "site.zip")),
        fi(str(tmp_path / "a/index.html")),
        fi(str(tmp_path / "b/index.html")),
    ]
    kept = await fold_loose_files_into_archive(sandbox, attachments)
    assert [a.file_path for a in kept] == [str(tmp_path / "site.zip")]
    with ZipFile(tmp_path / "site.zip") as z:
        names = z.namelist()
    assert names.count("index.html") == 1  # original member untouched
    assert "a/index.html" in names
    assert "b/index.html" in names
    # Nothing got clobbered: 1 original + 2 structured folds.
    assert len([n for n in names if n.endswith("index.html")]) == 3


@pytest.mark.asyncio
async def test_fold_never_folds_junk_or_secrets(tmp_path: Path) -> None:
    """Junk/secrets are never appended INTO a deliverable archive."""
    with ZipFile(tmp_path / "project.zip", "w") as z:
        z.writestr("App.tsx", "export default () => null;")
    for rel in ("app/server.pid", "app/.env.local", "app/src/index.js"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"// {rel}")
    sandbox = FakeSandbox(tmp_path)
    attachments = [
        fi(str(tmp_path / "project.zip")),
        fi(str(tmp_path / "app/server.pid")),
        fi(str(tmp_path / "app/.env.local")),
        fi(str(tmp_path / "app/src/index.js")),
    ]
    kept = await fold_loose_files_into_archive(sandbox, attachments)
    with ZipFile(tmp_path / "project.zip") as z:
        names = z.namelist()
    assert "app/src/index.js" in names       # real file folded, structured
    assert not any(n.endswith(".pid") for n in names)
    assert not any(n.split("/")[-1] == ".env.local" for n in names)


@pytest.mark.asyncio
async def test_fold_fail_open_on_exec_error(tmp_path: Path) -> None:
    class BrokenSandbox:
        async def exec_command(self, *a, **kw):
            class R:
                success = False
                data = None
                message = "sandbox exploded"
            return R()

    attachments = [
        fi(str(tmp_path / "project.zip")),
        fi(str(tmp_path / "client/src/counter.ts")),
    ]
    kept = await fold_loose_files_into_archive(BrokenSandbox(), attachments)
    # Fail-open: loose file stays a card rather than being lost.
    assert len(kept) == 2
