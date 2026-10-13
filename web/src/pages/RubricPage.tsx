import { api } from "../api/client";
import type { CheckSpec } from "../api/types";
import { Card, ErrorNote, Spinner } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { DIMENSION_LABELS, DIMENSION_ORDER, formatRelative, METHOD_LABELS } from "../utils/format";

function CheckCard({ check }: { check: CheckSpec }) {
  return (
    <div style={{ padding: "12px 0", borderBottom: "1px solid var(--border)" }}>
      <div className="row">
        <span className="mono" style={{ fontWeight: 600 }}>
          {check.id}
        </span>
        <strong>{check.title}</strong>
        <span className="tag">{METHOD_LABELS[check.method]}</span>
        {check.severity === "critical" ? <span className="tag">critical</span> : null}
      </div>
      <p className="secondary" style={{ marginTop: 4 }}>
        PASS only if: {check.pass_condition}
      </p>
      {check.judge ? (
        <details style={{ marginTop: 6 }}>
          <summary style={{ fontSize: "0.86rem" }}>Judge instructions</summary>
          <div className="stack" style={{ gap: 6, marginTop: 8, fontSize: "0.88rem" }}>
            <div>
              <strong>Question:</strong> {check.judge.question}
            </div>
            <div>
              <strong>Pass if all:</strong>
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {check.judge.pass_criteria.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
            <div>
              <strong>Fail if any:</strong>
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {check.judge.fail_criteria.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
            {check.judge.notes.length ? (
              <div>
                <strong>Clarifications approved by reviewers:</strong>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {check.judge.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}
      {Object.keys(check.params).length ? (
        <div className="row" style={{ marginTop: 6, gap: 6 }}>
          {Object.entries(check.params).map(([k, v]) => (
            <span key={k} className="tag mono">
              {k}={String(v)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function RubricPage() {
  const active = useAsync(() => api.memory.activeRubric(), []);
  const versions = useAsync(() => api.memory.rubricVersions(), []);
  const rubric = active.data?.rubric;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Rubric {rubric ? `v${rubric.version}` : ""}</h1>
          <p className="lead">
            {rubric?.description ??
              "Hard pass/fail checkpoints. A lesson ships only when every single check passes - there is no partial credit."}
          </p>
        </div>
        {rubric ? (
          <div className="page-actions">
            <span className="badge badge-accent">{rubric.checks.length} checks</span>
            <span className="badge">ship policy: all must pass</span>
          </div>
        ) : null}
      </header>
      <ErrorNote error={active.error} />
      {!rubric && !active.error ? <Spinner label="Loading rubric…" /> : null}

      {rubric ? (
        <div className="grid-2">
          {DIMENSION_ORDER.map((dimension) => {
            const checks = rubric.checks.filter((c) => c.dimension === dimension);
            return (
              <Card key={dimension} title={DIMENSION_LABELS[dimension]} hint={`${checks.length} checks`}>
                <div style={{ marginTop: -12 }}>
                  {checks.map((c) => (
                    <CheckCard key={c.id} check={c} />
                  ))}
                </div>
              </Card>
            );
          })}
        </div>
      ) : null}

      <Card title="Version history" hint="New versions come only from human-approved proposals." flush>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Version</th>
                <th>Status</th>
                <th>Change</th>
                <th>By</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {versions.data?.map((v) => (
                <tr key={v.version}>
                  <td className="mono">v{v.version}</td>
                  <td>{v.status === "active" ? <span className="badge badge-good">active</span> : <span className="badge">superseded</span>}</td>
                  <td>{v.change_note}</td>
                  <td className="secondary">{v.created_by}</td>
                  <td className="secondary nowrap">{formatRelative(v.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
