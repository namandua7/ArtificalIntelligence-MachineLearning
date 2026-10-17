"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { deletePost, getPosts, type PostListItem } from "@/lib/api";

export default function AdminPage() {
  const [posts, setPosts] = useState<PostListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      setPosts(await getPosts());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load posts");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleDelete(slug: string) {
    if (!confirm(`Delete post "${slug}"? This cannot be undone.`)) return;
    try {
      await deletePost(slug);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete post");
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Admin</h1>
        <Link href="/admin/new" className="bg-black text-white px-4 py-2 rounded text-sm">
          New Post
        </Link>
      </div>

      {error && <p className="text-sm text-red-600 mb-4">{error}</p>}
      {loading ? (
        <p className="text-gray-500">Loading…</p>
      ) : posts.length === 0 ? (
        <p className="text-gray-500">No posts yet.</p>
      ) : (
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-gray-200 text-sm text-gray-500">
              <th className="py-2">Title</th>
              <th className="py-2">Slug</th>
              <th className="py-2">Created</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {posts.map((post) => (
              <tr key={post.id} className="border-b border-gray-100">
                <td className="py-2">{post.title}</td>
                <td className="py-2 font-mono text-sm text-gray-600">{post.slug}</td>
                <td className="py-2 text-sm text-gray-500">
                  {new Date(post.created_at).toLocaleDateString()}
                </td>
                <td className="py-2 text-right space-x-3">
                  <Link href={`/admin/edit/${post.slug}`} className="text-blue-600 underline text-sm">
                    Edit
                  </Link>
                  <button
                    onClick={() => handleDelete(post.slug)}
                    className="text-red-600 underline text-sm"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
