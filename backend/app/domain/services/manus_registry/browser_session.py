"""Browser Session Manager (agent architecture contract v1.0).

Contract: agent_architecture_json/browser-session-manager/contract.json

Role: mempertahankan browser target, page, tab, dan state antar tool call.

State schema (contract):
    {task_id, target: sandbox|my_browser, session_id?, active_url?,
     last_view_hash?}

Rules enforced / observed here (light-touch — heavy rules live in the
browser toolkits and prompts):
  - reuse same session within task      → session_id pinned per run
  - refresh view after navigation       → mutations invalidate view hash
  - never trust stale element indexes   → every mutation clears the hash
  - do not log cookies or credentials   → URLs pass redact_secrets()
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Optional

from app.domain.services.manus_registry.errors import redact_secrets

logger = logging.getLogger(__name__)

# Browser mutations that make the last view (element indexes, screenshot)
# stale — the next browser_view MUST re-capture before further interaction.
_MUTATING_TOOLS = {
    "browser_navigate", "browser_click", "browser_input",
    "browser_fill_form", "browser_select_option", "browser_press_key",
    "browser_scroll", "browser_upload_file", "browser_tab_new",
    "browser_tab_select", "browser_go_back", "browser_go_forward",
}
_VIEW_TOOLS = {"browser_view", "browser_screenshot"}


def _hash_view(content: Any) -> Optional[str]:
    if content is None:
        return None
    if not isinstance(content, str):
        import json as _json
        try:
            content = _json.dumps(content, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            content = str(content)
    if not content:
        return None
    return hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()[:16]


def _safe_url(url: Any) -> Optional[str]:
    """Credential-safe URL for state/trace storage.

    Query strings are dropped entirely — URLs routinely carry tokens,
    session ids and one-time codes (?token=…, ?auth=…), and the contract
    forbids logging cookies or credentials. scheme+host+path is enough to
    reason about "where is the browser now".
    """
    if not isinstance(url, str) or not url:
        return None
    clean = url.split("?", 1)[0].split("#", 1)[0]
    return redact_secrets(clean)


class BrowserSessionTracker:
    """Per-run browser state observer fed by the gate after each tool call."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.target: str = "sandbox"
        self.session_id: Optional[str] = None
        self.active_url: Optional[str] = None
        self.last_view_hash: Optional[str] = None
        self.updated_at: float = 0.0

    def observe(
        self, tool_name: str, arguments: Dict[str, Any], payload: Dict[str, Any]
    ) -> None:
        """Update the tracked state from one finished browser_* tool call."""
        if not tool_name.startswith("browser_"):
            return
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        args = arguments or {}

        if self.session_id is None and isinstance(args.get("session_id"), str):
            self.session_id = args["session_id"]

        # active_url: prefer the result's final URL, fall back to the
        # navigate target. Redacted — URLs can embed tokens.
        url = data.get("url") or data.get("final_url") or (
            args.get("url") if tool_name == "browser_navigate" else None
        )
        if isinstance(url, str) and url:
            self.active_url = _safe_url(url)

        if tool_name in _VIEW_TOOLS:
            view = (
                data.get("screenshot")
                or data.get("content")
                or data.get("view")
            )
            h = _hash_view(view)
            if h:
                self.last_view_hash = h
        elif tool_name in _MUTATING_TOOLS:
            # Fresh page state — stale element indexes must not be reused.
            self.last_view_hash = None
            if tool_name == "browser_tab_new" and isinstance(args.get("url"), str):
                self.active_url = _safe_url(args["url"])

        self.updated_at = __import__("time").time()

    def snapshot(self) -> Dict[str, Any]:
        """Contract state_schema snapshot (safe for events / trace / API)."""
        return {
            "task_id": self.task_id,
            "target": self.target,
            "session_id": self.session_id,
            "active_url": self.active_url,
            "last_view_hash": self.last_view_hash,
        }
