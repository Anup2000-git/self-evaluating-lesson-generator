import { useState, type ReactNode } from "react";

export interface Datum {
  key: string;
  label: string;
  value: number;
  /** Extra tooltip / table lines, e.g. "status: shipped". */
  extra?: string[];
}

/** Chart container: title, subtitle, and the table-view twin every chart must have. */
export function ChartFrame({
  title,
  subtitle,
  data,
  valueLabel,
  format,
  children,
}: {
  title: string;
  subtitle?: string;
  data: Datum[];
  valueLabel: string;
  format: (value: number) => string;
  children: ReactNode;
}) {
  const [table, setTable] = useState(false);
  return (
    <figure className="chart-figure">
      <div className="chart-head">
        <div>
          <div className="chart-title">{title}</div>
          {subtitle ? <div className="chart-subtitle">{subtitle}</div> : null}
        </div>
        <button type="button" className="btn btn-ghost btn-sm" aria-pressed={table} onClick={() => setTable((t) => !t)}>
          {table ? "Chart view" : "Table view"}
        </button>
      </div>
      {data.length === 0 ? (
        <div className="chart-empty">No data yet.</div>
      ) : table ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">{valueLabel}</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d) => (
                <tr key={d.key}>
                  <td>{d.label}</td>
                  <td className="num">{format(d.value)}</td>
                  <td className="secondary">{d.extra?.join(" · ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
    </figure>
  );
}

export function niceMax(max: number): number {
  if (max <= 0) return 1;
  const exponent = Math.floor(Math.log10(max));
  const base = 10 ** exponent;
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (max <= step * base) return step * base;
  }
  return 10 * base;
}

/** Clean axis ticks from 0: steps of 1/2/5 x 10^k (no 2.5 steps when values are counts). */
export function niceTicks(max: number, { count = 4, integer = false } = {}): number[] {
  const raw = Math.max(max, integer ? 1 : Number.EPSILON) / count;
  const exponent = Math.floor(Math.log10(raw));
  const base = 10 ** exponent;
  const steps = integer ? [1, 2, 5, 10] : [1, 2, 2.5, 5, 10];
  let step = (steps.find((s) => raw <= s * base) ?? 10) * base;
  if (integer) step = Math.max(1, Math.round(step));
  const ticks: number[] = [];
  for (let t = 0; t <= max + step * 0.001 || ticks.length < 2; t += step) {
    ticks.push(Number(t.toFixed(10)));
    if (ticks.length > 12) break;
  }
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

export function Tooltip({
  x,
  y,
  value,
  label,
  extra,
}: {
  x: number;
  y: number;
  value: string;
  label: string;
  extra?: string[];
}) {
  return (
    <div className="chart-tooltip" style={{ left: x, top: y }} role="presentation">
      <div className="tt-value">{value}</div>
      <div className="tt-label">
        <span className="tt-key" />
        {label}
      </div>
      {extra?.map((line) => (
        <div key={line} className="tt-extra">
          {line}
        </div>
      ))}
    </div>
  );
}
