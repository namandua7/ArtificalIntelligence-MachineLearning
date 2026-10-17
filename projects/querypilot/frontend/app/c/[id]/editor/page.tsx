"use client";

import { AlertCircle, BookmarkPlus, Gauge, Play, Sparkles, WandSparkles } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ResultView } from "@/components/ResultView";
import { SqlCode } from "@/components/SqlCode";
import { Dialog } from "@/components/ui/dialog";
import { Button, EmptyState, Input, Kbd, Skeleton } from "@/components/ui/primitives";
import { useWorkspace } from "@/components/WorkspaceContext";
import type { QueryResult } from "@/lib/api";
import { api } from "@/lib/api";

const SqlEditor = dynamic(() => import("@/components/SqlEditor").then((m) => m.SqlEditor), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full rounded-none" />,
});

const DRAFT_KEY = (id: number) => `qp:editor-draft:${id}`;

function readDraft(id: number): string | null {
  try {
    return localStorage.getItem(DRAFT_KEY(id));
  } catch {
    return null;
  }
}

function EditorInner() {
  const { connectionId, schema } = useWorkspace();
  const params = useSearchParams();
  const [sql, setSql] = useState<string>("");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [fix, setFix] = useState<{ sql: string; explanation: string } | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const fromUrl = params.get("sql");
    setSql(fromUrl ?? readDraft(connectionId) ?? "SELECT *\nFROM film\nLIMIT 20;");
  }, [params, connectionId]);

  useEffect(() => {
    try {
      localStorage.setItem(DRAFT_KEY(connectionId), sql);
    } catch {
      // storage unavailable: drafts just won't persist
    }
  }, [sql, connectionId]);

  const run = useCallback(async () => {
    if (!sql.trim()) return;
    setRunning(true);
    setError(null);
    setFix(null);
    try {
      setResult(await api.runQuery(connectionId, sql));
    } catch (err) {
      setResult(null);
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }, [connectionId, sql]);

  const format = async () => {
    try {
      setSql((await api.formatSql(sql)).sql);
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  const askFix = async () => {
    if (!error) return;
    setFixing(true);
    try {
      setFix(await api.fixSql(connectionId, sql, error));
    } catch (err) {
      toast.error("AI fix failed", { description: (err as Error).message });
    } finally {
      setFixing(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.createMemory(connectionId, question, sql);
      toast.success("Saved to memory", { description: "Used as an example for similar questions." });
      setSaveOpen(false);
      setQuestion("");
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-4 py-2.5">
        <h1 className="mr-2 text-sm font-medium">SQL Editor</h1>
        <Button size="sm" variant="primary" onClick={run} loading={running}>
          {!running && <Play className="h-3.5 w-3.5 fill-current" />} Run
        </Button>
        <span className="hidden text-[11px] text-muted sm:inline">
          <Kbd>⌘</Kbd> <Kbd>↵</Kbd>
        </span>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="ghost" onClick={format}>
            <WandSparkles className="h-3.5 w-3.5" /> Format
          </Button>
          <Link href={`/c/${connectionId}/doctor?sql=${encodeURIComponent(sql)}`}>
            <Button size="sm" variant="ghost">
              <Gauge className="h-3.5 w-3.5" /> Analyze
            </Button>
          </Link>
          <Button size="sm" variant="outline" onClick={() => setSaveOpen(true)} disabled={!sql.trim()}>
            <BookmarkPlus className="h-3.5 w-3.5" /> Save
          </Button>
        </div>
      </div>

      <div className="h-[40vh] shrink-0 border-b border-border/60 md:h-[45%]">
        <SqlEditor value={sql} onChange={setSql} onRun={run} schema={schema} />
      </div>

      <div className="min-h-[40vh] flex-1 overflow-auto p-4 md:min-h-0">
        {error && (
          <div className="space-y-3">
            <div className="rounded-xl border border-danger/30 bg-danger/5 p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
                <pre className="flex-1 whitespace-pre-wrap font-mono text-xs text-danger/90">{error}</pre>
                {!error.startsWith("Blocked") && (
                  <Button size="sm" variant="primary" onClick={askFix} loading={fixing}>
                    {!fixing && <Sparkles className="h-3.5 w-3.5" />} Fix with AI
                  </Button>
                )}
              </div>
            </div>
            {fix && (
              <div className="glass space-y-3 rounded-xl p-3">
                <div className="flex items-center gap-2 text-sm">
                  <Sparkles className="h-4 w-4 text-accent" />
                  <span className="text-fg/90">{fix.explanation}</span>
                </div>
                <SqlCode sql={fix.sql} />
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setFix(null)}>
                    Dismiss
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => {
                      setSql(fix.sql);
                      setFix(null);
                      setError(null);
                    }}
                  >
                    Apply fix
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
        {result && <ResultView result={result} className="h-full" tableClassName="flex-1" />}
        {!result && !error && (
          <EmptyState
            icon={<Play className="h-5 w-5" />}
            title="Run a query"
            description="Read-only SELECTs only. Autocomplete knows your tables and columns."
          />
        )}
      </div>

      <Dialog
        open={saveOpen}
        onOpenChange={setSaveOpen}
        title="Save to memory"
        description="Describe what this query answers. Similar future questions will use it as a verified example."
      >
        <div className="space-y-4">
          <Input
            autoFocus
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. Monthly revenue per store"
          />
          <SqlCode sql={sql} maxHeight="max-h-40" />
          <div className="flex justify-end">
            <Button variant="primary" onClick={save} loading={saving} disabled={!question.trim()}>
              Save
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

export default function EditorPage() {
  return (
    <Suspense>
      <EditorInner />
    </Suspense>
  );
}
