"use client";

import { useState } from "react";
import { slugify, type PostInput } from "@/lib/api";

type PostFormProps = {
  initial?: PostInput;
  submitLabel: string;
  onSubmit: (data: PostInput) => Promise<void>;
};

export default function PostForm({ initial, submitLabel, onSubmit }: PostFormProps) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [slugTouched, setSlugTouched] = useState(Boolean(initial?.slug));
  const [content, setContent] = useState(initial?.content ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleTitleChange(value: string) {
    setTitle(value);
    if (!slugTouched) {
      setSlug(slugify(value));
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({ title, slug, content });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-2">
          {error}
        </p>
      )}
      <div>
        <label className="block text-sm font-medium mb-1" htmlFor="title">
          Title
        </label>
        <input
          id="title"
          className="w-full border border-gray-300 rounded px-3 py-2"
          value={title}
          onChange={(e) => handleTitleChange(e.target.value)}
          required
        />
      </div>
      <div>
        <label className="block text-sm font-medium mb-1" htmlFor="slug">
          Slug
        </label>
        <input
          id="slug"
          className="w-full border border-gray-300 rounded px-3 py-2 font-mono text-sm"
          value={slug}
          onChange={(e) => {
            setSlugTouched(true);
            setSlug(e.target.value);
          }}
          required
        />
      </div>
      <div>
        <label className="block text-sm font-medium mb-1" htmlFor="content">
          Content (Markdown)
        </label>
        <textarea
          id="content"
          className="w-full border border-gray-300 rounded px-3 py-2 font-mono text-sm"
          rows={16}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          required
        />
      </div>
      <button
        type="submit"
        disabled={submitting}
        className="bg-black text-white px-4 py-2 rounded disabled:opacity-50"
      >
        {submitting ? "Saving…" : submitLabel}
      </button>
    </form>
  );
}
