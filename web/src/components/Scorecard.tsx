import type { CheckMethod, CheckResult, CheckSpec, Dimension, Verdict } from "../api/types";
import { DIMENSION_LABELS, DIMENSION_ORDER, METHOD_LABELS } from "../utils/format";
import { Icon } from "./Icon";
import { VerdictChip } from "./ui";

export interface ScoreItem {
  checkId: string;
  title: string;
  dimension: Dimension;
  method: CheckMethod;
  verdict: Verdict | "PENDING";
  full?: CheckResult;
  reasoning?: string;
}

export function scoreItems(specs: CheckSpec[], results: Record<string, Partial<ScoreItem>>): ScoreItem[] {
  if (!specs.length) {
    return Object.values(results).filter((r): r is ScoreItem => Boolean(r.checkId && r.title));
  }
  return specs.map((spec) => ({
    checkId: spec.id,
    title: spec.title,
    dimension: spec.dimension,
    method: spec.method,
    verdict: "PENDING" as const,
    ...results[spec.id],
  }));
}

export function Scorecard({
  items,
  selected,
  onSelect,
}: {
  items: ScoreItem[];
  selected: string | null;
  onSelect: (checkId: string) => void;
}) {
  return (
    <div className="scorecard">
      {DIMENSION_ORDER.map((dimension) => {
        const group = items.filter((i) => i.dimension === dimension);
        if (!group.length) return null;
        const failed = group.filter((i) => i.verdict === "FAIL").length;
        const done = group.filter((i) => i.verdict !== "PENDING").length;
        return (
          <div key={dimension} className="dimension">
            <h3>
              <span>{DIMENSION_LABELS[dimension]}</span>
              <span>{done < group.length ? `${done}/${group.length}` : failed ? `${failed} failed` : "all pass"}</span>
            </h3>
            {group.map((item) => (
              <button
                key={item.checkId}
                type="button"
                className="check-row"
                aria-pressed={selected === item.checkId}
                onClick={() => onSelect(item.checkId)}
              >
                <VerdictChip verdict={item.verdict} />
                <span className="check-name">
                  <span className="check-id">
                    {item.checkId} · {METHOD_LABELS[item.method]}
                  </span>
                  <span className="check-title">{item.title}</span>
                </span>
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}

type Claim = { id: string; claim: string; quote: string; kind: string; verdict: string; explanation: string };
type Answer = {
  question_id: string;
  question: string;
  answer: string;
  support_quote: string;
  supported_by_lesson: boolean;
  correct: boolean;
  grader_reason: string;
};

function Metrics({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(
    ([k, v]) => !["claims", "answers", "error"].includes(k) && v !== null && v !== undefined && typeof v !== "object",
  );
  const lists = Object.entries(details).filter(([k, v]) => Array.isArray(v) && !["claims", "answers"].includes(k) && v.length);
  if (!entries.length && !lists.length) return null;
  return (
    <dl className="kv">
      {entries.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k.replaceAll("_", " ")}</dt>
          <dd className="tabular">{String(v)}</dd>
        </div>
      ))}
      {lists.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k.replaceAll("_", " ")}</dt>
          <dd>{(v as unknown[]).map(String).join(", ")}</dd>
        </div>
      ))}
    </dl>
  );
}

export function CheckDetail({ item, spec }: { item: ScoreItem; spec?: CheckSpec }) {
  const full = item.full;
  const claims = (full?.details?.claims as Claim[] | undefined) ?? [];
  const answers = (full?.details?.answers as Answer[] | undefined) ?? [];
  return (
    <div className="check-detail">
      <h3>
        <VerdictChip verdict={item.verdict} />
        <span className="mono">{item.checkId}</span>
        <span>{item.title}</span>
        <span className="tag">{METHOD_LABELS[item.method]}</span>
        {full?.severity === "critical" ? <span className="tag">critical</span> : null}
      </h3>
      {spec ? <p className="secondary">PASS only if: {spec.pass_condition}</p> : null}
      {item.verdict === "PENDING" ? <p className="muted">This check is still running…</p> : null}
      {full?.reasoning || item.reasoning ? <p>{full?.reasoning ?? item.reasoning}</p> : null}

      {full?.evidence?.length ? (
        <div className="stack" style={{ gap: 6 }}>
          <span className="field-label">
            Evidence from the lesson{" "}
            {full.evidence_verified === true ? (
              <span className="badge badge-good">
                <Icon name="check" size={12} /> quotes verified
              </span>
            ) : full.evidence_verified === false ? (
              <span className="badge badge-warning">
                <Icon name="alert" size={12} /> quote not found verbatim
              </span>
            ) : null}
          </span>
          {full.evidence.map((e, i) => (
            <blockquote key={i} className="quote">
              {e}
            </blockquote>
          ))}
        </div>
      ) : null}

      {full?.fix_instruction ? (
        <div className="fix">
          <strong>Fix sent to the writer: </strong>
          {full.fix_instruction}
        </div>
      ) : null}

      {full?.votes?.length ? (
        <div className="votes">
          <span className="field-label">Judge votes (a FAIL needs confirmation)</span>
          {full.votes.map((v, i) => (
            <div key={i} className="vote">
              <span className="mono">{v.model}</span>
              <VerdictChip verdict={v.verdict} />
              <span className="secondary">{v.reasoning}</span>
            </div>
          ))}
        </div>
      ) : null}

      {claims.length ? (
        <div className="table-wrap">
          <span className="field-label">Claims checked against the knowledge base</span>
          <table className="table claims">
            <thead>
              <tr>
                <th>Claim</th>
                <th>Verdict</th>
                <th>Knowledge base says</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((c) => (
                <tr key={c.id}>
                  <td>
                    <span className="mono muted">{c.id}</span> {c.claim}
                    {c.kind === "specific_fact" ? <span className="tag" style={{ marginLeft: 6 }}>specific fact</span> : null}
                  </td>
                  <td>
                    <span className={`verdict ${c.verdict === "SUPPORTED" ? "pass" : c.verdict === "CONTRADICTED" ? "fail" : "pending"}`}>
                      {c.verdict.replace("_", " ")}
                    </span>
                  </td>
                  <td className="secondary">{c.explanation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {answers.length ? (
        <div className="table-wrap">
          <span className="field-label">
            Simulated learner: {String(full?.details?.score ?? "?")} / {answers.length} correct (needs{" "}
            {String(full?.details?.needed ?? "?")})
          </span>
          <table className="table">
            <thead>
              <tr>
                <th>Question</th>
                <th>Learner's answer</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {answers.map((a) => (
                <tr key={a.question_id}>
                  <td>{a.question}</td>
                  <td>
                    {a.answer}
                    {a.support_quote ? <div className="muted" style={{ fontSize: "0.8rem" }}>“{a.support_quote}”</div> : null}
                  </td>
                  <td>
                    <VerdictChip verdict={a.correct ? "PASS" : "FAIL"} />
                    {!a.supported_by_lesson ? <div className="muted" style={{ fontSize: "0.78rem" }}>not backed by the lesson</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {full?.details && full.method === "deterministic" ? <Metrics details={full.details} /> : null}
      {full?.details?.error ? (
        <div className="callout callout-critical">
          <Icon name="alert" />
          <span>Evaluation error: {String(full.details.error)}</span>
        </div>
      ) : null}
    </div>
  );
}
