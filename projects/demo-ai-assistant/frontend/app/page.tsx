import Link from "next/link";
import { getPosts } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const posts = await getPosts();

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Posts</h1>
      {posts.length === 0 ? (
        <p className="text-gray-500">
          No posts yet.{" "}
          <Link href="/admin/new" className="text-blue-600 underline">
            Create the first one
          </Link>
          .
        </p>
      ) : (
        <ul className="space-y-6">
          {posts.map((post) => (
            <li key={post.id} className="border-b border-gray-100 pb-6">
              <Link href={`/posts/${post.slug}`} className="text-xl font-semibold hover:underline">
                {post.title}
              </Link>
              <p className="text-sm text-gray-500 mt-1">
                {new Date(post.created_at).toLocaleDateString()}
              </p>
              <p className="mt-2 text-gray-700">{post.excerpt}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
