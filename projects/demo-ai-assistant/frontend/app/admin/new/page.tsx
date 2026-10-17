"use client";

import { useRouter } from "next/navigation";
import PostForm from "@/components/PostForm";
import { createPost, type PostInput } from "@/lib/api";

export default function NewPostPage() {
  const router = useRouter();

  async function handleSubmit(data: PostInput) {
    const post = await createPost(data);
    router.push(`/posts/${post.slug}`);
  }

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">New Post</h1>
      <PostForm submitLabel="Create Post" onSubmit={handleSubmit} />
    </div>
  );
}
