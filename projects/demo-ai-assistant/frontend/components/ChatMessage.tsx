import Link from "next/link";
import ReactMarkdown from "react-markdown";
import type { ChatSource } from "@/lib/api";

export type DisplayMessage = {
  role: "user" | "assistant";
  content: string;
  fromBlog?: boolean;
  sources?: ChatSource[];
  pending?: boolean;
};

export default function ChatMessage({ message }: { message: DisplayMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-lg px-4 py-3 ${
          isUser ? "bg-black text-white" : "bg-gray-100 text-gray-900"
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose-blog">
            <ReactMarkdown>{message.content || (message.pending ? "…" : "")}</ReactMarkdown>
          </div>
        )}

        {!isUser && !message.pending && message.fromBlog === false && (
          <p className="mt-2 text-xs italic text-gray-500 border-t border-gray-200 pt-2">
            This answer is not from the blog — general knowledge response.
          </p>
        )}

        {!isUser && message.fromBlog && message.sources && message.sources.length > 0 && (
          <div className="mt-2 text-xs text-gray-600 border-t border-gray-200 pt-2">
            <span className="font-medium">Sources: </span>
            {message.sources.map((source, idx) => (
              <span key={source.slug}>
                <Link href={`/posts/${source.slug}`} className="text-blue-600 underline">
                  {source.title}
                </Link>
                {idx < message.sources!.length - 1 ? ", " : ""}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
