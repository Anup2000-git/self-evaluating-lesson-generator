import type {
  ConsolidationResult,
  DoctorRow,
  FaultApplied,
  FaultInfo,
  Feedback,
  FeedbackCreate,
  GlossaryItem,
  Guideline,
  KBDocument,
  Lesson,
  RubricProposal,
  RubricVersionInfo,
  RunDetail,
  RunList,
  RunRecord,
  RunRequest,
  SearchResponse,
  StatsResponse,
  SystemStatus,
  TopicPack,
  TopicPackSummary,
} from "./types";

// Every service is reached through the gateway under its own prefix (nginx in production,
// the Vite proxy in development) - the browser never needs to know internal hostnames.
const BASE = {
  orchestrator: "/api/orchestrator",
  memory: "/api/memory",
  evaluator: "/api/evaluator",
  knowledge: "/api/knowledge",
} as const;

type Service = keyof typeof BASE;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function describeProblem(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
  }
  return fallback;
}

async function request<T>(service: Service, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE[service]}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, describeProblem(body, `${service} returned ${response.status}`));
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("json") ? response.json() : response.text()) as Promise<T>;
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const query = (params: Record<string, string | number | boolean | null | undefined>) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return entries.length ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}` : "";
};

export const api = {
  runs: {
    create: (body: RunRequest) => request<RunRecord>("orchestrator", "/v1/runs", json(body)),
    list: (params: { limit?: number; offset?: number; status?: string; mode?: string } = {}) =>
      request<RunList>("orchestrator", `/v1/runs${query(params)}`),
    get: (id: string) => request<RunDetail>("orchestrator", `/v1/runs/${encodeURIComponent(id)}`),
    cancel: (id: string) => request<unknown>("orchestrator", `/v1/runs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
    resume: (id: string) => request<unknown>("orchestrator", `/v1/runs/${encodeURIComponent(id)}/resume`, { method: "POST" }),
    rejectionLog: (id: string) =>
      request<string>("orchestrator", `/v1/runs/${encodeURIComponent(id)}/export/rejection-log.md`),
    eventsUrl: (id: string) => `${BASE.orchestrator}/v1/runs/${encodeURIComponent(id)}/events`,
    lessonExportUrl: (id: string) => `${BASE.orchestrator}/v1/runs/${encodeURIComponent(id)}/export/lesson.md`,
    rejectionLogUrl: (id: string) => `${BASE.orchestrator}/v1/runs/${encodeURIComponent(id)}/export/rejection-log.md`,
  },
  topics: () => request<TopicPackSummary[]>("orchestrator", "/v1/topics"),
  system: {
    status: () => request<SystemStatus>("orchestrator", "/v1/system/status"),
    llmCheck: () => request<{ results: DoctorRow[] }>("orchestrator", "/v1/system/llm-check", { method: "POST" }),
  },
  learning: {
    consolidate: () => request<ConsolidationResult>("orchestrator", "/v1/learning/consolidate", { method: "POST" }),
  },
  memory: {
    stats: () => request<StatsResponse>("memory", "/v1/stats"),
    guidelines: (status?: string) => request<Guideline[]>("memory", `/v1/guidelines${query({ status })}`),
    updateGuideline: (id: string, body: { text?: string; status?: string; reason: string }) =>
      request<Guideline>("memory", `/v1/guidelines/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    proposals: (status?: string) => request<RubricProposal[]>("memory", `/v1/rubric/proposals${query({ status })}`),
    approve: (id: string, note = "") =>
      request<RubricProposal>("memory", `/v1/rubric/proposals/${encodeURIComponent(id)}/approve`, json({ note })),
    reject: (id: string, note = "") =>
      request<RubricProposal>("memory", `/v1/rubric/proposals/${encodeURIComponent(id)}/reject`, json({ note })),
    feedback: (runId?: string) => request<Feedback[]>("memory", `/v1/feedback${query({ run_id: runId })}`),
    addFeedback: (body: FeedbackCreate) => request<Feedback>("memory", "/v1/feedback", json(body)),
    activeRubric: () => request<RubricVersionInfo>("memory", "/v1/rubric/active"),
    rubricVersions: () => request<RubricVersionInfo[]>("memory", "/v1/rubric/versions"),
  },
  evaluator: {
    faults: () => request<FaultInfo[]>("evaluator", "/v1/faults"),
    applyFault: (lesson: Lesson, faultId: string) =>
      request<FaultApplied>("evaluator", "/v1/faults/apply", json({ lesson, fault_id: faultId })),
    referenceLesson: () => request<Lesson>("evaluator", "/v1/faults/reference-lesson"),
  },
  knowledge: {
    topic: (id: string) => request<TopicPack>("knowledge", `/v1/topics/${encodeURIComponent(id)}`),
    glossary: (id: string) => request<GlossaryItem[]>("knowledge", `/v1/topics/${encodeURIComponent(id)}/glossary`),
    documents: (id: string) => request<KBDocument[]>("knowledge", `/v1/topics/${encodeURIComponent(id)}/documents`),
    search: (topicId: string, q: string, k = 4) =>
      request<SearchResponse>("knowledge", "/v1/search", json({ topic_id: topicId, query: q, k })),
  },
};
