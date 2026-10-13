import { describe, expect, it } from "vitest";
import type { RunEvent } from "../api/types";
import { initialLiveRun, reduceRun } from "./runStream";

let seq = 0;
const ev = (type: string, data: Record<string, unknown> = {}, extra: Partial<RunEvent> = {}): RunEvent => ({
  id: `${++seq}-0`,
  run_id: "run_1",
  ts: "2026-10-14T10:00:00Z",
  service: "orchestrator",
  type,
  node: null,
  attempt: null,
  data,
  ...extra,
});

const fold = (events: RunEvent[]) => events.reduce(reduceRun, initialLiveRun());

describe("reduceRun", () => {
  it("tracks node progress, attempts and cost", () => {
    const state = fold([
      ev("run.queued", { topic: "RAG", max_retries: 2 }),
      ev("run.started"),
      ev("node.started", { node: "plan" }),
      ev("node.completed", { node: "plan", duration_ms: 1500, cost_usd: 0.02, summary: "7 sections" }),
      ev("node.started", { node: "write" }, { attempt: 1 }),
    ]);
    expect(state.status).toBe("running");
    expect(state.nodes.plan).toMatchObject({ status: "done", visits: 1, summary: "7 sections" });
    expect(state.nodes.write.status).toBe("active");
    expect(state.activeNode).toBe("write");
    expect(state.attempt).toBe(1);
    expect(state.costUsd).toBeCloseTo(0.02);
  });

  it("collects live check results per attempt and the loop decision", () => {
    const state = fold([
      ev("check.completed", { check_id: "EX-1", title: "Worked example", dimension: "examples", method: "llm_judge", verdict: "FAIL", reasoning: "too generic" }, { attempt: 1 }),
      ev("check.completed", { check_id: "LANG-1", title: "Reading level", dimension: "language", method: "deterministic", verdict: "PASS" }, { attempt: 1 }),
      ev("attempt.rejected", { attempt: 1, next: "revise", reason: "1 check(s) failed" }),
      ev("revision.completed", { attempt: 2, strategy: "patch", notes: [{ check_id: "EX-1", change: "added real text" }] }),
    ]);
    expect(Object.keys(state.checks[1])).toEqual(["EX-1", "LANG-1"]);
    expect(state.checks[1]["EX-1"].verdict).toBe("FAIL");
    expect(state.route).toEqual({ next: "revise", reason: "1 check(s) failed" });
    expect(state.attempt).toBe(2);
    expect(state.activity.at(-1)?.detail).toContain("EX-1: added real text");
  });

  it("shows ReAct steps as thought -> action -> observation", () => {
    const state = fold([
      ev("agent.tool_call", { agent: "writer", tool: "search_knowledge_base", reason: "Need the definition", args: { query: "what is RAG" } }),
      ev("agent.tool_result", { agent: "writer", tool: "search_knowledge_base", preview: "[rag/02] RAG is..." }),
    ]);
    expect(state.activity[0]).toMatchObject({ tone: "agent", agent: "writer", detail: "Thought: Need the definition" });
    expect(state.activity[0].extra).toContain("query: what is RAG");
    expect(state.activity[1].title).toBe("Observation from search_knowledge_base");
  });

  it("marks terminal states and ignores replayed duplicates", () => {
    const failed = ev("run.failed", { error: "generator -> 424" });
    const state = fold([ev("node.started", { node: "plan" }), failed, failed]);
    expect(state.terminal).toBe(true);
    expect(state.status).toBe("failed");
    expect(state.nodes.plan.status).toBe("failed");
    expect(state.activity.filter((a) => a.type === "run.failed")).toHaveLength(1);
  });
});
