"use client";

import { motion } from "framer-motion";
import {
  ArrowRight,
  BrainCircuit,
  Database,
  Gauge,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { AddConnectionDialog } from "@/components/AddConnectionDialog";
import { LlmBadge, useMeta } from "@/components/LlmBadge";
import { Logo } from "@/components/Logo";
import { Badge, Button, Card, EmptyState, Skeleton } from "@/components/ui/primitives";
import type { Connection } from "@/lib/api";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

const FEATURES = [
  { icon: BrainCircuit, title: "Self-correcting agent", text: "Writes SQL, runs it, reads errors, fixes itself." },
  { icon: Workflow, title: "Schema RAG", text: "Hybrid search + foreign-key graph finds the right tables." },
  { icon: Gauge, title: "Performance doctor", text: "EXPLAIN plans + hypothetical-index cost measurements." },
  { icon: ShieldCheck, title: "Read-only by design", text: "SQL guard, read-only transactions, timeouts." },
];

function StatusBadge({ connection }: { connection: Connection }) {
  switch (connection.indexStatus) {
    case "ready":
      return <Badge tone="ok">● Ready</Badge>;
    case "error":
      return <Badge tone="danger">Index failed</Badge>;
    default:
      return (
        <Badge tone="accent">
          <Loader2 className="h-3 w-3 animate-spin" /> Indexing
        </Badge>
      );
  }
}

export default function HomePage() {
  const meta = useMeta();
  const [connections, setConnections] = useState<Connection[] | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setConnections(await api.listConnections());
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while any connection is still indexing.
  useEffect(() => {
    if (!connections?.some((c) => c.indexStatus === "pending" || c.indexStatus === "indexing")) return;
    const id = setInterval(load, 1500);
    return () => clearInterval(id);
  }, [connections, load]);

  const remove = async (c: Connection) => {
    if (!confirm(`Remove "${c.name}"? Its schema index, chats and memory are deleted (the database itself is untouched).`)) return;
    try {
      await api.deleteConnection(c.id);
      toast.success("Connection removed");
      load();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  const reindex = async (c: Connection) => {
    try {
      await api.reindex(c.id);
      load();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
      <header className="flex items-center justify-between py-6">
        <Logo />
        <LlmBadge meta={meta} />
      </header>

      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="pb-12 pt-10 text-center sm:pt-16"
      >
        <Badge tone="accent" className="mb-5 px-2.5 py-1 text-xs">
          LLM agent · Schema RAG · MCP server
        </Badge>
        <h1 className="mx-auto max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
          Ask your database <span className="gradient-text">anything</span>.
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-base text-muted">
          QueryPilot turns plain English into tested SQL, charts the results, and tells you why your slow
          queries are slow.
        </p>
        <div className="mt-8 flex justify-center gap-3">
          <Button variant="primary" size="lg" onClick={() => setDialogOpen(true)}>
            <Plus className="h-4 w-4" /> Connect a database
          </Button>
        </div>
      </motion.section>

      <div className="mb-14 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {FEATURES.map((f, i) => (
          <motion.div
            key={f.title}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 + i * 0.06 }}
          >
            <Card className="h-full p-4">
              <f.icon className="mb-3 h-5 w-5 text-accent" />
              <div className="text-sm font-medium">{f.title}</div>
              <div className="mt-1 text-xs leading-relaxed text-muted">{f.text}</div>
            </Card>
          </motion.div>
        ))}
      </div>

      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">Your databases</h2>
          {connections && connections.length > 0 && (
            <Button size="sm" variant="outline" onClick={() => setDialogOpen(true)}>
              <Plus className="h-3.5 w-3.5" /> Add
            </Button>
          )}
        </div>

        {error && (
          <Card className="border-danger/40 p-4 text-sm text-danger">
            {error}
            <div className="mt-1 text-xs text-muted">
              Start it with <code className="font-mono">uvicorn app.main:app --port 8001</code> in backend/.
            </div>
          </Card>
        )}

        {!connections && !error && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-36 rounded-xl" />
            ))}
          </div>
        )}

        {connections && connections.length === 0 && (
          <Card>
            <EmptyState
              icon={<Database className="h-5 w-5" />}
              title="No databases yet"
              description="Connect a PostgreSQL database, or start with the bundled Pagila sample."
              action={
                <Button variant="primary" onClick={() => setDialogOpen(true)}>
                  <Plus className="h-4 w-4" /> Connect a database
                </Button>
              }
            />
          </Card>
        )}

        {connections && connections.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {connections.map((c, i) => (
              <motion.div key={c.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
                <Card className="group relative flex h-full flex-col p-4 transition hover:border-accent/40">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 flex-1 items-center gap-2.5">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-elevated">
                        <Database className="h-4 w-4 text-accent-2" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{c.name}</div>
                        <div className="truncate font-mono text-[11px] text-muted">{c.displayUrl}</div>
                      </div>
                    </div>
                    <div className="shrink-0">
                      <StatusBadge connection={c} />
                    </div>
                  </div>
                  {c.indexStatus === "error" && (
                    <p className="mt-3 line-clamp-2 text-xs text-danger">{c.indexError}</p>
                  )}
                  <div className="mt-4 flex items-center gap-3 text-xs text-muted">
                    <span>{c.tableCount} tables</span>
                    {c.lastIndexedAt && <span>· indexed {timeAgo(c.lastIndexedAt)}</span>}
                  </div>
                  <div className="mt-4 flex items-center gap-2 pt-1">
                    {c.indexStatus === "ready" ? (
                      <Link href={`/c/${c.id}/ask`} className="flex-1">
                        <Button variant="primary" size="sm" className="w-full">
                          Open <ArrowRight className="h-3.5 w-3.5" />
                        </Button>
                      </Link>
                    ) : (
                      <Button size="sm" className="flex-1" disabled>
                        {c.indexStatus === "error" ? "Unavailable" : "Indexing schema…"}
                      </Button>
                    )}
                    <Button size="icon" variant="ghost" title="Re-index schema" onClick={() => reindex(c)}>
                      <RefreshCw className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="icon" variant="ghost" title="Remove" onClick={() => remove(c)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </Card>
              </motion.div>
            ))}
          </div>
        )}
      </section>

      <AddConnectionDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        sampleUrl={meta?.sampleConnectionUrl}
        onCreated={() => load()}
      />
    </div>
  );
}
