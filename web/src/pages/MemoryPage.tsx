import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { Guideline, RubricProposal } from "../api/types";
import { BarChart } from "../components/charts/BarChart";
import { ColumnChart } from "../components/charts/ColumnChart";
import { Icon } from "../components/Icon";
import { Card, ErrorNote, Segmented, useToast, VerdictChip } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { formatCost, formatPercent, formatRelative } from "../utils/format";

function StatTile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {note ? <div className="stat-note">{note}</div> : null}
    </div>
  );
}

function effectiveness(g: Guideline): string {
  const judged = g.times_helped + g.times_missed;
  return judged ? `${Math.round((g.times_helped / judged) * 100)}%` : "-";
}

function ProposalCard({ proposal, onDecided }: { proposal: RubricProposal; onDecided: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const change = proposal.proposed_change as Record<string, unknown>;
  const notes = [
    ...((change.add_notes as string[] | undefined) ?? []).map((n) => `Note: ${n}`),
    ...((change.add_pass_criteria as string[] | undefined) ?? []).map((n) => `Pass criterion: ${n}`),
    ...((change.add_fail_criteria as string[] | undefined) ?? []).map((n) => `Fail criterion: ${n}`),
  ];

  async function decide(approve: boolean) {
    setBusy(true);
    try {
      const result = approve ? await api.memory.approve(proposal.id) : await api.memory.reject(proposal.id);
      toast(
        approve
          ? result.resulting_version
            ? `Approved - rubric v${result.resulting_version} is now active.`
            : "Approved - noted for the engineering team."
          : "Rejected.",
      );
      onDecided();
    } catch (err) {
      toast((err as Error).message, true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ padding: "14px 16px" }}>
      <div className="row">
        <strong>{proposal.title}</strong>
        <span className="tag">{proposal.kind === "clarify_check" ? "rubric clarification" : "needs engineering"}</span>
        <span className="tag">from {proposal.source}</span>
        {proposal.check_id ? <span className="tag mono">{proposal.check_id}</span> : null}
        <span className="spacer" />
        <span className="muted">{formatRelative(proposal.created_at)}</span>
      </div>
      <p className="secondary" style={{ marginTop: 6 }}>
        {proposal.rationale}
      </p>
      {notes.length ? (
        <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
      {proposal.evidence.length ? <p className="muted" style={{ marginTop: 6 }}>Evidence: {proposal.evidence.join(" · ")}</p> : null}
      {proposal.status === "pending" ? (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => decide(true)}>
            Approve
          </button>
          <button className="btn btn-sm" disabled={busy} onClick={() => decide(false)}>
            Reject
          </button>
          <span className="muted" style={{ fontSize: "0.8rem" }}>
            The rubric never changes without a human decision.
          </span>
        </div>
      ) : (
        <p className="muted" style={{ marginTop: 6 }}>
          {proposal.status} {proposal.resulting_version ? `→ rubric v${proposal.resulting_version}` : ""}
        </p>
      )}
    </div>
  );
}

export function MemoryPage() {
  const toast = useToast();
  const stats = useAsync(() => api.memory.stats(), []);
  const [showRetired, setShowRetired] = useState<"active" | "retired">("active");
  const guidelines = useAsync(() => api.memory.guidelines(showRetired), [showRetired]);
  const proposals = useAsync(() => api.memory.proposals(), []);
  const feedback = useAsync(() => api.memory.feedback(), []);
  const s = stats.data;

  const trend = (s?.trend ?? []).map((p, i) => ({
    key: p.run_id,
    label: `#${i + 1}`,
    value: p.first_attempt_failed_checks,
    extra: [
      `run ${p.run_id}`,
      `${p.status.replaceAll("_", " ")} after ${p.attempts} attempt${p.attempts === 1 ? "" : "s"}`,
      `${p.guidelines_applied} guideline(s) applied`,
      `cost ${formatCost(p.cost_usd)}`,
    ],
  }));
  const checks = (s?.checks ?? [])
    .filter((c) => c.first_attempt_fail_rate > 0)
    .slice(0, 10)
    .map((c) => ({
      key: c.check_id,
      label: c.check_id,
      value: c.first_attempt_fail_rate,
      extra: [`failed first in ${c.first_attempt_failures} of ${c.runs} runs`, `failed at any attempt in ${c.any_attempt_failures}`],
    }));

  async function retire(g: Guideline, status: "active" | "retired") {
    try {
      await api.memory.updateGuideline(g.id, { status, reason: status === "retired" ? "retired by a human" : "re-activated by a human" });
      guidelines.reload();
      stats.reload();
    } catch (err) {
      toast((err as Error).message, true);
    }
  }

  async function learnNow() {
    try {
      const result = await api.learning.consolidate();
      toast(`Memory updated: ${result.summary}`);
      guidelines.reload();
      proposals.reload();
      feedback.reload();
      stats.reload();
    } catch (err) {
      toast((err as Error).message, true);
    }
  }

  const pending = proposals.data?.filter((p) => p.status === "pending") ?? [];
  const decided = proposals.data?.filter((p) => p.status !== "pending").slice(0, 5) ?? [];

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Memory &amp; learning</h1>
          <p className="lead">
            After every run the system turns what failed - and what fixed it - into short writing guidelines that are
            injected into the next run. Guidelines that do not help are retired automatically; rubric changes always need
            your approval.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={learnNow}>
            <Icon name="brain" /> Process pending feedback
          </button>
        </div>
      </header>
      <ErrorNote error={stats.error} />

      <div className="kpis">
        <StatTile label="Runs with a verdict" value={String(s?.runs_total ?? "-")} note={`${s?.runs_shipped ?? 0} shipped · ${s?.runs_needs_review ?? 0} need review`} />
        <StatTile label="First-attempt pass rate" value={formatPercent(s?.first_pass_rate)} note="passed all checks with no retry" />
        <StatTile label="Average attempts per run" value={s?.avg_attempts?.toFixed(2) ?? "-"} note="1 = shipped first time" />
        <StatTile label="Average cost per run" value={formatCost(s?.avg_cost_usd)} note={`${formatCost(s?.total_cost_usd)} in total`} />
        <StatTile label="Active guidelines" value={String(s?.guidelines_active ?? "-")} note={`${s?.guidelines_retired ?? 0} retired`} />
        <StatTile label="Proposals awaiting you" value={String(s?.pending_proposals ?? "-")} note="rubric changes need approval" />
      </div>

      <div className="grid-2">
        <Card>
          <ColumnChart
            title="Checks failed on the first attempt, per run"
            subtitle="Learning shows up as this falling over time (runs in order)."
            data={trend}
            valueLabel="Checks failed on attempt 1"
            format={(v) => String(Math.round(v))}
            integer
          />
        </Card>
        <Card>
          <BarChart
            title="First-attempt failure rate by check"
            subtitle="Where the writer still struggles most before any retry."
            data={checks}
            valueLabel="First-attempt failure rate"
            format={(v) => formatPercent(v)}
            max={1}
          />
        </Card>
      </div>

      <Card
        title="Learned guidelines"
        hint="Injected into the planner/writer prompts at the start of every run, best first."
        actions={
          <Segmented
            label="Guideline status"
            value={showRetired}
            onChange={setShowRetired}
            options={[
              { value: "active", label: "Active" },
              { value: "retired", label: "Retired" },
            ]}
          />
        }
        flush
      >
        <ErrorNote error={guidelines.error} />
        {guidelines.data?.length === 0 ? (
          <div className="empty">No {showRetired} guidelines yet - they appear after runs with failures or feedback.</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Guideline</th>
                  <th>Prevents</th>
                  <th>For</th>
                  <th className="num">Applied</th>
                  <th className="num">Helped</th>
                  <th className="num">Missed</th>
                  <th className="num">Effective</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {guidelines.data?.map((g) => (
                  <tr key={g.id}>
                    <td style={{ minWidth: 280 }}>
                      {g.text}
                      <div className="muted" style={{ fontSize: "0.78rem" }}>
                        <span className="mono">{g.id}</span> · v{g.version} · from {g.origin}
                        {g.created_from_run ? (
                          <>
                            {" "}
                            · <Link to={`/runs/${g.created_from_run}`}>{g.created_from_run}</Link>
                          </>
                        ) : null}
                      </div>
                      {g.history.length > 1 ? (
                        <details style={{ marginTop: 4 }}>
                          <summary style={{ fontSize: "0.8rem" }}>History ({g.history.length})</summary>
                          <ol style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: "0.82rem" }}>
                            {g.history.map((h) => (
                              <li key={`${h.version}-${h.at}`}>
                                <strong>v{h.version}</strong> {h.text} <span className="muted">- {h.reason}</span>
                              </li>
                            ))}
                          </ol>
                        </details>
                      ) : null}
                    </td>
                    <td className="mono">{g.check_ids.join(", ")}</td>
                    <td>{g.target}</td>
                    <td className="num">{g.times_applied}</td>
                    <td className="num">{g.times_helped}</td>
                    <td className="num">{g.times_missed}</td>
                    <td className="num">{effectiveness(g)}</td>
                    <td>
                      <button className="btn btn-ghost btn-sm" onClick={() => retire(g, g.status === "active" ? "retired" : "active")}>
                        {g.status === "active" ? "Retire" : "Re-activate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Rubric proposals" hint="From human feedback and from checks that keep failing despite guidelines.">
        <ErrorNote error={proposals.error} />
        <div className="stack">
          {pending.length === 0 ? <p className="muted">Nothing is waiting for a decision.</p> : null}
          {pending.map((p) => (
            <ProposalCard
              key={p.id}
              proposal={p}
              onDecided={() => {
                proposals.reload();
                stats.reload();
              }}
            />
          ))}
          {decided.length ? (
            <details>
              <summary>Recently decided ({decided.length})</summary>
              <div className="stack" style={{ marginTop: 10 }}>
                {decided.map((p) => (
                  <ProposalCard key={p.id} proposal={p} onDecided={proposals.reload} />
                ))}
              </div>
            </details>
          ) : null}
        </div>
      </Card>

      <Card title="Human feedback" flush>
        {feedback.data?.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Rating</th>
                  <th>Comment</th>
                  <th>Check corrections</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {feedback.data.slice(0, 20).map((f) => (
                  <tr key={f.id}>
                    <td>
                      <Link to={`/runs/${f.run_id}`} className="mono">
                        {f.run_id}
                      </Link>
                    </td>
                    <td>{f.rating === "up" ? "Good" : f.rating === "down" ? "Needs work" : "-"}</td>
                    <td>{f.comment || <span className="muted">-</span>}</td>
                    <td>
                      {f.check_overrides.map((o) => (
                        <div key={o.check_id} className="row" style={{ gap: 6 }}>
                          <span className="mono">{o.check_id}</span> should <VerdictChip verdict={o.human_verdict} />
                        </div>
                      ))}
                    </td>
                    <td>{f.processed ? <span className="badge badge-good">learned</span> : <span className="badge">pending</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">No feedback yet. Add some on any finished run.</div>
        )}
      </Card>
    </div>
  );
}
