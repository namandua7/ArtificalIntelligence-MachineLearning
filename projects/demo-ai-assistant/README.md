# Demo AI Assistant Blog

A personal blog with a RAG-powered AI assistant. Posts are chunked and embedded on
create/update so the assistant can answer questions grounded in blog content, and
falls back to a general-purpose answer (clearly labeled) when nothing relevant is found.

Monorepo layout:

```
demo-ai-assistant/
  backend/   FastAPI + SQLAlchemy + Alembic + Postgres/pgvector + Ollama (local LLM + embeddings)
  frontend/  Next.js 14 App Router + TypeScript + Tailwind
```

This is a **demo app with no authentication** — the `/admin` pages are open to anyone
who can reach the frontend. Do not deploy this publicly as-is.

## Prerequisites

- Docker + Docker Compose
- Python 3.11+
- Node.js 18.18+ (Next.js 14 requirement) and npm
- [Ollama](https://ollama.com) installed and running locally — no API key, no billing,
  everything runs on your machine

## 0. Start Ollama and pull the models

```bash
brew install ollama        # or download from https://ollama.com
brew services start ollama # or: ollama serve
ollama pull llama3.2           # chat model
ollama pull nomic-embed-text   # embedding model (768-dim)
```

Confirm it's up: `curl http://localhost:11434/api/version`.

## 1. Start Postgres (pgvector)

From the repo root:

```bash
docker compose up -d
```

This starts Postgres 16 with the `pgvector` extension available, on `localhost:5433`,
database `blogdb`, user/password `postgres`/`postgres` (matches `backend/.env.example`).
(Mapped to host port 5433 instead of the default 5432 to avoid colliding with any
Postgres already running locally on your machine.)

## 2. Backend setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
```

`backend/.env.example` already has working defaults — nothing is required to fill in:

- `OLLAMA_BASE_URL` — leave as `http://localhost:11434`
- `OLLAMA_CHAT_MODEL` — leave as `llama3.2`, or swap for any chat model you've pulled
- `OLLAMA_EMBED_MODEL` — leave as `nomic-embed-text` (the DB schema's vector column is
  sized for its 768-dim output; swapping embedding models requires a new migration if
  the dimension differs)
- `DATABASE_URL` — leave as default, it already matches `docker-compose.yml`
- `SIMILARITY_THRESHOLD` — leave as `0.5` to start; tune later (see "How RAG routing
  works" below)

Run migrations (creates the `vector` extension, `posts`, and `chunks` tables):

```bash
alembic upgrade head
```

Start the API:

```bash
uvicorn app.main:app --reload
```

The API is now at http://localhost:8000 (interactive docs at http://localhost:8000/docs).

## 3. Frontend setup

In a new terminal, from the repo root:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

`frontend/.env.local` only needs `NEXT_PUBLIC_API_URL=http://localhost:8000`, which is
already the default in `.env.example` — no key required here.

Open http://localhost:3000.

## 4. Try it out

1. Go to **Admin** (http://localhost:3000/admin) → **New Post**, write a post with some
   real content, and save. This indexes it automatically (chunk + embed + store).
2. View it on the public blog list/page.
3. Go to **Assistant** (http://localhost:3000/assistant) and ask a question about what
   you just wrote. You should get an answer with source links back to your post.
4. Ask something unrelated to your blog content — you should get a general answer
   clearly marked as **not** coming from the blog.
5. Edit or delete the post from Admin and confirm the assistant's answers change
   accordingly (old chunks are removed/replaced on every edit or delete).

## How indexing works

On post create/update, the backend:

1. Splits `content` into ~500-word chunks with 50-word overlap (`app/services/chunking.py`).
2. Embeds each chunk locally via Ollama's `nomic-embed-text` model (`app/services/embeddings.py`).
3. On update, deletes all existing chunks for that post first, then inserts fresh ones
   (`app/services/indexing.py`). On delete, chunks are removed via `ON DELETE CASCADE`.

## How RAG chat routing works

1. The user's question is embedded locally via Ollama's `nomic-embed-text` model.
2. The top 5 chunks by cosine similarity are retrieved from Postgres/pgvector.
3. If the **best** similarity score is `>= SIMILARITY_THRESHOLD`, the local chat model
   (`llama3.2` by default) is instructed to answer using **only** the retrieved chunks,
   and the response includes links to the source posts.
4. If it's below the threshold, the model answers as a general assistant with no blog
   context, and the UI clearly labels the answer as not from the blog.
5. The last ~6 messages of conversation history are included in each request for
   follow-up questions.
6. Responses are streamed to the browser over Server-Sent Events.

Raise `SIMILARITY_THRESHOLD` to make the assistant more conservative about treating an
answer as "from the blog"; lower it to make it more willing to use blog content.

## Stages (for reference)

This app was built to cover 5 stages: (1) project setup/docker/DB models/migrations,
(2) blog CRUD API + Next.js blog pages, (3) indexing pipeline on create/update/delete,
(4) RAG chat endpoint with threshold routing, (5) assistant chat page with streaming
and source links. All five are implemented.

## Troubleshooting

- **`alembic upgrade head` fails to connect** — make sure `docker compose up -d`
  finished and `docker compose ps` shows `db` as healthy.
- **Chat returns an error event / connection refused to 11434** — Ollama isn't running.
  Run `brew services start ollama` (or `ollama serve`) and confirm with
  `curl http://localhost:11434/api/version`.
- **`model not found` error** — pull it: `ollama pull llama3.2` or
  `ollama pull nomic-embed-text`.
- **CORS errors in the browser console** — confirm the backend is running on port 8000
  and `frontend/.env.local` points `NEXT_PUBLIC_API_URL` at it.
