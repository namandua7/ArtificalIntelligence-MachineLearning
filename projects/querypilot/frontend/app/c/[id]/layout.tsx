"use client";

import {
  BookMarked,
  ChevronLeft,
  Database,
  FlaskConical,
  Gauge,
  MessageSquare,
  Network,
  Search,
  SquareTerminal,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { CommandPalette } from "@/components/CommandPalette";
import { LlmBadge } from "@/components/LlmBadge";
import { Logo } from "@/components/Logo";
import { Kbd } from "@/components/ui/primitives";
import { WorkspaceProvider, useWorkspace } from "@/components/WorkspaceContext";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "ask", label: "Ask", icon: MessageSquare },
  { href: "schema", label: "Schema", icon: Network },
  { href: "editor", label: "SQL Editor", icon: SquareTerminal },
  { href: "doctor", label: "Doctor", icon: Gauge },
  { href: "memory", label: "Memory", icon: BookMarked },
  { href: "evals", label: "Evals", icon: FlaskConical },
];

function Sidebar() {
  const pathname = usePathname();
  const { connectionId, connection, meta } = useWorkspace();
  const base = `/c/${connectionId}`;

  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-border/60 bg-panel/40 backdrop-blur-xl md:h-screen md:w-60 md:border-b-0 md:border-r">
      <div className="flex items-center justify-between px-4 py-4">
        <Link href="/">
          <Logo />
        </Link>
      </div>

      <div className="px-3">
        <Link
          href="/"
          className="group flex items-center gap-2.5 rounded-lg border border-border bg-elevated/60 p-2.5 transition hover:border-accent/40"
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent-2/10">
            <Database className="h-3.5 w-3.5 text-accent-2" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-medium">{connection?.name ?? "Loading…"}</div>
            <div className="text-[11px] text-muted">{connection ? `${connection.tableCount} tables` : " "}</div>
          </div>
          <ChevronLeft className="h-3.5 w-3.5 text-muted opacity-0 transition group-hover:opacity-100" />
        </Link>

        <button
          onClick={() => window.dispatchEvent(new Event("qp:command-palette"))}
          className="mt-3 flex w-full items-center gap-2 rounded-lg border border-border bg-bg/40 px-2.5 py-2 text-xs text-muted transition hover:text-fg"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="flex-1 text-left">Search…</span>
          <Kbd>⌘K</Kbd>
        </button>
      </div>

      <nav className="flex gap-1 overflow-x-auto px-3 py-3 md:flex-col md:overflow-visible">
        {NAV.map((item) => {
          const href = `${base}/${item.href}`;
          const active = pathname.startsWith(href);
          return (
            <Link
              key={item.href}
              href={href}
              className={cn(
                "relative flex shrink-0 items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition",
                active ? "bg-elevated text-fg" : "text-muted hover:bg-elevated/60 hover:text-fg"
              )}
            >
              {active && <span className="absolute inset-y-2 left-0 hidden w-0.5 rounded-full bg-accent md:block" />}
              <item.icon className={cn("h-4 w-4", active && "text-accent")} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto hidden p-4 md:block">
        <LlmBadge meta={meta} />
      </div>
    </aside>
  );
}

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string }>();
  const connectionId = Number(params.id);

  return (
    <WorkspaceProvider connectionId={connectionId}>
      <div className="flex min-h-screen flex-col md:h-screen md:flex-row md:overflow-hidden">
        <Sidebar />
        <main className="flex min-w-0 flex-1 flex-col md:overflow-hidden">{children}</main>
      </div>
      <CommandPalette />
    </WorkspaceProvider>
  );
}
