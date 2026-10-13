// Pure reducer: folds the run's Server-Sent Events into a view model for the live run page.
// Kept framework-free so it is unit-tested without a browser.

import type { CheckMethod, Dimension, RunEvent, RunStatus, Verdict } from "../api/types";

export const PIPELINE_NODES = [
  "recall_memory",
  "plan",
  "write",
  "evaluate",
  "revise",
  "select_best",
  "finalize",
  "consolidate_memory",
] as const;

export type PipelineNode = (typeof PIPELINE_NODES)[number];
export type NodeStatus = "pending" | "active" | "done" | "failed";

export interface NodeState {
  status: NodeStatus;
  visits: number;
  durationMs?: number;
  summary?: string;
  costUsd?: number;
}

export interface LiveCheck {
  checkId: string;
  title: string;
  dimension: Dimension;
  method: CheckMethod;
  verdict: Verdict;
  reasoning: string;
  error: boolean;
}

export type ActivityTone = "info" | "pass" | "fail" | "agent" | "muted" | "memory";

export interface ActivityItem {
  key: string;
  ts: string;
  type: string;
  service: string;
  node: string | null;
  attempt: number | null;
  agent?: string;
  tone: ActivityTone;
  title: string;
  detail?: string;
  extra?: string;
}

export interface LiveRun {
  status: RunStatus | "unknown";
  terminal: boolean;
  nodes: Record<PipelineNode, NodeState>;
  activeNode: PipelineNode | null;
  attempt: number;
  checks: Record<number, Record<string, LiveCheck>>;
  activity: ActivityItem[];
  costUsd: number;
  lastEventId: string | null;
  route?: { next: string; reason: string };
  recalled?: { guidelines: { id: string; text: string }[]; frequentFailures: number };
  consolidation?: string;
  error?: string;
}

export function initialLiveRun(): LiveRun {
  const nodes = Object.fromEntries(
    PIPELINE_NODES.map((n) => [n, { status: "pending", visits: 0 } satisfies NodeState]),
  ) as Record<PipelineNode, NodeState>;
  return {
    status: "unknown",
    terminal: false,
    nodes,
    activeNode: null,
    attempt: 0,
    checks: {},
    activity: [],
    costUsd: 0,
    lastEventId: null,
  };
}

const NODE_LABEL: Record<string, string> = {
  recall_memory: "Recall memory",
  plan: "Plan lesson",
  write: "Write draft",
  evaluate: "Evaluate",
  revise: "Revise",
  select_best: "Select best attempt",
  finalize: "Finalize",
  consolidate_memory: "Update memory",
};

export const nodeLabel = (node: string) => NODE_LABEL[node] ?? node;

const isNode = (value: unknown): value is PipelineNode =>
  typeof value === "string" && (PIPELINE_NODES as readonly string[]).includes(value);

function short(value: unknown, max = 160): string {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? "");
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function describeArgs(args: Record<string, unknown> | undefined): string {
  if (!args) return "";
  const parts = Object.entries(args).map(([k, v]) => {
    if (Array.isArray(v)) return `${k}: [${v.map((x) => short(x, 40)).join(", ")}]`;
    return `${k}: ${short(v, 80)}`;
  });
  return parts.join(" · ");
}

function item(event: RunEvent, tone: ActivityTone, title: string, detail?: string, extra?: string): ActivityItem {
  return {
    key: event.id ?? `${event.ts}-${event.type}`,
    ts: event.ts,
    type: event.type,
    service: event.service,
    node: event.node,
    attempt: event.attempt,
    agent: typeof event.data.agent === "string" ? event.data.agent : undefined,
    tone,
    title,
    detail,
    extra,
  };
}

const TERMINAL_TYPES = new Set(["run.completed", "run.failed", "run.cancelled"]);

export function reduceRun(state: LiveRun, event: RunEvent): LiveRun {
  if (event.id && state.lastEventId === event.id) return state; // replayed duplicate
  const next: LiveRun = {
    ...state,
    nodes: { ...state.nodes },
    checks: { ...state.checks },
    lastEventId: event.id ?? state.lastEventId,
  };
  const d = event.data ?? {};
  let entry: ActivityItem | null = null;

  switch (event.type) {
    case "run.queued":
      next.status = "queued";
      entry = item(event, "muted", "Run queued", `${d.topic ?? ""} · max ${d.max_retries ?? "?"} retries`);
      break;
    case "run.started":
      next.status = "running";
      entry = item(event, "info", "Worker picked up the run");
      break;
    case "node.started": {
      const node = d.node;
      if (isNode(node)) {
        const prev = next.nodes[node];
        next.nodes[node] = { ...prev, status: "active", visits: prev.visits + 1 };
        next.activeNode = node;
      }
      if (typeof event.attempt === "number" && event.attempt > next.attempt) next.attempt = event.attempt;
      next.status = next.status === "unknown" || next.status === "queued" ? "running" : next.status;
      entry = item(event, "muted", `${nodeLabel(String(node))} started`);
      break;
    }
    case "node.completed": {
      const node = d.node;
      if (isNode(node)) {
        next.nodes[node] = {
          ...next.nodes[node],
          status: "done",
          durationMs: d.duration_ms,
          summary: d.summary,
          costUsd: d.cost_usd,
        };
        if (next.activeNode === node) next.activeNode = null;
      }
      next.costUsd += Number(d.cost_usd ?? 0);
      const seconds = typeof d.duration_ms === "number" ? ` · ${(d.duration_ms / 1000).toFixed(1)}s` : "";
      entry = item(event, "info", `${nodeLabel(String(node))} done${seconds}`, d.summary || undefined);
      break;
    }
    case "memory.recalled": {
      const guidelines = Array.isArray(d.guidelines) ? d.guidelines : [];
      next.recalled = {
        guidelines: guidelines.map((g: { id: string; text: string }) => ({ id: g.id, text: g.text })),
        frequentFailures: Array.isArray(d.frequent_failures) ? d.frequent_failures.length : 0,
      };
      entry = item(
        event,
        "memory",
        `Recalled ${guidelines.length} learned guideline${guidelines.length === 1 ? "" : "s"} from memory`,
        guidelines.map((g: { text: string }) => `• ${g.text}`).join("\n") || undefined,
      );
      break;
    }
    case "plan.created":
      entry = item(event, "info", `Plan: ${d.title ?? "lesson outline"}`, d.analogy ? `Analogy: ${short(d.analogy, 220)}` : undefined);
      break;
    case "agent.thought":
      entry = item(event, "agent", `${d.agent ?? "agent"} is thinking`, short(d.text, 400));
      break;
    case "agent.tool_call":
      entry = item(
        event,
        "agent",
        `${d.agent ?? "agent"} → ${d.tool}`,
        d.reason ? `Thought: ${short(d.reason, 300)}` : undefined,
        describeArgs(d.args),
      );
      break;
    case "agent.tool_result":
      entry = item(event, "muted", `Observation from ${d.tool}`, short(d.preview, 300));
      break;
    case "agent.submitted": {
      const facts = Object.entries(d)
        .filter(([k]) => !["agent", "tool"].includes(k))
        .map(([k, v]) => `${k}: ${v}`)
        .join(" · ");
      entry = item(event, "agent", `${d.agent ?? "agent"} submitted (${d.tool})`, facts || undefined);
      break;
    }
    case "check.completed": {
      const attempt = event.attempt ?? next.attempt;
      const check: LiveCheck = {
        checkId: d.check_id,
        title: d.title,
        dimension: d.dimension,
        method: d.method,
        verdict: d.verdict,
        reasoning: d.reasoning ?? "",
        error: Boolean(d.error),
      };
      next.checks[attempt] = { ...(next.checks[attempt] ?? {}), [check.checkId]: check };
      entry = item(
        event,
        check.verdict === "PASS" ? "pass" : "fail",
        `${check.checkId} ${check.title}: ${check.verdict}`,
        check.verdict === "FAIL" ? short(check.reasoning, 240) : undefined,
      );
      break;
    }
    case "evaluation.completed":
      entry = item(event, d.passed ? "pass" : "fail", `Evaluation: ${d.summary ?? (d.passed ? "PASS" : "FAIL")}`);
      break;
    case "attempt.rejected":
      next.route = { next: d.next, reason: d.reason };
      entry = item(event, "fail", `Attempt ${d.attempt} rejected → ${String(d.next).replace("_", " ")}`, d.reason);
      break;
    case "revision.completed": {
      const notes = Array.isArray(d.notes) ? d.notes : [];
      next.attempt = Math.max(next.attempt, Number(d.attempt ?? 0));
      entry = item(
        event,
        "info",
        `Attempt ${d.attempt} written (${d.strategy})`,
        notes.map((n: { check_id: string; change: string }) => `${n.check_id}: ${n.change}`).join("\n") || d.reason,
      );
      break;
    }
    case "memory.consolidated":
      next.consolidation = d.summary;
      entry = item(event, "memory", "Memory updated", d.summary);
      break;
    case "run.completed":
      next.status = (d.status as RunStatus) ?? "shipped";
      next.terminal = true;
      next.activeNode = null;
      entry = item(event, d.status === "shipped" ? "pass" : "info", `Run finished: ${String(d.status).replaceAll("_", " ")}`, d.status_reason);
      break;
    case "run.failed":
      next.status = "failed";
      next.terminal = true;
      next.error = d.error;
      if (next.activeNode) next.nodes[next.activeNode] = { ...next.nodes[next.activeNode], status: "failed" };
      next.activeNode = null;
      entry = item(event, "fail", "Run failed", d.error);
      break;
    case "run.cancelled":
      next.status = "cancelled";
      next.terminal = true;
      next.activeNode = null;
      entry = item(event, "muted", "Run cancelled");
      break;
    case "log":
      entry = item(event, "muted", short(d.message, 200));
      break;
    default:
      break;
  }
  if (entry) next.activity = [...state.activity, entry];
  if (TERMINAL_TYPES.has(event.type)) next.terminal = true;
  return next;
}
