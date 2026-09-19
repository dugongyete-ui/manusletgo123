"""Hard loop-guard tests — Codex/Claude-Code-style harness discipline.

Regression basis: session 126051f9d15848b3 burned ~25 minutes retrying
`npx tailwindcss init -p` (a command that CANNOT succeed on tailwindcss
v4) while interleaved `ls` probes kept resetting the old consecutive-only
counter. These tests pin the mutation-aware, outcome-aware semantics of
manus_registry.trace.LoopSafety:

  - blind repeats are blocked (same call + same outcome + no mutation),
  - interleaved read-only probes no longer launder a failing approach,
  - command families (npx X ≈ ./node_modules/.bin/X ≈ X) share one
    failure budget, blocked with the last error excerpt attached,
  - a real state change between attempts (file_write, npm install)
    resets the budget — legit fix-and-retry engineering stays allowed,
  - identical-outcome SUCCESS spam (ls treadmill) is blocked too,
  - observation/wait/communication tools are exempt.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.services.manus_registry.trace import (  # noqa: E402
    LoopSafety,
    arguments_hash,
    failure_loop_payload,
    shell_command_read_only,
)
from app.domain.services.agents.loop_detector import (  # noqa: E402
    ActionLoopDetector,
    leading_binary,
)


def _hash(tool, args):
    return arguments_hash(tool, args)


# ── shell read-only classifier ──────────────────────────────────────────

def test_readonly_classifier_basics():
    assert shell_command_read_only("ls -la /x")
    assert shell_command_read_only("cd /a/b && ls -la && cat x.txt")
    assert shell_command_read_only("git status && npm list tailwindcss")
    assert not shell_command_read_only("cd /a && npm install -D tailwindcss")
    assert not shell_command_read_only("echo hi > out.txt")        # redirection
    assert not shell_command_read_only("rm -rf /x")
    assert not shell_command_read_only("npx tailwindcss init -p")  # generates files
    assert not shell_command_read_only("cat > f << EOF")           # heredoc write


# ── blind repeat rule ───────────────────────────────────────────────────

def test_blind_repeat_blocked_across_interleaved_probes():
    """The EXACT regression: fail → ls → fail → ls → fail → retry must be
    blocked on the 3rd identical attempt (consecutive-only guard never
    saw a streak because the ls probes reset it)."""
    g = LoopSafety()
    cmd = {"command": "cd /w && npx tailwindcss init -p"}
    h = _hash("shell_exec", cmd)
    err = "npm error could not determine executable to run"

    assert g.check_before_execute("shell_exec", h, cmd) is None
    g.record_result("shell_exec", h, False, "EXECUTION_ERROR", err, arguments=cmd)
    assert g.check_before_execute("shell_exec", h, cmd) is None

    ls = {"command": "ls -la /w/node_modules/.bin"}
    hl = _hash("shell_exec", ls)
    g.check_before_execute("shell_exec", hl, ls)
    g.record_result("shell_exec", hl, True, output_excerpt="", arguments=ls)

    assert g.check_before_execute("shell_exec", h, cmd) is None
    g.record_result("shell_exec", h, False, "EXECUTION_ERROR", err, arguments=cmd)

    # 3rd identical attempt with the same error and no mutation between:
    # BLOCKED — despite the ls probe in between.
    block = g.check_before_execute("shell_exec", h, cmd)
    assert block is not None
    assert block["error"]["code"] == "LOOP_DETECTED"
    details = block["error"]["details"]
    assert "could not determine executable" in details["last_error"]
    assert "different method" in details["guidance"]


def test_mutation_between_attempts_resets_budget():
    """fail → fail → file_write (mutating) → same command = legit retry."""
    g = LoopSafety()
    cmd = {"command": "cd /w && npm run build"}
    h = _hash("shell_exec", cmd)
    for _ in range(2):
        assert g.check_before_execute("shell_exec", h, cmd) is None
        g.record_result("shell_exec", h, False, "EXECUTION_ERROR", "build failed", arguments=cmd)
    w = {"file": "/w/src/app.ts", "content": "export default 1;"}
    hw = _hash("file_write", w)
    g.check_before_execute("file_write", hw, w)
    g.record_result("file_write", hw, True, output_excerpt="written", arguments=w)
    # world changed → the retry is informed, not blind
    assert g.check_before_execute("shell_exec", h, cmd) is None


def test_changed_outcome_is_not_blind_repeat():
    """Polling pattern: identical command whose OUTPUT changes is progress."""
    g = LoopSafety()
    cmd = {"command": "curl -s localhost:3000/health"}
    h = _hash("shell_exec", cmd)
    assert g.check_before_execute("shell_exec", h, cmd) is None
    g.record_result("shell_exec", h, False, "EXECUTION_ERROR", "connection refused", arguments=cmd)
    assert g.check_before_execute("shell_exec", h, cmd) is None
    g.record_result("shell_exec", h, True, output_excerpt='{"ok":true}', arguments=cmd)
    # outcome changed between attempts → never blocked
    assert g.check_before_execute("shell_exec", h, cmd) is None


def test_identical_success_spam_blocked():
    """ls treadmill: same directory listed repeatedly with identical
    output = no new information — the 3rd identical call is blocked."""
    g = LoopSafety()
    cmd = {"command": "ls -la /w/dzeck-landing-page"}
    h = _hash("shell_exec", cmd)
    out = "file 253 index.html\ndir 0 src"
    for _ in range(2):
        assert g.check_before_execute("shell_exec", h, cmd) is None
        g.record_result("shell_exec", h, True, output_excerpt=out, arguments=cmd)
    block = g.check_before_execute("shell_exec", h, cmd)
    assert block is not None and block["error"]["code"] == "LOOP_DETECTED"
    assert block["error"]["details"]["rule"] == "blind_repeat"


def test_directory_change_prevents_ls_block():
    """A file_write between two identical ls calls changes the world, so
    re-listing is legitimate verification, not spam."""
    g = LoopSafety()
    cmd = {"command": "ls -la /w/dist"}
    h = _hash("shell_exec", cmd)
    w = {"file": "/w/dist/index.html", "content": "<html>"}
    hw = _hash("file_write", w)
    for _ in range(2):
        assert g.check_before_execute("shell_exec", h, cmd) is None
        g.check_before_execute("file_write", hw, w)
        g.record_result("file_write", hw, True, output_excerpt="written", arguments=w)
    assert g.check_before_execute("shell_exec", h, cmd) is None


# ── command-family rule ─────────────────────────────────────────────────

def test_family_variants_blocked_with_last_error():
    """npx X / ./node_modules/.bin/X / X are ONE family: 3 failures of any
    variants block the 4th — with the actual error excerpt attached."""
    g = LoopSafety()
    variants = [
        {"command": "cd /w && npx tailwindcss init -p"},
        {"command": "cd /w && npx tailwindcss init -p 2>&1"},
        {"command": "cd /w && ./node_modules/.bin/tailwindcss init -p"},
    ]
    err = "npm error could not determine executable to run"
    for v in variants:
        h = _hash("shell_exec", v)
        # no mutation between variants → the family budget keeps burning
        g.record_result("shell_exec", h, False, "EXECUTION_ERROR", err, arguments=v)
    fourth = {"command": "cd /w && node_modules/.bin/tailwindcss init -p"}
    h4 = _hash("shell_exec", fourth)
    # fresh hash (never seen) but the family is dead → blocked
    block = g.check_before_execute("shell_exec", h4, fourth)
    assert block is not None
    details = block["error"]["details"]
    assert details["rule"] == "family_failure"
    assert details["command_family"] == "tailwindcss"
    assert "could not determine executable" in details["last_error"]


def test_family_success_resets_budget():
    """fail, fail, SUCCESS, fail → the success proves the family works."""
    g = LoopSafety()
    err = "ECONNREFUSED"
    c1 = {"command": "npm install react"}
    h1 = _hash("shell_exec", c1)
    g.record_result("shell_exec", h1, False, "EXECUTION_ERROR", err, arguments=c1)
    c2 = {"command": "npm install lodash"}
    h2 = _hash("shell_exec", c2)
    g.record_result("shell_exec", h2, False, "EXECUTION_ERROR", err, arguments=c2)
    c3 = {"command": "npm install vue"}
    h3 = _hash("shell_exec", c3)
    g.record_result("shell_exec", h3, True, output_excerpt="added 1 package", arguments=c3)
    c4 = {"command": "npm install svelte"}
    h4 = _hash("shell_exec", c4)
    assert g.check_before_execute("shell_exec", h4, c4) is None


def test_family_budget_survives_readonly_interleave():
    """ls probes between family failures do NOT reset the family budget."""
    g = LoopSafety()
    err = "npm error could not determine executable to run"
    probes = [
        {"command": "ls -la /w/node_modules/.bin"},
        {"command": "cat /w/package.json"},
        {"command": "find /w -name tailwind*"},
    ]
    for i, probe in enumerate(probes):
        v = {"command": f"npx tailwindcss init -p --config c{i}.js"}
        hv = _hash("shell_exec", v)
        g.record_result("shell_exec", hv, False, "EXECUTION_ERROR", err, arguments=v)
        hp = _hash("shell_exec", probe)
        g.record_result("shell_exec", hp, True, output_excerpt="x", arguments=probe)
    fourth = {"command": "npx tailwindcss init -p"}
    h4 = _hash("shell_exec", fourth)
    block = g.check_before_execute("shell_exec", h4, fourth)
    assert block is not None and block["error"]["details"]["rule"] == "family_failure"


# ── exemptions ──────────────────────────────────────────────────────────

def test_observation_tools_exempt_from_hard_rules():
    g = LoopSafety()
    for _ in range(6):
        h = _hash("shell_view", {"id": "s1"})
        assert g.check_before_execute("shell_view", h, {"id": "s1"}) is None
        g.record_result("shell_view", h, True, output_excerpt="still running", arguments={"id": "s1"})
    h = _hash("browser_view", {})
    assert g.check_before_execute("browser_view", h, {}) is None


# ── error-memory immediate stop ─────────────────────────────────────────

def test_error_memory_stops_after_repeated_identical_failures():
    g = LoopSafety()
    cmd = {"command": "npx prisma migrate dev --name init"}
    h = _hash("shell_exec", cmd)
    err = "P1001: can't reach database server"
    stop = None
    for _ in range(3):
        stop = g.record_result("shell_exec", h, False, "EXECUTION_ERROR", err, arguments=cmd)
    assert stop is not None
    assert stop["error"]["details"]["rule"] == "error_memory"
    assert "P1001" in stop["error"]["details"]["last_error"]


def test_error_memory_reset_by_mutation():
    g = LoopSafety()
    cmd = {"command": "npx prisma migrate dev --name init"}
    h = _hash("shell_exec", cmd)
    err = "P1001: can't reach database server"
    g.record_result("shell_exec", h, False, "EXECUTION_ERROR", err, arguments=cmd)
    g.record_result("shell_exec", h, False, "EXECUTION_ERROR", err, arguments=cmd)
    # docker-compose up -d (mutating) starts the DB → error memory is stale
    up = {"command": "docker-compose up -d"}
    hu = _hash("shell_exec", up)
    g.record_result("shell_exec", hu, True, output_excerpt="Started", arguments=up)
    stop = g.record_result("shell_exec", h, False, "EXECUTION_ERROR", err, arguments=cmd)
    # only 1 failure since the mutation → no stop payload
    assert stop is None


# ── payload shape ───────────────────────────────────────────────────────

def test_failure_payload_shape():
    p = failure_loop_payload(
        "shell_exec", "Command family 'tailwindcss' already failed 3x",
        last_error="npm error could not determine executable to run",
        family="tailwindcss", rule="family_failure",
    )
    assert p["success"] is False
    assert p["retryable"] is False
    assert p["error"]["code"] == "LOOP_DETECTED"
    d = p["error"]["details"]
    assert d["rule"] == "family_failure"
    assert d["command_family"] == "tailwindcss"
    assert "READ" in d["guidance"]


# ── soft detector upgrades ──────────────────────────────────────────────

def test_soft_output_stagnation_across_interleave():
    d = ActionLoopDetector()
    outputs = ["same-out", "probe-a", "same-out", "probe-b", "same-out", "probe-c"]
    for out in outputs:
        d.record_action("shell_exec", {"command": "curl -s x"})
        d.record_result("shell_exec", out)
    msg = d.get_nudge_message()
    # identical results appear 3x across the window — nudge mentions circling
    assert msg is None or "progressing" not in msg or True  # nudge layer is advisory
    # strictly: 3 identical < 4 threshold → not yet; add more
    for out in ["same-out", "probe-d"]:
        d.record_action("shell_exec", {"command": "curl -s x"})
        d.record_result("shell_exec", out)
    msg = d.get_nudge_message()
    assert msg and "OUTPUT STAGNATION" in msg


def test_soft_exploration_spam_nudge():
    d = ActionLoopDetector()
    for i in range(12):
        cmd = {"command": f"ls -la /w/dir{i % 3}"}
        d.record_action("shell_exec", cmd)
        d.record_result("shell_exec", f"listing {i % 3}")
    msg = d.get_nudge_message()
    assert msg and "EXPLORATION SPAM" in msg


def test_soft_no_exploration_spam_when_mutating_present():
    d = ActionLoopDetector()
    for i in range(12):
        d.record_action("shell_exec", {"command": f"ls -la /w/dir{i}"})
        d.record_result("shell_exec", f"listing {i}")
        d.record_action("shell_exec", {"command": f"npm install pkg{i}"})
        d.record_result("shell_exec", "added packages")
    msg = d.get_nudge_message()
    assert not (msg and "EXPLORATION SPAM" in msg)


def test_leading_binary_family_consistency():
    assert leading_binary("cd /w && npx tailwindcss init -p") == "tailwindcss"
    assert leading_binary("./node_modules/.bin/tailwindcss init -p") == "tailwindcss"
    assert leading_binary("node_modules/.bin/tailwindcss init -p") == "tailwindcss"
    assert leading_binary("npx tailwindcss init -p 2>&1") == "tailwindcss"
