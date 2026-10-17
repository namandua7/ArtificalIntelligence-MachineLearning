"use client";

import { motion } from "framer-motion";
import { Activity, AlertTriangle, Gauge, Lightbulb, Stethoscope, TrendingDown } from "lucide-react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Markdown } from "@/components/Markdown";
import { PlanTree } from "@/components/PlanTree";
import { SqlCode } from "@/components/SqlCode";
import { Badge, Button, Card, EmptyState, Skeleton } from "@/components/ui/primitives";
import { useWorkspace } from "@/components/WorkspaceContext";
import type { Diagnosis, Suggestion } from "@/lib/api";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

const SqlEditor = dynamic(() => import("@/components/SqlEditor").then((m) => m.SqlEditor), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full rounded-none" />,
});

const EXAMPLE = `SELECT c.first_name, c.last_name, SUM(p.amount) AS total
FROM payment p
JOIN customer c ON c.customer_id = p.customer_id
WHERE p.amount > 9
GROUP BY c.customer_id
ORDER BY total DESC
LIMIT 10;`;

function Stat({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Gauge }) {
  return (
    <Card className="p-3">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-muted">
        <Icon className="h-3.5 w-3.5" /> {label}
      </div>
      <div className="mt-1 font-mono text-lg font-semibold tabular-nums">{value}</div>
    </Card>
  );
}

function CostBar({ before, after, pct, label }: { before: number; after: number; pct: number; label: string }) {
  const better = after < before;
  return (
    <div className="space-y-1.5 rounded-lg border border-border bg-bg/50 p-3">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span className={better ? "font-semibold text-ok" : "text-muted"}>
          {better ? `−${pct}% cost` : "no improvement"}
        </span>
      </div>
      <div className="space-y-1">
        <div className="flex items-center gap-2 text-[11px]">
          <span className="w-10 text-muted">before</span>
          <div className="h-2 flex-1 rounded-full bg-danger/50" />
          <span className="w-16 text-right font-mono text-muted">{formatNumber(before)}</span>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="w-10 text-muted">after</span>
          <div className="h-2 flex-1">
            <motion.div
              initial={{ width: "100%" }}
              animate={{ width: `${Math.max(Math.min((after / before) * 100, 100), 2)}%` }}
              transition={{ duration: 0.8, ease: "easeOut" }}
              className="h-2 rounded-full bg-ok/70"
            />
          </div>
          <span className="w-16 text-right font-mono text-muted">{formatNumber(after)}</span>
        </div>
      </div>
    </div>
  );
}

function SuggestionCard({ s, i, connectionId }: { s: Suggestion; i: number; connectionId: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.08 }}>
      <Card className="space-y-3 p-4">
        <div className="flex items-start gap-2">
          <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{s.title}</span>
              <Badge tone={s.kind === "index" ? "accent" : s.kind === "rewrite" ? "cyan" : "neutral"}>{s.kind}</Badge>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted">{s.detail}</p>
          </div>
        </div>
        {s.sql && <SqlCode sql={s.sql} connectionId={s.kind === "rewrite" ? connectionId : undefined} maxHeight="max-h-48" />}
        {s.hypothetical && (
          <CostBar
            label={`Hypothetical index (hypopg)${s.hypothetical.indexUsed ? "" : " · not used by planner"}`}
            before={s.hypothetical.costBefore}
            after={s.hypothetical.costAfter}
            pct={s.hypothetical.improvementPct}
          />
        )}
        {s.rewriteCost && (
          <CostBar label="Rewritten query plan" before={s.rewriteCost.costBefore} after={s.rewriteCost.costAfter} pct={s.rewriteCost.improvementPct} />
        )}
        {(s.hypotheticalError || s.rewriteError) && (
          <p className="text-[11px] text-warn">Couldn&apos;t measure: {s.hypotheticalError ?? s.rewriteError}</p>
        )}
      </Card>
    </motion.div>
  );
}

function DoctorInner() {
  const { connectionId, schema } = useWorkspace();
  const params = useSearchParams();
  const [sql, setSql] = useState("");
  const [analyze, setAnalyze] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Diagnosis | null>(null);

  useEffect(() => {
    setSql(params.get("sql") ?? EXAMPLE);
  }, [params]);

  const run = async () => {
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      setReport(await api.doctor(connectionId, sql, analyze));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex flex-wrap items-center gap-3 border-b border-border/60 px-4 py-2.5">
        <h1 className="text-sm font-medium">Performance Doctor</h1>
        <span className="hidden text-xs text-muted sm:inline">EXPLAIN → AI diagnosis → measured fixes</span>
        <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-xs text-muted" title="Runs the query to get real timings (still read-only)">
          <input type="checkbox" checked={analyze} onChange={(e) => setAnalyze(e.target.checked)} className="accent-violet-500" />
          EXPLAIN ANALYZE
        </label>
        <Button size="sm" variant="primary" onClick={run} loading={loading}>
          {!loading && <Stethoscope className="h-3.5 w-3.5" />} Diagnose
        </Button>
      </div>

      <div className="h-56 shrink-0 border-b border-border/60">
        <SqlEditor value={sql} onChange={setSql} onRun={run} schema={schema} />
      </div>

      <div className="space-y-6 p-4 sm:p-6">
        {error && (
          <div className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger/5 p-3 text-sm text-danger">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <pre className="whitespace-pre-wrap font-mono text-xs">{error}</pre>
          </div>
        )}

        {loading && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
            </div>
            <Skeleton className="h-24 rounded-xl" />
            <Skeleton className="h-48 rounded-xl" />
          </div>
        )}

        {!report && !loading && !error && (
          <EmptyState
            icon={<Gauge className="h-5 w-5" />}
            title="Paste a slow query"
            description="QueryPilot reads the execution plan, explains the bottleneck and tests suggested indexes with hypothetical indexes (nothing is created in your database)."
          />
        )}

        {report && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat icon={Gauge} label="Plan cost" value={formatNumber(report.stats.totalCost)} />
              <Stat icon={Activity} label="Est. rows" value={formatNumber(report.stats.planRows)} />
              <Stat icon={TrendingDown} label="Execution" value={report.stats.executionMs != null ? `${report.stats.executionMs.toFixed(1)} ms` : "—"} />
              <Stat icon={Stethoscope} label="Planning" value={report.stats.planningMs != null ? `${report.stats.planningMs.toFixed(1)} ms` : "—"} />
            </div>

            <Card className="p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <Stethoscope className="h-4 w-4 text-accent" /> Diagnosis
              </div>
              <Markdown>{report.summary}</Markdown>
              {report.bottlenecks.length > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {report.bottlenecks.map((b, i) => (
                    <li key={i} className="flex gap-2 text-xs text-muted">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" /> {b}
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <div className="grid gap-6 xl:grid-cols-2">
              <section>
                <h2 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted">
                  Suggestions {!report.hypopg && <span className="normal-case tracking-normal text-warn">· install hypopg to measure index impact</span>}
                </h2>
                <div className="space-y-3">
                  {report.suggestions.length === 0 && <p className="text-sm text-muted">No changes needed. This query is already efficient.</p>}
                  {report.suggestions.map((s, i) => (
                    <SuggestionCard key={i} s={s} i={i} connectionId={connectionId} />
                  ))}
                </div>
              </section>
              <section>
                <h2 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted">Execution plan</h2>
                <PlanTree plan={report.plan.Plan} />
              </section>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function DoctorPage() {
  return (
    <Suspense>
      <DoctorInner />
    </Suspense>
  );
}
