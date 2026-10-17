"use client";

import { AreaChart, BarChart3, Download, LineChart, PieChart, Table2 } from "lucide-react";
import { useState } from "react";

import { ResultChart, inferChart } from "@/components/ResultChart";
import { ResultsTable } from "@/components/ResultsTable";
import type { ChartSpec, QueryResult } from "@/lib/api";
import { cn, downloadCsv } from "@/lib/utils";

type View = "table" | ChartSpec["type"];

const CHART_BUTTONS: { type: Exclude<ChartSpec["type"], "none">; icon: typeof BarChart3 }[] = [
  { type: "bar", icon: BarChart3 },
  { type: "line", icon: LineChart },
  { type: "area", icon: AreaChart },
  { type: "pie", icon: PieChart },
];

export function ResultView({
  result,
  chart,
  className,
  tableClassName,
}: {
  result: QueryResult;
  chart?: ChartSpec;
  className?: string;
  tableClassName?: string;
}) {
  const base = chart && chart.type !== "none" ? chart : inferChart(result.columns, result.rows);
  const chartable = base.type !== "none";
  const [view, setView] = useState<View>(chart && chart.type !== "none" ? chart.type : "table");
  const spec: ChartSpec = view === "table" ? { type: "none" } : { ...base, type: view };

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-border bg-bg/50 p-0.5">
          <button
            onClick={() => setView("table")}
            className={cn("rounded-md p-1.5 text-muted transition hover:text-fg", view === "table" && "bg-elevated text-fg")}
            title="Table"
          >
            <Table2 className="h-3.5 w-3.5" />
          </button>
          {chartable &&
            CHART_BUTTONS.map(({ type, icon: Icon }) => (
              <button
                key={type}
                onClick={() => setView(type)}
                className={cn("rounded-md p-1.5 text-muted transition hover:text-fg", view === type && "bg-elevated text-fg")}
                title={`${type} chart`}
              >
                <Icon className="h-3.5 w-3.5" />
              </button>
            ))}
        </div>
        <span className="text-xs text-muted">
          {result.rowCount.toLocaleString()}
          {result.truncated ? "+" : ""} rows · {result.durationMs} ms
          {result.limitAdded && " · auto-limited"}
        </span>
        <button
          onClick={() => downloadCsv("querypilot-result.csv", result.columns, result.rows)}
          className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted transition hover:bg-elevated hover:text-fg"
        >
          <Download className="h-3.5 w-3.5" /> CSV
        </button>
      </div>
      {view === "table" ? (
        <ResultsTable columns={result.columns} rows={result.rows} className={tableClassName} pageSize={25} />
      ) : (
        <div className="rounded-lg border border-border bg-bg/40 p-3">
          <ResultChart spec={spec} columns={result.columns} rows={result.rows} />
        </div>
      )}
    </div>
  );
}
