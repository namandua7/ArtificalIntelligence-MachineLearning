"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  ChevronDown,
  Code2,
  Lightbulb,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ResultsTable } from "@/components/ResultsTable";
import { SqlCode } from "@/components/SqlCode";
import { Badge, Button } from "@/components/ui/primitives";
import type { Analysis, Confidence, Drivers, Insights, Timing } from "@/lib/api";
import { api } from "@/lib/api";
import { cn, formatNumber } from "@/lib/utils";

const secs = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`);

// --- Timing ----------------------------------------------------------------------------------

const SEGMENTS: { key: keyof Timing; label: string; color: string }[] = [
  { key: "retrievalMs", label: "Retrieval", color: "bg-accent-2" },
  { key: "llmMs", label: "LLM", color: "bg-accent" },
  { key: "sqlMs", label: "SQL", color: "bg-ok" },
  { key: "otherMs", label: "Other", color: "bg-muted/50" },
];

export function TimingBreakdown({ timing, cached }: { timing: Timing; cached?: boolean }) {
  const [open, setOpen] = useState(false);
  const total = Math.max(timing.totalMs, 1);
  return (
    <div className="text-[11px] text-muted">
      <button onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-1.5 transition hover:text-fg">
        <Zap className={cn("h-3 w-3", cached ? "text-warn" : "text-accent")} />
        {cached ? `Answered from cache in ${secs(timing.totalMs)}` : `Answered in ${secs(timing.totalMs)}`}
        <ChevronDown className={cn("h-3 w-3 transition", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="mt-2 max-w-md space-y-2">
              <div className="flex h-1.5 overflow-hidden rounded-full bg-elevated">
                {SEGMENTS.map((s) => (
                  <div key={s.key} className={s.color} style={{ width: `${(Number(timing[s.key]) / total) * 100}%` }} />
                ))}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {SEGMENTS.map((s) => (
                  <span key={s.key} className="inline-flex items-center gap-1.5">
                    <span className={cn("h-2 w-2 rounded-sm", s.color)} />
                    {s.label} {secs(Number(timing[s.key]))}
                    {s.key === "llmMs" && timing.llmCalls > 0 && ` (${timing.llmCalls} call${timing.llmCalls > 1 ? "s" : ""})`}
                  </span>
                ))}
              </div>
              {cached && <p className="text-muted/80">Identical question asked recently; nothing was recomputed.</p>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// --- Confidence (self-consistency) -----------------------------------------------------------

const LEVELS = {
  high: { icon: ShieldCheck, tone: "ok" as const, label: "High confidence" },
  medium: { icon: ShieldQuestion, tone: "warn" as const, label: "Medium confidence" },
  low: { icon: ShieldAlert, tone: "danger" as const, label: "Low confidence" },
  unverified: { icon: ShieldQuestion, tone: "neutral" as const, label: "Couldn't cross-check" },
};

export function ConfidenceBadge({ confidence, connectionId }: { confidence: Confidence; connectionId: number }) {
  const [open, setOpen] = useState(confidence.level === "low");
  const meta = LEVELS[confidence.level];
  const differing = confidence.alternatives.filter((a) => a.status === "differs");
  const detail =
    confidence.level === "unverified"
      ? "No independent attempt produced a runnable query."
      : `${confidence.agreeing} of ${confidence.total} independent attempt${confidence.total === 1 ? "" : "s"} returned the same values.`;

  return (
    <div className="space-y-2">
      <button onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-2 text-left">
        <Badge tone={meta.tone} className="gap-1.5 py-1">
          <meta.icon className="h-3 w-3" /> {meta.label}
        </Badge>
        <span className="text-[11px] text-muted">{detail}</span>
        {confidence.alternatives.length > 0 && <ChevronDown className={cn("h-3 w-3 text-muted transition", open && "rotate-180")} />}
      </button>
      {open && confidence.alternatives.length > 0 && (
        <div className="space-y-2 rounded-xl border border-border/70 bg-bg/40 p-3">
          {differing.length > 0 && (
            <p className="flex items-start gap-1.5 text-xs text-warn">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Another reading of your question gave different numbers. Check the question&apos;s wording, or compare the
              queries below.
            </p>
          )}
          {confidence.alternatives.map((a, i) => (
            <div key={i} className="space-y-1">
              <div className="flex items-center gap-2 text-[11px]">
                <span className="text-muted">Attempt {i + 1}</span>
                <Badge tone={a.status === "agrees" ? "ok" : a.status === "differs" ? "warn" : "neutral"}>
                  {a.status === "agrees" ? "same result" : a.status === "differs" ? "different result" : "failed to run"}
                </Badge>
                {a.rowCount !== null && <span className="text-muted">{a.rowCount} rows</span>}
              </div>
              {a.status === "error" ? (
                <p className="font-mono text-[11px] text-muted">{a.error?.split("\n")[0]}</p>
              ) : (
                <SqlCode sql={a.sql} connectionId={connectionId} maxHeight="max-h-40" />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Drivers (root cause) --------------------------------------------------------------------

const signed = (n: number, digits = 0) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${formatNumber(Math.abs(n), digits)}`;

export function DriversPanel({ drivers }: { drivers: Drivers }) {
  const max = Math.max(...drivers.drivers.map((d) => Math.abs(d.delta)), 1e-9);
  const down = drivers.delta < 0;
  const Icon = down ? TrendingDown : TrendingUp;
  return (
    <div className="rounded-xl border border-border/70 bg-bg/40 p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Icon className={cn("h-4 w-4", down ? "text-danger" : "text-ok")} />
        <span className="font-medium">
          {drivers.metric} {down ? "fell" : "rose"} {signed(drivers.delta, 2)}
          {drivers.pctChange !== null && ` (${signed(drivers.pctChange * 100, 1)}%)`}
        </span>
        <span className="inline-flex items-center gap-1 text-xs text-muted">
          {drivers.periodBefore} <ArrowRight className="h-3 w-3" /> {drivers.periodAfter}
        </span>
        <Badge tone="cyan" className="ml-auto">by {drivers.dimension}</Badge>
      </div>
      <div className="mt-3 space-y-1.5">
        {drivers.drivers.map((d) => {
          const neg = d.delta < 0;
          return (
            <div key={d.segment} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3 text-xs">
              <span className="truncate" title={d.segment}>{d.segment}</span>
              <div className="relative h-4">
                <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
                <div
                  className={cn("absolute inset-y-0.5 rounded-sm", neg ? "right-1/2 bg-danger/70" : "left-1/2 bg-ok/70")}
                  style={{ width: `${(Math.abs(d.delta) / max) * 50}%` }}
                />
              </div>
              <span className={cn("w-32 text-right tabular-nums", neg ? "text-danger" : "text-ok")}>
                {signed(d.delta, 2)}
                {d.share !== null && <span className="ml-1 text-muted">({Math.round(d.share * 100)}%)</span>}
              </span>
            </div>
          );
        })}
      </div>
      {drivers.segmentCount > drivers.drivers.length && (
        <p className="mt-2 text-[11px] text-muted">Top {drivers.drivers.length} of {drivers.segmentCount} segments by absolute change.</p>
      )}
    </div>
  );
}

// --- Python analysis -------------------------------------------------------------------------

export function AnalysisCard({ analysis }: { analysis: Analysis }) {
  const [showCode, setShowCode] = useState(false);
  return (
    <div className="rounded-xl border border-border/70 bg-bg/40">
      <button onClick={() => setShowCode((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-muted transition hover:text-fg">
        <Code2 className="h-3.5 w-3.5 text-accent-2" />
        <span className="font-medium">Python analysis</span>
        <span>· pandas on {formatNumber(analysis.inputRows)} rows · {analysis.durationMs} ms</span>
        {!analysis.ok && <Badge tone="danger">failed</Badge>}
        <ChevronDown className={cn("ml-auto h-3.5 w-3.5 transition", showCode && "rotate-180")} />
      </button>
      {showCode && (
        <pre className="mx-3 mb-3 max-h-64 overflow-auto rounded-lg border border-border bg-bg/70 p-3 font-mono text-[11.5px] leading-relaxed text-fg/90">
          {analysis.code}
        </pre>
      )}
      <div className="space-y-2 px-3 pb-3">
        {analysis.error && <p className="whitespace-pre-wrap font-mono text-xs text-danger">{analysis.error}</p>}
        {analysis.stdout && (
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-elevated/60 p-2.5 font-mono text-xs text-fg/90">{analysis.stdout}</pre>
        )}
        {analysis.table && (
          <div>
            <ResultsTable columns={analysis.table.columns} rows={analysis.table.rows} pageSize={10} className="max-h-72" />
            {analysis.table.truncated && (
              <p className="mt-1 text-[11px] text-muted">Showing {analysis.table.rows.length} of {analysis.table.rowCount} rows.</p>
            )}
          </div>
        )}
        {!analysis.table && analysis.value !== null && analysis.value !== undefined && (
          <pre className="overflow-auto rounded-lg bg-elevated/60 p-2.5 font-mono text-xs text-amber-200">
            {typeof analysis.value === "string" ? analysis.value : JSON.stringify(analysis.value, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

// --- Insights --------------------------------------------------------------------------------

export function InsightsPanel({
  messageId,
  initial,
  onAsk,
}: {
  messageId: number;
  initial?: Insights;
  onAsk?: (question: string) => void;
}) {
  const [data, setData] = useState<Insights | undefined>(initial);
  const [loading, setLoading] = useState(false);

  const load = async (refresh = false) => {
    setLoading(true);
    try {
      setData(await api.insights(messageId, refresh));
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  if (!data) {
    return (
      <Button size="sm" variant="outline" onClick={() => load()} loading={loading} className="self-start">
        {!loading && <Lightbulb className="h-3.5 w-3.5 text-warn" />} Insights &amp; follow-ups
      </Button>
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-3 rounded-xl border border-border/70 bg-bg/40 p-4">
      <div className="flex items-center gap-2 text-xs font-medium">
        <Lightbulb className="h-3.5 w-3.5 text-warn" /> Insights
        <button onClick={() => load(true)} disabled={loading} className="ml-auto text-[11px] font-normal text-muted transition hover:text-fg">
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : "Regenerate"}
        </button>
      </div>

      {data.facts.length > 0 && (
        <ul className="space-y-1 text-[13px]">
          {data.facts.map((f, i) => (
            <li key={i} className="flex gap-2">
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-accent-2" />
              <span>{f}</span>
            </li>
          ))}
        </ul>
      )}

      {data.takeaways.length > 0 && (
        <div className="space-y-1 border-t border-border/60 pt-3 text-[13px] text-muted">
          {data.takeaways.map((t, i) => (
            <p key={i} className="flex gap-2">
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
              <span>{t}</span>
            </p>
          ))}
        </div>
      )}

      {data.llmError && <p className="text-[11px] text-muted">Takeaways and follow-ups unavailable: {data.llmError}</p>}

      {data.followups.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-border/60 pt-3">
          {data.followups.map((q) => (
            <button
              key={q}
              onClick={() => onAsk?.(q)}
              disabled={!onAsk}
              className="rounded-full border border-border bg-elevated/60 px-3 py-1.5 text-left text-xs text-muted transition hover:border-accent/40 hover:text-fg"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </motion.div>
  );
}
