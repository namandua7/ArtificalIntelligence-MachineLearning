const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type PostListItem = {
  id: number;
  title: string;
  slug: string;
  created_at: string;
  excerpt: string;
};

export type Post = {
  id: number;
  title: string;
  slug: string;
  content: string;
  created_at: string;
  updated_at: string;
};

export type PostInput = {
  title: string;
  slug: string;
  content: string;
};

export type ChatRole = "user" | "assistant";

export type ChatHistoryMessage = {
  role: ChatRole;
  content: string;
};

export type ChatSource = {
  title: string;
  slug: string;
};

export type ChatCallbacks = {
  onToken: (text: string) => void;
  onSources: (payload: { fromBlog: boolean; sources: ChatSource[] }) => void;
  onDone: () => void;
  onError: (message: string) => void;
};

async function handleJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Request failed (${res.status}): ${body || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function getPosts(): Promise<PostListItem[]> {
  const res = await fetch(`${API_URL}/api/posts`, { cache: "no-store" });
  return handleJson<PostListItem[]>(res);
}

export async function getPost(slug: string): Promise<Post> {
  const res = await fetch(`${API_URL}/api/posts/${encodeURIComponent(slug)}`, {
    cache: "no-store",
  });
  return handleJson<Post>(res);
}

export async function createPost(data: PostInput): Promise<Post> {
  const res = await fetch(`${API_URL}/api/posts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handleJson<Post>(res);
}

export async function updatePost(slug: string, data: PostInput): Promise<Post> {
  const res = await fetch(`${API_URL}/api/posts/${encodeURIComponent(slug)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handleJson<Post>(res);
}

export async function deletePost(slug: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/posts/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Request failed (${res.status}): ${body || res.statusText}`);
  }
}

export async function streamChat(
  message: string,
  history: ChatHistoryMessage[],
  callbacks: ChatCallbacks
): Promise<void> {
  const { onToken, onSources, onDone, onError } = callbacks;

  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    });
  } catch (err) {
    onError(err instanceof Error ? err.message : "Network error");
    return;
  }

  if (!res.ok || !res.body) {
    const body = await res.text().catch(() => "");
    onError(`Request failed (${res.status}): ${body || res.statusText}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const processFrame = (frame: string) => {
    const lines = frame.split("\n");
    let event = "message";
    let data = "";
    for (const line of lines) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        data += line.slice(5).trim();
      }
    }
    if (!data) return;

    try {
      const parsed = JSON.parse(data);
      if (event === "token") {
        onToken(parsed as string);
      } else if (event === "sources") {
        onSources(parsed as { fromBlog: boolean; sources: ChatSource[] });
      } else if (event === "done") {
        onDone();
      } else if (event === "error") {
        onError((parsed as { message: string }).message);
      }
    } catch {
      // ignore malformed frame
    }
  };

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let separatorIndex = buffer.indexOf("\n\n");
    while (separatorIndex !== -1) {
      const frame = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      processFrame(frame);
      separatorIndex = buffer.indexOf("\n\n");
    }
  }
}

export function slugify(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
}
