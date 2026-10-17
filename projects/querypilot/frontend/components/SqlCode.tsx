"use client";

import { Check, Copy, SquareTerminal } from "lucide-react";
import Link from "next/link";
import { Fragment, useMemo, useState } from "react";

import { cn } from "@/lib/utils";

const KEYWORDS = new Set(
  (
    "select from where join left right inner outer full cross on and or not in is null as group by order having limit offset " +
    "with union all distinct case when then else end asc desc between like ilike exists interval over partition " +
    "count sum avg min max round coalesce cast date_trunc extract filter true false lateral using any nulls first last"
  ).split(" ")
);

const TOKEN = /('(?:[^']|'')*')|(--[^\n]*)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+)|(.)/g;

function highlight(sql: string) {
  const out: { text: string; cls: string }[] = [];
  for (const m of sql.matchAll(TOKEN)) {
    const [text, str, comment, num, word] = m;
    let cls = "";
    if (str) cls = "text-emerald-300";
    else if (comment) cls = "text-muted italic";
    else if (num) cls = "text-amber-300";
    else if (word && KEYWORDS.has(word.toLowerCase())) cls = "text-violet-300 font-medium";
    out.push({ text, cls });
  }
  return out;
}

export function SqlCode({
  sql,
  connectionId,
  className,
  maxHeight = "max-h-72",
}: {
  sql: string;
  connectionId?: number;
  className?: string;
  maxHeight?: string;
}) {
  const [copied, setCopied] = useState(false);
  const tokens = useMemo(() => highlight(sql), [sql]);

  const copy = async () => {
    await navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div className={cn("group relative overflow-hidden rounded-lg border border-border bg-bg/70", className)}>
      <div className="absolute right-2 top-2 z-10 flex gap-1 opacity-0 transition group-hover:opacity-100">
        {connectionId !== undefined && (
          <Link
            href={`/c/${connectionId}/editor?sql=${encodeURIComponent(sql)}`}
            title="Open in SQL editor"
            className="rounded-md border border-border bg-panel p-1.5 text-muted hover:text-fg"
          >
            <SquareTerminal className="h-3.5 w-3.5" />
          </Link>
        )}
        <button onClick={copy} title="Copy" className="rounded-md border border-border bg-panel p-1.5 text-muted hover:text-fg">
          {copied ? <Check className="h-3.5 w-3.5 text-ok" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
      <pre className={cn("overflow-auto p-3 font-mono text-[12.5px] leading-relaxed", maxHeight)}>
        <code>
          {tokens.map((t, i) => (
            <Fragment key={i}>{t.cls ? <span className={t.cls}>{t.text}</span> : t.text}</Fragment>
          ))}
        </code>
      </pre>
    </div>
  );
}
