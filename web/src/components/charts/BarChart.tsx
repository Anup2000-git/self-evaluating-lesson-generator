import { useState } from "react";
import { useElementWidth } from "../../hooks/useElementWidth";
import { ChartFrame, niceMax, Tooltip, type Datum } from "./ChartFrame";

/** Horizontal single-series bars, ranked: value at the tip, 4px rounded data-end,
 * square at the baseline, hairline vertical grid, hover/focus tooltips, table twin. */
export function BarChart({
  title,
  subtitle,
  data,
  valueLabel,
  format = (v) => String(v),
  max,
}: {
  title: string;
  subtitle?: string;
  data: Datum[];
  valueLabel: string;
  format?: (value: number) => string;
  max?: number;
}) {
  const { ref, width } = useElementWidth<HTMLDivElement>(560);
  const [hover, setHover] = useState<number | null>(null);
  const row = 30;
  const barH = 16;
  const labelW = Math.min(170, Math.max(70, ...data.map((d) => d.label.length * 7)));
  const margin = { top: 6, right: 52, bottom: 24, left: labelW + 10 };
  const plotW = Math.max(100, width - margin.left - margin.right);
  const height = margin.top + data.length * row + margin.bottom;
  const top = max ?? niceMax(Math.max(0.0001, ...data.map((d) => d.value)));
  const x = (v: number) => margin.left + (Math.min(v, top) / top) * plotW;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * top);

  return (
    <ChartFrame title={title} subtitle={subtitle} data={data} valueLabel={valueLabel} format={format}>
      <div ref={ref} className={`chart-canvas${hover !== null ? " hovering" : ""}`}>
        <svg width={width} height={height} role="img" aria-label={`${title}. Bar chart with ${data.length} bars.`}>
          {ticks.map((t) => (
            <g key={t}>
              <line
                className={t === 0 ? "chart-baseline" : "chart-grid"}
                x1={x(t)}
                x2={x(t)}
                y1={margin.top}
                y2={height - margin.bottom}
              />
              <text className="chart-tick" x={x(t)} y={height - 6} textAnchor="middle">
                {format(t)}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const yTop = margin.top + i * row + (row - barH) / 2;
            const x0 = x(0);
            const x1 = x(d.value);
            const r = Math.min(4, barH / 2, x1 - x0);
            const path =
              x1 - x0 > 0
                ? `M${x0},${yTop} H${x1 - r} Q${x1},${yTop} ${x1},${yTop + r} V${yTop + barH - r} Q${x1},${yTop + barH} ${x1 - r},${yTop + barH} H${x0} Z`
                : "";
            return (
              <g key={d.key}>
                <text className="chart-category" x={margin.left - 10} y={yTop + barH / 2 + 4} textAnchor="end">
                  {d.label}
                </text>
                {path ? <path className={`chart-mark${hover === i ? " hot" : ""}`} d={path} /> : null}
                <text className="chart-label" x={x1 + 6} y={yTop + barH / 2 + 4}>
                  {format(d.value)}
                </text>
                <rect
                  className="chart-hit"
                  x={0}
                  y={margin.top + i * row}
                  width={width}
                  height={row}
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
            x={Math.min(x(data[hover].value), width - 130)}
            y={margin.top + hover * row + 4}
            value={format(data[hover].value)}
            label={`${valueLabel} · ${data[hover].label}`}
            extra={data[hover].extra}
          />
        ) : null}
      </div>
    </ChartFrame>
  );
}
