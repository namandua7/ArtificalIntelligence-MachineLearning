"use client";

import { AlertCircle, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AgentTimeline } from "@/components/AgentTimeline";
import { Logo } from "@/components/Logo";
import { Markdown } from "@/components/Markdown";
import { ResultView } from "@/components/ResultView";
import { SqlCode } from "@/components/SqlCode";
import type { AssistantPayload } from "@/lib/api";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-md bg-gradient-to-br from-accent/90 to-violet-700/90 px-4 py-2.5 text-sm text-white shadow-lg shadow-accent/10">
        {text}
      </div>
    </div>
  );
}

export function AssistantMessage({
  connectionId,
  messageId,
  content,
  payload,
  streaming = false,
  status,
}: {
  connectionId: number;
  messageId?: number;
  content: string;
  payload: AssistantPayload;
  streaming?: boolean;
  status?: string;
}) {
  const [feedback, setFeedback] = useState(payload.feedback);
  const [sending, setSending] = useState(false);
  const steps = payload.steps ?? [];

  const sendFeedback = async (verified: boolean) => {
    if (!messageId) return;
    setSending(true);
    try {
      await api.feedback(messageId, verified);
      setFeedback(verified ? "up" : "down");
      toast.success(verified ? "Saved to memory" : "Feedback noted", {
        description: verified
          ? "This question → SQL pair will be used as an example for similar questions."
          : "Removed from memory if it was saved.",
      });
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 hidden sm:block">
        <Logo withText={false} className="scale-90" />
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        {(streaming || steps.length > 0 || payload.retrieval) && (
          <AgentTimeline
            retrieval={payload.retrieval}
            steps={steps}
            status={status}
            streaming={streaming}
            defaultOpen={false}
          />
        )}

        {payload.error && (
          <div className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger/5 p-3 text-sm text-danger">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{payload.error}</span>
          </div>
        )}

        {content && <Markdown>{content}</Markdown>}

        {payload.sql && <SqlCode sql={payload.sql} connectionId={connectionId} />}

        {payload.result && (
          <ResultView result={payload.result} chart={payload.chart} tableClassName="max-h-80" />
        )}

        {!streaming && messageId && payload.sql && (
          <div className="flex items-center gap-1 pt-1">
            <span className="mr-1 text-xs text-muted">Correct answer?</span>
            <button
              disabled={sending}
              onClick={() => sendFeedback(true)}
              title="Correct: save to memory"
              className={cn(
                "rounded-md p-1.5 text-muted transition hover:bg-elevated hover:text-ok",
                feedback === "up" && "bg-ok/10 text-ok"
              )}
            >
              <ThumbsUp className="h-3.5 w-3.5" />
            </button>
            <button
              disabled={sending}
              onClick={() => sendFeedback(false)}
              title="Wrong"
              className={cn(
                "rounded-md p-1.5 text-muted transition hover:bg-elevated hover:text-danger",
                feedback === "down" && "bg-danger/10 text-danger"
              )}
            >
              <ThumbsDown className="h-3.5 w-3.5" />
            </button>
            {feedback === "up" && <span className="ml-1 text-xs text-ok">Saved to memory</span>}
          </div>
        )}
      </div>
    </div>
  );
}
