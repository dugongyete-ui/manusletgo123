"""Unit tests for the provider-conditional system prompt.

The agent must be told the truth about the sandbox it actually runs in:
  - "replit" → Ubuntu 24.04, user ``runner``, /home/runner/users/{id},
    /home/runner/workspace prohibitions, Python 3.12, bc
  - "e2b"    → Debian 12 microVM, user ``user``, /home/user, no app source
    code inside, Python 3.11, NO bc (python3 for arithmetic), VNC live view

A mismatched prompt (e.g. Ubuntu paths inside a Debian E2B VM) makes the
agent emit commands and file paths that cannot work.
"""

from app.domain.services.prompts.system import get_system_prompt


REPLIT_HOME = "/home/runner/users/u123"
REPLIT_UPLOAD = "/home/runner/users/u123/upload"
E2B_HOME = "/home/user"
E2B_UPLOAD = "/home/user/upload"


def test_replit_prompt_describes_replit_environment():
    prompt = get_system_prompt(user_home=REPLIT_HOME, upload_dir=REPLIT_UPLOAD)
    assert "Ubuntu 24.04" in prompt
    assert "`runner`" in prompt
    assert "Python 3.12" in prompt
    assert "Basic calculator (command: bc)" in prompt
    assert "Xvfb virtual display with Chrome browser and VNC server" in prompt
    assert REPLIT_HOME in prompt
    assert REPLIT_UPLOAD in prompt


def test_replit_prompt_keeps_workspace_prohibitions():
    prompt = get_system_prompt(user_home=REPLIT_HOME, upload_dir=REPLIT_UPLOAD)
    # The shared Replit container really contains the app source code — the
    # strict /home/runner/workspace prohibitions must stay in the prompt.
    assert "/home/runner/workspace" in prompt
    assert "ABSOLUTE PROHIBITIONS" in prompt


def test_e2b_prompt_describes_e2b_environment():
    prompt = get_system_prompt(
        user_home=E2B_HOME, upload_dir=E2B_UPLOAD, environment="e2b"
    )
    assert "Debian GNU/Linux 12" in prompt
    assert "`user`" in prompt
    assert "Python 3.11" in prompt
    assert "Node.js 20" in prompt
    assert "Git 2.39" in prompt
    assert "bc is not installed" in prompt
    # VNC live view now works on E2B (Xvfb + x11vnc + websockify stack)
    assert "VNC server" in prompt
    assert E2B_HOME in prompt
    assert E2B_UPLOAD in prompt


def test_e2b_prompt_never_mentions_replit_paths():
    prompt = get_system_prompt(
        user_home=E2B_HOME, upload_dir=E2B_UPLOAD, environment="e2b"
    )
    # The E2B microVM has no /home/runner at all and no app source code.
    assert "/home/runner" not in prompt
    assert "Ubuntu" not in prompt
    assert "Python 3.12" not in prompt


def test_both_prompts_render_placeholders_fully():
    for env, home, upload in (
        ("replit", REPLIT_HOME, REPLIT_UPLOAD),
        ("e2b", E2B_HOME, E2B_UPLOAD),
    ):
        prompt = get_system_prompt(
            user_home=home, upload_dir=upload, environment=env
        )
        assert "{security_rules}" not in prompt
        assert "{sandbox_environment}" not in prompt
        assert "{user_home}" not in prompt
        assert "{upload_dir}" not in prompt
        # Shared backbone stays identical in both environments
        assert "You are Dzeck" in prompt
        assert "<system_capability>" in prompt
        assert "<important_notes>" in prompt


def test_default_environment_is_replit():
    # Backwards compatibility: existing callers without `environment` keep
    # getting the Replit prompt.
    prompt = get_system_prompt()
    assert "Ubuntu 24.04" in prompt
    assert "/home/runner/workspace" in prompt


def test_unknown_environment_falls_back_to_replit():
    prompt = get_system_prompt(environment="something-else")
    assert "Ubuntu 24.04" in prompt


def test_sandbox_provider_attributes():
    """All sandbox implementations expose a `provider` attribute so
    PlanActFlow can pick the matching prompt."""
    from app.infrastructure.external.sandbox.e2b_sandbox import E2BSandbox
    from app.infrastructure.external.sandbox.replit_sandbox import ReplitSandbox

    assert E2BSandbox.provider == "e2b"
    assert ReplitSandbox.provider == "replit"
    assert E2BSandbox.shared is False
    assert ReplitSandbox.shared is True


def test_user_scoped_sandbox_passes_provider_through():
    """UserScopedSandbox (Replit fallback wrapper) forwards the provider."""
    from app.infrastructure.external.sandbox.user_sandbox import UserScopedSandbox

    class _Inner:
        provider = "replit"
        vnc_url = ""

    wrapper = UserScopedSandbox.__new__(UserScopedSandbox)
    wrapper._inner = _Inner()
    assert wrapper.provider == "replit"

    class _InnerNoAttr:
        vnc_url = ""

    wrapper2 = UserScopedSandbox.__new__(UserScopedSandbox)
    wrapper2._inner = _InnerNoAttr()
    # Missing attribute degrades gracefully to "replit"
    assert wrapper2.provider == "replit"
