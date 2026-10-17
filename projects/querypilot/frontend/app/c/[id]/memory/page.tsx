"use client";

import { AnimatePresence, motion } from "framer-motion";
import { BookMarked, Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { SqlCode } from "@/components/SqlCode";
import { Dialog } from "@/components/ui/dialog";
import { Badge, Button, Card, EmptyState, Input, PageHeader, Skeleton, Textarea } from "@/components/ui/primitives";
import { useWorkspace } from "@/components/WorkspaceContext";
import type { SavedQuery } from "@/lib/api";
import { api } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";

type Draft = { id?: number; question: string; sql: string };

export default function MemoryPage() {
  const { connectionId } = useWorkspace();
  const [items, setItems] = useState<SavedQuery[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api.memory(connectionId).then(setItems).catch((err) => toast.error(err.message));
  }, [connectionId]);

  useEffect(load, [load]);

  const submit = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      if (draft.id) await api.updateMemory(draft.id, { question: draft.question, sql: draft.sql });
      else await api.createMemory(connectionId, draft.question, draft.sql);
      toast.success(draft.id ? "Updated" : "Added to memory");
      setDraft(null);
      load();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (item: SavedQuery) => {
    try {
      await api.updateMemory(item.id, { verified: !item.verified });
      load();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  const remove = async (item: SavedQuery) => {
    try {
      await api.deleteMemory(item.id);
      setItems((xs) => xs?.filter((x) => x.id !== item.id) ?? null);
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <PageHeader
        title="Memory"
        description="Verified question → SQL pairs. The most similar ones are retrieved as few-shot examples for new questions."
        actions={
          <Button variant="primary" size="sm" onClick={() => setDraft({ question: "", sql: "" })}>
            <Plus className="h-3.5 w-3.5" /> Add example
          </Button>
        }
      />

      <div className="mx-auto w-full max-w-5xl space-y-3 p-4 sm:p-6">
        <Card className="flex items-start gap-3 border-accent/20 bg-accent/5 p-4 text-xs leading-relaxed text-muted">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
          <div>
            Click 👍 on a correct answer in <b className="text-fg">Ask</b> to save it here. Examples are embedded locally
            (nomic-embed-text) and retrieved by similarity (≥ 0.55), so the agent reuses your team&apos;s conventions:
            which table holds revenue, how “active customer” is defined, and so on. Unverified examples are kept but not used.
          </div>
        </Card>

        {!items && [0, 1, 2].map((i) => <Skeleton key={i} className="h-32 rounded-xl" />)}

        {items?.length === 0 && (
          <Card>
            <EmptyState
              icon={<BookMarked className="h-5 w-5" />}
              title="No examples yet"
              description="Give a 👍 to correct answers, or add an example manually."
            />
          </Card>
        )}

        <AnimatePresence initial={false}>
          {items?.map((item) => (
            <motion.div key={item.id} layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: -20 }}>
              <Card className={cn("space-y-3 p-4", !item.verified && "opacity-60")}>
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{item.question}</div>
                    <div className="mt-0.5 text-[11px] text-muted">added {timeAgo(item.createdAt)}</div>
                  </div>
                  <button onClick={() => toggle(item)} title="Toggle whether the agent uses this example">
                    <Badge tone={item.verified ? "ok" : "neutral"}>{item.verified ? "✓ used by agent" : "disabled"}</Badge>
                  </button>
                  <Button size="icon" variant="ghost" title="Edit" onClick={() => setDraft({ id: item.id, question: item.question, sql: item.sql })}>
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button size="icon" variant="ghost" title="Delete" onClick={() => remove(item)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <SqlCode sql={item.sql} connectionId={connectionId} maxHeight="max-h-44" />
              </Card>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      <Dialog
        open={draft !== null}
        onOpenChange={(o) => !o && setDraft(null)}
        title={draft?.id ? "Edit example" : "Add example"}
        description="The SQL is validated against the database before saving."
        className="max-w-2xl"
      >
        {draft && (
          <div className="space-y-4">
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-muted">Question</span>
              <Input value={draft.question} onChange={(e) => setDraft({ ...draft, question: e.target.value })} placeholder="Revenue per store per month" />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-muted">SQL</span>
              <Textarea
                value={draft.sql}
                onChange={(e) => setDraft({ ...draft, sql: e.target.value })}
                rows={8}
                className="font-mono text-xs"
                placeholder="SELECT ..."
              />
            </label>
            <div className="flex justify-end">
              <Button variant="primary" onClick={submit} loading={saving} disabled={!draft.question.trim() || !draft.sql.trim()}>
                Save
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
