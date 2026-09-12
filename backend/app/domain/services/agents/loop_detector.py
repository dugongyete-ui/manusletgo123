"""Action-loop detection for the execution agent.

Ported (and generalised) from browser-use's ``ActionLoopDetector``
(browser_use/agent/views.py): the agent's adaptive loop needs to NOTICE
when it is repeating itself before it burns its whole iteration budget.

Design mirrors browser-use:
  * ``record_action``    — rolling window of action hashes; identical or
                           near-identical calls (same tool + same args)
                           pile up the repetition counter.
  * ``record_result``    — consecutive identical tool RESULTS mean the
                           actions are not changing the world (stagnation).
  * ``get_nudge_message``— escalating awareness messages at 3 / 6 / 9
                           repetitions (soft: never blocks the model,
                           just adds context so it can self-correct).

Two deliberate deviations from upstream, fitting our architecture:
  1. Observation / communication tools (browser_view, wait_*, message_*)
     are exempt from hashing — they legitimately repeat every round, which
     upstream handles by only hashing its own exempt list.
  2. The detector is tool-agnostic: shell_exec retry loops are as deadly
     as browser_click retry loops, so both are tracked.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Optional

# Tools that naturally repeat without signalling a stuck loop:
# pure observation, waiting, and user-communication helpers.
EXEMPT_TOOLS: frozenset = frozenset({
    "browser_view",
    "browser_console_view",
    "browser_list_tabs",
    "browser_wait_for_element",
    "browser_wait_for_network_idle",
    "browser_get_select_options",
    "browser_verify_value",
    "message_notify_user",
    "message_ask_user",
})

# Shell tools whose commands get coarse-keyed (leading binary).
_SHELL_TOOLS: frozenset = frozenset({"shell_exec", "shell_command"})

# Leading tokens that only wrap the real command.
_WRAPPER_BINARIES: frozenset = frozenset({
    "sudo", "npx", "nohup", "timeout", "exec", "command",
})

_CD_CHAIN = re.compile(r"^(?:cd\s+[\"\']?[^&\s]+[\"\']?\s*&&\s*)+", re.IGNORECASE)


def leading_binary(command: str) -> str:
    """First real binary of a shell command — cd-chains and wrappers stripped.

    Collapses the trial-and-error spiral where the model retries the same
    failing tool with syntactic variations (session 1303b902a2d54516: 30+
    variants of prisma commands, each string distinct so exact-hash loop
    detection never fired):

        'cd /a/b && npx prisma migrate dev --name init'  -> 'prisma'
        './node_modules/.bin/prisma migrate dev'          -> 'prisma'
        'sudo systemctl restart nginx'                    -> 'systemctl'
        'ls -la prisma/'                                  -> 'ls'
    """
    if not command:
        return ""
    cmd = _CD_CHAIN.sub("", " ".join(str(command).split()))
    for tok in cmd.split():
        base = tok.removeprefix("./").rsplit("/", 1)[-1]
        for suffix in (".js", ".cjs", ".mjs"):
            base = base.removesuffix(suffix)
        if not base or base in ("&&", "||", ";", "|", ">>", ">"):
            continue
        if base in _WRAPPER_BINARIES:
            continue
        return base
    return ""


def _normalize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Drop noisy fields so semantically-identical calls hash identically."""
    cleaned: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        if key == "brief":  # user-facing label, irrelevant to behaviour
            continue
        if isinstance(value, str):
            value = " ".join(value.split())  # collapse whitespace noise
        cleaned[key] = value
    return cleaned


def compute_action_hash(tool_name: str, params: Dict[str, Any]) -> str:
    """Stable short hash for a tool call (name + normalised arguments)."""
    normalized = json.dumps(
        {tool_name: _normalize_params(params)},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


class ActionLoopDetector:
    """Tracks action repetition and result stagnation inside one step run.

    Soft detection only — it produces context messages for the LLM but never
    blocks anything (same philosophy as browser-use).
    """

    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        self.recent_action_hashes: list[str] = []
        self.recent_command_keys: list[str] = []
        self.consecutive_identical_results: int = 0
        self._last_result_hash: Optional[str] = None
        # Cache of counts so get_nudge_message() is pure.
        self._recompute()

    # ── recording ──────────────────────────────────────────────────────

    def record_action(self, tool_name: str, params: Dict[str, Any]) -> None:
        """Record one executed tool call and refresh repetition stats."""
        if tool_name in EXEMPT_TOOLS:
            return
        self.recent_action_hashes.append(compute_action_hash(tool_name, params))
        if len(self.recent_action_hashes) > self.window_size:
            self.recent_action_hashes = self.recent_action_hashes[-self.window_size:]
        # Coarse key for shell commands: variants of the same leading
        # binary (npx X / ./node_modules/.bin/X / X --other-flags) collapse
        # to one family so a syntactic-variation retry spiral is still seen.
        if tool_name in _SHELL_TOOLS:
            raw = str((params or {}).get("command") or (params or {}).get("cmd") or "")
            key = leading_binary(raw)
            if key:
                self.recent_command_keys.append(key)
                if len(self.recent_command_keys) > self.window_size:
                    self.recent_command_keys = self.recent_command_keys[-self.window_size:]
        self._recompute()

    def record_result(self, tool_name: str, result_content: Any) -> None:
        """Record the outcome signature of one tool call (stagnation check).

        Only meaningful for non-exempt tools: identical consecutive results
        mean the repeated action is having no observable effect.
        """
        if tool_name in EXEMPT_TOOLS:
            return
        digest = hashlib.sha256(
            str(result_content)[:2000].encode("utf-8", "replace")
        ).hexdigest()[:12]
        if digest == self._last_result_hash:
            self.consecutive_identical_results += 1
        else:
            self.consecutive_identical_results = 0
            self._last_result_hash = digest

    def _recompute(self) -> None:
        counts: Dict[str, int] = {}
        for h in self.recent_action_hashes:
            counts[h] = counts.get(h, 0) + 1
        if counts:
            self.most_repeated_hash = max(counts, key=lambda k: counts[k])
            self.max_repetition_count = counts[self.most_repeated_hash]
        else:
            self.most_repeated_hash = None
            self.max_repetition_count = 0
        key_counts: Dict[str, int] = {}
        for k in self.recent_command_keys:
            key_counts[k] = key_counts.get(k, 0) + 1
        if key_counts:
            self.focus_binary = max(key_counts, key=lambda k: key_counts[k])
            self.max_command_focus = key_counts[self.focus_binary]
        else:
            self.focus_binary = None
            self.max_command_focus = 0

    # ── nudges ─────────────────────────────────────────────────────────

    @property
    def repetition_count(self) -> int:
        return self.max_repetition_count

    def get_nudge_message(self) -> Optional[str]:
        """Escalating awareness nudge, or None when behaviour looks healthy.

        Thresholds 3 / 6 / 9 (tightened from upstream 5 / 8 / 12): end users
        watch the tool timeline live, and three identical actions already
        READ as a stuck loop in the chat — self-correction must start
        before the user loses patience, not after the budget is half gone.
        """
        messages: list[str] = []

        if self.max_repetition_count >= 9:
            messages.append(
                f"LOOP ALERT: you have repeated a near-identical action "
                f"{self.max_repetition_count} times in the last "
                f"{len(self.recent_action_hashes)} actions. This is almost "
                "certainly not working. Stop retrying it. Either (a) try a "
                "fundamentally different tool or approach, or (b) conclude "
                "this step now and report honestly what worked, what failed, "
                "and what you learned."
            )
        elif self.max_repetition_count >= 6:
            messages.append(
                f"LOOP WARNING: you have repeated a near-identical action "
                f"{self.max_repetition_count} times in the last "
                f"{len(self.recent_action_hashes)} actions. Retrying the same "
                "arguments rarely fixes anything. Change strategy: re-observe "
                "the current state (browser_view for pages, shell_view for "
                "command output), pick a different element, tool, or method "
                "entirely."
            )
        elif self.max_repetition_count >= 3:
            messages.append(
                f"NOTE: you have repeated a similar action "
                f"{self.max_repetition_count} times in the last "
                f"{len(self.recent_action_hashes)} actions. If each attempt "
                "is genuinely making progress, continue. Otherwise "
                "reconsider your approach now, before wasting more of the "
                "action budget."
            )

        if self.consecutive_identical_results >= 2:
            messages.append(
                f"The last {self.consecutive_identical_results + 1} actions "
                "returned byte-identical results — your actions appear to "
                "have no effect on the page. The element you are acting on "
                "is probably not the right one (stale index, wrong frame, or "
                "a widget that needs different events). Re-observe and "
                "choose differently."
            )

        # Coarse command-family focus: syntactic variants of the same
        # failing binary (the prisma-style spiral) never trip the exact
        # hash counter — this catches them anyway.
        if self.max_command_focus >= 10:
            messages.append(
                f"COMMAND-FOCUS ALERT: {self.max_command_focus} of your "
                f"last {len(self.recent_command_keys)} shell commands are "
                f"variations around '{self.focus_binary}'. The command "
                "family itself is failing in this environment — more flag "
                "or path variants will NOT fix it. Circuit breaker: stop "
                "retrying; re-read the skill's prescribed approach, switch "
                "method, or conclude and report the blocker honestly."
            )
        elif self.max_command_focus >= 6:
            messages.append(
                f"COMMAND-FOCUS WARNING: {self.max_command_focus} of your "
                f"last {len(self.recent_command_keys)} shell commands are "
                f"variations around '{self.focus_binary}' with the step "
                "goal still unmet. If the tool itself is failing here (no "
                "server, missing daemon, wrong stack for this sandbox), no "
                "variant of the command will fix it — check the skill's "
                "prescribed approach or report the blocker."
            )

        if messages:
            return "\n\n".join(messages)
        return None
