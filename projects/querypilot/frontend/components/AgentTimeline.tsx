"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  FileSearch,
  Flag,
  Loader2,
  Play,
  Search,
  Table2,
  XCircle,
} from "lucide-react";
import { useState } from "react";

import type { AgentStep, Retrieval } from "@/lib/api";
import { cn } from "@/lib/utils";

const TOOL_META: Record<string, { label: string; icon: typeof Search }> = {
  search_schema: { label: "Search schema", icon: Search },
  get_table_details: { label: "Inspect table", icon: Table2 },
  run_sql: { label: "Run SQL", icon: Play },
  final_answer: { label: "Final answer", icon: Flag },
};

function stepDetail(step: AgentStep): string {
  const a = step.args ?? {};
  if (step.tool === "search_schema") return String(a.query ?? "");
  if (step.tool === "get_table_details") return String(a.table ?? "");
  if (step.tool === "run_sql" || step.tool === "final_answer") return String(a.sql ?? "").replace(/\s+/g, " ");
  return JSON.stringify(a);
}

export function AgentTimeline({
  retrieval,
  steps,
  status,
  streaming,
  defaultOpen,
}: {
  retrieval?: Retrieval;
  steps: AgentStep[];
  status?: string;
  streaming: boolean;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const isOpen = streaming || open;
  const failures = steps.filter((s) => s.ok === false && (s.tool === "run_sql" || s.tool === "final_answer")).length;

  return (
    <div className="rounded-xl border border-border/70 bg-bg/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-muted transition hover:text-fg"
      >
        {streaming ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />
        ) : (
          <CircleDashed className="h-3.5 w-3.5 text-accent" />
        )}
        <span className="font-medium">
          {streaming ? status ?? "Working…" : `Agent trace · ${steps.length} step${steps.length === 1 ? "" : "s"}`}
        </span>
        {!streaming && failures > 0 && (
          <span className="rounded bg-warn/10 px-1.5 py-0.5 text-[10px] font-medium text-warn">
            self-corrected {failures}×
          </span>
        )}
        {!streaming && <ChevronDown className={cn("ml-auto h-3.5 w-3.5 transition", isOpen && "rotate-180")} />}
      </button>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="space-y-2 border-t border-border/60 px-3 py-3">
              {retrieval && (
                <div className="flex gap-2.5">
                  <FileSearch className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent-2" />
                  <div className="min-w-0 text-xs">
                    <div className="text-muted">
                      Retrieved {retrieval.tables.length} tables
                      {retrieval.examples.length > 0 && ` · ${retrieval.examples.length} verified example${retrieval.examples.length > 1 ? "s" : ""} from memory`}
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {retrieval.tables.map((t) => (
                        <span
                          key={t.name}
                          title={t.reason === "join" ? "Added via foreign key" : `score ${t.score}`}
                          className={cn(
                            "rounded-md border px-1.5 py-0.5 font-mono text-[10.5px]",
                            t.reason === "match"
                              ? "border-accent-2/30 bg-accent-2/5 text-accent-2"
                              : "border-border bg-elevated text-muted"
                          )}
                        >
                          {t.name}
                          {t.reason === "join" && " ⇢"}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {steps.map((step, i) => {
                const meta = TOOL_META[step.tool] ?? { label: step.tool, icon: Play };
                const pending = step.ok === undefined;
                return (
                  <motion.div
                    key={step.id ?? i}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="flex gap-2.5"
                  >
                    <div className="mt-0.5 shrink-0">
                      {pending ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-muted" />
                      ) : step.ok ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-ok" />
                      ) : (
                        <XCircle className="h-3.5 w-3.5 text-danger" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1 text-xs">
                      <div className="flex items-center gap-1.5">
                        <meta.icon className="h-3 w-3 text-muted" />
                        <span className="font-medium">{meta.label}</span>
                        {step.durationMs !== undefined && step.tool !== "final_answer" && (
                          <span className="text-muted/70">· {step.durationMs} ms</span>
                        )}
                        {step.summary && step.ok && <span className="truncate text-muted">· {step.summary}</span>}
                      </div>
                      <div className="mt-0.5 truncate font-mono text-[11px] text-muted/80">{stepDetail(step)}</div>
                      {step.ok === false && step.error && (
                        <div className="mt-1 whitespace-pre-wrap rounded-md border border-danger/20 bg-danger/5 px-2 py-1 font-mono text-[11px] text-danger/90">
                          {step.error.split("\n").slice(0, 3).join("\n")}
                        </div>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
