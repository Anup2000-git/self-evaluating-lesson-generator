import { useEffect, useRef } from "react";
import type { ActivityItem } from "../state/runStream";
import { Icon, type IconName } from "./Icon";

function iconFor(item: ActivityItem): IconName {
  switch (item.type) {
    case "agent.tool_call":
      return "tool";
    case "agent.tool_result":
      return "eye";
    case "agent.thought":
      return "thought";
    case "agent.submitted":
      return "send";
    case "check.completed":
    case "evaluation.completed":
      return item.tone === "pass" ? "check" : "x";
    case "attempt.rejected":
      return "refresh";
    case "memory.recalled":
    case "memory.consolidated":
      return "brain";
    case "run.failed":
      return "alert";
    case "node.started":
      return "play";
    case "revision.completed":
    case "plan.created":
      return "doc";
    default:
      return item.tone === "pass" ? "check" : "info";
  }
}

const SERVICE_LABEL: Record<string, string> = {
  orchestrator: "orchestrator",
  generator: "generator",
  evaluator: "evaluator",
  memory: "memory",
};

export function ActivityFeed({ items, live }: { items: ActivityItem[]; live: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (el && live && stick.current) el.scrollTop = el.scrollHeight;
  }, [items.length, live]);

  if (!items.length) {
    return (
      <div className="empty">
        {live ? "Waiting for the first event…" : "No live events recorded for this run (event history is kept for 30 days)."}
      </div>
    );
  }
  return (
    <div
      className="feed"
      ref={ref}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      }}
      aria-live={live ? "polite" : undefined}
    >
      {items.map((item) => (
        <div key={item.key} className={`feed-item tone-${item.tone}`}>
          <span className="icon">
            <Icon name={iconFor(item)} size={15} />
          </span>
          <div>
            <div className="feed-title">
              {item.title}
              <span className="feed-meta">
                {SERVICE_LABEL[item.service] ?? item.service}
                {item.attempt ? ` · attempt ${item.attempt}` : ""} ·{" "}
                {new Date(item.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
            </div>
            {item.detail ? <div className="feed-detail">{item.detail}</div> : null}
            {item.extra ? <div className="feed-extra">{item.extra}</div> : null}
          </div>
        </div>
      ))}
    </div>
  );
}
