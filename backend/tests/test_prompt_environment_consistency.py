"""Prompt ↔ environment consistency (No-hardcode audit).

The agent runs on whichever sandbox provider actually serves the session —
E2B microVM (user `user`, home /home/user) or the shared Replit container
(user `runner`, home /home/runner[/users/<id>]). The sandbox can SWITCH at
runtime (E2B quota exhausted → HybridSandboxFactory falls back to Replit),
so no prompt that reaches the model may carry a provider-specific absolute
path: it must either use a {user_home} placeholder resolved from the live
sandbox, or phrase paths relative to the home described in
<sandbox_environment>.

Regression guard for the de-hardcoding pass:
  - prompts/execution.py and prompts/planner.py must contain no literal
    /home/runner or /home/user paths.
  - EXECUTION_PROMPT / SUMMARIZE_PROMPT render correctly with any home.
  - The E2B system prompt stays free of /home/runner (provider test covers
    the full prompt; here we also check the awareness block exists).
"""

import inspect
from pathlib import Path

from app.domain.services.prompts.execution import (
    EXECUTION_PROMPT,
    SUMMARIZE_PROMPT,
)
from app.domain.services.prompts.system import get_system_prompt

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "app/domain/services/prompts"


def test_prompt_sources_have_no_provider_paths():
    """No hard-coded provider home may appear in execution/planner prompts."""
    for name in ("execution.py", "planner.py"):
        src = (PROMPTS_DIR / name).read_text()
        assert "/home/runner" not in src, f"{name} hard-codes /home/runner"
        assert "/home/user" not in src, f"{name} hard-codes /home/user"


def test_execution_prompt_formats_with_any_home():
    """EXECUTION_PROMPT renders for E2B and Replit homes alike."""
    e2b = EXECUTION_PROMPT.format(
        step="s", message="m", attachments="", language="id",
        user_home="/home/user",
    )
    assert "/home/user/report.pdf" in e2b
    assert "{user_home}" not in e2b

    replit = EXECUTION_PROMPT.format(
        step="s", message="m", attachments="", language="id",
        user_home="/home/runner/users/u1",
    )
    assert "/home/runner/users/u1/report.pdf" in replit


def test_summarize_prompt_formats_with_any_home():
    """SUMMARIZE_PROMPT resolves the summary path for the live sandbox."""
    e2b = SUMMARIZE_PROMPT.format(user_home="/home/user")
    assert "/home/user/summary_" in e2b
    assert "/home/user/summary_persib_bandung.md" in e2b
    assert "{user_home}" not in e2b

    replit = SUMMARIZE_PROMPT.format(user_home="/home/runner/users/u1")
    assert "/home/runner/users/u1/summary_" in replit
    assert "/home/runner" not in e2b


def test_summarize_prompt_keeps_json_examples_renderable():
    """After .format() the JSON examples must be valid-looking JSON braces
    (the template escapes them as {{...}} — formatting must collapse them)."""
    rendered = SUMMARIZE_PROMPT.format(user_home="/home/user")
    assert "{{" not in rendered and "}}" not in rendered
    assert '"attachments": [' in rendered


def test_system_prompt_has_environment_awareness_block():
    """The system prompt tells the agent to verify reality instead of
    trusting the (possibly drifted / switched) environment description."""
    for env in ("replit", "e2b"):
        prompt = get_system_prompt(
            user_home="/x", upload_dir="/x/upload", environment=env
        )
        assert "<environment_awareness>" in prompt
        assert "whoami && echo $HOME && pwd" in prompt


def test_e2b_system_prompt_still_free_of_replit_paths():
    prompt = get_system_prompt(
        user_home="/home/user", upload_dir="/home/user/upload", environment="e2b"
    )
    assert "/home/runner" not in prompt
    assert "/home/user/summary_" not in prompt  # summary path lives in the
    # runtime summarize prompt, not the static system prompt.
