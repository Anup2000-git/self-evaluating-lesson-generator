import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api/client";
import { Icon, type IconName } from "../components/Icon";
import { Card, ErrorNote, Segmented, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { formatCost, formatRelative, MODE_LABELS } from "../utils/format";

const LANGUAGES = ["Hindi", "Marathi", "Bengali", "Gujarati", "Punjabi", "Odia", "Tamil", "Telugu", "Kannada", "Malayalam", "Urdu"];

const STEPS: { icon: IconName; title: string; text: string }[] = [
  { icon: "brain", title: "Recall", text: "Guidelines learned from earlier runs are loaded from memory." },
  { icon: "doc", title: "Plan & write", text: "A planner outlines the lesson; a ReAct writer researches the knowledge base and drafts it." },
  { icon: "rubric", title: "Evaluate", text: "23 hard pass/fail checks: code metrics, focused LLM judges, a fact-check agent and a simulated learner." },
  { icon: "refresh", title: "Regenerate", text: "Failed checks and their fixes go back to the writer - at most 2 retries, so it always stops." },
  { icon: "check", title: "Ship & learn", text: "A passing lesson ships with its rejection log; memory turns failures into new guidelines." },
];

export function StudioPage() {
  const navigate = useNavigate();
  const topics = useAsync(() => api.topics(), []);
  const recent = useAsync(() => api.runs.list({ limit: 6 }), []);
  const [topic, setTopic] = useState("Introduction to RAG");
  const [language, setLanguage] = useState("Hindi");
  const [retries, setRetries] = useState(2);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<Error>();

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(undefined);
    try {
      const run = await api.runs.create({ topic, helper_language: language, max_retries: retries, mode: "generate" });
      navigate(`/runs/${run.id}`);
    } catch (err) {
      setError(err as Error);
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Create a beginner lesson</h1>
          <p className="lead">
            The system writes a lesson for a 12th-grade graduate from a non-English-medium school, judges it against a
            strict rubric, and keeps improving it until every check passes - before a human ever sees it.
          </p>
        </div>
      </header>

      <div className="split">
        <Card title="New run" hint="Topics must have a curated knowledge pack, so every fact can be checked.">
          <form className="stack" onSubmit={submit}>
            <div className="field">
              <label htmlFor="topic">Topic</label>
              <input
                id="topic"
                className="input"
                list="topic-options"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                required
                minLength={2}
                maxLength={200}
              />
              <datalist id="topic-options">
                {topics.data?.map((t) => (
                  <option key={t.id} value={t.title} />
                ))}
              </datalist>
              <span className="help">
                Available packs: {topics.data?.map((t) => t.title).join(", ") || "loading…"}
              </span>
            </div>
            <div className="grid-2">
              <div className="field">
                <label htmlFor="language">Helper language for word hints</label>
                <select id="language" className="select" value={language} onChange={(e) => setLanguage(e.target.value)}>
                  {LANGUAGES.map((l) => (
                    <option key={l}>{l}</option>
                  ))}
                </select>
                <span className="help">Hindi uses reviewed meanings from the knowledge pack.</span>
              </div>
              <div className="field">
                <span className="field-label">Maximum retries</span>
                <Segmented
                  label="Maximum retries"
                  value={retries}
                  onChange={setRetries}
                  options={[
                    { value: 1, label: "1 retry" },
                    { value: 2, label: "2 retries" },
                  ]}
                />
                <span className="help">The loop stops after {retries + 1} attempts at most.</span>
              </div>
            </div>
            <ErrorNote error={error} />
            <div className="row">
              <button className="btn btn-primary btn-lg" type="submit" disabled={submitting}>
                <Icon name="spark" />
                {submitting ? "Starting…" : "Generate lesson"}
              </button>
              <span className="muted">Watch the agents work live on the next screen.</span>
            </div>
          </form>
        </Card>

        <Card title="How it works">
          <ol className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: 12 }}>
            {STEPS.map((s) => (
              <li key={s.title} className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                <span className="badge badge-accent" style={{ padding: 6 }}>
                  <Icon name={s.icon} />
                </span>
                <span>
                  <strong>{s.title}</strong>
                  <br />
                  <span className="secondary">{s.text}</span>
                </span>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      <Card title="Recent runs" actions={<Link to="/runs">All runs</Link>} flush>
        <ErrorNote error={recent.error} />
        {recent.data && recent.data.items.length === 0 ? (
          <div className="empty">No runs yet - start one above.</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Topic</th>
                  <th>Mode</th>
                  <th className="num">Attempts</th>
                  <th className="num">Cost</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {recent.data?.items.map((run) => (
                  <tr key={run.id} className="clickable" onClick={() => navigate(`/runs/${run.id}`)}>
                    <td>
                      <StatusBadge status={run.status} />
                    </td>
                    <td>
                      <Link to={`/runs/${run.id}`}>{run.topic}</Link>
                    </td>
                    <td className="secondary">{MODE_LABELS[run.mode]}</td>
                    <td className="num">{run.attempts_count}</td>
                    <td className="num">{formatCost(run.usage?.cost_usd)}</td>
                    <td className="secondary nowrap">{formatRelative(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
