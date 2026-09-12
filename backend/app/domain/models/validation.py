"""Domain models for the final validation gate and evidence register.

Design contract (honesty first):
- A check may report PASS only when it was mechanically verified from real
  execution data (plan steps, tool results, sandbox file contents).
- Anything that cannot be verified mechanically is reported as WARN with an
  explicit "requires review" detail — never as PASS.
- Every count in the execution summary is derived from the executor's actual
  memory; nothing is estimated or fabricated.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
from enum import Enum
import uuid


class CheckState(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    # Used for categories that cannot be verified mechanically at all
    # (e.g. calculation consistency) — surfaced so a human can review them.
    SKIPPED = "skipped"


class ValidationCheck(BaseModel):
    """One line of the VALIDATION RESULT block."""
    key: str  # required_stages | required_files | file_integrity | ...
    state: CheckState
    detail: str  # human-readable, derived from real data


class EvidenceType(str, Enum):
    FACT = "fact"
    ESTIMATE = "estimate"
    ASSUMPTION = "assumption"
    INTERPRETATION = "interpretation"
    RECOMMENDATION = "recommendation"


class EvidenceConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class EvidenceEntry(BaseModel):
    """One source collected during the task (search result or browser visit).

    Metadata is captured from what the tools ACTUALLY returned — fields the
    source did not provide stay empty/None and the entry is marked
    verified=False rather than being filled with guesses.
    """
    id: str = Field(default_factory=lambda: f"EV-{uuid.uuid4().hex[:8].upper()}")
    summary: str = ""          # title / claim as returned by the source
    url: str = ""              # actual URL that was opened / result link
    requested_url: str = ""    # for browser visits: the URL the agent asked for
    title: str = ""
    site_name: str = ""        # host, derived from the URL
    published_date: Optional[str] = None
    accessed_date: Optional[datetime] = None
    quote: str = ""            # snippet / supporting text, when available
    type: EvidenceType = EvidenceType.FACT
    confidence: EvidenceConfidence = EvidenceConfidence.UNKNOWN
    verified: bool = False
    source: Literal["search", "browser"] = "search"
    # True when the browser ended up on a different domain than requested.
    redirected: bool = False


class ExecutionSummaryData(BaseModel):
    """Aggregated facts about the task run (P1 execution summary)."""
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    total_steps: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    tool_calls_total: int = 0
    tool_calls_succeeded: int = 0
    tool_calls_failed: int = 0
    files_created: int = 0
    files_updated: int = 0
    evidence_count: int = 0
    warnings: int = 0
    errors: int = 0


class ValidationResult(BaseModel):
    """Complete result of the final validation gate."""
    overall: Literal["pass", "needs_review"] = "needs_review"
    checks: List[ValidationCheck] = Field(default_factory=list)
    unresolved_errors: int = 0
    warnings: int = 0
    summary: ExecutionSummaryData = Field(default_factory=ExecutionSummaryData)
    evidence: List[EvidenceEntry] = Field(default_factory=list)

    def state_for(self, key: str) -> Optional[CheckState]:
        for c in self.checks:
            if c.key == key:
                return c.state
        return None
