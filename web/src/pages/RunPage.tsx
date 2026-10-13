import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import { TERMINAL_STATUSES, type AttemptRecord, type CheckSpec, type RunDetail, type RunStatus } from "../api/types";
import { ActivityFeed } from "../components/ActivityFeed";
import { Icon } from "../components/Icon";
import { LessonViewer } from "../components/LessonViewer";
import { PipelineGraph } from "../components/PipelineGraph";
import { FaultDetection, FeedbackPanel, PlanView, RejectionLogView, WhatChanged } from "../components/RunPanels";
import { CheckDetail, Scorecard, scoreItems, type ScoreItem } from "../components/Scorecard";
import { Card, ErrorNote, Spinner, StatusBadge, Tabs, useToast } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useRunStream } from "../hooks/useRunStream";
import { initialLiveRun, type LiveRun, type NodeState, type PipelineNode } from "../state/runStream";
import { formatCost, formatDuration, MODE_LABELS, plural } from "../utils/format";
import { copyLessonForDocs } from "../utils/lessonExport";

type Tab = "checks" | "lesson" | "changes" | "log" | "plan";

/** When the event history is gone (or before it arrives), derive the graph from stored data. */
function nodesFromRun(run: RunDetail): Record<PipelineNode, NodeState> {
  const nodes = initialLiveRun().nodes;
  const done = (node: PipelineNode, visits = 1) => (nodes[node] = { status: "done", visits });
  if (!TERMINAL_STATUSES.includes(run.status)) return nodes;
  const attempts = run.attempts.length;
  if (run.mode !== "evaluate_only") done("recall_memory");
  if (run.plan) done("plan");
  if (run.attempts[0]?.kind === "initial") done("write");
  if (attempts) done("evaluate", attempts);
  if (attempts > 1) done("revise", attempts - 1);
  if (run.status === "needs_human_review") done("select_best");
  if (run.status !== "failed" && run.status !== "cancelled") done("finalize");
  if (run.mode !== "evaluate_only" && (run.status === "shipped" || run.status === "needs_human_review")) done("consolidate_memory");
  return nodes;
}

function attemptLabel(a: AttemptRecord) {
  const failed = a.evaluation.failed_check_ids.length;
  return failed ? `${failed} failed` : "all passed";
}

export function RunPage() {
  const { id = "" } = useParams();
  const toast = useToast();
  const run = useAsync(() => api.runs.get(id), [id]);
  const rubric = useAsync(() => api.memory.activeRubric(), []);
  const live: LiveRun = useRunStream(id, true, run.reload);
  const data = run.data;
  const faults = useAsync(() => (data?.fault_id ? api.evaluator.faults() : Promise.resolve([])), [data?.fault_id]);
  const [tab, setTab] = useState<Tab>("checks");
  const [attemptNo, setAttemptNo] = useState<number | null>(null);
  const [selectedCheck, setSelectedCheck] = useState<string | null>(null);

  const status: RunStatus | "unknown" = data
    ? TERMINAL_STATUSES.includes(data.status)
      ? data.status
      : live.terminal && live.status !== "unknown"
        ? live.status
        : data.status
    : live.status;
  const isActive = status === "queued" || status === "running";
  const attempts = useMemo(() => [...(data?.attempts ?? [])].sort((a, b) => a.attempt_no - b.attempt_no), [data]);
  const liveAttempt = live.attempt;
  const viewAttempt = attemptNo ?? (isActive && liveAttempt > (attempts.at(-1)?.attempt_no ?? 0) ? liveAttempt : attempts.at(-1)?.attempt_no ?? liveAttempt);
  const record = attempts.find((a) => a.attempt_no === viewAttempt);
  const specs: CheckSpec[] = rubric.data?.rubric.checks ?? [];
  const finalAttempt = attempts.find((a) => a.attempt_no === data?.final_attempt_no) ?? attempts.at(-1);

  useEffect(() => {
    setSelectedCheck(null);
  }, [viewAttempt]);

  const items: ScoreItem[] = useMemo(() => {
    if (record) {
      const byId = Object.fromEntries(
        record.evaluation.results.map((r) => [
          r.check_id,
          { checkId: r.check_id, title: r.title, dimension: r.dimension, method: r.method, verdict: r.verdict, full: r },
        ]),
      );
      return scoreItems(specs, byId);
    }
    const liveChecks = live.checks[viewAttempt] ?? {};
    const byId = Object.fromEntries(
      Object.values(liveChecks).map((c) => [
        c.checkId,
        { checkId: c.checkId, title: c.title, dimension: c.dimension, method: c.method, verdict: c.verdict, reasoning: c.reasoning },
      ]),
    );
    return scoreItems(specs, byId);
  }, [record, specs, live.checks, viewAttempt]);

  const selected = items.find((i) => i.checkId === selectedCheck) ?? items.find((i) => i.verdict === "FAIL") ?? null;
  const nodes = live.activity.length ? live.nodes : data ? nodesFromRun(data) : live.nodes;
  const maxAttempts = (data?.max_retries ?? 2) + 1;
  const costUsd = Math.max(data?.usage?.cost_usd ?? 0, live.costUsd);
  const fault = faults.data?.find((f) => f.id === data?.fault_id);

  async function act(action: "cancel" | "resume") {
    try {
      await (action === "cancel" ? api.runs.cancel(id) : api.runs.resume(id));
      toast(action === "cancel" ? "Cancel requested - the run stops before its next step." : "Resuming from the last checkpoint…");
      run.reload();
    } catch (err) {
      toast((err as Error).message, true);
    }
  }

  async function copyForDocs() {
    if (!finalAttempt) return;
    try {
      await copyLessonForDocs(finalAttempt.lesson, data?.helper_language);
      toast("Lesson copied - paste it into a Google Doc to keep the formatting.");
    } catch {
      toast("Copy failed - use Download .md instead.", true);
    }
  }

  if (run.error && !data) {
    return (
      <div className="page">
        <ErrorNote error={run.error} />
        <Link to="/runs">← Back to runs</Link>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <Link to="/runs" className="muted">
            ← Runs
          </Link>
          <div className="run-title" style={{ marginTop: 6 }}>
            <h1>{data?.topic ?? "Loading run…"}</h1>
            <StatusBadge status={status} />
          </div>
          {data ? (
            <div className="run-meta">
              <span className="mono">{data.id}</span>
              <span>{MODE_LABELS[data.mode]}</span>
              <span>
                <Icon name="refresh" size={14} />{" "}
                {Math.max(attempts.length, liveAttempt)
                  ? `attempt ${Math.max(attempts.length, liveAttempt)} of ${maxAttempts}`
                  : `no attempts yet (max ${maxAttempts})`}
              </span>
              <span>
                <Icon name="coin" size={14} /> {formatCost(costUsd)}
              </span>
              <span>
                <Icon name="clock" size={14} /> {formatDuration(data.started_at, data.finished_at)}
              </span>
              {data.rubric_version ? <span>rubric v{data.rubric_version}</span> : null}
              <span>
                <Icon name="brain" size={14} /> {plural(data.guideline_ids_applied.length, "guideline")} applied
              </span>
            </div>
          ) : null}
        </div>
        <div className="page-actions">
          {isActive ? (
            <button className="btn btn-danger" onClick={() => act("cancel")}>
              <Icon name="stop" /> Cancel
            </button>
          ) : null}
          {status === "failed" || status === "cancelled" ? (
            <button className="btn" onClick={() => act("resume")}>
              <Icon name="refresh" /> Resume from checkpoint
            </button>
          ) : null}
          {finalAttempt ? (
            <>
              <button className="btn" onClick={copyForDocs}>
                <Icon name="copy" /> Copy for Google Docs
              </button>
              <a className="btn" href={api.runs.lessonExportUrl(id)}>
                <Icon name="download" /> Lesson .md
              </a>
              <a className="btn" href={api.runs.rejectionLogUrl(id)}>
                <Icon name="download" /> Rejection log
              </a>
            </>
          ) : null}
        </div>
      </header>

      {data?.status === "shipped" ? (
        <div className="callout callout-good">
          <Icon name="check" />
          <span>
            <strong>Shipped.</strong> {data.status_reason}
          </span>
        </div>
      ) : null}
      {data?.status === "needs_human_review" ? (
        <div className="callout callout-warning">
          <Icon name="alert" />
          <span>
            <strong>Not shipped - needs human review.</strong> {data.status_reason}
          </span>
        </div>
      ) : null}
      {data?.status === "failed" ? (
        <div className="callout callout-critical">
          <Icon name="alert" />
          <span>
            <strong>Run failed.</strong> {data.error ?? live.error}
          </span>
        </div>
      ) : null}
      {data?.status === "evaluated" ? (
        <div className="callout callout-accent">
          <Icon name="info" />
          <span>{data.status_reason}</span>
        </div>
      ) : null}

      {data?.fault_id ? <FaultDetection run={data} fault={fault} /> : null}

      <Card
        title="Agentic loop"
        hint={live.route ? `Last decision: ${live.route.next.replace("_", " ")} - ${live.route.reason}` : "LangGraph state machine, live"}
      >
        <PipelineGraph nodes={nodes} activeNode={live.activeNode} attempt={Math.max(viewAttempt, liveAttempt)} maxAttempts={maxAttempts} />
        {live.recalled?.guidelines.length ? (
          <details style={{ marginTop: 8 }}>
            <summary>
              Memory injected {plural(live.recalled.guidelines.length, "learned guideline")} into this run
            </summary>
            <ul>
              {live.recalled.guidelines.map((g) => (
                <li key={g.id}>
                  <span className="mono muted">{g.id}</span> {g.text}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        {live.consolidation ? <p className="secondary" style={{ marginTop: 8 }}>Memory update: {live.consolidation}</p> : null}
      </Card>

      <div className="split">
        <section className="card">
          <Tabs<Tab>
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "checks", label: "Evaluation" },
              { id: "lesson", label: "Lesson" },
              { id: "changes", label: "What changed" },
              { id: "log", label: "Rejection log" },
              { id: "plan", label: "Plan" },
            ]}
          />
          <div className="card-body">
            {tab === "checks" ? (
              <div className="stack">
                <div className="attempts" role="group" aria-label="Attempts">
                  {attempts.map((a, i) => (
                    <span key={a.attempt_no} className="row" style={{ gap: 8 }}>
                      {i > 0 ? <span className="attempt-arrow">→</span> : null}
                      <button className="attempt-pill" aria-pressed={viewAttempt === a.attempt_no} onClick={() => setAttemptNo(a.attempt_no)}>
                        <Icon name={a.evaluation.passed ? "check" : "x"} size={14} />
                        Attempt {a.attempt_no} · {a.kind} · {attemptLabel(a)}
                      </button>
                    </span>
                  ))}
                  {isActive && liveAttempt > (attempts.at(-1)?.attempt_no ?? 0) ? (
                    <span className="row" style={{ gap: 8 }}>
                      {attempts.length ? <span className="attempt-arrow">→</span> : null}
                      <button className="attempt-pill" aria-pressed={viewAttempt === liveAttempt} onClick={() => setAttemptNo(null)}>
                        <span className="spinner" style={{ width: 12, height: 12 }} /> Attempt {liveAttempt} · in progress
                      </button>
                    </span>
                  ) : null}
                </div>
                {record ? (
                  <p className="secondary">
                    {record.evaluation.summary} · evaluated in {(record.evaluation.duration_ms / 1000).toFixed(1)}s ·{" "}
                    {formatCost(record.evaluation.usage?.cost_usd)}
                  </p>
                ) : null}
                {!record && !Object.keys(live.checks[viewAttempt] ?? {}).length ? (
                  isActive ? (
                    <Spinner label="The lesson is being planned and written - checks appear here as soon as evaluation starts." />
                  ) : (
                    <div className="empty">No evaluation for this run.</div>
                  )
                ) : (
                  <>
                    <Scorecard items={items} selected={selected?.checkId ?? null} onSelect={setSelectedCheck} />
                    {selected ? (
                      <Card>
                        <CheckDetail item={selected} spec={specs.find((s) => s.id === selected.checkId)} />
                      </Card>
                    ) : null}
                  </>
                )}
              </div>
            ) : null}
            {tab === "lesson" ? (
              finalAttempt ? (
                <div className="stack">
                  {data?.status === "needs_human_review" ? (
                    <div className="callout callout-warning">
                      <Icon name="alert" />
                      <span>This is the best attempt (#{finalAttempt.attempt_no}) but it did not pass every check.</span>
                    </div>
                  ) : (
                    <p className="muted">
                      Showing attempt {finalAttempt.attempt_no}
                      {data?.final_attempt_no ? " (final)" : " (latest)"}.
                    </p>
                  )}
                  <LessonViewer lesson={finalAttempt.lesson} helperLanguage={data?.helper_language} />
                </div>
              ) : (
                <div className="empty">The lesson appears here after its first evaluation.</div>
              )
            ) : null}
            {tab === "changes" ? <WhatChanged attempt={record} /> : null}
            {tab === "log" ? (
              attempts.length ? (
                <RejectionLogView runId={id} version={`${attempts.length}-${data?.status}`} />
              ) : (
                <div className="empty">Nothing has been evaluated yet.</div>
              )
            ) : null}
            {tab === "plan" ? <PlanView plan={data?.plan ?? null} /> : null}
          </div>
        </section>

        <Card title="Live activity" hint={isActive ? "streaming" : `${live.activity.length} events`} flush>
          <ActivityFeed items={live.activity} live={isActive} />
        </Card>
      </div>

      {data && TERMINAL_STATUSES.includes(data.status) && attempts.length ? <FeedbackPanel run={data} /> : null}
    </div>
  );
}
