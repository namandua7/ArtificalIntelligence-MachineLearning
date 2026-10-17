"use client";

import { useRef, useState } from "react";
import ChatMessage, { type DisplayMessage } from "@/components/ChatMessage";
import { streamChat, type ChatHistoryMessage, type ChatSource } from "@/lib/api";

const HISTORY_LIMIT = 6;

export default function AssistantPage() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  function scrollToBottom() {
    requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    });
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || sending) return;

    const history: ChatHistoryMessage[] = messages
      .filter((m) => !m.pending)
      .slice(-HISTORY_LIMIT)
      .map((m) => ({ role: m.role, content: m.content }));

    const userMessage: DisplayMessage = { role: "user", content: trimmed };
    const pendingAssistant: DisplayMessage = { role: "assistant", content: "", pending: true };

    setMessages((prev) => [...prev, userMessage, pendingAssistant]);
    setInput("");
    setSending(true);
    scrollToBottom();

    let fullText = "";

    await streamChat(trimmed, history, {
      onToken: (text) => {
        fullText += text;
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { ...next[next.length - 1], content: fullText, pending: true };
          return next;
        });
        scrollToBottom();
      },
      onSources: (payload: { fromBlog: boolean; sources: ChatSource[] }) => {
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = {
            ...next[next.length - 1],
            fromBlog: payload.fromBlog,
            sources: payload.sources,
          };
          return next;
        });
      },
      onDone: () => {
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { ...next[next.length - 1], pending: false };
          return next;
        });
        setSending(false);
        scrollToBottom();
      },
      onError: (message) => {
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = {
            ...next[next.length - 1],
            content: fullText || `Error: ${message}`,
            pending: false,
          };
          return next;
        });
        setSending(false);
      },
    });
  }

  return (
    <div className="flex flex-col h-[calc(100vh-10rem)]">
      <h1 className="text-3xl font-bold mb-4">Assistant</h1>
      <p className="text-sm text-gray-500 mb-4">
        Ask questions about the blog. If nothing relevant is found, you&apos;ll get a general
        answer clearly marked as not coming from the blog.
      </p>

      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {messages.length === 0 && (
          <p className="text-gray-400 text-sm">No messages yet. Ask something below.</p>
        )}
        {messages.map((message, idx) => (
          <ChatMessage key={idx} message={message} />
        ))}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSend} className="mt-4 flex gap-2">
        <input
          className="flex-1 border border-gray-300 rounded px-3 py-2"
          placeholder="Ask about the blog…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="bg-black text-white px-4 py-2 rounded disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}
