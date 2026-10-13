import { useState } from "react";
import { api } from "../api/client";
import type { DoctorRow } from "../api/types";
import { Icon } from "../components/Icon";
import { Card, ErrorNote, Spinner, useToast } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { formatCost } from "../utils/format";

export function SystemPage() {
  const toast = useToast();
  const status = useAsync(() => api.system.status(), []);
  const [doctor, setDoctor] = useState<DoctorRow[]>();
  const [checking, setChecking] = useState(false);
  const s = status.data;

  async function runDoctor() {
    setChecking(true);
    try {
      setDoctor((await api.system.llmCheck()).results);
    } catch (err) {
      toast((err as Error).message, true);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>System</h1>
          <p className="lead">
            Nine containers behind one gateway: orchestrator API and worker, generator, evaluator, knowledge and memory
            services, plus Postgres and Redis. Only the gateway is exposed.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={status.reload}>
            <Icon name="refresh" /> Refresh
          </button>
        </div>
      </header>
      <ErrorNote error={status.error} />
      {!s && !status.error ? <Spinner label="Checking services…" /> : null}

      {s ? (
        <>
          <div className="kpis">
            {s.services.map((svc) => (
              <div key={svc.name} className="stat">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="stat-label">{svc.name}</span>
                  {svc.ok ? (
                    <span className="badge badge-good">
                      <Icon name="check" size={12} /> ready
                    </span>
                  ) : (
                    <span className="badge badge-critical">
                      <Icon name="x" size={12} /> down
                    </span>
                  )}
                </div>
                <div className="stat-note">
                  {svc.version ? `v${svc.version}` : ""}
                  {svc.checks ? ` · ${Object.entries(svc.checks).map(([k, v]) => `${k}: ${v}`).join(", ")}` : ""}
                  {svc.error ? ` · ${svc.error}` : ""}
                </div>
              </div>
            ))}
            <div className="stat">
              <div className="stat-label">Job queue (Redis Streams)</div>
              <div className="stat-value">{s.queue.pending ?? 0}</div>
              <div className="stat-note">running or waiting · {s.queue.stream_length ?? 0} jobs in the stream</div>
            </div>
          </div>

          <div className="grid-2">
            <Card
              title="Models per role"
              hint={s.llm.configured ? `Azure OpenAI · API ${s.llm.api_version}` : "Azure OpenAI is not configured (.env)"}
              flush
            >
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Role</th>
                      <th>Deployment</th>
                      <th>Reasoning</th>
                      <th>Purpose</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.llm.roles.map((r) => (
                      <tr key={r.role}>
                        <td className="mono nowrap">{r.role}</td>
                        <td className="nowrap">
                          {r.deployment} <span className="tag">{r.tier}</span>
                        </td>
                        <td>{r.reasoning_effort ?? "default"}</td>
                        <td className="secondary">{r.purpose}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <div className="stack">
              <Card title="Loop policy">
                <dl className="kv">
                  <dt>Max retries</dt>
                  <dd>{s.policy.max_retries} (at most {s.policy.max_retries + 1} attempts per run)</dd>
                  <dt>Budget per run</dt>
                  <dd>{formatCost(s.policy.run_budget_usd)} - no new retry starts after it is spent</dd>
                  <dt>Patch vs rewrite</dt>
                  <dd>patch when ≤ {s.policy.patch_max_failed_checks} checks fail, otherwise rewrite</dd>
                  <dt>Helper language</dt>
                  <dd>{s.policy.helper_language}</dd>
                </dl>
              </Card>
              <Card
                title="Verify Azure OpenAI"
                hint="Three tiny calls per deployment: chat, structured output, tool calling."
                footer={
                  <button className="btn btn-primary" onClick={runDoctor} disabled={checking || !s.llm.configured}>
                    {checking ? "Checking…" : "Run LLM check"}
                  </button>
                }
              >
                {doctor ? (
                  <div className="stack" style={{ gap: 8 }}>
                    {doctor.map((row) => (
                      <div key={row.deployment}>
                        <div className="row">
                          <strong>{row.deployment}</strong>
                          {row.ok ? <span className="badge badge-good">all good</span> : <span className="badge badge-critical">problem</span>}
                        </div>
                        {(["chat", "structured_output", "tool_calling"] as const).map((k) => (
                          <div key={k} className="secondary" style={{ fontSize: "0.84rem" }}>
                            {row[k].ok ? "✓" : "✗"} {k.replace("_", " ")} · {row[k].latency_ms} ms {row[k].ok ? "" : `· ${row[k].detail}`}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">{s.llm.configured ? "Not run yet." : "Add your Azure endpoint and key to .env, then restart."}</p>
                )}
              </Card>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
