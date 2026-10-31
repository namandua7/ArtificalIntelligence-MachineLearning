"use client";

import { ArrowDown, ArrowUp, CheckCircle2, ChevronDown, FlaskConical, GitCompare, Loader2, Play, XCircle } from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { toast } from "sonner";

import { SqlCode } from "@/components/SqlCode";
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { useWorkspace } from "@/components/WorkspaceContext";
import type { Bucket, EvalCompare, EvalRun, EvalRunDetail } from "@/lib/api";
import { api } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";

const AccuracyChart = dynamic(() => import("@/components/AccuracyChart").then((m) => m.AccuracyChart), {
  ssr: false,
  loading: () => <Skeleton className="h-48 rounded-xl" />,
});

function pct(v: number | null) {
  return v === null ? "—" : `${(v * 100).toFixed(1)}%`;
}

const DIFFICULTY_TONE: Record<string, "ok" | "warn" | "danger"> = { easy: "ok", medium: "warn", hard: "danger" };

const FAILURE_LABEL: Record<string, string> = {
  wrong_result: "wrong result",
  sql_error: "SQL error",
  no_sql: "no SQL",
  blocked: "blocked by guard",
  agent_error: "agent error",
  gold_error: "gold SQL failed",
};

function BucketBars({ title, buckets }: { title: string; buckets: Record<string, Bucket> }) {
  const entries = Object.entries(buckets);
  if (entries.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted">{title}</div>
      {entries.map(([key, b]) => (
        <div key={key} className="grid grid-cols-[5.5rem_1fr_auto] items-center gap-2 text-xs">
          <span className="truncate capitalize text-muted">{key}</span>
          <div className="h-1.5 overflow-hidden rounded-full bg-elevated">
            <div
              className={cn("h-full", b.accuracy >= 0.8 ? "bg-ok" : b.accuracy >= 0.5 ? "bg-warn" : "bg-danger")}
              style={{ width: `${b.accuracy * 100}%` }}
            />
          </div>
          <span className="w-16 text-right tabular-nums text-muted">
            {b.passed}/{b.total}
          </span>
        </div>
      ))}
    </div>
  );
}

function Breakdown({ detail }: { detail: EvalRunDetail }) {
  const b = detail.breakdown;
  if (!b || detail.results.length === 0) return null;
  return (
    <Card className="grid gap-5 p-4 sm:grid-cols-2 xl:grid-cols-3">
      <BucketBars title="By difficulty" buckets={b.byDifficulty} />
      <BucketBars title="By category" buckets={b.byCategory} />
      <div className="space-y-2">
        <div className="text-[11px] font-medium uppercase tracking-wider text-muted">Failure types</div>
        {Object.keys(b.failures).length === 0 ? (
          <p className="text-xs text-ok">No failures</p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(b.failures).map(([k, n]) => (
              <Badge key={k} tone="danger">
                {FAILURE_LABEL[k] ?? k} · {n}
              </Badge>
            ))}
          </div>
        )}
        <div className="pt-1 text-xs text-muted">
          avg {b.avgSteps} steps · {(b.avgDurationMs / 1000).toFixed(1)}s per question
        </div>
      </div>
    </Card>
  );
}

function ComparePanel({ cmp }: { cmp: EvalCompare }) {
  const changed = cmp.items.filter((i) => i.change === "fixed" || i.change === "regressed");
  const delta = (cmp.b.accuracy ?? 0) - (cmp.a.accuracy ?? 0);
  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <GitCompare className="h-4 w-4 text-accent" />
        <span className="font-medium">
          Run #{cmp.a.id} <span className="text-muted">({pct(cmp.a.accuracy)})</span> → Run #{cmp.b.id}{" "}
          <span className="text-muted">({pct(cmp.b.accuracy)})</span>
        </span>
        <Badge tone={delta > 0 ? "ok" : delta < 0 ? "danger" : "neutral"}>
          {delta > 0 ? "+" : ""}
          {(delta * 100).toFixed(1)} pts
        </Badge>
        <span className="ml-auto flex gap-2 text-xs">
          <span className="text-ok">{cmp.summary.fixed} fixed</span>
          <span className="text-danger">{cmp.summary.regressed} regressed</span>
        </span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <BucketBars title={`Run #${cmp.a.id} by difficulty`} buckets={cmp.byDifficultyA} />
        <BucketBars title={`Run #${cmp.b.id} by difficulty`} buckets={cmp.byDifficultyB} />
      </div>
      {changed.length === 0 ? (
        <p className="text-xs text-muted">No question changed outcome between these runs.</p>
      ) : (
        <ul className="divide-y divide-border/50 rounded-lg border border-border/60">
          {changed.map((i) => (
            <li key={i.question} className="flex items-start gap-2 px-3 py-2 text-[13px]">
              {i.change === "fixed" ? (
                <ArrowUp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" />
              ) : (
                <ArrowDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
              )}
              <span className="flex-1">{i.question}</span>
              {i.difficulty && <Badge tone={DIFFICULTY_TONE[i.difficulty] ?? "neutral"}>{i.difficulty}</Badge>}
              {i.change === "regressed" && i.b?.failureType && <Badge tone="danger">{FAILURE_LABEL[i.b.failureType] ?? i.b.failureType}</Badge>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function EvalsPage() {
  const { connectionId } = useWorkspace();
  const [datasets, setDatasets] = useState<{ name: string; size: number }[]>([]);
  const [dataset, setDataset] = useState("pagila");
  const [useMemory, setUseMemory] = useState(true);
  const [verify, setVerify] = useState(false);
  const [model, setModel] = useState("");
  const [compareWith, setCompareWith] = useState<number | null>(null);
  const [compare, setCompare] = useState<EvalCompare | null>(null);
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<EvalRunDetail | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);

  const loadRuns = useCallback(async () => {
    try {
      const list = await api.evalRuns(connectionId);
      setRuns(list);
      setSelectedId((id) => id ?? list[0]?.id ?? null);
    } catch (err) {
      toast.error((err as Error).message);
    }
  }, [connectionId]);

  useEffect(() => {
    api.evalDatasets().then((d) => {
      setDatasets(d);
      if (d.length && !d.some((x) => x.name === "pagila")) setDataset(d[0].name);
    });
    loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (selectedId === null) return;
    api.evalRun(selectedId).then(setDetail).catch(() => undefined);
  }, [selectedId, runs]);

  useEffect(() => {
    setCompare(null);
    if (compareWith === null || selectedId === null || compareWith === selectedId) return;
    api.compareEvals(connectionId, compareWith, selectedId).then(setCompare).catch((err) => toast.error(err.message));
  }, [compareWith, selectedId, connectionId]);

  const running = runs?.some((r) => r.status === "running");
  useEffect(() => {
    if (!running) return;
    const id = setInterval(loadRuns, 2500);
    return () => clearInterval(id);
  }, [running, loadRuns]);

  const start = async () => {
    setStarting(true);
    try {
      const run = await api.startEval(connectionId, {
        dataset,
        useMemory,
        verify,
        model: model.trim() || undefined,
      });
      setSelectedId(run.id);
      toast.success(`Eval run #${run.id} started`, { description: "Questions are paced to respect free-tier rate limits." });
      loadRuns();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const best = useMemo(() => runs?.reduce<number | null>((m, r) => (r.accuracy !== null && (m === null || r.accuracy > m) ? r.accuracy : m), null), [runs]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <PageHeader
        title="Evals"
        description="Execution accuracy: the agent answers known questions and its results are compared with hand-written gold SQL."
        actions={
          <>
            <select
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              className="h-8 rounded-lg border border-border bg-elevated px-2 text-xs"
            >
              {datasets.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name} ({d.size} questions)
                </option>
              ))}
            </select>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="model (default)"
              title="Chat model to evaluate. Leave empty for the configured one."
              className="h-8 w-36 rounded-lg border border-border bg-elevated px-2 text-xs placeholder:text-muted/60"
            />
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted">
              <input type="checkbox" checked={useMemory} onChange={(e) => setUseMemory(e.target.checked)} className="accent-violet-500" />
              Memory
            </label>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted" title="Self-consistency: extra LLM calls per question">
              <input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} className="accent-violet-500" />
              Verify
            </label>
            <Button size="sm" variant="primary" onClick={start} loading={starting} disabled={running}>
              {!starting && <Play className="h-3.5 w-3.5 fill-current" />} Run eval
            </Button>
          </>
        }
      />

      <div className="mx-auto w-full max-w-6xl space-y-5 p-4 sm:p-6">
        {!runs && <Skeleton className="h-40 rounded-xl" />}
        {runs?.length === 0 && (
          <Card>
            <EmptyState
              icon={<FlaskConical className="h-5 w-5" />}
              title="No eval runs yet"
              description="Run the Pagila suite (41 questions, easy to hard). Compare runs across models, memory on/off and verification to measure what each change is worth."
            />
          </Card>
        )}

        {runs && runs.length > 0 && (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Card className="p-4">
                <div className="text-[11px] uppercase tracking-wider text-muted">Latest accuracy</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums">{pct(runs.find((r) => r.accuracy !== null)?.accuracy ?? null)}</div>
              </Card>
              <Card className="p-4">
                <div className="text-[11px] uppercase tracking-wider text-muted">Best</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-ok">{pct(best ?? null)}</div>
              </Card>
              <Card className="p-4">
                <div className="text-[11px] uppercase tracking-wider text-muted">Runs</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums">{runs.length}</div>
              </Card>
            </div>

            <AccuracyChart runs={runs} />

            <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
              <div className="space-y-1.5">
                {runs.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => setSelectedId(r.id)}
                    className={cn(
                      "w-full rounded-xl border p-3 text-left transition",
                      r.id === selectedId ? "border-accent/50 bg-accent/5" : "border-border bg-panel/40 hover:border-border/100 hover:bg-elevated/50"
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">Run #{r.id}</span>
                      {r.status === "running" ? (
                        <Badge tone="accent">
                          <Loader2 className="h-3 w-3 animate-spin" /> {r.completed}/{r.total}
                        </Badge>
                      ) : r.status === "error" ? (
                        <Badge tone="danger">error</Badge>
                      ) : (
                        <Badge tone={(r.accuracy ?? 0) >= 0.8 ? "ok" : "warn"}>{pct(r.accuracy)}</Badge>
                      )}
                    </div>
                    <div className="mt-1 truncate font-mono text-[10.5px] text-muted">{r.model}</div>
                    <div className="text-[10.5px] text-muted">
                      memory {r.useMemory ? "on" : "off"}
                      {r.verify && " · verify"} · {timeAgo(r.createdAt)}
                    </div>
                    {r.label && <div className="truncate text-[10.5px] text-accent">{r.label}</div>}
                    {r.status === "running" && (
                      <div className="mt-2 h-1 overflow-hidden rounded-full bg-elevated">
                        <div className="h-full bg-accent transition-all" style={{ width: `${(r.completed / r.total) * 100}%` }} />
                      </div>
                    )}
                  </button>
                ))}
              </div>

              <div className="min-w-0 space-y-4">
              {detail && selectedId !== null && (
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  <GitCompare className="h-3.5 w-3.5" />
                  Compare run #{selectedId} against
                  <select
                    value={compareWith ?? ""}
                    onChange={(e) => setCompareWith(e.target.value ? Number(e.target.value) : null)}
                    className="h-7 rounded-md border border-border bg-elevated px-2 text-xs text-fg"
                  >
                    <option value="">none</option>
                    {runs
                      .filter((r) => r.id !== selectedId && r.status === "done")
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          #{r.id} · {r.model} · {pct(r.accuracy)}
                        </option>
                      ))}
                  </select>
                </div>
              )}
              {compare && <ComparePanel cmp={compare} />}
              {detail && <Breakdown detail={detail} />}
              <Card className="overflow-hidden">
                {!detail && <Skeleton className="h-64 rounded-none" />}
                {detail && (
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-border bg-elevated/60 text-[11px] uppercase tracking-wider text-muted">
                      <tr>
                        <th className="w-8 px-3 py-2" />
                        <th className="px-3 py-2 font-medium">Question</th>
                        <th className="hidden px-3 py-2 font-medium sm:table-cell">Steps</th>
                        <th className="hidden px-3 py-2 font-medium sm:table-cell">Time</th>
                        <th className="w-8 px-3 py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {detail.results.map((r) => (
                        <Fragment key={r.id}>
                          <tr
                            onClick={() => setExpanded((e) => (e === r.id ? null : r.id))}
                            className="cursor-pointer border-b border-border/50 hover:bg-elevated/40"
                          >
                            <td className="px-3 py-2">
                              {r.passed ? <CheckCircle2 className="h-4 w-4 text-ok" /> : <XCircle className="h-4 w-4 text-danger" />}
                            </td>
                            <td className="px-3 py-2 text-[13px]">
                              {r.question}
                              <span className="ml-2 inline-flex gap-1 align-middle">
                                {r.difficulty && <Badge tone={DIFFICULTY_TONE[r.difficulty] ?? "neutral"}>{r.difficulty}</Badge>}
                                {!r.passed && r.failureType && <Badge tone="danger">{FAILURE_LABEL[r.failureType] ?? r.failureType}</Badge>}
                              </span>
                            </td>
                            <td className="hidden px-3 py-2 font-mono text-xs text-muted sm:table-cell">{r.steps}</td>
                            <td className="hidden px-3 py-2 font-mono text-xs text-muted sm:table-cell">{(r.durationMs / 1000).toFixed(1)}s</td>
                            <td className="px-3 py-2">
                              <ChevronDown className={cn("h-3.5 w-3.5 text-muted transition", expanded === r.id && "rotate-180")} />
                            </td>
                          </tr>
                          {expanded === r.id && (
                            <tr className="border-b border-border/50 bg-bg/40">
                              <td colSpan={5} className="space-y-3 px-4 py-3">
                                {r.error && <p className="font-mono text-xs text-danger">{r.error}</p>}
                                <div className="grid gap-3 xl:grid-cols-2">
                                  <div>
                                    <div className="mb-1 text-[11px] uppercase tracking-wider text-muted">Gold SQL</div>
                                    <SqlCode sql={r.goldSql} connectionId={connectionId} maxHeight="max-h-48" />
                                  </div>
                                  <div>
                                    <div className="mb-1 text-[11px] uppercase tracking-wider text-muted">Agent SQL</div>
                                    {r.predictedSql ? (
                                      <SqlCode sql={r.predictedSql} connectionId={connectionId} maxHeight="max-h-48" />
                                    ) : (
                                      <p className="text-xs text-muted">No SQL produced.</p>
                                    )}
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                      {detail.results.length === 0 && (
                        <tr>
                          <td colSpan={5} className="px-3 py-10 text-center text-sm text-muted">
                            {detail.status === "running" ? "First results arriving shortly…" : detail.error ?? "No results."}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                )}
              </Card>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
