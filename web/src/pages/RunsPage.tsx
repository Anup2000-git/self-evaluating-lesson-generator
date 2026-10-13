import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api/client";
import { Card, ErrorNote, Segmented, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { formatCost, formatDuration, formatRelative, MODE_LABELS } from "../utils/format";

const PAGE = 20;
const FILTERS = [
  { value: "", label: "All" },
  { value: "shipped", label: "Shipped" },
  { value: "needs_human_review", label: "Needs review" },
  { value: "running", label: "Running" },
  { value: "failed", label: "Failed" },
];

export function RunsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const runs = useAsync(() => api.runs.list({ limit: PAGE, offset, status: status || undefined }), [status, offset]);
  const total = runs.data?.total ?? 0;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Runs</h1>
          <p className="lead">Every run is stored with all its attempts, evaluations and rejection log.</p>
        </div>
        <div className="page-actions">
          <Segmented
            label="Filter by status"
            value={status}
            onChange={(v) => {
              setStatus(v);
              setOffset(0);
            }}
            options={FILTERS}
          />
          <button className="btn" onClick={runs.reload}>
            Refresh
          </button>
        </div>
      </header>
      <Card flush>
        <ErrorNote error={runs.error} />
        <div className="table-wrap" style={{ opacity: runs.loading && runs.data ? 0.6 : 1 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Topic</th>
                <th>Mode</th>
                <th className="num">Attempts</th>
                <th className="num">Guidelines used</th>
                <th className="num">Cost</th>
                <th className="num">Duration</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {runs.data?.items.map((run) => (
                <tr key={run.id} className="clickable" onClick={() => navigate(`/runs/${run.id}`)}>
                  <td>
                    <StatusBadge status={run.status} />
                  </td>
                  <td>
                    <Link to={`/runs/${run.id}`}>{run.topic}</Link>
                    <div className="mono muted">{run.id}</div>
                  </td>
                  <td className="secondary">{MODE_LABELS[run.mode]}</td>
                  <td className="num">
                    {run.attempts_count}/{run.max_retries + 1}
                  </td>
                  <td className="num">{run.guideline_ids_applied.length}</td>
                  <td className="num">{formatCost(run.usage?.cost_usd)}</td>
                  <td className="num">{formatDuration(run.started_at, run.finished_at)}</td>
                  <td className="secondary nowrap">{formatRelative(run.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {runs.data && runs.data.items.length === 0 ? <div className="empty">No runs match this filter.</div> : null}
        </div>
        <div className="card-footer">
          <span className="muted">
            {total ? `${offset + 1}-${Math.min(offset + PAGE, total)} of ${total}` : "0 runs"}
          </span>
          <span className="spacer" />
          <button className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Previous
          </button>
          <button className="btn btn-sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
            Next
          </button>
        </div>
      </Card>
    </div>
  );
}
