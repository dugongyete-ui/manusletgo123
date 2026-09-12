import type { FileInfo } from '../api/file';

export type AgentSSEEvent = {
  event: 'tool' | 'step' | 'message' | 'message_chunk' | 'error' | 'done' | 'title' | 'wait' | 'plan' | 'attachments' | 'validation' | 'knowledge';
  data: ToolEventData | StepEventData | MessageEventData | MessageChunkEventData | ErrorEventData | DoneEventData | TitleEventData | WaitEventData | PlanEventData | ValidationEventData | KnowledgeEventData;
}

export interface BaseEventData {
  event_id: string;
  timestamp: number;
}

export interface ToolEventData extends BaseEventData {
  tool_call_id: string;
  name: string;
  status: "calling" | "called";
  function: string;
  args: {[key: string]: any};
  content?: any;
  /** Official Manus natural-language action label. */
  brief?: string;
}

export interface StepEventData extends BaseEventData {
  status: "pending" | "running" | "completed" | "failed"
  id: string
  description: string
  /** Present when the step finished with a concrete outcome. */
  result?: string
}

export interface MessageEventData extends BaseEventData {
  content: string;
  role: "user" | "assistant";
  attachments: FileInfo[];
  /** true = compact progress narration belonging to the step timeline */
  is_progress?: boolean;
  /** true = the task's final summary message (single delivery point for files) */
  is_final?: boolean;
  /** true = agent question that pauses the task and needs a user answer */
  is_question?: boolean;
}

export interface MessageChunkEventData extends BaseEventData {
  content: string;
  role: "user" | "assistant";
  done: boolean;
}

export interface ErrorEventData extends BaseEventData {
  error: string;
}

export interface DoneEventData extends BaseEventData {
}

export interface WaitEventData extends BaseEventData {
}

export interface TitleEventData extends BaseEventData {
  title: string;
}

export interface PlanEventData extends BaseEventData {
  steps: StepEventData[];
}

// ── Final validation gate (P0) ────────────────────────────────────────────
export type CheckState = 'pass' | 'fail' | 'warn' | 'skipped';

export interface ValidationCheck {
  key: string;
  state: CheckState;
  detail: string;
}

export interface EvidenceEntry {
  id: string;
  summary: string;
  url: string;
  requested_url?: string;
  title: string;
  site_name?: string;
  published_date?: string | null;
  quote?: string;
  verified: boolean;
  source: 'search' | 'browser';
  redirected?: boolean;
}

export interface ExecutionSummaryData {
  started_at?: string | null;
  finished_at?: string | null;
  duration_seconds?: number | null;
  total_steps: number;
  steps_completed: number;
  steps_failed: number;
  tool_calls_total: number;
  tool_calls_succeeded: number;
  tool_calls_failed: number;
  files_created: number;
  files_updated: number;
  evidence_count: number;
  warnings: number;
  errors: number;
}

export interface ValidationResultData {
  overall: 'pass' | 'needs_review';
  checks: ValidationCheck[];
  unresolved_errors: number;
  warnings: number;
  summary: ExecutionSummaryData;
  evidence: EvidenceEntry[];
}

export interface ValidationEventData extends BaseEventData {
  result: ValidationResultData;
}
export interface KnowledgeEventData extends BaseEventData {
  /** Proposed learnings (display text). */
  items: string[];
  /** Knowledge item ids aligned with items by index (accept/reject API). */
  item_ids?: string[];
  status: 'pending';
}
