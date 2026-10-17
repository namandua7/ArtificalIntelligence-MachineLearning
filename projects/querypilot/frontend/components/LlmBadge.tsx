"use client";

import { AlertTriangle, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import type { Meta } from "@/lib/api";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export function useMeta() {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);
  return meta;
}

export function LlmBadge({ meta, className }: { meta: Meta | null; className?: string }) {
  if (!meta) return null;
  const { provider, model, configured } = meta.llm;
  return (
    <div
      title={configured ? `LLM: ${provider} / ${model}` : "Set GEMINI_API_KEY in backend/.env and restart the API"}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
        configured ? "border-border bg-elevated/70 text-muted" : "border-warn/40 bg-warn/10 text-warn",
        className
      )}
    >
      {configured ? <Sparkles className="h-3 w-3 text-accent" /> : <AlertTriangle className="h-3 w-3" />}
      <span className="font-mono">{configured ? model : "Gemini key missing"}</span>
    </div>
  );
}
