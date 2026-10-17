"use client";

import { CheckCircle2, Database, Sparkles, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Input } from "@/components/ui/primitives";
import { Dialog } from "@/components/ui/dialog";
import type { Connection } from "@/lib/api";
import { api } from "@/lib/api";

export function AddConnectionDialog({
  open,
  onOpenChange,
  sampleUrl,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sampleUrl?: string;
  onCreated: (connection: Connection) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);

  const useSample = () => {
    if (!sampleUrl) return;
    setName("Pagila (DVD rental sample)");
    setUrl(sampleUrl);
    setTest(null);
  };

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      const res = await api.testConnection(url);
      setTest(res.ok ? { ok: true, message: res.version?.split(" on ")[0] ?? "Connected" } : { ok: false, message: res.error ?? "Failed" });
    } catch (err) {
      setTest({ ok: false, message: (err as Error).message });
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const connection = await api.createConnection(name, url);
      toast.success("Connected", { description: "Indexing schema in the background…" });
      onCreated(connection);
      onOpenChange(false);
      setName("");
      setUrl("");
      setTest(null);
    } catch (err) {
      toast.error("Could not add connection", { description: (err as Error).message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Connect a database"
      description="PostgreSQL only. Use a read-only user. The URL is encrypted at rest."
    >
      <div className="space-y-4">
        {sampleUrl && (
          <button
            onClick={useSample}
            className="group flex w-full items-center gap-3 rounded-xl border border-dashed border-accent/40 bg-accent/5 p-3 text-left transition hover:border-accent/70 hover:bg-accent/10"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/15 text-accent">
              <Sparkles className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-medium">Use the sample database</div>
              <div className="text-xs text-muted">Pagila: films, rentals, payments, customers (docker-compose)</div>
            </div>
          </button>
        )}
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-muted">Name</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Production replica" />
        </label>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-muted">Connection URL</span>
          <Input
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              setTest(null);
            }}
            placeholder="postgresql://readonly_user:password@host:5432/dbname"
            className="font-mono text-xs"
          />
        </label>
        {test && (
          <div
            className={`flex items-start gap-2 rounded-lg border p-2.5 text-xs ${
              test.ok ? "border-ok/30 bg-ok/5 text-ok" : "border-danger/30 bg-danger/5 text-danger"
            }`}
          >
            {test.ok ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
            <span className="break-all font-mono">{test.message}</span>
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={runTest} loading={testing} disabled={!url}>
            Test
          </Button>
          <Button variant="primary" onClick={save} loading={saving} disabled={!name.trim() || !url.trim()}>
            <Database className="h-4 w-4" />
            Connect & index
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
