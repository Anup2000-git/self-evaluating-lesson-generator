// TypeScript mirrors of the backend's Pydantic contracts (libs/common/src/lessongen_common/schemas).

export type SectionKind = "hook" | "what" | "why" | "how" | "example" | "misconceptions" | "summary";

export interface Section {
  kind: SectionKind;
  heading: string;
  body_markdown: string;
}

export interface GlossaryEntry {
  term: string;
  simple_meaning: string;
  helper_meaning: string;
}

export interface QuizQuestion {
  question: string;
  options: string[];
  correct_option_index: number;
  explanation: string;
}

export interface Lesson {
  title: string;
  learning_objectives: string[];
  sections: Section[];
  glossary: GlossaryEntry[];
  quiz: QuizQuestion[];
}

export interface PlannedSection {
  kind: SectionKind;
  heading: string;
  key_points: string[];
  terms_to_define: string[];
}

export interface LessonPlan {
  title: string;
  learning_objectives: string[];
  analogy: string;
  worked_example: string;
  sections: PlannedSection[];
  glossary_terms: string[];
  quiz_focus: string[];
}

export interface ModelUsage {
  llm_calls: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cost_usd: number;
}

export interface Usage extends ModelUsage {
  by_model: Record<string, ModelUsage>;
}

export type Verdict = "PASS" | "FAIL";
export type Dimension = "accuracy" | "language" | "examples" | "jargon" | "coverage" | "flow";
export type CheckMethod = "deterministic" | "llm_judge" | "fact_check" | "learner";
export type Severity = "critical" | "major";

export interface JudgeVote {
  model: string;
  verdict: Verdict;
  reasoning: string;
}

export interface CheckResult {
  check_id: string;
  dimension: Dimension;
  title: string;
  method: CheckMethod;
  severity: Severity;
  verdict: Verdict;
  reasoning: string;
  evidence: string[];
  fix_instruction: string;
  details: Record<string, unknown>;
  evidence_verified: boolean | null;
  votes: JudgeVote[];
  latency_ms: number;
}

export interface EvaluationReport {
  rubric_version: number;
  passed: boolean;
  results: CheckResult[];
  failed_check_ids: string[];
  error_check_ids: string[];
  summary: string;
  usage: Usage;
  duration_ms: number;
}

export interface RevisionNote {
  check_id: string;
  change: string;
}

export interface SectionDiff {
  kind: string;
  heading: string;
  change: "added" | "removed" | "modified" | "unchanged";
  words_before: number;
  words_after: number;
}

export type AttemptKind = "initial" | "patch" | "rewrite" | "provided";

export interface AttemptRecord {
  attempt_no: number;
  kind: AttemptKind;
  lesson: Lesson;
  evaluation: EvaluationReport;
  revision_notes: RevisionNote[];
  diff: SectionDiff[];
  strategy_reason: string;
  generation_usage: Usage;
  created_at: string;
}

export type RunMode = "generate" | "evaluate_only" | "repair";
export type RunStatus =
  | "queued"
  | "running"
  | "shipped"
  | "needs_human_review"
  | "evaluated"
  | "failed"
  | "cancelled";

export const TERMINAL_STATUSES: RunStatus[] = [
  "shipped",
  "needs_human_review",
  "evaluated",
  "failed",
  "cancelled",
];

export interface RunRecord {
  id: string;
  topic: string;
  topic_id: string | null;
  mode: RunMode;
  status: RunStatus;
  status_reason: string | null;
  max_retries: number;
  helper_language: string;
  attempts_count: number;
  final_attempt_no: number | null;
  rubric_version: number | null;
  guideline_ids_applied: string[];
  plan: LessonPlan | null;
  usage: Usage;
  fault_id: string | null;
  source_run_id: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunDetail extends RunRecord {
  attempts: AttemptRecord[];
  /** Link to the run's Langfuse trace; null when tracing is off. */
  trace_url?: string | null;
}

export interface RunList {
  items: RunRecord[];
  total: number;
}

export interface RunRequest {
  topic: string;
  mode?: RunMode;
  max_retries?: number;
  helper_language?: string;
  initial_lesson?: Lesson;
  fault_id?: string;
  source_run_id?: string;
}

export interface RunEvent {
  id: string | null;
  run_id: string;
  ts: string;
  service: string;
  type: string;
  node: string | null;
  attempt: number | null;
  data: Record<string, any>;
}

// ------------------------------------------------------------------ memory
export interface GuidelineHistoryEntry {
  version: number;
  text: string;
  reason: string;
  at: string;
}

export interface Guideline {
  id: string;
  topic_id: string | null;
  text: string;
  check_ids: string[];
  target: "planner" | "writer" | "both";
  status: "active" | "retired";
  origin: "failure" | "feedback" | "human";
  version: number;
  times_applied: number;
  times_helped: number;
  times_missed: number;
  created_from_run: string | null;
  history: GuidelineHistoryEntry[];
  created_at: string;
  updated_at: string;
}

export interface CheckFailureStat {
  check_id: string;
  runs: number;
  first_attempt_failures: number;
  any_attempt_failures: number;
  first_attempt_fail_rate: number;
}

export interface RunTrendPoint {
  run_id: string;
  created_at: string;
  status: string;
  attempts: number;
  first_attempt_passed: boolean;
  first_attempt_failed_checks: number;
  guidelines_applied: number;
  cost_usd: number;
}

export interface StatsResponse {
  runs_total: number;
  runs_shipped: number;
  runs_needs_review: number;
  first_pass_rate: number | null;
  avg_attempts: number | null;
  avg_cost_usd: number | null;
  total_cost_usd: number;
  guidelines_active: number;
  guidelines_retired: number;
  pending_proposals: number;
  trend: RunTrendPoint[];
  checks: CheckFailureStat[];
}

export interface CheckOverride {
  check_id: string;
  human_verdict: Verdict;
  note: string;
}

export interface FeedbackCreate {
  run_id: string;
  rating: "up" | "down" | null;
  comment: string;
  check_overrides: CheckOverride[];
}

export interface Feedback extends FeedbackCreate {
  id: string;
  processed: boolean;
  created_at: string;
}

export interface RubricProposal {
  id: string;
  check_id: string | null;
  kind: "clarify_check" | "prompt_change";
  title: string;
  proposed_change: Record<string, unknown>;
  rationale: string;
  evidence: string[];
  source: "consolidation" | "feedback" | "escalation";
  status: "pending" | "approved" | "rejected";
  created_at: string;
  decided_at: string | null;
  resulting_version: number | null;
}

export interface JudgeSpec {
  question: string;
  pass_criteria: string[];
  fail_criteria: string[];
  notes: string[];
}

export interface CheckSpec {
  id: string;
  dimension: Dimension;
  title: string;
  method: CheckMethod;
  severity: Severity;
  pass_condition: string;
  impl: string | null;
  params: Record<string, unknown>;
  judge: JudgeSpec | null;
}

export interface Rubric {
  version: number;
  name: string;
  ship_policy: string;
  description: string;
  checks: CheckSpec[];
}

export interface RubricVersionInfo {
  version: number;
  status: "active" | "superseded";
  change_note: string;
  created_by: string;
  created_at: string;
  rubric: Rubric;
}

export interface ConsolidationResult {
  run_id: string | null;
  added: Guideline[];
  sharpened: Guideline[];
  retired: Guideline[];
  proposals: RubricProposal[];
  feedback_processed: number;
  summary: string;
}

// --------------------------------------------------------------- knowledge
export interface TopicPackSummary {
  id: string;
  title: string;
  aliases: string[];
  summary: string;
  version: string;
  document_count: number;
  chunk_count: number;
}

export interface KeyPoints {
  what: string;
  why: string[];
  how_steps: string[];
  misconceptions: string[];
  limitations: string[];
}

export interface TopicPack {
  id: string;
  title: string;
  version: string;
  aliases: string[];
  summary: string;
  key_points: KeyPoints;
  example_must_show: string[];
  jargon: { term: string; aliases: string[] }[];
  acronyms: Record<string, string>;
}

export interface GlossaryItem {
  term: string;
  aliases: string[];
  simple_meaning: string;
  translations: Record<string, string>;
}

export interface KBChunk {
  id: string;
  doc_id: string;
  doc_title: string;
  heading: string;
  text: string;
  source: string;
}

export interface KBDocument {
  id: string;
  title: string;
  source: string;
  chunks: KBChunk[];
}

export interface SearchResponse {
  topic_id: string;
  query: string;
  retriever: string;
  hits: { chunk: KBChunk; score: number }[];
}

// ------------------------------------------------------------- evaluator lab
export interface FaultInfo {
  id: string;
  title: string;
  category: string;
  description: string;
  injected_text: string;
  expected_checks: string[];
}

export interface FaultApplied {
  lesson: Lesson;
  fault: FaultInfo;
}

// ------------------------------------------------------------------- system
export interface ServiceHealth {
  name: string;
  ok: boolean;
  status: number | null;
  version?: string;
  error?: string;
  checks?: Record<string, string>;
}

export interface RoleInfo {
  role: string;
  tier: string;
  deployment: string;
  reasoning_effort: string | null;
  max_output_tokens: number;
  purpose: string;
}

export interface TracingStatus {
  enabled: boolean;
  ui_url?: string;
  project_id?: string | null;
  ok?: boolean;
  version?: string | null;
  error?: string;
}

export interface SystemStatus {
  services: ServiceHealth[];
  queue: { stream_length?: number; pending?: number; error?: string };
  tracing: TracingStatus;
  llm: { configured: boolean; api_version: string; roles: RoleInfo[] };
  policy: {
    max_retries: number;
    run_budget_usd: number;
    patch_max_failed_checks: number;
    helper_language: string;
  };
}

export interface DoctorCheck {
  ok: boolean;
  detail: string;
  latency_ms: number;
}

export interface DoctorRow {
  deployment: string;
  roles: string[];
  reasoning_effort: string | null;
  ok: boolean;
  chat: DoctorCheck;
  structured_output: DoctorCheck;
  tool_calling: DoctorCheck;
  efforts?: Record<string, DoctorCheck>;
}
