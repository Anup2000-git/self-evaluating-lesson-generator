import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { SearchResponse } from "../api/types";
import { Icon } from "../components/Icon";
import { Card, ErrorNote, Spinner } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

export function KnowledgePage() {
  const topics = useAsync(() => api.topics(), []);
  const [topicId, setTopicId] = useState("");
  useEffect(() => {
    if (!topicId && topics.data?.length) setTopicId(topics.data[0].id);
  }, [topics.data, topicId]);
  const pack = useAsync(() => (topicId ? api.knowledge.topic(topicId) : Promise.resolve(undefined)), [topicId]);
  const glossary = useAsync(() => (topicId ? api.knowledge.glossary(topicId) : Promise.resolve([])), [topicId]);
  const documents = useAsync(() => (topicId ? api.knowledge.documents(topicId) : Promise.resolve([])), [topicId]);
  const [query, setQuery] = useState("Why do LLMs give outdated answers?");
  const [results, setResults] = useState<SearchResponse>();
  const [searchError, setSearchError] = useState<Error>();
  const kp = pack.data?.key_points;

  async function search(event: FormEvent) {
    event.preventDefault();
    setSearchError(undefined);
    try {
      setResults(await api.knowledge.search(topicId, query, 4));
    } catch (err) {
      setSearchError(err as Error);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Knowledge packs</h1>
          <p className="lead">
            The curated, sourced ground truth. The writer researches from it (RAG for writing about RAG) and the
            fact-checker verifies every claim against it. Topics without a pack are refused rather than guessed.
          </p>
        </div>
        <div className="page-actions">
          <select className="select" value={topicId} onChange={(e) => setTopicId(e.target.value)} aria-label="Topic">
            {topics.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
        </div>
      </header>
      <ErrorNote error={topics.error ?? pack.error} />

      <div className="grid-2">
        <Card title="What every lesson must teach" hint={pack.data ? `pack ${pack.data.id} · v${pack.data.version}` : undefined}>
          {kp ? (
            <dl className="kv">
              <dt>What</dt>
              <dd>{kp.what}</dd>
              <dt>Why</dt>
              <dd>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {kp.why.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </dd>
              <dt>How</dt>
              <dd>
                <ol style={{ margin: 0, paddingLeft: 18 }}>
                  {kp.how_steps.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ol>
              </dd>
              <dt>Misconceptions</dt>
              <dd>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {kp.misconceptions.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </dd>
            </dl>
          ) : (
            <Spinner label="Loading pack…" />
          )}
        </Card>

        <Card title="Try the retriever" hint="The same search the writer and fact-checker agents call as a tool.">
          <form className="row" onSubmit={search} style={{ flexWrap: "nowrap" }}>
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search query" />
            <button className="btn btn-primary" type="submit" disabled={!topicId || !query.trim()}>
              <Icon name="eye" /> Search
            </button>
          </form>
          <ErrorNote error={searchError} />
          {results ? (
            <div className="stack" style={{ marginTop: 12, gap: 10 }}>
              <span className="muted">Retriever: {results.retriever}</span>
              {results.hits.map((h) => (
                <div key={h.chunk.id}>
                  <div className="row" style={{ gap: 8 }}>
                    <strong>{h.chunk.heading}</strong>
                    <span className="tag mono">score {h.score}</span>
                  </div>
                  <div className="mono muted">{h.chunk.id}</div>
                  <p className="secondary" style={{ marginTop: 4, fontSize: "0.88rem" }}>
                    {h.chunk.text.length > 320 ? `${h.chunk.text.slice(0, 320)}…` : h.chunk.text}
                  </p>
                </div>
              ))}
            </div>
          ) : null}
        </Card>
      </div>

      <Card title="Approved glossary" hint="Simple meanings and reviewed Hindi hints, served to the writer by the lookup_glossary tool." flush>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Term</th>
                <th>Simple meaning</th>
                <th>Hindi</th>
              </tr>
            </thead>
            <tbody>
              {glossary.data?.map((g) => (
                <tr key={g.term}>
                  <td>
                    <strong>{g.term}</strong>
                    {g.aliases.length ? <div className="muted" style={{ fontSize: "0.78rem" }}>{g.aliases.join(", ")}</div> : null}
                  </td>
                  <td>{g.simple_meaning}</td>
                  <td className="hindi">{g.translations.hindi ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Source documents" hint={`${documents.data?.length ?? 0} curated notes, chunked by heading`}>
        <div className="stack" style={{ gap: 8 }}>
          {documents.data?.map((d) => (
            <details key={d.id}>
              <summary>
                {d.title} <span className="muted">· {d.chunks.length} sections</span>
              </summary>
              <p className="muted" style={{ margin: "6px 0", fontSize: "0.82rem" }}>
                Source: {d.source}
              </p>
              {d.chunks.map((c) => (
                <div key={c.id} style={{ margin: "8px 0 12px" }}>
                  <strong style={{ fontSize: "0.9rem" }}>{c.heading}</strong>
                  <p className="secondary" style={{ fontSize: "0.88rem" }}>
                    {c.text}
                  </p>
                </div>
              ))}
            </details>
          ))}
        </div>
      </Card>
    </div>
  );
}
