"use client";

import { ChevronRight } from "lucide-react";
import { useState } from "react";

import type { PlanNode } from "@/lib/api";
import { cn, formatNumber } from "@/lib/utils";

const SLOW_NODES = new Set(["Seq Scan", "Sort", "Hash", "Nested Loop", "Materialize"]);

function selfCost(node: PlanNode) {
  const children = (node.Plans ?? []).reduce((s, c) => s + c["Total Cost"], 0);
  return Math.max(node["Total Cost"] - children, 0);
}

function Node({ node, rootCost, depth }: { node: PlanNode; rootCost: number; depth: number }) {
  const [open, setOpen] = useState(true);
  const own = selfCost(node);
  const share = rootCost ? own / rootCost : 0;
  const hot = share > 0.3;
  const children = node.Plans ?? [];
  const condition = node["Index Cond"] ?? node["Hash Cond"] ?? node.Filter;
  const misestimate =
    node["Actual Rows"] !== undefined && node["Plan Rows"] > 0
      ? Math.max(node["Actual Rows"] / node["Plan Rows"], node["Plan Rows"] / Math.max(node["Actual Rows"], 1))
      : 1;

  return (
    <div className={cn(depth > 0 && "ml-4 border-l border-border/70 pl-3")}>
      <div
        className={cn(
          "group relative my-1 overflow-hidden rounded-lg border px-3 py-2 text-xs",
          hot ? "border-danger/40 bg-danger/5" : "border-border bg-panel/60"
        )}
      >
        <div className="absolute inset-y-0 left-0 bg-accent/10" style={{ width: `${Math.min(share * 100, 100)}%` }} />
        <div className="relative flex items-center gap-2">
          {children.length > 0 ? (
            <button onClick={() => setOpen((o) => !o)} className="text-muted hover:text-fg">
              <ChevronRight className={cn("h-3.5 w-3.5 transition", open && "rotate-90")} />
            </button>
          ) : (
            <span className="w-3.5" />
          )}
          <span className={cn("font-semibold", SLOW_NODES.has(node["Node Type"]) && hot && "text-danger")}>
            {node["Join Type"] ? `${node["Join Type"]} ` : ""}
            {node["Node Type"]}
          </span>
          {node["Relation Name"] && <span className="font-mono text-accent-2">{node["Relation Name"]}</span>}
          {node["Index Name"] && <span className="font-mono text-muted">using {node["Index Name"]}</span>}
          <span className="ml-auto flex shrink-0 items-center gap-3 font-mono text-[11px] text-muted">
            {misestimate >= 10 && <span className="text-warn" title="Row estimate off by 10×+ (stale statistics?)">est. ×{Math.round(misestimate)}</span>}
            <span title="Estimated rows">{formatNumber(node["Plan Rows"])} rows</span>
            {node["Actual Total Time"] !== undefined && <span>{node["Actual Total Time"].toFixed(1)} ms</span>}
            <span className={cn(hot && "text-danger")}>{Math.round(share * 100)}%</span>
          </span>
        </div>
        {condition && (
          <div className="relative mt-1 truncate pl-5 font-mono text-[11px] text-muted" title={condition}>
            {condition}
            {node["Rows Removed by Filter"] ? ` · removed ${formatNumber(node["Rows Removed by Filter"])} rows` : ""}
          </div>
        )}
      </div>
      {open && children.map((c, i) => <Node key={i} node={c} rootCost={rootCost} depth={depth + 1} />)}
    </div>
  );
}

export function PlanTree({ plan }: { plan: PlanNode }) {
  return <Node node={plan} rootCost={plan["Total Cost"]} depth={0} />;
}
