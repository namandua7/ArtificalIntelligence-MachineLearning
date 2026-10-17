"use client";

import { Command } from "cmdk";
import {
  BookMarked,
  Database,
  FlaskConical,
  Gauge,
  MessageSquare,
  Network,
  Search,
  SquareTerminal,
  Table2,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useWorkspace } from "@/components/WorkspaceContext";
import type { Conversation, SavedQuery } from "@/lib/api";
import { api } from "@/lib/api";

function Item({ onSelect, icon, children, hint }: { onSelect: () => void; icon: ReactNode; children: ReactNode; hint?: string }) {
  return (
    <Command.Item
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-muted aria-selected:bg-elevated aria-selected:text-fg"
    >
      <span className="text-muted">{icon}</span>
      <span className="flex-1 truncate">{children}</span>
      {hint && <span className="text-[11px] text-muted/70">{hint}</span>}
    </Command.Item>
  );
}

const GROUP = "px-1 py-1.5 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted/70";

export function CommandPalette() {
  const router = useRouter();
  const { connectionId, connections, schema } = useWorkspace();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [saved, setSaved] = useState<SavedQuery[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("qp:command-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("qp:command-palette", onOpen);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    setSearch("");
    api.conversations(connectionId).then(setConversations).catch(() => undefined);
    api.memory(connectionId).then(setSaved).catch(() => undefined);
  }, [open, connectionId]);

  const go = (path: string) => {
    setOpen(false);
    router.push(path);
  };
  const base = `/c/${connectionId}`;

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 pt-[12vh] backdrop-blur-sm" onClick={() => setOpen(false)}>
      <Command
        label="Command palette"
        className="glass w-full max-w-xl overflow-hidden rounded-2xl shadow-2xl shadow-black/60"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      >
        <div className="flex items-center gap-2 border-b border-border px-4">
          <Search className="h-4 w-4 text-muted" />
          <Command.Input
            autoFocus
            value={search}
            onValueChange={setSearch}
            placeholder="Ask a question, jump to a page, table or saved query…"
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted/70"
          />
        </div>
        <Command.List className="max-h-[60vh] overflow-y-auto p-1.5">
          <Command.Empty className="px-4 py-8 text-center text-sm text-muted">No results.</Command.Empty>

          {search.trim().length > 3 && (
            <Command.Group heading="Ask AI" className={GROUP}>
              <Item
                icon={<MessageSquare className="h-4 w-4 text-accent" />}
                onSelect={() => go(`${base}/ask?q=${encodeURIComponent(search.trim())}`)}
                hint="↵"
              >
                Ask: “{search.trim()}”
              </Item>
            </Command.Group>
          )}

          <Command.Group heading="Navigate" className={GROUP}>
            <Item icon={<MessageSquare className="h-4 w-4" />} onSelect={() => go(`${base}/ask`)}>Ask (new chat)</Item>
            <Item icon={<Network className="h-4 w-4" />} onSelect={() => go(`${base}/schema`)}>Schema diagram</Item>
            <Item icon={<SquareTerminal className="h-4 w-4" />} onSelect={() => go(`${base}/editor`)}>SQL editor</Item>
            <Item icon={<Gauge className="h-4 w-4" />} onSelect={() => go(`${base}/doctor`)}>Performance doctor</Item>
            <Item icon={<BookMarked className="h-4 w-4" />} onSelect={() => go(`${base}/memory`)}>Memory</Item>
            <Item icon={<FlaskConical className="h-4 w-4" />} onSelect={() => go(`${base}/evals`)}>Evals</Item>
          </Command.Group>

          {conversations.length > 0 && (
            <Command.Group heading="Recent chats" className={GROUP}>
              {conversations.slice(0, 8).map((c) => (
                <Item key={c.id} icon={<MessageSquare className="h-4 w-4" />} onSelect={() => go(`${base}/ask?c=${c.id}`)}>
                  {c.title}
                </Item>
              ))}
            </Command.Group>
          )}

          {saved.length > 0 && (
            <Command.Group heading="Saved queries" className={GROUP}>
              {saved.slice(0, 8).map((s) => (
                <Item
                  key={s.id}
                  icon={<BookMarked className="h-4 w-4" />}
                  onSelect={() => go(`${base}/editor?sql=${encodeURIComponent(s.sql)}`)}
                  hint="open in editor"
                >
                  {s.question}
                </Item>
              ))}
            </Command.Group>
          )}

          {schema && (
            <Command.Group heading="Tables" className={GROUP}>
              {schema.tables.map((t) => (
                <Item
                  key={t.name}
                  icon={<Table2 className="h-4 w-4" />}
                  onSelect={() => go(`${base}/schema?table=${encodeURIComponent(t.name)}`)}
                  hint={t.kind}
                >
                  {t.name}
                </Item>
              ))}
            </Command.Group>
          )}

          {connections.length > 1 && (
            <Command.Group heading="Switch database" className={GROUP}>
              {connections
                .filter((c) => c.id !== connectionId && c.indexStatus === "ready")
                .map((c) => (
                  <Item key={c.id} icon={<Database className="h-4 w-4" />} onSelect={() => go(`/c/${c.id}/ask`)}>
                    {c.name}
                  </Item>
                ))}
            </Command.Group>
          )}
        </Command.List>
      </Command>
    </div>
  );
}
