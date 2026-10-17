"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import PostForm from "@/components/PostForm";
import { getPost, updatePost, type Post, type PostInput } from "@/lib/api";

export default function EditPostPage({ params }: { params: { slug: string } }) {
  const router = useRouter();
  const [post, setPost] = useState<Post | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPost(params.slug)
      .then(setPost)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load post"));
  }, [params.slug]);

  async function handleSubmit(data: PostInput) {
    const updated = await updatePost(params.slug, data);
    router.push(`/posts/${updated.slug}`);
  }

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!post) return <p className="text-gray-500">Loading…</p>;

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Edit Post</h1>
      <PostForm
        initial={{ title: post.title, slug: post.slug, content: post.content }}
        submitLabel="Save Changes"
        onSubmit={handleSubmit}
      />
    </div>
  );
}
