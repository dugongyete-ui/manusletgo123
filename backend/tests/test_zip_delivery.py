"""Unit tests for the ZIP-only delivery safety net
(`ExecutionAgent._drop_zip_member_attachments`):

When a .zip is among the final deliverables, the individual files already
bundled inside the archive must be dropped — the user receives ONLY the zip.
Non-member files (research summary .md, unrelated documents) are kept.
"""

from types import SimpleNamespace

import pytest

from app.domain.models.file import FileInfo
from app.domain.services.agents.execution import ExecutionAgent
from app.domain.services.tools.file import FileToolkit


class _FakeSandbox:
    """Sandbox stub returning canned zip member listings per archive path."""

    def __init__(self, listings: dict):
        self._listings = listings
        self.calls = []

    async def exec_command(self, session_id, exec_dir, command):
        self.calls.append((session_id, command))
        for path, output in self._listings.items():
            # The inspected archive path is embedded in the python script.
            if path in command:
                return SimpleNamespace(
                    success=True,
                    data={"output": output, "returncode": 0},
                )
        return SimpleNamespace(success=False, data=None)


def make_executor(listings: dict):
    agent = ExecutionAgent.__new__(ExecutionAgent)
    agent.toolkits = [FileToolkit(_FakeSandbox(listings))]
    return agent


def fi(path: str) -> FileInfo:
    return FileInfo(file_path=path)


@pytest.mark.asyncio
async def test_zip_members_dropped_zip_kept():
    """Full-path match: files listed next to their zip are dropped."""
    listings = {
        "/home/runner/website.zip": "site/index.html\nsite/style.css\nsite/app.js",
    }
    agent = make_executor(listings)
    attachments = [
        fi("/home/runner/website.zip"),
        fi("/home/runner/site/index.html"),
        fi("/home/runner/site/style.css"),
        fi("/home/runner/site/app.js"),
    ]
    kept = await agent._drop_zip_member_attachments(attachments)
    paths = [a.file_path for a in kept]
    assert paths == ["/home/runner/website.zip"]


@pytest.mark.asyncio
async def test_basename_match_dropped_summary_md_kept():
    """Basename match under the zip dir (zip made from inside the project
    dir) drops the bundled files — but the research summary .md created by
    the system is NOT a member and must be kept."""
    listings = {
        "/home/runner/project.zip": "index.html\nstyle.css",
    }
    agent = make_executor(listings)
    attachments = [
        fi("/home/runner/project.zip"),
        fi("/home/runner/project/index.html"),
        fi("/home/runner/project/style.css"),
        fi("/home/runner/summary_riset.md"),
    ]
    kept = await agent._drop_zip_member_attachments(attachments)
    paths = [a.file_path for a in kept]
    assert "/home/runner/project.zip" in paths
    assert "/home/runner/summary_riset.md" in paths
    assert "/home/runner/project/index.html" not in paths
    assert "/home/runner/project/style.css" not in paths


@pytest.mark.asyncio
async def test_no_zip_returns_unchanged():
    """Without a zip deliverable nothing is inspected, nothing is dropped."""
    agent = make_executor({})
    attachments = [fi("/home/runner/a.html"), fi("/home/runner/b.css")]
    kept = await agent._drop_zip_member_attachments(attachments)
    assert kept == attachments


@pytest.mark.asyncio
async def test_inspection_failure_returns_unchanged():
    """If the sandbox cannot read the zip, deliver everything (safe
    fallback) rather than blocking the final message."""
    agent = make_executor({})  # no listing → success=False
    attachments = [
        fi("/home/runner/website.zip"),
        fi("/home/runner/site/index.html"),
    ]
    kept = await agent._drop_zip_member_attachments(attachments)
    assert len(kept) == 2


@pytest.mark.asyncio
async def test_second_zip_kept():
    """Another archive is never treated as a member of the first zip."""
    listings = {
        "/home/runner/site.zip": "index.html",
        "/home/runner/data.zip": "data.csv",
    }
    agent = make_executor(listings)
    attachments = [
        fi("/home/runner/site.zip"),
        fi("/home/runner/data.zip"),
        fi("/home/runner/index.html"),
    ]
    kept = await agent._drop_zip_member_attachments(attachments)
    paths = [a.file_path for a in kept]
    assert paths == ["/home/runner/site.zip", "/home/runner/data.zip"]


@pytest.mark.asyncio
async def test_corrupt_zip_listing_ignored():
    """A zip the sandbox cannot open (ZIP_ERR in output) contributes no
    members — its siblings stay."""
    listings = {
        "/home/runner/broken.zip": "ZIP_ERR:File is not a zip file",
    }
    agent = make_executor(listings)
    attachments = [
        fi("/home/runner/broken.zip"),
        fi("/home/runner/notes.txt"),
    ]
    kept = await agent._drop_zip_member_attachments(attachments)
    assert len(kept) == 2
