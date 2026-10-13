import type { CheckMethod, Dimension, RunMode, RunStatus } from "../api/types";

export const DIMENSION_LABELS: Record<Dimension, string> = {
  accuracy: "Accurate & grounded",
  language: "Beginner-friendly language",
  examples: "Teaches by example",
  jargon: "Clear, no unexplained jargon",
  coverage: "Covers the key points",
  flow: "Coherent teaching flow",
};

export const DIMENSION_ORDER: Dimension[] = ["accuracy", "language", "examples", "jargon", "coverage", "flow"];

export const METHOD_LABELS: Record<CheckMethod, string> = {
  deterministic: "Code",
  llm_judge: "LLM judge",
  fact_check: "Fact-check agent",
  learner: "Simulated learner",
};

export const STATUS_LABELS: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  shipped: "Shipped",
  needs_human_review: "Needs human review",
  evaluated: "Evaluated",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const MODE_LABELS: Record<RunMode, string> = {
  generate: "Generate",
  evaluate_only: "Evaluate only",
  repair: "Evaluate + repair",
};

export function formatCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "-";
  if (usd === 0) return "$0";
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${Math.round(value * 100)}%`;
}

export function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "-";
  const ms = (end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime();
  if (ms < 0) return "-";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
}

export function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: value >= 10000 ? "compact" : "standard" }).format(value);
}

export function plural(count: number, word: string, many = `${word}s`): string {
  return `${count} ${count === 1 ? word : many}`;
}
