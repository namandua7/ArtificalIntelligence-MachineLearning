# CLAUDE.md

Architecture and conventions for this repo, for future Claude Code sessions.

## Monorepo layout

```
demo-ai-assistant/
  docker-compose.yml       # Postgres 16 + pgvector, local dev only
  backend/                 # FastAPI, Python 3.11+
    app/
      main.py              # FastAPI app, CORS, router registration, /health
      config.py            # pydantic-settings Settings, reads backend/.env
      database.py          # SQLAlchemy engine/session/Base, sync (not async)
      models.py            # Post, Chunk ORM models
      schemas.py           # Pydantic request/response models
      routers/
        posts.py           # /api/posts CRUD
        chat.py             # /api/chat SSE endpoint
      services/
        chunking.py         # word-count chunker (~500 words, 50 overlap)
        embeddings.py        # local Ollama embeddings client wrapper
        indexing.py           # (re)index a post's chunks on create/update
        rag.py                # retrieval + threshold routing + local Ollama chat streaming
    alembic/                  # migrations; 0001_initial creates the vector extension +
                               # posts/chunks tables; 0002_ollama_embedding_dim switches
                               # the embedding column from 512 (Voyage) to 768 (Ollama
                               # nomic-embed-text) dims, truncating old chunk rows
  frontend/                 # Next.js 14 App Router, TypeScript strict, Tailwind
    app/
      page.tsx                        # server component: blog list
      posts/[slug]/page.tsx           # server component: single post (react-markdown)
      admin/page.tsx                  # client: list posts, delete, link to edit
      admin/new/page.tsx              # client: create form
      admin/edit/[slug]/page.tsx      # client: edit form
      assistant/page.tsx              # client: chat UI, SSE streaming
    lib/api.ts                        # typed API client, incl. manual SSE parsing
    components/PostForm.tsx           # shared create/edit form
    components/ChatMessage.tsx        # renders one chat bubble incl. source links
```

## Data flow: indexing

`POST /api/posts` and `PUT /api/posts/{slug}` both call
`app.services.indexing.reindex_post(db, post)` after committing the post row:

1. Delete all `Chunk` rows for `post.id`.
2. `chunk_text(post.content)` → list of ~500-word chunks with 50-word overlap
   (`app/services/chunking.py`).
3. `embed_texts(chunks, input_type="document")` via the local Ollama embedding model
   (`input_type` is accepted for call-site symmetry but unused — Ollama embedding
   models don't distinguish query vs. document inputs).
4. Insert one `Chunk` row per chunk with its embedding, then commit.

`DELETE /api/posts/{slug}` deletes the `Post` row; `chunks.post_id` has
`ON DELETE CASCADE`, so chunks are removed automatically (also mirrored by the
SQLAlchemy relationship's `cascade="all, delete-orphan"`).

**If you add a new way to mutate post content, you must call `reindex_post` after
committing, or chunks will go stale.**

## Data flow: RAG chat

`POST /api/chat` (`app/routers/chat.py`) trims `history` to the last 6 messages and
calls `app.services.rag.stream_chat_response(db, message, history)`, a generator that
yields raw SSE frame strings. The route wraps it in `StreamingResponse(..., media_type="text/event-stream")`.

Inside `stream_chat_response`:

1. Embed `message` locally via Ollama (`embed_query`).
2. Retrieve top 5 chunks via pgvector cosine distance:
   `Chunk.embedding.cosine_distance(query_embedding)`, ordered ascending, joined to `Post`
   for title/slug.
3. `best_similarity = 1 - distance_of_top_chunk` (0 if no chunks exist yet).
4. If `best_similarity >= settings.similarity_threshold`: build a system prompt that
   restricts the model to the retrieved chunk content only, collect distinct
   `{title, slug}` sources.
5. Else: generic "helpful assistant" system prompt, no context, empty sources.
6. Call `ollama.Client(host=settings.ollama_base_url).chat(model=settings.ollama_chat_model,
   messages=[...], stream=True)` (system prompt is the first message, role `"system"`),
   yield an `event: token` SSE frame per `chunk.message.content` delta.
7. After the stream completes, yield one `event: sources` frame
   (`{"fromBlog": bool, "sources": [{"title","slug"}, ...]}`), then `event: done`.
8. Any exception is caught and turned into `event: error`.

SSE frame format: `event: <name>\ndata: <json>\n\n`. Events: `token` (data is a raw
JSON string), `sources`, `done` (`{}`), `error` (`{"message": str}`).

The frontend (`frontend/lib/api.ts`, `streamChat`) does **not** use `EventSource`
(it can't POST) — it manually reads `response.body.getReader()`, buffers on `\n\n`,
and parses `event:`/`data:` lines itself. If you change the SSE frame format on the
backend, update the parser in `streamChat` to match.

## Conventions

- **New backend endpoint**: add a Pydantic schema in `app/schemas.py`, a route in the
  relevant `app/routers/*.py` (or a new router registered in `app/main.py`), and a
  service function in `app/services/` if it does non-trivial work. Keep routers thin.
- **New frontend page**: Server Components by default (blog pages fetch directly from
  the backend with `cache: "no-store"` / `export const dynamic = "force-dynamic"`).
  Only mark a file `"use client"` when it needs state/interactivity (forms, chat,
  admin list with delete). Add any new typed backend call to `frontend/lib/api.ts`
  rather than calling `fetch` ad hoc in a component.
- **Env vars** — backend (`backend/.env`, see `backend/.env.example`):
  `OLLAMA_BASE_URL`, `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL`,
  `DATABASE_URL`, `SIMILARITY_THRESHOLD`, `FRONTEND_ORIGIN`. No API keys needed — Ollama
  runs locally with no auth. Frontend (`frontend/.env.local`, see
  `frontend/.env.example`): `NEXT_PUBLIC_API_URL`.
- **Migrations**: managed with Alembic, `backend/alembic/versions/`. `env.py` reads
  `DATABASE_URL` from `app.config.settings` (not from `alembic.ini`) and imports
  `app.models` so `Base.metadata` is populated for autogenerate. Run
  `alembic revision --autogenerate -m "..."` after changing `app/models.py`, then
  review the generated file before `alembic upgrade head` — pgvector columns
  (`pgvector.sqlalchemy.Vector`) sometimes need the import added manually to the
  generated migration.
- **Embedding dimension is pinned at 768** (`EMBEDDING_DIM` in `app/models.py`,
  matching `nomic-embed-text`). If you change `OLLAMA_EMBED_MODEL` to one with a
  different output dimension, you must write a new migration to alter the
  `chunks.embedding` column type (see `0002_ollama_embedding_dim.py` for the pattern —
  it truncates `chunks` since old embeddings can't be cast across dimensions), and
  re-index every existing post afterward (re-save each post from `/admin`, or write a
  one-off re-index script).
- **Ollama must be running** (`ollama serve`, or `brew services start ollama`) with both
  `OLLAMA_CHAT_MODEL` and `OLLAMA_EMBED_MODEL` pulled (`ollama pull llama3.2`,
  `ollama pull nomic-embed-text`), or indexing and chat will fail with connection errors.
- **Chunking** is word-count based (not a real tokenizer) — see
  `app/services/chunking.py`, `CHUNK_SIZE_WORDS = 500`, `CHUNK_OVERLAP_WORDS = 50`.
  Good enough for a demo; swap in `tiktoken` or similar if token-accurate chunking
  matters later.
- **No authentication** anywhere, including `/admin` and the mutating `/api/posts`
  endpoints. This is intentional for a local demo. Do not add real user accounts to
  this codebase without reconsidering the whole auth story first.
