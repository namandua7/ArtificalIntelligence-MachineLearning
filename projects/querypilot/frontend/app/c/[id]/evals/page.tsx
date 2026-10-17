"use client";

import { CheckCircle2, ChevronDown, FlaskConical, Loader2, Play, XCircle } from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { SqlCode } from "@/components/SqlCode";
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { useWorkspace } from "@/components/WorkspaceContext";
import type { EvalRun, EvalRunDetail } from "@/lib/api";
import { api } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";

function pct(v: number | null) {
  return v === null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function AccuracyChart({ runs }: { runs: EvalRun[] }) {
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

export default function EvalsPage() {
  const { connectionId } = useWorkspace();
  const [datasets, setDatasets] = useState<{ name: string; size: number }[]>([]);
  const [dataset, setDataset] = useState("pagila");
  const [useMemory, setUseMemory] = useState(true);
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

  const running = runs?.some((r) => r.status === "running");
  useEffect(() => {
    if (!running) return;
    const id = setInterval(loadRuns, 2500);
    return () => clearInterval(id);
  }, [running, loadRuns]);

  const start = async () => {
    setStarting(true);
    try {
      const run = await api.startEval(connectionId, dataset, useMemory);
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
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted">
              <input type="checkbox" checked={useMemory} onChange={(e) => setUseMemory(e.target.checked)} className="accent-violet-500" />
              Use memory
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
              description="Run the Pagila suite (22 questions). Compare runs with memory on vs off to measure what 👍 feedback is worth."
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
                      memory {r.useMemory ? "on" : "off"} · {timeAgo(r.createdAt)}
                    </div>
                    {r.status === "running" && (
                      <div className="mt-2 h-1 overflow-hidden rounded-full bg-elevated">
                        <div className="h-full bg-accent transition-all" style={{ width: `${(r.completed / r.total) * 100}%` }} />
                      </div>
                    )}
                  </button>
                ))}
              </div>

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
                            <td className="px-3 py-2 text-[13px]">{r.question}</td>
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
          </>
        )}
      </div>
    </div>
  );
}
