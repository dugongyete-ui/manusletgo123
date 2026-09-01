"""Unit tests for the frontend dist self-healing guard.

The guard exists because a reprovision restored an old frontend/dist while
the source stayed new — production silently regressed to the pre-fix chat
UI. These tests pin the freshness logic itself (pure filesystem checks).
"""

import os
import shutil
import time
from pathlib import Path

import pytest

from app.infrastructure.build_guard import (
    dist_is_stale,
    newest_source_mtime,
    ensure_fresh_frontend,
    rebuild_frontend,
)


@pytest.fixture()
def fake_frontend(tmp_path: Path) -> Path:
    """A minimal frontend tree: src/ + package.json + dist/index.html."""
    fe = tmp_path / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "dist").mkdir(parents=True)
    (fe / "package.json").write_text("{}")
    (fe / "src" / "App.vue").write_text("<template>ok</template>")
    (fe / "dist" / "index.html").write_text("<!doctype html><html></html>")
    return fe


def _touch(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


def test_missing_dist_is_stale(fake_frontend: Path) -> None:
    shutil.rmtree(fake_frontend / "dist")  # no dist at all
    assert dist_is_stale(fake_frontend) is True


def test_fresh_dist_is_not_stale(fake_frontend: Path) -> None:
    now = time.time()
    _touch(fake_frontend / "src" / "App.vue", now - 10)
    _touch(fake_frontend / "package.json", now - 10)
    _touch(fake_frontend / "dist" / "index.html", now)  # built after sources
    assert dist_is_stale(fake_frontend) is False


def test_stale_dist_is_detected(fake_frontend: Path) -> None:
    """THE production incident: dist built BEFORE the newest source file."""
    now = time.time()
    _touch(fake_frontend / "src" / "App.vue", now - 10)
    _touch(fake_frontend / "dist" / "index.html", now - 3600)  # 1h old build
    assert dist_is_stale(fake_frontend) is True


def test_tolerance_avoids_jitter_false_positive(fake_frontend: Path) -> None:
    now = time.time()
    _touch(fake_frontend / "src" / "App.vue", now)
    _touch(fake_frontend / "dist" / "index.html", now - 1)  # 1s skew is fine
    assert dist_is_stale(fake_frontend) is False


def test_node_modules_excluded_from_newest_mtime(fake_frontend: Path) -> None:
    now = time.time()
    _touch(fake_frontend / "src" / "App.vue", now - 100)
    _touch(fake_frontend / "package.json", now - 100)
    node_dir = fake_frontend / "node_modules" / "vite"
    node_dir.mkdir(parents=True)
    pkg = node_dir / "package.json"
    pkg.write_text("{}")
    _touch(pkg, now)  # node_modules touched NOW — must not count
    assert newest_source_mtime(fake_frontend) == pytest.approx(now - 100, abs=5)
    assert dist_is_stale(fake_frontend) is False


def test_no_sources_means_not_stale(fake_frontend: Path) -> None:
    shutil.rmtree(fake_frontend / "src")
    ancient = time.time() - 9999
    _touch(fake_frontend / "package.json", ancient)
    _touch(fake_frontend / "dist" / "index.html", ancient)
    assert dist_is_stale(fake_frontend) is False


def test_ensure_fresh_noop_when_fresh(fake_frontend: Path, monkeypatch) -> None:
    now = time.time()
    _touch(fake_frontend / "src" / "App.vue", now - 10)
    _touch(fake_frontend / "dist" / "index.html", now)
    called = []
    monkeypatch.setattr(
        "app.infrastructure.build_guard.rebuild_frontend",
        lambda fe, timeout=600: called.append(fe) or True,
    )
    assert ensure_fresh_frontend(fake_frontend) is False
    assert called == []  # nothing started


def test_ensure_fresh_spawns_rebuild_when_stale(fake_frontend: Path, monkeypatch) -> None:
    now = time.time()
    _touch(fake_frontend / "src" / "App.vue", now)
    _touch(fake_frontend / "dist" / "index.html", now - 3600)
    started = []
    monkeypatch.setattr(
        "app.infrastructure.build_guard.rebuild_frontend",
        lambda fe, timeout=600: started.append(str(fe)) or True,
    )
    assert ensure_fresh_frontend(fake_frontend) is True
    # the worker thread runs rebuild_frontend asynchronously
    deadline = time.time() + 5
    while not started and time.time() < deadline:
        time.sleep(0.05)
    assert started == [str(fake_frontend)]


def test_rebuild_failure_is_fail_open(fake_frontend: Path, monkeypatch, caplog) -> None:
    """A failed build must return False and NEVER raise."""
    import subprocess

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="vite exploded")

    monkeypatch.setattr(subprocess, "run", fake_run)
    (fake_frontend / "dist" / "index.html").unlink()
    assert rebuild_frontend(fake_frontend) is False
    # dist/index.html still absent but the call returned cleanly
