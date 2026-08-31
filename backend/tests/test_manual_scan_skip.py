"""Unit tests for the artifact-scan manual-subtree skip
(`AgentTaskRunner._scan_user_home_files`):

The scaffolded workspace operating manual ({home}/project/ with AGENTS.md
+ skills/) is platform scaffolding — it must NEVER be scanned, synced, or
delivered as task artifacts. A genuine build folder named "project"
(without the AGENTS.md+skills markers) is still scanned normally.
"""

from types import SimpleNamespace

import pytest

from app.domain.services.agent_task_runner import AgentTaskRunner


def _entry(name: str, is_dir: bool, size: int = 0):
    return SimpleNamespace(name=name, type="dir" if is_dir else "file", size=size)


class _FakeSandbox:
    """Serves canned directory listings per path (dict/attr entry shapes)."""

    def __init__(self, listings: dict):
        self.user_home = "/home/runner"
        self._listings = listings

    async def file_list(self, path: str):
        entries = self._listings.get(path)
        if entries is None:
            return SimpleNamespace(success=False, data=None)
        dict_entries = [
            {"name": e.name, "type": e.type, "size": e.size} for e in entries
        ]
        return SimpleNamespace(success=True, data={"entries": dict_entries})


def _runner(listings: dict) -> AgentTaskRunner:
    runner = AgentTaskRunner.__new__(AgentTaskRunner)
    runner._sandbox = _FakeSandbox(listings)
    return runner


@pytest.mark.asyncio
async def test_manual_subtree_skipped():
    listings = {
        "/home/runner": [
            _entry("project", True),
            _entry("upload", True),
            _entry("my-app", True),
            _entry("laporan.md", False, 1200),
        ],
        "/home/runner/project": [
            _entry("AGENTS.md", False, 3000),
            _entry("skills", True),
            _entry("SOUL.md", False, 800),
        ],
        "/home/runner/project/skills": [
            _entry("web-app", True),
        ],
        "/home/runner/my-app": [
            _entry("index.html", False, 500),
        ],
    }
    found = await _runner(listings)._scan_user_home_files()
    assert "/home/runner/laporan.md" in found
    assert "/home/runner/my-app/index.html" in found
    assert not any(p.startswith("/home/runner/project") for p in found)


@pytest.mark.asyncio
async def test_genuine_project_dir_still_scanned():
    """A build folder legitimately named "project" (no manual markers)
    still delivers its files."""
    listings = {
        "/home/runner": [
            _entry("project", True),
        ],
        "/home/runner/project": [
            _entry("index.html", False, 500),
            _entry("app.js", False, 300),
        ],
    }
    found = await _runner(listings)._scan_user_home_files()
    assert "/home/runner/project/index.html" in found
    assert "/home/runner/project/app.js" in found


@pytest.mark.asyncio
async def test_junk_dirs_still_skipped():
    listings = {
        "/home/runner": [
            _entry("node_modules", True),
            _entry("app", True),
        ],
        "/home/runner/node_modules": [
            _entry("left-pad", True),
        ],
        "/home/runner/app": [
            _entry("main.py", False, 100),
        ],
    }
    found = await _runner(listings)._scan_user_home_files()
    assert found == {"/home/runner/app/main.py": 100}
