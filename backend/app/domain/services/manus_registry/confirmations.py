"""Confirmation Manager (agent architecture contract v1.0).

Contract: agent_architecture_json/confirmation-manager/contract.json

Role: menghentikan eksekusi sensitif sampai user menyetujui.

Contract rules implemented here:
  - issue a random confirmation token (secrets.token_urlsafe)
  - expire tokens (TTL, lazily enforced + purge)
  - bind token to (task_id, tool, arguments_hash)
  - never execute before approval (the gate checks this store)
  - resume the same task after approval — the store is GLOBAL and
    session-scoped, so approval survives the ask_user pause AND the
    model-mediated message_ask_user flow (register_user_reply)

Decision enum (contract): approved | rejected | expired.

Two approval channels feed the same store:
  1. In-band  : the user replies in chat → BaseAgent calls
                ConfirmationLedger.register_user_reply (policy.py)
  2. Out-band : POST /sessions/{id}/confirmations/{token} {decision}
"""
from __future__ import annotations

import logging
import secrets
import time
from typing import Any, Dict, Optional

from app.domain.services.manus_registry.errors import redact_secrets
from app.domain.services.manus_registry.trace import arguments_hash

logger = logging.getLogger(__name__)

APPROVED = "approved"
REJECTED = "rejected"
EXPIRED = "expired"
PENDING = "pending"

MAX_STORE = 200


class GlobalConfirmationStore:
    """Process-wide store of pending/decided confirmations.

    Keyed by random token; queryable by (task_id, tool, args_hash) so the
    gate can honour an approval issued on a PREVIOUS run of the same task
    (contract: "resume same task after approval").
    """

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}

    # ── issue ────────────────────────────────────────────────────────────
    def issue(
        self,
        task_id: str,
        tool: str,
        arguments: Dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Register (or reuse) a pending confirmation. Idempotent per
        (task_id, tool, args_hash): re-asking returns the SAME token."""
        from app.core.config import get_settings
        ttl = int(
            ttl_seconds
            if ttl_seconds is not None
            else getattr(get_settings(), "manus_confirmation_ttl_seconds", 600)
        )
        h = arguments_hash(tool, arguments)
        existing = self._find(task_id, tool, h)
        if existing and existing["status"] == PENDING:
            return self._public(existing)
        token = secrets.token_urlsafe(16)
        rec = {
            "token": token,
            "task_id": task_id,
            "tool": tool,
            "args_hash": h,
            "arguments": redact_secrets(arguments),
            "status": PENDING,
            "created_at": time.time(),
            "expires_at": time.time() + max(30, ttl),
            "decided_at": None,
        }
        self._records[token] = rec
        self._purge()
        logger.info(
            "confirmation issued task=%s tool=%s token=%s ttl=%ss",
            task_id, tool, token[:6], ttl,
        )
        return self._public(rec)

    # ── decide (API / in-band) ───────────────────────────────────────────
    def decide(self, token: str, decision: str) -> Dict[str, Any]:
        """Apply an explicit user decision to a pending confirmation."""
        rec = self._records.get(token)
        if rec is None:
            return {"ok": False, "status": "not_found"}
        if rec["status"] == PENDING and time.time() > rec["expires_at"]:
            rec["status"] = EXPIRED
        if rec["status"] != PENDING:
            return {"ok": False, "status": rec["status"]}
        if decision not in (APPROVED, REJECTED):
            return {"ok": False, "status": "invalid_decision"}
        rec["status"] = decision
        rec["decided_at"] = time.time()
        logger.info(
            "confirmation %s -> %s (task=%s tool=%s)",
            rec["token"][:6], decision, rec["task_id"], rec["tool"],
        )
        return {"ok": True, "status": decision, "tool": rec["tool"]}

    def approve_hash(self, task_id: str, tool: str, args_hash: str) -> None:
        """In-band approval: mark (task, tool, hash) approved — creates the
        record if the pending entry was issued on an earlier process."""
        rec = self._find(task_id, tool, args_hash)
        if rec is None:
            rec = {
                "token": secrets.token_urlsafe(16),
                "task_id": task_id,
                "tool": tool,
                "args_hash": args_hash,
                "arguments": {},
                "status": APPROVED,
                "created_at": time.time(),
                "expires_at": time.time() + 3600,
                "decided_at": time.time(),
            }
            self._records[rec["token"]] = rec
        elif rec["status"] == PENDING:
            rec["status"] = APPROVED
            rec["decided_at"] = time.time()

    def reject_hash(self, task_id: str, tool: str, args_hash: str) -> None:
        rec = self._find(task_id, tool, args_hash)
        if rec and rec["status"] == PENDING:
            rec["status"] = REJECTED
            rec["decided_at"] = time.time()

    # ── gate queries ─────────────────────────────────────────────────────
    def status_for(self, task_id: str, tool: str, args_hash: str) -> str:
        """Contract decision status for a (task, tool, hash) — PENDING when
        nothing was ever issued (caller decides whether to ask)."""
        rec = self._find(task_id, tool, args_hash)
        if rec is None:
            return PENDING
        if rec["status"] == PENDING and time.time() > rec["expires_at"]:
            rec["status"] = EXPIRED
        return rec["status"]

    def is_approved(self, task_id: str, tool: str, args_hash: str) -> bool:
        return self.status_for(task_id, tool, args_hash) == APPROVED

    def is_rejected(self, task_id: str, tool: str, args_hash: str) -> bool:
        return self.status_for(task_id, tool, args_hash) == REJECTED

    # ── internals ────────────────────────────────────────────────────────
    def _find(self, task_id: str, tool: str, args_hash: str) -> Optional[Dict[str, Any]]:
        for rec in self._records.values():
            if (
                rec["task_id"] == task_id
                and rec["tool"] == tool
                and rec["args_hash"] == args_hash
            ):
                if rec["status"] == PENDING and time.time() > rec["expires_at"]:
                    rec["status"] = EXPIRED
                return rec
        return None

    def _purge(self) -> None:
        now = time.time()
        for token in list(self._records.keys()):
            rec = self._records[token]
            if rec["status"] == PENDING and now > rec["expires_at"]:
                rec["status"] = EXPIRED
            if rec["status"] in (REJECTED, EXPIRED) and (
                now - (rec["decided_at"] or rec["created_at"]) > 3600
            ):
                self._records.pop(token, None)
        while len(self._records) > MAX_STORE:
            self._records.pop(next(iter(self._records)), None)

    @staticmethod
    def _public(rec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "confirmation_token": rec["token"],
            "tool": rec["tool"],
            "task_id": rec["task_id"],
            "expires_at": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(rec["expires_at"]))
            ),
            "arguments_preview": rec["arguments"],
        }


# Module-level singleton (survives across runs within the process).
confirmation_store = GlobalConfirmationStore()
