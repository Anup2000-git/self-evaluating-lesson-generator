import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import type { RunStatus, Verdict as VerdictType } from "../api/types";
import { STATUS_LABELS } from "../utils/format";
import { Icon } from "./Icon";

export function Card({
  title,
  hint,
  actions,
  children,
  flush,
  footer,
  className = "",
}: {
  title?: ReactNode;
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title || actions ? (
        <header className="card-header">
          {title ? <h2>{title}</h2> : null}
          {hint ? <span className="hint">{hint}</span> : null}
          <span className="spacer" />
          {actions}
        </header>
      ) : null}
      <div className={`card-body${flush ? " flush" : ""}`}>{children}</div>
      {footer ? <footer className="card-footer">{footer}</footer> : null}
    </section>
  );
}

const STATUS_TONE: Record<RunStatus, string> = {
  queued: "",
  running: "badge-accent badge-live",
  shipped: "badge-good",
  needs_human_review: "badge-warning",
  evaluated: "badge-accent",
  failed: "badge-critical",
  cancelled: "",
};

const STATUS_ICON: Partial<Record<RunStatus, "check" | "alert" | "x" | "stop">> = {
  shipped: "check",
  needs_human_review: "alert",
  failed: "x",
  cancelled: "stop",
};

export function StatusBadge({ status }: { status: RunStatus | "unknown" }) {
  if (status === "unknown") return <span className="badge">Loading</span>;
  const icon = STATUS_ICON[status];
  return (
    <span className={`badge ${STATUS_TONE[status]} ${icon ? "" : "badge-dot"}`}>
      {icon ? <Icon name={icon} size={13} /> : null}
      {STATUS_LABELS[status]}
    </span>
  );
}

export function VerdictChip({ verdict }: { verdict: VerdictType | "PENDING" }) {
  if (verdict === "PENDING") {
    return (
      <span className="verdict pending">
        <span className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5 }} /> Running
      </span>
    );
  }
  const pass = verdict === "PASS";
  return (
    <span className={`verdict ${pass ? "pass" : "fail"}`}>
      <Icon name={pass ? "check" : "x"} size={12} />
      {verdict}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row muted" role="status">
      <span className="spinner" />
      {label ? <span>{label}</span> : null}
    </span>
  );
}

export function Empty({ title, children, icon = "info" }: { title: string; children?: ReactNode; icon?: "info" | "doc" | "lab" }) {
  return (
    <div className="empty">
      <Icon name={icon} size={22} />
      <strong>{title}</strong>
      {children ? <div>{children}</div> : null}
    </div>
  );
}

export function ErrorNote({ error }: { error: Error | undefined }) {
  if (!error) return null;
  return (
    <div className="callout callout-critical" role="alert">
      <Icon name="alert" />
      <span>{error.message}</span>
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: ReactNode }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={t.id === value} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ toasts
type Toast = { id: number; text: string; error?: boolean };
const ToastContext = createContext<(text: string, error?: boolean) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const show = useCallback((text: string, error = false) => {
    const id = Date.now();
    setToast({ id, text, error });
    window.setTimeout(() => setToast((t) => (t?.id === id ? null : t)), 3800);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast ? (
        <div className={`toast${toast.error ? " error" : ""}`} role="status" aria-live="polite">
          {toast.text}
        </div>
      ) : null}
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
