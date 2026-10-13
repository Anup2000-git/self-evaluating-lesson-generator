import { useState } from "react";
import { useElementWidth } from "../../hooks/useElementWidth";
import { ChartFrame, niceTicks, Tooltip, type Datum } from "./ChartFrame";

/** Vertical single-series columns (slot-1 hue): <=24px thick, 4px rounded data-end,
 * square at the baseline, hairline grid, selective value labels (latest + max), hover/focus tooltips. */
export function ColumnChart({
  title,
  subtitle,
  data,
  valueLabel,
  format = (v) => String(v),
  height = 220,
  integer = false,
}: {
  title: string;
  subtitle?: string;
  data: Datum[];
  valueLabel: string;
  format?: (value: number) => string;
  height?: number;
  /** Values are counts: ticks step by whole numbers. */
  integer?: boolean;
}) {
  const { ref, width } = useElementWidth<HTMLDivElement>(480);
  const [hover, setHover] = useState<number | null>(null);
  const margin = { top: 22, right: 8, bottom: 28, left: 34 };
  const plotW = Math.max(120, width - margin.left - margin.right);
  const plotH = height - margin.top - margin.bottom;
  const ticks = niceTicks(Math.max(...data.map((d) => d.value), integer ? 1 : 0), { integer });
  const max = ticks[ticks.length - 1] || 1;
  const band = plotW / Math.max(1, data.length);
  const barW = Math.min(24, band * 0.6);
  const y = (v: number) => margin.top + plotH - (v / max) * plotH;
  const peak = data.reduce((best, d, i) => (d.value > data[best].value ? i : best), 0);
  const labelled = new Set([data.length - 1, peak]);
  const labelEvery = Math.ceil(data.length / Math.max(1, Math.floor(plotW / 34)));

  return (
    <ChartFrame title={title} subtitle={subtitle} data={data} valueLabel={valueLabel} format={format}>
      <div ref={ref} className={`chart-canvas${hover !== null ? " hovering" : ""}`}>
        <svg width={width} height={height} role="img" aria-label={`${title}. Column chart with ${data.length} values.`}>
          {ticks.map((t) => (
            <g key={t}>
              <line className={t === 0 ? "chart-baseline" : "chart-grid"} x1={margin.left} x2={margin.left + plotW} y1={y(t)} y2={y(t)} />
              <text className="chart-tick" x={margin.left - 6} y={y(t) + 4} textAnchor="end">
                {format(t)}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const cx = margin.left + band * i + band / 2;
            const x = cx - barW / 2;
            const top = y(d.value);
            const base = y(0);
            const r = Math.min(4, barW / 2, base - top);
            const path =
              base - top > 0
                ? `M${x},${base} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${base} Z`
                : "";
            return (
              <g key={d.key}>
                {path ? <path className={`chart-mark${hover === i ? " hot" : ""}`} d={path} /> : null}
                {labelled.has(i) ? (
                  <text className="chart-label" x={cx} y={top - 6} textAnchor="middle">
                    {format(d.value)}
                  </text>
                ) : null}
                {i % labelEvery === 0 || i === data.length - 1 ? (
                  <text className="chart-tick" x={cx} y={height - 8} textAnchor="middle">
                    {d.label}
                  </text>
                ) : null}
                <rect
                  className="chart-hit"
                  x={margin.left + band * i}
                  y={margin.top}
                  width={band}
                  height={plotH}
                  tabIndex={0}
                  aria-label={`${d.label}: ${format(d.value)}`}
                  onPointerEnter={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                />
              </g>
            );
          })}
        </svg>
        {hover !== null && data[hover] ? (
          <Tooltip
            x={margin.left + band * hover + band / 2}
            y={y(data[hover].value)}
            value={format(data[hover].value)}
            label={`${valueLabel} · ${data[hover].label}`}
            extra={data[hover].extra}
          />
        ) : null}
      </div>
    </ChartFrame>
  );
}
