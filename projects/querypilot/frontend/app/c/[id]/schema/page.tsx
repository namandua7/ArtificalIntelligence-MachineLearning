"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Eye, KeyRound, Link2, MessageSquare, Search, SquareTerminal, X } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { ResultsTable } from "@/components/ResultsTable";
import { Badge, Button, Input, Skeleton } from "@/components/ui/primitives";
import { useWorkspace } from "@/components/WorkspaceContext";
import type { QueryResult } from "@/lib/api";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

const SchemaDiagram = dynamic(() => import("@/components/SchemaDiagram").then((m) => m.SchemaDiagram), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full rounded-none" />,
});

function TablePanel({ name, onClose, onSelect }: { name: string; onClose: () => void; onSelect: (n: string) => void }) {
  const { schema, connectionId, meta } = useWorkspace();
  const table = schema?.tables.find((t) => t.name === name);
  const [sample, setSample] = useState<QueryResult | null>(null);
  const [sampleError, setSampleError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setSample(null);
    setSampleError(null);
  }, [name]);

  if (!table || !schema) return null;
  const outgoing = schema.relations.filter((r) => r.fromTable === name);
  const incoming = schema.relations.filter((r) => r.toTable === name);

  const loadSample = async () => {
    setLoading(true);
    try {
      setSample(await api.sampleRows(connectionId, name));
    } catch (err) {
      setSampleError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.aside
      initial={{ x: 24, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: 24, opacity: 0 }}
      className="glass absolute inset-y-3 right-3 z-10 flex w-[min(420px,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl shadow-2xl shadow-black/40"
    >
      <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {table.kind === "view" && <Eye className="h-4 w-4 text-accent-2" />}
            <h2 className="truncate font-mono text-sm font-semibold">{table.name}</h2>
            <Badge tone={table.kind === "view" ? "cyan" : "accent"}>{table.kind}</Badge>
          </div>
          <p className="mt-0.5 text-xs text-muted">
            {table.columns.length} columns
            {table.rowEstimate !== null && table.kind === "table" && ` · ~${formatNumber(table.rowEstimate)} rows`}
          </p>
          {table.comment && <p className="mt-1 text-xs text-fg/80">{table.comment}</p>}
        </div>
        <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-elevated hover:text-fg">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
        <div className="flex gap-2">
          <Link href={`/c/${connectionId}/ask?q=${encodeURIComponent(`Give me an overview of the ${table.name} table`)}`} className="flex-1">
            <Button size="sm" variant="primary" className="w-full">
              <MessageSquare className="h-3.5 w-3.5" /> Ask about it
            </Button>
          </Link>
          <Link href={`/c/${connectionId}/editor?sql=${encodeURIComponent(`SELECT *\nFROM ${table.name}\nLIMIT 50;`)}`} className="flex-1">
            <Button size="sm" variant="outline" className="w-full">
              <SquareTerminal className="h-3.5 w-3.5" /> Query
            </Button>
          </Link>
        </div>

        <section>
          <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-muted">Columns</h3>
          <div className="divide-y divide-border/60 rounded-lg border border-border">
            {table.columns.map((c) => (
              <div key={c.name} className="flex items-center gap-2 px-3 py-1.5 text-xs">
                <span className="w-3.5 shrink-0">
                  {c.pk ? <KeyRound className="h-3 w-3 text-warn" /> : c.fk ? <Link2 className="h-3 w-3 text-accent" /> : null}
                </span>
                <span className="font-mono">{c.name}</span>
                {!c.nullable && !c.pk && <span className="text-[10px] text-muted/70">not null</span>}
                <span className="ml-auto truncate pl-2 font-mono text-[10.5px] text-muted">{c.type}</span>
              </div>
            ))}
          </div>
        </section>

        {(outgoing.length > 0 || incoming.length > 0) && (
          <section>
            <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-muted">Relationships</h3>
            <div className="space-y-1">
              {outgoing.map((r) => (
                <button
                  key={`o-${r.fromColumn}-${r.toTable}`}
                  onClick={() => onSelect(r.toTable)}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left font-mono text-[11.5px] text-muted transition hover:bg-elevated hover:text-fg"
                >
                  {r.fromColumn} <ArrowRight className="h-3 w-3 text-accent" /> {r.toTable}.{r.toColumn}
                </button>
              ))}
              {incoming.map((r) => (
                <button
                  key={`i-${r.fromTable}-${r.fromColumn}`}
                  onClick={() => onSelect(r.fromTable)}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left font-mono text-[11.5px] text-muted transition hover:bg-elevated hover:text-fg"
                >
                  {r.fromTable}.{r.fromColumn} <ArrowRight className="h-3 w-3 text-accent-2" /> {r.toColumn}
                </button>
              ))}
            </div>
          </section>
        )}

        {meta?.allowSampleRows && (
          <section>
            <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-muted">Sample rows</h3>
            {!sample && !sampleError && (
              <Button size="sm" variant="outline" onClick={loadSample} loading={loading}>
                Load 20 rows
              </Button>
            )}
            {sampleError && <p className="text-xs text-danger">{sampleError}</p>}
            {sample && <ResultsTable columns={sample.columns} rows={sample.rows} className="max-h-72" />}
          </section>
        )}
      </div>
    </motion.aside>
  );
}

function SchemaInner() {
  const { schema } = useWorkspace();
  const params = useSearchParams();
  const [search, setSearch] = useState("");
  const [showViews, setShowViews] = useState(false);
  const [selected, setSelected] = useState<string | null>(params.get("table"));

  useEffect(() => {
    const t = params.get("table");
    if (t) {
      setSelected(t);
      if (schema?.tables.find((x) => x.name === t)?.kind === "view") setShowViews(true);
    }
  }, [params, schema]);

  const counts = useMemo(
    () => ({
      tables: schema?.tables.filter((t) => t.kind === "table").length ?? 0,
      views: schema?.tables.filter((t) => t.kind === "view").length ?? 0,
      relations: schema?.relations.length ?? 0,
    }),
    [schema]
  );

  return (
    <div className="relative flex min-h-[70vh] flex-1 flex-col md:min-h-0">
      <div className="flex flex-wrap items-center gap-3 border-b border-border/60 px-4 py-2.5">
        <h1 className="text-sm font-medium">Schema</h1>
        <span className="text-xs text-muted">
          {counts.tables} tables · {counts.views} views · {counts.relations} foreign keys
        </span>
        <div className="ml-auto flex items-center gap-2">
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted">
            <input
              type="checkbox"
              checked={showViews}
              onChange={(e) => setShowViews(e.target.checked)}
              className="accent-violet-500"
            />
            Show views
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Find table or column"
              className="h-8 w-56 pl-8 text-xs"
            />
          </div>
        </div>
      </div>
      <div className="relative min-h-0 flex-1 bg-bg/40">
        {schema ? (
          <SchemaDiagram schema={schema} showViews={showViews} search={search} selected={selected} onSelect={setSelected} />
        ) : (
          <Skeleton className="h-full w-full rounded-none" />
        )}
        <AnimatePresence>
          {selected && <TablePanel key={selected} name={selected} onClose={() => setSelected(null)} onSelect={setSelected} />}
        </AnimatePresence>
      </div>
    </div>
  );
}

export default function SchemaPage() {
  return (
    <Suspense>
      <SchemaInner />
    </Suspense>
  );
}
