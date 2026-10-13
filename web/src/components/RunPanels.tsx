import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
import type { AttemptRecord, CheckOverride, FaultInfo, LessonPlan, RunDetail, Verdict } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { Icon } from "./Icon";
import { Card, ErrorNote, Spinner, useToast, VerdictChip } from "./ui";

/** Evaluator Lab runs: did the evaluator catch the deliberate error? */
export function FaultDetection({ run, fault }: { run: RunDetail; fault: FaultInfo | undefined }) {
  const first = run.attempts.find((a) => a.attempt_no === 1);
  if (!fault) return null;
  const failed = new Set(first?.evaluation.failed_check_ids ?? []);
  const caught = fault.expected_checks.filter((c) => failed.has(c));
  const extra = [...failed].filter((c) => !fault.expected_checks.includes(c));
  return (
    <Card
      title={`Deliberate error: ${fault.title}`}
      hint={fault.description}
      actions={
        first ? (
          caught.length ? (
            <span className="badge badge-good">
              <Icon name="check" size={13} /> Caught by {caught.join(", ")}
            </span>
          ) : (
            <span className="badge badge-critical">
              <Icon name="x" size={13} /> Not caught
            </span>
          )
        ) : (
          <Spinner label="Evaluating…" />
        )
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        <blockquote className="quote">Injected: {fault.injected_text}</blockquote>
        <div className="fault-banner">
          <span className="secondary">Expected to be caught by:</span>
          {fault.expected_checks.map((c) => (
            <span key={c} className={`badge ${!first ? "" : failed.has(c) ? "badge-good" : "badge-critical"}`}>
              {first ? <Icon name={failed.has(c) ? "check" : "x"} size={12} /> : null}
              {c}
            </span>
          ))}
          {extra.length ? <span className="muted">Also flagged: {extra.join(", ")}</span> : null}
        </div>
      </div>
    </Card>
  );
}

export function WhatChanged({ attempt }: { attempt: AttemptRecord | undefined }) {
  if (!attempt) return <div className="empty">Select an attempt.</div>;
  if (attempt.attempt_no === 1) {
    return (
      <div className="callout">
        <Icon name="info" />
        <span>
          Attempt 1 is the {attempt.kind === "provided" ? "lesson you provided" : "writer's first draft"}. Later attempts
          show what changed and why.
        </span>
      </div>
    );
  }
  const changed = attempt.diff.filter((d) => d.change !== "unchanged");
  return (
    <div className="stack">
      <div className="callout callout-accent">
        <Icon name="refresh" />
        <span>{attempt.strategy_reason || `Attempt ${attempt.attempt_no} (${attempt.kind}).`}</span>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Failed check</th>
              <th>What the writer changed</th>
            </tr>
          </thead>
          <tbody>
            {attempt.revision_notes.map((n) => (
              <tr key={n.check_id + n.change}>
                <td className="mono nowrap">{n.check_id}</td>
                <td>{n.change}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <span className="field-label">Sections touched</span>
        <div className="diff-chips">
          {changed.length ? (
            changed.map((d) => (
              <span key={d.kind + d.heading} className={`badge ${d.change === "removed" ? "badge-critical" : d.change === "added" ? "badge-good" : "badge-accent"}`}>
                {d.heading} · {d.change} · {d.words_before}→{d.words_after} words
              </span>
            ))
          ) : (
            <span className="muted">No section text changed.</span>
          )}
          {attempt.diff
            .filter((d) => d.change === "unchanged")
            .map((d) => (
              <span key={d.kind + d.heading} className="badge badge-outline">
                {d.heading} · kept
              </span>
            ))}
        </div>
      </div>
    </div>
  );
}

export function PlanView({ plan }: { plan: LessonPlan | null }) {
  if (!plan) return <div className="empty">No plan for this run (lessons provided in the Lab skip planning).</div>;
  return (
    <div className="stack">
      <dl className="kv">
        <dt>Title</dt>
        <dd>{plan.title}</dd>
        <dt>Objectives</dt>
        <dd>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {plan.learning_objectives.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </dd>
        <dt>Analogy</dt>
        <dd>{plan.analogy}</dd>
        <dt>Worked example</dt>
        <dd>{plan.worked_example}</dd>
      </dl>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Section</th>
              <th>Key points</th>
              <th>Terms introduced</th>
            </tr>
          </thead>
          <tbody>
            {plan.sections.map((s) => (
              <tr key={s.kind + s.heading}>
                <td>
                  <span className="tag">{s.kind}</span>
                  <div>{s.heading}</div>
                </td>
                <td>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {s.key_points.map((k) => (
                      <li key={k}>{k}</li>
                    ))}
                  </ul>
                </td>
                <td className="secondary">{s.terms_to_define.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RejectionLogView({ runId, version }: { runId: string; version: string }) {
  const log = useAsync(() => api.runs.rejectionLog(runId), [runId, version]);
  if (log.error) return <ErrorNote error={log.error} />;
  if (!log.data) return <Spinner label="Loading rejection log…" />;
  return (
    <div className="lesson" style={{ fontSize: "0.95rem", maxWidth: "none" }}>
      <Markdown remarkPlugins={[remarkGfm]}>{log.data}</Markdown>
    </div>
  );
}

export function FeedbackPanel({ run }: { run: RunDetail }) {
  const toast = useToast();
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [comment, setComment] = useState("");
  const [overrides, setOverrides] = useState<CheckOverride[]>([]);
  const [checkId, setCheckId] = useState("");
  const [verdict, setVerdict] = useState<Verdict>("PASS");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const final = run.attempts.find((a) => a.attempt_no === run.final_attempt_no) ?? run.attempts.at(-1);
  const results = final?.evaluation.results ?? [];

  async function submit() {
    setBusy(true);
    try {
      await api.memory.addFeedback({ run_id: run.id, rating, comment, check_overrides: overrides });
      toast("Feedback saved. Memory will learn from it at the next consolidation.");
      setRating(null);
      setComment("");
      setOverrides([]);
    } catch (err) {
      toast((err as Error).message, true);
    } finally {
      setBusy(false);
    }
  }

  async function learnNow() {
    setBusy(true);
    try {
      const result = await api.learning.consolidate();
      toast(`Memory updated: ${result.summary}`);
    } catch (err) {
      toast((err as Error).message, true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Human feedback"
      hint="Comments become writing guidelines; disagreements with a check become rubric proposals you approve on the Memory page."
      footer={
        <>
          <button className="btn btn-primary" disabled={busy || (!rating && !comment.trim() && !overrides.length)} onClick={submit}>
            Save feedback
          </button>
          <button className="btn" disabled={busy} onClick={learnNow}>
            <Icon name="brain" /> Learn from feedback now
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="row">
          <span className="field-label">Was this lesson good?</span>
          <button
            type="button"
            className="btn btn-sm"
            aria-pressed={rating === "up"}
            style={rating === "up" ? { borderColor: "var(--good)", color: "var(--good-ink)" } : undefined}
            onClick={() => setRating(rating === "up" ? null : "up")}
          >
            <Icon name="thumbUp" /> Good
          </button>
          <button
            type="button"
            className="btn btn-sm"
            aria-pressed={rating === "down"}
            style={rating === "down" ? { borderColor: "var(--critical)", color: "var(--critical-ink)" } : undefined}
            onClick={() => setRating(rating === "down" ? null : "down")}
          >
            <Icon name="thumbDown" /> Needs work
          </button>
        </div>
        <div className="field">
          <label htmlFor="fb-comment">Comment for the writer</label>
          <textarea
            id="fb-comment"
            className="textarea"
            placeholder="e.g. Use a cricket example; the 'vector database' part is still hard to follow."
            value={comment}
            maxLength={2000}
            onChange={(e) => setComment(e.target.value)}
          />
        </div>
        {results.length ? (
          <details>
            <summary>The evaluator got a check wrong</summary>
            <div className="stack" style={{ marginTop: 10 }}>
              <div className="row">
                <select className="select" style={{ maxWidth: 280 }} value={checkId} onChange={(e) => setCheckId(e.target.value)}>
                  <option value="">Choose a check…</option>
                  {results.map((r) => (
                    <option key={r.check_id} value={r.check_id}>
                      {r.check_id} {r.title} (said {r.verdict})
                    </option>
                  ))}
                </select>
                <select className="select" style={{ maxWidth: 160 }} value={verdict} onChange={(e) => setVerdict(e.target.value as Verdict)}>
                  <option value="PASS">Should PASS</option>
                  <option value="FAIL">Should FAIL</option>
                </select>
              </div>
              <input className="input" placeholder="Why? (helps clarify the rubric)" value={note} onChange={(e) => setNote(e.target.value)} />
              <div>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={!checkId}
                  onClick={() => {
                    setOverrides([...overrides.filter((o) => o.check_id !== checkId), { check_id: checkId, human_verdict: verdict, note }]);
                    setCheckId("");
                    setNote("");
                  }}
                >
                  Add correction
                </button>
              </div>
              {overrides.map((o) => (
                <div key={o.check_id} className="row">
                  <span className="mono">{o.check_id}</span>
                  <span>should</span>
                  <VerdictChip verdict={o.human_verdict} />
                  <span className="secondary">{o.note}</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => setOverrides(overrides.filter((x) => x !== o))}>
                    Remove
                  </button>
                </div>
              ))}
            </div>
          </details>
        ) : null}
      </div>
    </Card>
  );
}
