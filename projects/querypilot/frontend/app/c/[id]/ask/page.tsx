"use client";

import { motion } from "framer-motion";
import { ArrowUp, MessageSquare, PanelLeft, Plus, Sparkles, Square, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { AssistantMessage, UserBubble } from "@/components/AssistantMessage";
import { Skeleton } from "@/components/ui/primitives";
import { useWorkspace } from "@/components/WorkspaceContext";
import type { AgentStep, AssistantPayload, ChatMessage, Conversation, Schema } from "@/lib/api";
import { api, streamChat } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";

type LiveTurn = {
  question: string;
  status: string;
  content: string;
  payload: AssistantPayload;
  messageId?: number;
};

const PAGILA_SUGGESTIONS = [
  "Which 10 customers have spent the most, and in which country do they live?",
  "Show monthly rental revenue as a trend",
  "Which film categories earn the most revenue per film?",
  "Which films are in inventory but have never been rented?",
];

function suggestionsFor(schema: Schema | null): string[] {
  if (!schema) return [];
  const names = new Set(schema.tables.map((t) => t.name));
  if (names.has("rental") && names.has("film")) return PAGILA_SUGGESTIONS;
  const biggest = [...schema.tables].sort((a, b) => (b.rowEstimate ?? 0) - (a.rowEstimate ?? 0)).slice(0, 3);
  return [
    ...biggest.map((t) => `Give me an overview of the ${t.name} table`),
    "Which tables have the most rows?",
  ];
}

function upsertStep(steps: AgentStep[], step: AgentStep): AgentStep[] {
  const i = steps.findIndex((s) => s.id === step.id);
  if (i === -1) return [...steps, step];
  const next = steps.slice();
  next[i] = { ...next[i], ...step };
  return next;
}

function AskInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { connectionId, schema, conversationsVersion, bumpConversations } = useWorkspace();

  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [input, setInput] = useState("");
  const [showList, setShowList] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const autoSent = useRef<string | null>(null);

  const suggestions = useMemo(() => suggestionsFor(schema), [schema]);

  useEffect(() => {
    api.conversations(connectionId).then(setConversations).catch(() => setConversations([]));
  }, [connectionId, conversationsVersion]);

  const openConversation = useCallback(async (id: number | null) => {
    abortRef.current?.abort();
    setLive(null);
    setConversationId(id);
    if (id === null) {
      setMessages([]);
      return;
    }
    setLoadingThread(true);
    try {
      const detail = await api.conversation(id);
      setMessages(detail.messages);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setLoadingThread(false);
    }
  }, []);

  // ?c=<id> opens a conversation (from the command palette)
  const cParam = searchParams.get("c");
  useEffect(() => {
    if (cParam) openConversation(Number(cParam));
  }, [cParam, openConversation]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, live?.payload.steps?.length, live?.payload.result, live?.content]);

  const send = useCallback(
    async (raw: string, forceNew = false) => {
      const question = raw.trim();
      if (!question || live) return;
      setInput("");
      const controller = new AbortController();
      abortRef.current = controller;
      const startId = forceNew ? null : conversationId;
      let convId = startId;
      setLive({ question, status: "Starting…", content: "", payload: { steps: [] } });

      const patch = (fn: (t: LiveTurn) => LiveTurn) => setLive((t) => (t ? fn(t) : t));

      await streamChat(
        connectionId,
        question,
        startId,
        {
          onMeta: (d) => {
            convId = d.conversationId;
            if (!startId) {
              setConversationId(d.conversationId);
              bumpConversations();
            }
            patch((t) => ({ ...t, messageId: d.messageId }));
          },
          onStatus: (d) => patch((t) => ({ ...t, status: d.text })),
          onRetrieval: (d) => patch((t) => ({ ...t, payload: { ...t.payload, retrieval: d } })),
          onStep: (d) =>
            patch((t) => ({
              ...t,
              status: d.tool === "run_sql" ? "Running SQL…" : d.tool === "final_answer" ? "Executing final query…" : "Inspecting schema…",
              payload: { ...t.payload, steps: upsertStep(t.payload.steps ?? [], d) },
            })),
          onStepResult: (d) => patch((t) => ({ ...t, payload: { ...t.payload, steps: upsertStep(t.payload.steps ?? [], d) } })),
          onResult: (d) => patch((t) => ({ ...t, payload: { ...t.payload, result: d } })),
          onAnswer: (d) =>
            patch((t) => ({
              ...t,
              content: d.explanation,
              payload: { ...t.payload, sql: d.sql, chart: d.chart, steps: d.steps, attempts: d.attempts },
            })),
          onError: (d) => patch((t) => ({ ...t, payload: { ...t.payload, error: d.message } })),
        },
        controller.signal
      );

      // Swap the live turn for the persisted messages (keeps ids for feedback).
      if (convId) {
        try {
          const detail = await api.conversation(convId);
          setMessages(detail.messages);
          setLive(null);
          return;
        } catch {
          // fall through: keep live view
        }
      }
      setLive((t) => (t ? { ...t, status: "" } : t));
    },
    [connectionId, conversationId, live, bumpConversations]
  );

  // ?q=<question> (from the command palette) starts a new chat with that question
  const qParam = searchParams.get("q");
  useEffect(() => {
    if (!qParam || autoSent.current === qParam || !schema) return;
    autoSent.current = qParam;
    setConversationId(null);
    setMessages([]);
    router.replace(`/c/${connectionId}/ask`);
    send(qParam, true);
  }, [qParam, schema, connectionId, router, send]);

  const stop = () => {
    abortRef.current?.abort();
    setLive((t) => (t ? { ...t, status: "", payload: { ...t.payload, error: t.payload.error ?? "Stopped." } } : t));
  };

  const removeConversation = async (id: number) => {
    try {
      await api.deleteConversation(id);
      if (id === conversationId) openConversation(null);
      bumpConversations();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  const empty = messages.length === 0 && !live && !loadingThread;

  return (
    <div className="flex min-h-0 flex-1">
      {/* Conversation list */}
      <div
        className={cn(
          "hidden w-64 shrink-0 flex-col border-r border-border/60 bg-panel/20 lg:flex",
          !showList && "lg:hidden"
        )}
      >
        <div className="flex items-center justify-between px-3 py-3">
          <span className="text-xs font-medium uppercase tracking-wider text-muted">Chats</span>
          <button
            onClick={() => openConversation(null)}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted transition hover:bg-elevated hover:text-fg"
          >
            <Plus className="h-3.5 w-3.5" /> New
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
          {!conversations && [0, 1, 2].map((i) => <Skeleton key={i} className="mx-1 h-9" />)}
          {conversations?.length === 0 && <p className="px-2 py-4 text-xs text-muted">No chats yet.</p>}
          {conversations?.map((c) => (
            <div
              key={c.id}
              className={cn(
                "group flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition",
                c.id === conversationId ? "bg-elevated text-fg" : "text-muted hover:bg-elevated/50 hover:text-fg"
              )}
              onClick={() => openConversation(c.id)}
            >
              <MessageSquare className="h-3.5 w-3.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px]">{c.title}</div>
                <div className="text-[10.5px] text-muted/70">{timeAgo(c.createdAt)}</div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  removeConversation(c.id);
                }}
                className="rounded p-1 text-muted opacity-0 transition hover:text-danger group-hover:opacity-100"
                title="Delete chat"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Thread */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2.5">
          <button
            onClick={() => setShowList((s) => !s)}
            className="hidden rounded-md p-1.5 text-muted transition hover:bg-elevated hover:text-fg lg:block"
            title="Toggle chat list"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <h1 className="truncate text-sm font-medium">
            {conversations?.find((c) => c.id === conversationId)?.title ?? "New chat"}
          </h1>
          <button
            onClick={() => openConversation(null)}
            className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted transition hover:bg-elevated hover:text-fg lg:hidden"
          >
            <Plus className="h-3.5 w-3.5" /> New
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 sm:px-6">
            {empty && (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="pt-[8vh] text-center">
                <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl border border-accent/30 bg-accent/10">
                  <Sparkles className="h-5 w-5 text-accent" />
                </div>
                <h2 className="text-2xl font-semibold tracking-tight">What do you want to know?</h2>
                <p className="mx-auto mt-2 max-w-md text-sm text-muted">
                  Ask in plain English. QueryPilot finds the right tables, writes and tests the SQL, fixes its own
                  mistakes and charts the answer.
                </p>
                <div className="mx-auto mt-8 grid max-w-2xl gap-2 sm:grid-cols-2">
                  {suggestions.map((s, i) => (
                    <motion.button
                      key={s}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.1 + i * 0.05 }}
                      onClick={() => send(s)}
                      className="glass rounded-xl px-4 py-3 text-left text-sm text-muted transition hover:border-accent/40 hover:text-fg"
                    >
                      {s}
                    </motion.button>
                  ))}
                </div>
              </motion.div>
            )}

            {loadingThread && (
              <div className="space-y-4">
                <Skeleton className="ml-auto h-10 w-1/2 rounded-2xl" />
                <Skeleton className="h-40 w-full rounded-xl" />
              </div>
            )}

            {messages.map((m) =>
              m.role === "user" ? (
                <UserBubble key={m.id} text={m.content} />
              ) : (
                <AssistantMessage
                  key={m.id}
                  connectionId={connectionId}
                  messageId={m.id}
                  content={m.content}
                  payload={m.payload ?? {}}
                />
              )
            )}

            {live && (
              <>
                <UserBubble text={live.question} />
                <AssistantMessage
                  connectionId={connectionId}
                  content={live.content}
                  payload={live.payload}
                  streaming={Boolean(live.status)}
                  status={live.status}
                />
              </>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-border/60 bg-bg/60 px-4 py-3 backdrop-blur-xl sm:px-6">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="mx-auto flex max-w-4xl items-end gap-2 rounded-2xl border border-border bg-panel/80 p-2 shadow-lg shadow-black/20 focus-within:border-accent/50 focus-within:ring-2 focus-within:ring-accent/15"
          >
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              placeholder={conversationId ? "Ask a follow-up…" : "Ask a question about your data…"}
              className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-muted/70"
            />
            {live?.status ? (
              <button
                type="button"
                onClick={stop}
                className="flex h-9 w-9 items-center justify-center rounded-xl bg-elevated text-fg transition hover:bg-border"
                title="Stop"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-b from-accent to-violet-600 text-white transition hover:brightness-110 disabled:opacity-40"
                title="Send"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
            )}
          </form>
          <p className="mx-auto mt-1.5 max-w-4xl px-1 text-[11px] text-muted/60">
            Read-only · queries run with a timeout · 👍 a correct answer to teach QueryPilot
          </p>
        </div>
      </div>
    </div>
  );
}

export default function AskPage() {
  return (
    <Suspense>
      <AskInner />
    </Suspense>
  );
}
