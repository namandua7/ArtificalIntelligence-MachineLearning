"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card } from "@/components/ui/primitives";
import type { EvalRun } from "@/lib/api";

export function AccuracyChart({ runs }: { runs: EvalRun[] }) {
  const data = [...runs]
    .filter((r) => r.accuracy !== null)
    .reverse()
    .map((r) => ({ run: `#${r.id}`, accuracy: Math.round((r.accuracy ?? 0) * 1000) / 10, memory: r.useMemory, model: r.model }));
  if (data.length < 2) return null;
  return (
    <Card className="p-4">
      <div className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted">Accuracy over runs</div>
      <div className="h-48">
        <ResponsiveContainer>
          <LineChart data={data}>
            <CartesianGrid stroke="rgb(39 39 46)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="run" stroke="rgb(148 148 160)" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis domain={[0, 100]} stroke="rgb(148 148 160)" fontSize={11} tickLine={false} axisLine={false} unit="%" width={44} />
            <Tooltip
              contentStyle={{ background: "rgb(17 17 21)", border: "1px solid rgb(39 39 46)", borderRadius: 8, fontSize: 12 }}
              formatter={(v: number, _n, p) => [`${v}% (memory ${p.payload.memory ? "on" : "off"})`, p.payload.model]}
            />
            <Line type="monotone" dataKey="accuracy" stroke="#a78bfa" strokeWidth={2} dot={{ r: 3, fill: "#a78bfa" }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
