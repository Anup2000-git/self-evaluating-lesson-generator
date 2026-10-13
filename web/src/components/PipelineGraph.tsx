import type { NodeState, NodeStatus, PipelineNode } from "../state/runStream";

// The LangGraph state machine, drawn as it is wired in orchestrator_svc/graph/pipeline.py.
const W = 124;
const H = 46;

interface Box {
  x: number;
  y: number;
  title: string;
  sub: string;
}

const BOXES: Record<PipelineNode, Box> = {
  recall_memory: { x: 10, y: 30, title: "Recall memory", sub: "learned guidelines" },
  plan: { x: 154, y: 30, title: "Plan", sub: "planner" },
  write: { x: 298, y: 30, title: "Write", sub: "ReAct writer" },
  evaluate: { x: 442, y: 30, title: "Evaluate", sub: "23 pass/fail checks" },
  revise: { x: 442, y: 150, title: "Revise", sub: "patch or rewrite" },
  select_best: { x: 716, y: 150, title: "Select best", sub: "for human review" },
  finalize: { x: 716, y: 30, title: "Finalize", sub: "ship or escalate" },
  consolidate_memory: { x: 860, y: 30, title: "Update memory", sub: "self-evolving" },
};

const DIAMOND = { cx: 638, cy: 53, rx: 36, ry: 27 };

function NodeBox({ id, state, badge }: { id: PipelineNode; state: NodeState; badge?: string }) {
  const box = BOXES[id];
  const status: NodeStatus = state.status;
  const label = `${box.title}: ${status}${state.visits > 1 ? `, ${state.visits} visits` : ""}${state.summary ? `. ${state.summary}` : ""}`;
  return (
    <g className={`node ${status}`} role="img" aria-label={label}>
      <title>{label}</title>
      {status === "active" ? (
        <rect className="ring" x={box.x - 3} y={box.y - 3} width={W + 6} height={H + 6} rx={11} fill="none" strokeWidth={1.5} />
      ) : null}
      <rect x={box.x} y={box.y} width={W} height={H} rx={9} />
      <text x={box.x + 12} y={box.y + 20}>
        {box.title}
      </text>
      <text className="sub" x={box.x + 12} y={box.y + 36}>
        {box.sub}
      </text>
      {status !== "pending" ? (
        <circle className={`status-dot ${status}`} cx={box.x + W - 12} cy={box.y + 12} r={4.5} />
      ) : null}
      {state.visits > 1 ? (
        <text className="sub" x={box.x + W - 12} y={box.y + 36} textAnchor="end">
          ×{state.visits}
        </text>
      ) : null}
      {badge ? (
        <g>
          <rect className="badge-bg" x={box.x + W - 78} y={box.y - 24} width={78} height={18} rx={9} />
          <text className="badge-text" x={box.x + W - 39} y={box.y - 11} textAnchor="middle">
            {badge}
          </text>
        </g>
      ) : null}
    </g>
  );
}

export function PipelineGraph({
  nodes,
  activeNode,
  attempt,
  maxAttempts,
}: {
  nodes: Record<PipelineNode, NodeState>;
  activeNode: PipelineNode | null;
  attempt: number;
  maxAttempts: number;
}) {
  const hot = (to: PipelineNode) => (activeNode === to ? "edge hot" : "edge");
  const routeVisited = nodes.evaluate.status === "done" || nodes.evaluate.visits > 0;
  return (
    <div className="pipeline-scroll">
      <svg className="pipeline" viewBox="0 0 994 214" role="group" aria-label="Agentic pipeline">
        <defs>
          <marker id="arrowhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 10 5 0 10z" fill="var(--axis)" />
          </marker>
          <marker id="arrowhead-hot" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 10 5 0 10z" fill="var(--accent)" />
          </marker>
        </defs>

        {[
          ["M134 53 H152", "plan"],
          ["M278 53 H296", "write"],
          ["M422 53 H440", "evaluate"],
        ].map(([d, to]) => (
          <path key={d} d={d} className={hot(to as PipelineNode)} markerEnd={`url(#${activeNode === to ? "arrowhead-hot" : "arrowhead"})`} />
        ))}
        <path d={`M566 53 H${DIAMOND.cx - DIAMOND.rx - 2}`} className="edge" markerEnd="url(#arrowhead)" />
        <path d={`M${DIAMOND.cx + DIAMOND.rx} 53 H714`} className={hot("finalize")} markerEnd={`url(#${activeNode === "finalize" ? "arrowhead-hot" : "arrowhead"})`} />
        <text className="edge-label" x={680} y={45} textAnchor="middle">
          pass
        </text>
        <path d={`M${DIAMOND.cx} ${DIAMOND.cy + DIAMOND.ry} V173 H568`} className={hot("revise")} markerEnd={`url(#${activeNode === "revise" ? "arrowhead-hot" : "arrowhead"})`} />
        <path d={`M${DIAMOND.cx} 118 H778 V148`} className={hot("select_best")} markerEnd={`url(#${activeNode === "select_best" ? "arrowhead-hot" : "arrowhead"})`} />
        <text className="edge-label" x={DIAMOND.cx + 6} y={100}>
          fail
        </text>
        <text className="edge-label" x={603} y={190} textAnchor="middle">
          retries left
        </text>
        <text className="edge-label" x={708} y={112} textAnchor="middle">
          retries / budget used
        </text>
        <path d="M504 150 V78" className={hot("evaluate")} markerEnd={`url(#${activeNode === "evaluate" ? "arrowhead-hot" : "arrowhead"})`} />
        <text className="edge-label" x={512} y={120}>
          new attempt
        </text>
        <path d="M778 150 V78" className={hot("finalize")} markerEnd="url(#arrowhead)" />
        <path d="M840 53 H858" className={hot("consolidate_memory")} markerEnd={`url(#${activeNode === "consolidate_memory" ? "arrowhead-hot" : "arrowhead"})`} />

        <g className={`node ${routeVisited ? "done" : "pending"}`} role="img" aria-label="Decision: did all checks pass?">
          <polygon
            points={`${DIAMOND.cx},${DIAMOND.cy - DIAMOND.ry} ${DIAMOND.cx + DIAMOND.rx},${DIAMOND.cy} ${DIAMOND.cx},${DIAMOND.cy + DIAMOND.ry} ${DIAMOND.cx - DIAMOND.rx},${DIAMOND.cy}`}
          />
          <text className="sub" x={DIAMOND.cx} y={DIAMOND.cy - 2} textAnchor="middle">
            all pass?
          </text>
          <text className="sub" x={DIAMOND.cx} y={DIAMOND.cy + 11} textAnchor="middle">
            route
          </text>
        </g>

        {(Object.keys(BOXES) as PipelineNode[]).map((id) => (
          <NodeBox
            key={id}
            id={id}
            state={nodes[id]}
            badge={id === "evaluate" && attempt > 0 ? `attempt ${attempt}/${maxAttempts}` : undefined}
          />
        ))}
      </svg>
    </div>
  );
}
