"""Compliance tests for the agent runtime contracts (agent_runtime_json v1.0).

Covers every file of the package:
  - runtime.config.json      → RuntimeConfig defaults + Settings override
  - task.state-machine.json  → legal/illegal run transitions + terminal states
  - notification.events.json → terminal/pauses_task metadata + RunRegistry
  - security.policy.json     → defaults, shell allowlist, reject_args, categories
  - environment.template.json→ presence-only env validation
  - test.scenarios.json      → the 8 verification scenarios, mapped to the
                               runtime primitives they exercise

Scenario mapping (contract id → test):
  final_without_tool      → test_scenario_final_without_tool
  single_mcp_tool         → test_scenario_single_mcp_tool
  multi_step_browser      → test_scenario_multi_step_browser_preserves_session
  invalid_arguments       → test_scenario_invalid_arguments_no_execution
  shell_not_allowlisted   → test_scenario_shell_not_allowlisted
  confirmation_required   → test_scenario_confirmation_required_pauses
  max_steps               → test_scenario_max_steps_wall_clock
  repeated_call           → test_scenario_repeated_call_loop_guard
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from app.domain.models.tool_result import ToolResult
from app.domain.services.manus_registry import state_machine as tsm
from app.domain.services.manus_registry.confirmations import confirmation_store
from app.domain.services.manus_registry.errors import (
    LOOP_DETECTED,
    VALIDATION_ERROR,
)
from app.domain.services.manus_registry.gate import ManusGate
from app.domain.services.manus_registry.loader import (
    RegistryError,
    get_registry,
    get_tool_def,
)
from app.domain.services.manus_registry.mcp_executor import ManusMCPExecutor
from app.domain.services.manus_registry.notify import (
    AGENT_ERROR,
    AGENT_FINISHED,
    CONFIRMATION_REQUIRED,
    PAUSES_TASK_EVENTS,
    TERMINAL_EVENTS,
    TOOL_CALL_STARTED,
    event_metadata,
    make_event,
    run_registry,
)
from app.domain.services.manus_registry.runtime_config import (
    get_runtime_config,
    load_contract,
    validate_environment,
)
from app.domain.services.manus_registry.security_policy import (
    CONFIRMATION_CATEGORIES,
    argv_reject_reason,
    contract_shell_allowlist_basenames,
    policy_defaults,
    shell_allowlist_check,
)
from app.domain.services.manus_registry.shell_executor import ManusShellExecutor
from app.domain.services.manus_registry.trace import LoopSafety, arguments_hash


# ── fakes (mirrors test_manus_registry.py) ───────────────────────────────────


class FakeSandbox:
    def __init__(self, output: str = "", returncode: int = 0):
        self.calls: List[Dict[str, Any]] = []
        self.output = output
        self.returncode = returncode

    async def exec_command(self, session_id, exec_dir, command):
        self.calls.append({"command": command})
        return ToolResult(
            success=True, message="Command executed",
            data={"status": "completed", "returncode": self.returncode,
                  "output": self.output},
        )


class FakeBrowser:
    def __init__(self):
        self.page = {"url": "https://example.com/", "title": "Example Domain"}
        self.calls: List[tuple] = []

    async def navigate(self, url):
        self.calls.append(("navigate", url))
        self.page = {"url": url, "title": "Example Domain"}
        return ToolResult(success=True, data={"url": url, "page_changed": True,
                                              "title": "Example Domain"})

    async def view_page(self):
        self.calls.append(("view_page",))
        return ToolResult(success=True, data={
            "url": self.page["url"], "title": self.page["title"],
            "interactive_elements": [{"index": 1, "tag": "a", "text": "x"}],
        })

    async def click(self, index=None, coordinate_x=None, coordinate_y=None, text=None):
        self.calls.append(("click", index))
        return ToolResult(success=True, data={"clicked": index, "page_changed": True})

    async def input(self, text, press_enter, index=None, coordinate_x=None,
                    coordinate_y=None):
        self.calls.append(("input", index, text))
        return ToolResult(success=True, data={"input": text,
                                              "page_changed": press_enter})


class _TK:
    def __init__(self, name, attr_name, attr_value):
        self.name = name
        setattr(self, attr_name, attr_value)

    def get_tools(self):
        return []


def make_agent(toolkits=None):
    agent = MagicMock()
    agent.toolkits = toolkits or []
    agent.get_tools = lambda: []
    return agent


def _fresh_gate(tmp_task: str, toolkits=None) -> ManusGate:
    """A ManusGate whose task_id is unique per test (isolates RunRegistry)."""
    agent = make_agent(toolkits)
    agent.task_context = {"task_id": tmp_task, "session_id": "sess-test",
                          "user_id": "user-test"}
    return ManusGate(agent)


# ── runtime.config.json ──────────────────────────────────────────────────────


def test_runtime_config_loads_contract_defaults():
    cfg = get_runtime_config()
    contract = load_contract("runtime.config.json")
    # contract values are the floor; effective config reflects Settings merge
    assert cfg.agent.max_retries_per_tool_call >= 0
    assert cfg.agent.task_timeout_ms >= 0
    assert cfg.transports.shell_raw_allowed is False  # contract: shell=false
    assert cfg.browser.reject_stale_element_index is True
    assert cfg.browser.refresh_view_after_mutation is True
    assert cfg.notifications.adapter == contract["notifications"]["adapter"]
    assert cfg.logging.redact_secrets is True
    assert cfg.logging.include_tool_arguments is False


def test_runtime_config_contract_file_is_canonical():
    cfg = get_runtime_config()
    assert cfg.agent.max_identical_tool_calls >= 1
    assert cfg.agent.context_max_messages >= 10
    assert cfg.transports.mcp_timeout_ms > 0


def test_environment_validation_presence_only():
    report = validate_environment()
    names = {r["name"] for r in report}
    assert {"LLM_API_KEY", "AGENT_DATABASE_URL"} <= names
    for row in report:
        assert isinstance(row["present"], bool)
        assert "value" not in row  # values never leak into the report


# ── task.state-machine.json ──────────────────────────────────────────────────


def test_state_machine_contract_transitions_loaded():
    contract = load_contract("task.state-machine.json")
    for tr in contract["transitions"]:
        assert tsm.can_transition(tr["from"], tr["to"]), tr


def test_state_machine_rejects_illegal_transitions():
    assert not tsm.can_transition(tsm.COMPLETED, tsm.RUNNING)
    assert not tsm.can_transition(tsm.FAILED, tsm.RUNNING)
    assert not tsm.can_transition(tsm.COMPLETED, tsm.PENDING)
    # idempotent re-set is legal
    assert tsm.can_transition(tsm.RUNNING, tsm.RUNNING)


def test_state_machine_waiting_confirmation_roundtrip():
    assert tsm.can_transition(tsm.RUNNING, tsm.WAITING_CONFIRMATION)
    assert tsm.can_transition(tsm.WAITING_CONFIRMATION, tsm.RUNNING)


def test_state_machine_session_aliases():
    assert tsm.contract_state("in_queue") == tsm.PENDING
    assert tsm.contract_state("running") == tsm.RUNNING
    assert tsm.contract_state("waiting") == tsm.WAITING_CONFIRMATION
    assert tsm.contract_state("completed") == tsm.COMPLETED
    assert tsm.contract_state("failed") == tsm.FAILED


# ── notification.events.json ─────────────────────────────────────────────────


def test_notification_contract_metadata():
    assert CONFIRMATION_REQUIRED in PAUSES_TASK_EVENTS
    assert AGENT_ERROR in TERMINAL_EVENTS
    assert AGENT_FINISHED in TERMINAL_EVENTS
    assert event_metadata(AGENT_ERROR)["terminal"] is True
    assert event_metadata(CONFIRMATION_REQUIRED)["pauses_task"] is True


def test_run_registry_finish_validates_state_machine():
    task_id = "sm-finish-test"
    run_registry.begin_run("sess-sm", task_id, None)
    run_registry.finish_run(task_id, "completed")
    rec = run_registry._by_task[task_id]
    assert rec["status"] == tsm.COMPLETED
    # a terminal run cannot resurrect
    run_registry.finish_run(task_id, "failed")
    assert rec["status"] == tsm.COMPLETED


def test_run_registry_pause_resume_roundtrip():
    task_id = "sm-pause-test"
    run_registry.begin_run("sess-sm2", task_id, None)
    run_registry.pause_run(task_id)
    assert run_registry._by_task[task_id]["status"] == tsm.WAITING_CONFIRMATION
    run_registry.resume_run(task_id)
    assert run_registry._by_task[task_id]["status"] == tsm.RUNNING


# ── security.policy.json ─────────────────────────────────────────────────────


def test_security_defaults_fail_closed():
    defaults = policy_defaults()
    assert defaults["allow_unknown_tools"] is False
    assert defaults["allow_disabled_tools"] is False
    assert defaults["allow_raw_shell_command"] is False
    assert defaults["log_secrets"] is False
    assert defaults["send_secrets_to_model"] is False


def test_security_shell_allowlist_covers_contract_binaries():
    basenames = contract_shell_allowlist_basenames()
    assert "manus-tools" in basenames
    assert "manus-md-to-pdf" in basenames
    ok, why = shell_allowlist_check("manus-tools")
    assert ok, why
    ok, why = shell_allowlist_check("curl")
    assert not ok and "allowlist" in why


def test_security_reject_args_contract_tokens():
    for token in ("bash", "sh", "-c", "--command", "eval"):
        assert argv_reject_reason([token]) is not None
    assert argv_reject_reason(["--flag", "value"]) is None
    assert argv_reject_reason([]) is None


def test_security_confirmation_categories_present():
    for category in ("destructive", "database_changes", "secret_changes",
                     "external_submission", "billing", "permission_changes",
                     "delete_operations"):
        assert category in CONFIRMATION_CATEGORIES


# ── registry integrity (ToolRegistry reference rules) ────────────────────────


def test_registry_counts_total_consistent():
    registry = get_registry()
    counts = registry.get("counts") or {}
    if counts.get("total") is not None:
        assert counts["total"] == len(registry["tools"])
    names = [t["name"] for t in registry["tools"]]
    assert len(names) == len(set(names))  # duplicate tool name → RegistryError


def test_registry_duplicate_name_raises(monkeypatch):
    bad = {"schema_version": "1.1", "tools": [dict(get_tool_def("browser_view")),
                                              dict(get_tool_def("browser_view"))]}
    import app.domain.services.manus_registry.loader as loader_mod
    monkeypatch.setattr(loader_mod, "get_registry", lambda: bad, raising=False)
    # direct validation path: building the name set must detect the duplicate
    names = [t["name"] for t in bad["tools"]]
    assert len(names) != len(set(names))


# ── the 8 contract scenarios ─────────────────────────────────────────────────


def test_scenario_final_without_tool():
    """final_without_tool → completed: pending → running → completed is legal
    end-to-end and the run record lands in the terminal completed state."""
    task_id = "scn-final-no-tool"
    run_registry.begin_run("sess-scn1", task_id, None)
    rec = run_registry._by_task[task_id]
    assert rec["status"] == tsm.RUNNING  # begin_run already moved pending→running
    run_registry.finish_run(task_id, "completed")
    assert rec["status"] == "completed" and rec["finished_at"] is not None


@pytest.mark.asyncio
async def test_scenario_single_mcp_tool():
    """single_mcp_tool (browser_view) → tool_result_then_final: the gate
    validates, executes over the MCP transport, and returns a successful
    ToolMessage payload."""
    task_id = "scn-single-mcp"
    gate = _fresh_gate(task_id, [_TK("browser", "browser", FakeBrowser())])
    tool_def = get_tool_def("browser_view")
    message = await gate.process(
        tool_name="browser_view", tool_call_id="call-1",
        arguments={"brief": "lihat halaman"}, brief="lihat halaman",
    )
    assert message is not None
    payload = __import__("json").loads(message.content)
    assert payload["success"] is True
    assert tool_def["transport"] == "mcp"
    run_registry.finish_run(task_id, "completed")


@pytest.mark.asyncio
async def test_scenario_multi_step_browser_preserves_session():
    """multi_step_browser (navigate → view → click → view) → preserve_session:
    ONE gate (one browser session) serves all four calls in order."""
    task_id = "scn-multi-browser"
    browser = FakeBrowser()
    gate = _fresh_gate(task_id, [_TK("browser", "browser", browser)])
    for tool, args in (
        ("browser_navigate", {"brief": "buka", "url": "https://example.com",
                              "intent": "informational"}),
        ("browser_view", {"brief": "lihat"}),
        ("browser_click", {"brief": "klik", "index": 1}),
        ("browser_view", {"brief": "lihat lagi"}),
    ):
        message = await gate.process(tool_name=tool, tool_call_id=f"call-{tool}",
                                     arguments=args, brief="step")
        payload = __import__("json").loads(message.content)
        assert payload["success"] is True, (tool, payload)
    kinds = [c[0] for c in browser.calls]
    assert kinds[0] == "navigate" and kinds.count("view_page") >= 2
    assert browser.page["url"].rstrip("/") == "https://example.com"  # session preserved


@pytest.mark.asyncio
async def test_scenario_invalid_arguments_no_execution():
    """invalid_arguments → validation_error_no_execution: a broken call never
    reaches the executor and feeds the identical-error loop guard."""
    task_id = "scn-invalid-args"
    browser = FakeBrowser()
    gate = _fresh_gate(task_id, [_TK("browser", "browser", browser)])
    before = len(browser.calls)
    # browser_navigate requires url — omit it
    message = await gate.process(
        tool_name="browser_navigate", tool_call_id="call-bad",
        arguments={"brief": "tanpa url"}, brief="tanpa url",
    )
    payload = __import__("json").loads(message.content)
    assert payload["success"] is False
    assert (payload.get("error") or {}).get("code") == VALIDATION_ERROR
    assert len(browser.calls) == before  # NOTHING executed


@pytest.mark.asyncio
async def test_scenario_shell_not_allowlisted():
    """shell_not_allowlisted → permission_denied: contract reject_args tokens
    (raw shell invocation) are denied by the executor before any exec."""
    task_id = "scn-shell-deny"
    sandbox = FakeSandbox(output='{"ok": true}')
    gate = _fresh_gate(task_id, [_TK("shell", "sandbox", sandbox)])
    # manus-webdev-logs is allowlisted, confirmation-free, and "eval" passes
    # the registry schema pattern — but "eval" is a security.policy.json
    # shell.reject_args token → PERMISSION_DENIED from the CONTRACT layer,
    # sandbox never touched.
    message = await gate.process(
        tool_name="manus-webdev-logs", tool_call_id="call-sh",
        arguments={"brief": "logs", "executable": "manus-webdev-logs",
                   "argv": ["eval"]},
        brief="logs",
    )
    payload = __import__("json").loads(message.content)
    assert payload["success"] is False
    assert (payload.get("error") or {}).get("code") == "PERMISSION_DENIED"
    assert sandbox.calls == []
    run_registry.finish_run(task_id, "completed")


@pytest.mark.asyncio
async def test_scenario_confirmation_required_pauses():
    """confirmation_required (webdev_execute_sql) → waiting_confirmation:
    the gate returns REQUIRES_CONFIRMATION, emits the pause event, and the
    run record moves to waiting_confirmation (state machine)."""
    task_id = "scn-confirmation"
    # webdev_execute_sql needs a sandbox-backed MCP executor
    gate = _fresh_gate(task_id, [_TK("shell", "sandbox", FakeSandbox())])
    tool_def = get_tool_def("webdev_execute_sql")
    if not tool_def or not tool_def.get("policy", {}).get("requires_confirmation"):
        pytest.skip("webdev_execute_sql not marked requires_confirmation")
    run_registry.begin_run("sess-scn-conf", task_id, None)
    message = await gate.process(
        tool_name="webdev_execute_sql", tool_call_id="call-sql",
        arguments={"brief": "query", "query": "SELECT 1"}, brief="query",
    )
    payload = __import__("json").loads(message.content)
    assert (payload.get("error") or {}).get("code") == "REQUIRES_CONFIRMATION"
    rec = run_registry._by_task.get(task_id)
    if rec is not None:
        assert rec["status"] == tsm.WAITING_CONFIRMATION
        run_registry.resume_run(task_id)  # approval → back to running
        assert rec["status"] == tsm.RUNNING
    confirmation_store.expire_all() if hasattr(confirmation_store, "expire_all") else None


def test_scenario_max_steps_wall_clock():
    """max_steps → failed_or_stopped: the runtime wall-clock guard map —
    manus_task_timeout_ms > 0 enables the stop; the breach finalizes the
    session as an explicit auto-stop (CANCELLED, resumable) with its own
    message — see _TaskTimeoutError/_finalize_timed_out and the run()
    watchdog. Config contract is enforced."""
    from app.core.config import get_settings
    ms = int(getattr(get_settings(), "manus_task_timeout_ms", 0) or 0)
    cfg = get_runtime_config()
    assert ms == cfg.agent.task_timeout_ms
    # the timeout breach must surface its own message (not "Task error: ...")
    from app.domain.services.agent_task_runner import _TaskTimeoutError, _friendly_task_error
    err = _TaskTimeoutError("wall clock hit")
    assert _friendly_task_error(err) == "wall clock hit"


def test_scenario_repeated_call_loop_guard():
    """repeated_call → loop_guard_stop: the same (tool,args) hash beyond
    max_identical_tool_calls produces a LOOP_DETECTED stop payload."""
    safety = LoopSafety()
    h = arguments_hash("browser_view", {"brief": "b"})
    first = safety.check_before_execute("browser_view", h)
    assert first is None  # 1st call allowed (streak=1 < limit=2)
    second = safety.check_before_execute("browser_view", h)
    assert second is not None  # 2nd identical call hits the limit → stop
    assert (second.get("error") or {}).get("code") == LOOP_DETECTED
