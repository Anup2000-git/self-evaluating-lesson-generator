import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import type { FaultInfo, Lesson, RunMode } from "../api/types";
import { Icon } from "../components/Icon";
import { LessonViewer } from "../components/LessonViewer";
import { Card, ErrorNote, Segmented, Spinner, useToast } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

type Source = "reference" | "run";

export function LabPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const faults = useAsync(() => api.evaluator.faults(), []);
  const topics = useAsync(() => api.topics(), []);
  const shipped = useAsync(() => api.runs.list({ status: "shipped", limit: 20 }), []);
  const [source, setSource] = useState<Source>("reference");
  const [runId, setRunId] = useState("");
  const [base, setBase] = useState<Lesson>();
  const [faultId, setFaultId] = useState<string>("factual_error");
  const [working, setWorking] = useState<Lesson>();
  const [applied, setApplied] = useState<FaultInfo>();
  const [error, setError] = useState<Error>();
  const [busy, setBusy] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  // 1. Load the base lesson.
  useEffect(() => {
    let cancelled = false;
    setError(undefined);
    const load =
      source === "reference"
        ? api.evaluator.referenceLesson()
        : runId
          ? api.runs.get(runId).then((r) => {
              const final = r.attempts.find((a) => a.attempt_no === r.final_attempt_no) ?? r.attempts.at(-1);
              if (!final) throw new Error("That run has no evaluated lesson.");
              return final.lesson;
            })
          : Promise.resolve(undefined);
    load
      .then((lesson) => !cancelled && setBase(lesson))
      .catch((err: Error) => !cancelled && setError(err));
    return () => {
      cancelled = true;
    };
  }, [source, runId]);

  // 2. Apply the selected fault to it.
  useEffect(() => {
    if (!base) {
      setWorking(undefined);
      return;
    }
    if (!faultId) {
      setWorking(base);
      setApplied(undefined);
      return;
    }
    let cancelled = false;
    api.evaluator
      .applyFault(base, faultId)
      .then((result) => {
        if (!cancelled) {
          setWorking(result.lesson);
          setApplied(result.fault);
        }
      })
      .catch((err: Error) => !cancelled && setError(err));
    return () => {
      cancelled = true;
    };
  }, [base, faultId]);

  async function start(mode: RunMode) {
    if (!working) return;
    setBusy(true);
    try {
      const topic = topics.data?.[0]?.title ?? "Introduction to RAG";
      const run = await api.runs.create({
        topic,
        mode,
        initial_lesson: working,
        fault_id: faultId || undefined,
        max_retries: mode === "repair" ? 2 : 0,
      });
      navigate(`/runs/${run.id}`);
    } catch (err) {
      toast((err as Error).message, true);
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Evaluator Lab</h1>
          <p className="lead">
            Plant a deliberate mistake in a good lesson and watch the evaluator catch it - then let the loop repair it.
            Each preset declares which rubric checks should fail, so you can see expected vs caught.
          </p>
        </div>
      </header>

      <Card title="1 · Pick a lesson">
        <div className="stack">
          <Segmented
            label="Lesson source"
            value={source}
            onChange={setSource}
            options={[
              { value: "reference", label: "Reference lesson (reviewed)" },
              { value: "run", label: "From a shipped run" },
            ]}
          />
          {source === "run" ? (
            <select className="select" style={{ maxWidth: 520 }} value={runId} onChange={(e) => setRunId(e.target.value)}>
              <option value="">Choose a shipped run…</option>
              {shipped.data?.items.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.topic} · {r.id} · {new Date(r.created_at).toLocaleString()}
                </option>
              ))}
            </select>
          ) : null}
          {source === "run" && shipped.data?.items.length === 0 ? (
            <p className="muted">No shipped runs yet - use the reference lesson.</p>
          ) : null}
          {base ? (
            <p className="secondary">
              Loaded: <strong>{base.title}</strong> · {base.sections.length} sections · {base.glossary.length} glossary
              words · {base.quiz.length} quiz questions
            </p>
          ) : null}
        </div>
      </Card>

      <Card title="2 · Inject a deliberate error">
        <ErrorNote error={faults.error ?? error} />
        <div className="scorecard">
          <button
            type="button"
            className="check-row"
            aria-pressed={faultId === ""}
            onClick={() => setFaultId("")}
            style={{ gridTemplateColumns: "1fr" }}
          >
            <span className="check-name">
              <span className="check-title">No fault</span>
              <span className="check-id">Evaluate the lesson exactly as it is</span>
            </span>
          </button>
          {faults.data?.map((f) => (
            <button
              key={f.id}
              type="button"
              className="check-row"
              aria-pressed={faultId === f.id}
              onClick={() => setFaultId(f.id)}
              style={{ gridTemplateColumns: "1fr" }}
            >
              <span className="check-name">
                <span className="check-title">{f.title}</span>
                <span className="secondary" style={{ fontSize: "0.82rem" }}>
                  {f.description}
                </span>
                <span className="check-id">expected: {f.expected_checks.join(", ")}</span>
              </span>
            </button>
          ))}
        </div>
        {applied ? (
          <div className="stack" style={{ marginTop: 14, gap: 8 }}>
            <span className="field-label">What was changed</span>
            <blockquote className="quote">{applied.injected_text}</blockquote>
          </div>
        ) : null}
      </Card>

      <Card
        title="3 · Run the evaluator"
        footer={
          <>
            <button className="btn btn-primary" disabled={!working || busy} onClick={() => start("evaluate_only")}>
              <Icon name="rubric" /> Evaluate only
            </button>
            <button className="btn" disabled={!working || busy} onClick={() => start("repair")}>
              <Icon name="refresh" /> Evaluate + repair (up to 2 retries)
            </button>
            <span className="spacer" />
            <button className="btn btn-ghost" disabled={!working} onClick={() => setShowPreview((v) => !v)}>
              <Icon name="eye" /> {showPreview ? "Hide" : "Preview"} lesson
            </button>
          </>
        }
      >
        <p className="secondary">
          <strong>Evaluate only</strong> runs all 23 checks once and reports. <strong>Evaluate + repair</strong> feeds
          the failures back to the writer, which fixes them, and the loop re-checks until it passes or retries run out.
        </p>
        {!working && !error ? <Spinner label="Preparing the lesson…" /> : null}
        {showPreview && working ? (
          <div style={{ marginTop: 16 }}>
            <LessonViewer lesson={working} />
          </div>
        ) : null}
      </Card>
    </div>
  );
}
