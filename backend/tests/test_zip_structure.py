"""Unit tests for the flat-archive restructure net.

Pins the live incident (session fbfcb72d, 2026-09-01): the model's zip
carried 37 BARE BASENAMES — extracting scattered every file at the top
level ("saat saya extract ... tidak ada folder sesuai masing-masing,
mentah gitu aja") — plus a real ``.env`` and fold-renamed
``favicon_1.svg`` members. The net must rebuild such archives so members
mirror the REAL sandbox project tree (GitHub-style: one clean root
directory), dropping junk/secret members, and never lose a member.
"""

from pathlib import Path
from zipfile import ZipFile

import pytest

from app.domain.models.file import FileInfo
from app.domain.services.agents.auto_bundle import restructure_flat_archives


def fi(path: str, name: str = None) -> FileInfo:
    return FileInfo(file_path=path, filename=name or path.rsplit("/", 1)[-1])


class ExecSandbox:
    """Runs the generated python one-liner LOCALLY (same filesystem)."""

    def __init__(self, home: Path):
        self.user_home = str(home)
        self.commands = []

    async def exec_command(self, session_id: str, exec_dir: str, command: str):
        import io
        import contextlib
        import shlex as _shlex

        self.commands.append((session_id, exec_dir, command))
        script = _shlex.split(command)[2]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(script, {"__name__": "__main__"})
            ok = True
            err = ""
        except SystemExit:
            ok = True
            err = ""
        except Exception as exc:  # pragma: no cover — surfaced via output
            ok = False
            err = str(exc)

        class R:
            success = ok
            data = {"output": buf.getvalue()}
            message = err

        return R()


def _make_project(home: Path) -> None:
    """The real project tree, as the incident sandbox had it."""
    files = {
        "simple-chatgpt-clone/package.json": "// root pkg",
        "simple-chatgpt-clone/.env.example": "DATABASE_URL=x",
        "simple-chatgpt-clone/client/index.html": "<html/>",
        "simple-chatgpt-clone/client/package.json": "// client pkg",
        "simple-chatgpt-clone/client/src/App.tsx": "// app",
        "simple-chatgpt-clone/client/src/components/Sidebar.tsx": "// sb",
        "simple-chatgpt-clone/client/public/favicon.svg": "<svg/>",
        "simple-chatgpt-clone/server/package.json": "// server pkg",
        "simple-chatgpt-clone/server/src/index.ts": "// srv",
        "simple-chatgpt-clone/server/.env": "SECRET=1",  # real secret on disk
    }
    for rel, content in files.items():
        p = home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def _make_flat_incident_zip(home: Path) -> Path:
    """Model-made FLAT zip: bare basenames + .env + fold-renames."""
    zp = home / "project.zip"
    with ZipFile(zp, "w") as z:
        z.writestr("package.json", "// root pkg")
        z.writestr(".env", "SECRET=1")
        z.writestr(".env.example", "DATABASE_URL=x")
        z.writestr("index.html", "<html/>")
        z.writestr("App.tsx", "// app")
        z.writestr("Sidebar.tsx", "// sb")
        z.writestr("favicon.svg", "<svg/>")
        z.writestr("index.ts", "// srv")
        z.writestr("package_1.json", "// client pkg")   # fold-rename
        z.writestr("package_2.json", "// server pkg")   # fold-rename
    return zp


@pytest.mark.asyncio
async def test_flat_incident_rebuilt_structured(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _make_project(home)
    zp = _make_flat_incident_zip(home)
    sandbox = ExecSandbox(home)

    out = await restructure_flat_archives(
        sandbox, [fi(str(zp), "project.zip")]
    )
    # The archive is swapped to the restructured path, display name kept.
    assert len(out) == 1
    assert out[0].file_path == str(home / "project-structured.zip")
    assert out[0].filename == "project.zip"

    with ZipFile(home / "project-structured.zip") as z:
        names = [n for n in z.namelist() if not n.endswith("/")]

    # 100% structured — extraction creates the real directory tree.
    flat = [n for n in names if "/" not in n]
    assert flat == []
    assert "simple-chatgpt-clone/client/index.html" in names
    assert "simple-chatgpt-clone/client/src/App.tsx" in names
    assert "simple-chatgpt-clone/client/src/components/Sidebar.tsx" in names
    assert "simple-chatgpt-clone/client/public/favicon.svg" in names
    assert "simple-chatgpt-clone/server/src/index.ts" in names
    # Secrets dropped.
    assert ".env" not in names
    assert not any(n.split("/")[-1] == ".env" for n in names)
    # Templates are deliverables.
    assert "simple-chatgpt-clone/.env.example" in names
    # Nothing lost: 10 input members - .env = 9 re-emitted (fold-renames
    # un-renamed back onto their real trees).
    assert len(names) == 9


@pytest.mark.asyncio
async def test_structured_zip_untouched(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _make_project(home)
    zp = home / "good.zip"
    with ZipFile(zp, "w") as z:
        z.writestr("simple-chatgpt-clone/client/index.html", "<html/>")
        z.writestr("simple-chatgpt-clone/server/src/index.ts", "// srv")

    sandbox = ExecSandbox(home)
    out = await restructure_flat_archives(
        sandbox, [fi(str(zp), "good.zip")]
    )
    assert out == [fi(str(zp), "good.zip")]
    assert not (home / "good-structured.zip").exists()
    assert sandbox.commands  # inspected, then STRUCTURE_OK


@pytest.mark.asyncio
async def test_junky_structured_zip_sanitized(tmp_path: Path) -> None:
    """Structured but carrying a secret member → rebuilt without it."""
    home = tmp_path / "home"
    home.mkdir()
    _make_project(home)
    zp = home / "mixed.zip"
    with ZipFile(zp, "w") as z:
        z.writestr("simple-chatgpt-clone/server/.env", "SECRET=1")
        z.writestr("simple-chatgpt-clone/server/src/index.ts", "// srv")

    sandbox = ExecSandbox(home)
    out = await restructure_flat_archives(
        sandbox, [fi(str(zp), "mixed.zip")]
    )
    assert out[0].file_path == str(home / "mixed-structured.zip")
    with ZipFile(home / "mixed-structured.zip") as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
    assert names == ["simple-chatgpt-clone/server/src/index.ts"]


@pytest.mark.asyncio
async def test_member_resolving_nowhere_is_kept(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _make_project(home)
    zp = home / "part.zip"
    with ZipFile(zp, "w") as z:
        z.writestr("App.tsx", "// app")
        z.writestr("ghost-orphan.txt", "deleted from sandbox")

    sandbox = ExecSandbox(home)
    out = await restructure_flat_archives(sandbox, [fi(str(zp))])
    with ZipFile(home / "part-structured.zip") as z:
        names = z.namelist()
    assert "simple-chatgpt-clone/client/src/App.tsx" in names
    # The orphan is copied from the original archive — nothing is lost.
    assert "ghost-orphan.txt" in names


@pytest.mark.asyncio
async def test_all_junk_zip_keeps_original(tmp_path: Path) -> None:
    """A rebuild that would be empty never swaps the attachment."""
    home = tmp_path / "home"
    home.mkdir()
    zp = home / "junk.zip"
    with ZipFile(zp, "w") as z:
        z.writestr("server.pid", "1")
        z.writestr(".env", "SECRET=1")

    sandbox = ExecSandbox(home)
    out = await restructure_flat_archives(sandbox, [fi(str(zp))])
    assert out == [fi(str(zp))]
    assert not (home / "junk-structured.zip").exists()


@pytest.mark.asyncio
async def test_project_prefix_stripped(tmp_path: Path) -> None:
    """Files under project/<app>/ become <app>/ — the DEPLOYMENT.md
    convention: unzipping creates ONE clean project directory."""
    home = tmp_path / "home"
    (home / "project" / "kopi-senja").mkdir(parents=True)
    (home / "project" / "AGENTS.md").write_text("manual")  # scaffold
    (home / "project" / "kopi-senja" / "index.html").write_text("<html/>")
    zp = home / "flat.zip"
    with ZipFile(zp, "w") as z:
        z.writestr("index.html", "<html/>")

    sandbox = ExecSandbox(home)
    out = await restructure_flat_archives(sandbox, [fi(str(zp))])
    with ZipFile(home / "flat-structured.zip") as z:
        names = z.namelist()
    assert names == ["kopi-senja/index.html"]


@pytest.mark.asyncio
async def test_non_zip_passthrough(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    sandbox = ExecSandbox(home)
    docs = [fi(str(home / "laporan.md"))]
    out = await restructure_flat_archives(sandbox, docs)
    assert out == docs
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_no_user_home_is_noop(tmp_path: Path) -> None:
    class NoHome:
        pass

    attachments = [fi("/nowhere/project.zip")]
    out = await restructure_flat_archives(NoHome(), attachments)
    assert out == attachments


@pytest.mark.asyncio
async def test_fail_open_on_exec_error(tmp_path: Path) -> None:
    class BrokenSandbox:
        user_home = "/home/runner"

        async def exec_command(self, *a, **kw):
            class R:
                success = False
                data = None
                message = "sandbox exploded"

            return R()

    attachments = [fi("/home/runner/project.zip")]
    out = await restructure_flat_archives(BrokenSandbox(), attachments)
    assert out == attachments  # fail-open: original delivered
