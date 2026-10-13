import { useEffect, useReducer, useRef } from "react";
import { api } from "../api/client";
import type { RunEvent } from "../api/types";
import { initialLiveRun, reduceRun, type LiveRun } from "../state/runStream";

type Action = { kind: "event"; event: RunEvent } | { kind: "reset" };

function reducer(state: LiveRun, action: Action): LiveRun {
  return action.kind === "reset" ? initialLiveRun() : reduceRun(state, action.event);
}

/** Events that change what the run detail endpoint returns (attempts, status). */
const REFRESH_ON = new Set([
  "evaluation.completed",
  "attempt.rejected",
  "revision.completed",
  "node.completed",
  "run.completed",
  "run.failed",
  "run.cancelled",
  "memory.consolidated",
]);

/**
 * Subscribes to the run's Server-Sent Events. The browser's EventSource reconnects on its
 * own and sends Last-Event-ID, and the server replays from there, so nothing is lost.
 * `onChange` fires (debounced) when the persisted run detail is worth re-fetching.
 */
export function useRunStream(runId: string | undefined, enabled: boolean, onChange?: () => void): LiveRun {
  const [state, dispatch] = useReducer(reducer, undefined, initialLiveRun);
  const changeRef = useRef(onChange);
  changeRef.current = onChange;

  useEffect(() => {
    dispatch({ kind: "reset" });
  }, [runId]);

  useEffect(() => {
    if (!runId || !enabled) return;
    const source = new EventSource(api.runs.eventsUrl(runId));
    let timer: number | undefined;
    const scheduleRefresh = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => changeRef.current?.(), 400);
    };
    source.onmessage = (message: MessageEvent<string>) => {
      try {
        const event = JSON.parse(message.data) as RunEvent;
        event.id = event.id ?? message.lastEventId ?? null;
        dispatch({ kind: "event", event });
        if (REFRESH_ON.has(event.type)) scheduleRefresh();
        if (event.type === "run.completed" || event.type === "run.failed" || event.type === "run.cancelled") {
          source.close();
        }
      } catch {
        /* ignore malformed frames */
      }
    };
    return () => {
      window.clearTimeout(timer);
      source.close();
    };
  }, [runId, enabled]);

  return state;
}
