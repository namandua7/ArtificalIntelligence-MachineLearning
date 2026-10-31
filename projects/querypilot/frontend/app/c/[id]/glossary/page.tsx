"use client";

import { AnimatePresence, motion } from "framer-motion";
import { BookText, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Dialog } from "@/components/ui/dialog";
import { Badge, Button, Card, EmptyState, Input, PageHeader, Skeleton, Textarea } from "@/components/ui/primitives";
import { useWorkspace } from "@/components/WorkspaceContext";
import type { GlossaryTerm } from "@/lib/api";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

type Draft = { id?: number; term: string; aliases: string; definition: string; sqlSnippet: string };

const EXAMPLES: Omit<Draft, "id">[] = [
  {
    term: "revenue",
    aliases: "sales, turnover, income",
    definition: "Money received from customers: the sum of payment amounts.",
    sqlSnippet: "SUM(payment.amount)",
  },
  {
    term: "active customer",
    aliases: "current customer",
    definition: "A customer flagged as active in the customer table.",
    sqlSnippet: "customer.active = 1",
  },
];

const toInput = (d: Draft) => ({
  term: d.term.trim(),
  aliases: d.aliases.split(",").map((a) => a.trim()).filter(Boolean),
  definition: d.definition.trim(),
  sqlSnippet: d.sqlSnippet.trim() || null,
});

export default function GlossaryPage() {
  const { connectionId } = useWorkspace();
  const [items, setItems] = useState<GlossaryTerm[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api.glossary(connectionId).then(setItems).catch((err) => toast.error(err.message));
  }, [connectionId]);

  useEffect(load, [load]);

  const submit = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      if (draft.id) await api.updateTerm(draft.id, toInput(draft));
      else await api.createTerm(connectionId, toInput(draft));
      toast.success(draft.id ? "Term updated" : "Term added");
      setDraft(null);
      load();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (item: GlossaryTerm) => {
    try {
      await api.deleteTerm(item.id);
      setItems((xs) => xs?.filter((x) => x.id !== item.id) ?? null);
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <PageHeader
        title="Glossary"
        description="Your semantic layer: define business terms once, and every answer uses the same meaning."
        actions={
          <Button variant="primary" size="sm" onClick={() => setDraft({ term: "", aliases: "", definition: "", sqlSnippet: "" })}>
            <Plus className="h-3.5 w-3.5" /> Add term
          </Button>
        }
      />

      <div className="mx-auto w-full max-w-5xl space-y-3 p-4 sm:p-6">
        <Card className="flex items-start gap-3 border-accent/20 bg-accent/5 p-4 text-xs leading-relaxed text-muted">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
          <div>
            When a question mentions a term (or an alias, or something close in meaning), its definition and SQL are
            injected into the agent&apos;s instructions as <b className="text-fg">authoritative</b>. That stops the model
            from picking a plausible but different meaning of “revenue” or “active customer” from one question to the next.
          </div>
        </Card>

        {!items && [0, 1].map((i) => <Skeleton key={i} className="h-24 rounded-xl" />)}

        {items?.length === 0 && (
          <Card>
            <EmptyState
              icon={<BookText className="h-5 w-5" />}
              title="No business terms yet"
              description="Add the words your team uses (revenue, active customer, churn…) and how they map to your tables."
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  {EXAMPLES.map((e) => (
                    <Button key={e.term} size="sm" variant="outline" onClick={() => setDraft(e)}>
                      <Plus className="h-3.5 w-3.5" /> “{e.term}”
                    </Button>
                  ))}
                </div>
              }
            />
          </Card>
        )}

        <AnimatePresence initial={false}>
          {items?.map((item) => (
            <motion.div key={item.id} layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: -20 }}>
              <Card className="space-y-2 p-4">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold">{item.term}</span>
                      {item.aliases.map((a) => (
                        <Badge key={a}>{a}</Badge>
                      ))}
                    </div>
                    <p className="mt-1 text-sm text-muted">{item.definition}</p>
                    <div className="mt-0.5 text-[11px] text-muted/70">added {timeAgo(item.createdAt)}</div>
                  </div>
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Edit"
                    onClick={() =>
                      setDraft({
                        id: item.id,
                        term: item.term,
                        aliases: item.aliases.join(", "),
                        definition: item.definition,
                        sqlSnippet: item.sqlSnippet ?? "",
                      })
                    }
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button size="icon" variant="ghost" title="Delete" onClick={() => remove(item)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
                {item.sqlSnippet && (
                  <pre className="overflow-x-auto rounded-lg border border-border bg-bg/60 px-3 py-2 font-mono text-xs text-accent-2">
                    {item.sqlSnippet}
                  </pre>
                )}
              </Card>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      <Dialog
        open={draft !== null}
        onOpenChange={(o) => !o && setDraft(null)}
        title={draft?.id ? "Edit term" : "Add term"}
        description="Saved terms apply to the next question you ask."
        className="max-w-2xl"
      >
        {draft && (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted">Term</span>
                <Input value={draft.term} onChange={(e) => setDraft({ ...draft, term: e.target.value })} placeholder="revenue" />
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted">Aliases (comma-separated)</span>
                <Input value={draft.aliases} onChange={(e) => setDraft({ ...draft, aliases: e.target.value })} placeholder="sales, turnover" />
              </label>
            </div>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-muted">Definition</span>
              <Textarea
                value={draft.definition}
                onChange={(e) => setDraft({ ...draft, definition: e.target.value })}
                rows={3}
                placeholder="What it means in your business, in plain English."
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-muted">SQL (optional)</span>
              <Textarea
                value={draft.sqlSnippet}
                onChange={(e) => setDraft({ ...draft, sqlSnippet: e.target.value })}
                rows={3}
                className="font-mono text-xs"
                placeholder="SUM(payment.amount)"
              />
            </label>
            <div className="flex justify-end">
              <Button variant="primary" onClick={submit} loading={saving} disabled={!draft.term.trim() || !draft.definition.trim()}>
                Save
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
