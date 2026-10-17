"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ChartSpec } from "@/lib/api";

export const SERIES_COLORS = ["#a78bfa", "#22d3ee", "#f472b6", "#34d399", "#fbbf24", "#60a5fa", "#fb923c", "#c084fc"];

const AXIS = { stroke: "rgb(148 148 160)", fontSize: 11, tickLine: false, axisLine: false } as const;

function compact(value: unknown) {
  if (typeof value !== "number") return String(value ?? "");
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function shortLabel(value: unknown) {
  const s = String(value ?? "");
  // ISO timestamps → date only
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) return s.slice(0, 10);
  return s.length > 14 ? `${s.slice(0, 13)}…` : s;
}

function TooltipBox({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: unknown }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-panel/95 px-3 py-2 text-xs shadow-xl backdrop-blur">
      <div className="mb-1 font-medium">{shortLabel(label ?? payload[0]?.name)}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 text-muted">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          {p.name}: <span className="font-mono text-fg">{typeof p.value === "number" ? p.value.toLocaleString() : p.value}</span>
        </div>
      ))}
    </div>
  );
}

/** Pick a sensible chart when the agent didn't (or the user switches type). */
export function inferChart(columns: string[], rows: unknown[][]): ChartSpec {
  if (rows.length < 2 || columns.length < 2) return { type: "none" };
  const numeric = columns.filter((_, i) => rows.every((r) => r[i] === null || typeof r[i] === "number"));
  const label = columns.find((c) => !numeric.includes(c)) ?? columns[0];
  const y = numeric.filter((c) => c !== label && !/(^|_)id$/i.test(c)).slice(0, 3);
  if (!y.length) return { type: "none" };
  const xi = columns.indexOf(label);
  const isTime = rows.every((r) => typeof r[xi] === "string" && /^\d{4}-\d{2}/.test(r[xi] as string));
  return { type: isTime ? "line" : "bar", x: label, y };
}

export function ResultChart({
  spec,
  columns,
  rows,
  height = 300,
}: {
  spec: ChartSpec;
  columns: string[];
  rows: unknown[][];
  height?: number;
}) {
  if (spec.type === "none" || !spec.x || !spec.y?.length) return null;
  const xi = columns.indexOf(spec.x);
  const yi = spec.y.map((c) => columns.indexOf(c));
  if (xi < 0 || yi.some((i) => i < 0)) return null;

  const data = rows.slice(0, 200).map((r) => {
    const point: Record<string, unknown> = { [spec.x!]: r[xi] };
    spec.y!.forEach((c, k) => {
      const v = r[yi[k]];
      point[c] = typeof v === "number" ? v : Number(v);
    });
    return point;
  });

  const grid = <CartesianGrid stroke="rgb(39 39 46)" strokeDasharray="3 3" vertical={false} />;
  const x = <XAxis dataKey={spec.x} {...AXIS} tickFormatter={shortLabel} minTickGap={16} />;
  const yAxis = <YAxis {...AXIS} tickFormatter={compact} width={48} />;
  const tooltip = <Tooltip content={<TooltipBox />} cursor={{ fill: "rgb(255 255 255 / 0.04)" }} />;
  const legend = spec.y.length > 1 ? <Legend wrapperStyle={{ fontSize: 12 }} /> : null;

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer>
        {spec.type === "pie" ? (
          <PieChart>
            <Pie data={data} dataKey={spec.y[0]} nameKey={spec.x} innerRadius="55%" outerRadius="85%" paddingAngle={2} stroke="none">
              {data.map((_, i) => (
                <Cell key={i} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
              ))}
            </Pie>
            {tooltip}
            <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v) => shortLabel(v)} />
          </PieChart>
        ) : spec.type === "line" ? (
          <LineChart data={data}>
            {grid}
            {x}
            {yAxis}
            {tooltip}
            {legend}
            {spec.y.map((c, i) => (
              <Line key={c} type="monotone" dataKey={c} stroke={SERIES_COLORS[i]} strokeWidth={2} dot={false} />
            ))}
          </LineChart>
        ) : spec.type === "area" ? (
          <AreaChart data={data}>
            <defs>
              {spec.y.map((c, i) => (
                <linearGradient key={c} id={`grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={SERIES_COLORS[i]} stopOpacity={0.4} />
                  <stop offset="100%" stopColor={SERIES_COLORS[i]} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            {grid}
            {x}
            {yAxis}
            {tooltip}
            {legend}
            {spec.y.map((c, i) => (
              <Area key={c} type="monotone" dataKey={c} stroke={SERIES_COLORS[i]} fill={`url(#grad-${i})`} strokeWidth={2} />
            ))}
          </AreaChart>
        ) : (
          <BarChart data={data}>
            {grid}
            {x}
            {yAxis}
            {tooltip}
            {legend}
            {spec.y.map((c, i) => (
              <Bar key={c} dataKey={c} fill={SERIES_COLORS[i]} radius={[4, 4, 0, 0]} maxBarSize={48} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
