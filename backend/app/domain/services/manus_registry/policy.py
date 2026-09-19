"""Confirmation policy gate for consequential tool actions.

Registry tools carrying policy.requires_confirmation=true are NOT executed
until the user explicitly approves. The gate:

1. Returns a structured REQUIRES_CONFIRMATION payload (tool never runs)
   describing tool, full arguments, impact and data involved.
2. Records a pending confirmation keyed by (tool, args_hash).
3. Grants approval when the model relays the user's explicit approval via
   ``message_ask_user`` (the platform's existing pause-and-resume UX) and
   the user's answer arrives — the resumed run re-issues the call and the
   ledger approves it.

Ordinary reversible actions (navigate, fill draft, create checkpoint…)
stay confirmation-free per registry policy.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from app.domain.services.manus_registry.errors import (
    REQUIRES_CONFIRMATION,
    redact_secrets,
)
from app.domain.services.manus_registry.trace import arguments_hash

logger = logging.getLogger(__name__)

# Human-facing impact descriptions per known consequential tool.
_IMPACT = {
    "webdev_execute_sql": (
        "Menjalankan SQL langsung pada database project — bisa mengubah atau "
        "menghapus data permanen."
    ),
    "webdev_rollback_checkpoint": (
        "Mengembalikan state project ke checkpoint sebelumnya — perubahan "
        "setelah checkpoint akan hilang."
    ),
    "webdev_request_secrets": (
        "Meminta nilai secret/token dari pemilik project untuk ditulis ke "
        "environment runtime."
    ),
    "manus-config": "Mengubah konfigurasi sesi/agent yang tersimpan.",
    "manus-heartbeat": "Mengirim sinyal heartbeat ke layanan eksternal.",
    "manus-channel": "Mengirim pesan ke channel antar-agent.",
}


def confirmation_description(tool_name: str, arguments: Dict[str, Any]) -> str:
    base = _IMPACT.get(tool_name) or (
        "Tool ini menandai aksi berisiko yang butuh persetujuan eksplisit."
    )
    return base


def requires_confirmation(tool_def: Dict[str, Any]) -> bool:
    """Whether the registry policy demands confirmation for this tool."""
    policy = tool_def.get("policy") or {}
    return bool(policy.get("requires_confirmation"))


class ConfirmationLedger:
    """Per-run ledger of pending + approved confirmations."""

    def __init__(self) -> None:
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._approved: Set[str] = set()

    def pending_payload(
        self, tool_name: str, tool_def: Dict[str, Any], arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build the REQUIRES_CONFIRMATION failure payload + register pending."""
        h = arguments_hash(tool_name, arguments)
        self._pending[h] = {
            "tool": tool_name,
            "arguments": arguments,
        }
        return {
            "success": False,
            "tool": tool_name,
            "data": None,
            "error": {
                "code": REQUIRES_CONFIRMATION,
                "message": (
                    f"{tool_name} butuh persetujuan user sebelum dijalankan. "
                    f"Tanyakan ke user via message_ask_user dengan "
                    f"confirmation_id '{h}' dan tunggu jawaban eksplisit "
                    f"sebelum memanggil ulang tool ini."
                ),
                "details": {
                    "confirmation_id": h,
                    "tool": tool_name,
                    "arguments": redact_secrets(arguments),
                    "impact": confirmation_description(tool_name, arguments),
                    "data_involved": redact_secrets(
                        _data_involved(tool_name, arguments)
                    ),
                    "guidance": (
                        "JANGAN eksekusi ulang sebelum user menyetujui. "
                        "Setelah user setuju, panggil ulang tool dengan "
                        "argumen yang sama persis."
                    ),
                },
            },
            "retryable": False,
        }

    def register_user_reply(self, user_reply: str) -> Optional[str]:
        """Mark pending confirmations approved when the user's answer is
        affirmative. Returns the confirmation_id approved (if any)."""
        if not user_reply:
            return None
        norm = user_reply.strip().lower()
        approved_id: Optional[str] = None
        for h in list(self._pending.keys()):
            if h in norm or _is_affirmative(norm):
                approved_id = h
            if approved_id:
                self._approved.add(h)
                self._pending.pop(h, None)
                logger.info("confirmation %s approved by user reply", approved_id)
                break
        return approved_id

    # Legacy alias
    register_user_approval = register_user_reply

    def is_approved(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        h = arguments_hash(tool_name, arguments)
        if h in self._approved:
            # one-shot approval: consume it
            self._approved.discard(h)
            return True
        return False

    def reset(self) -> None:
        self._pending.clear()
        self._approved.clear()


_AFFIRMATIVE = {
    "ya", "yes", "y", "ok", "oke", "setuju", "approved", "approve",
    "lanjut", "lanjutkan", "go", "gas", "confirm", "confirmed", "1",
    "silakan", "boleh",
}


def _is_affirmative(norm_reply: str) -> bool:
    return any(
        word in norm_reply.split() or word == norm_reply
        for word in _AFFIRMATIVE
    )


def _data_involved(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """Which data the action would touch (for the confirmation dialog)."""
    if tool_name == "webdev_execute_sql":
        return {"query": arguments.get("query", "")}
    if tool_name == "webdev_request_secrets":
        return {"secrets": arguments.get("secret_names") or arguments.get("names")}
    if tool_name == "manus-channel":
        return {"target": arguments.get("argv", [])}
    return {"arguments": arguments}
