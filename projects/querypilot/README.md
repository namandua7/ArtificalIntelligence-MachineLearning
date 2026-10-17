# QueryPilot

An AI copilot for PostgreSQL. Ask a question in plain English, and an LLM agent finds the right tables
(schema RAG), writes SQL, **runs it, reads the errors and fixes itself**, then charts the answer. It also
diagnoses slow queries, learns from 👍 feedback, measures its own accuracy, and exposes everything as an
**MCP server** for Claude Code, Cursor or any MCP client.

| Topic | Where it lives |
| --- | --- |
| **LLM function calling** | `backend/app/services/agent.py`: tool loop (`search_schema`, `get_table_details`, `run_sql`, `final_answer`) with forced tool calls on Gemini |
| **Structured outputs** | `final_answer` → `{sql, explanation, chart}`; Performance Doctor → `Diagnosis` Pydantic schema; "Fix with AI" → `FixResult` |
| **AI agents** | self-correcting loop: failed SQL is fed back to the model, every attempt is logged in `query_runs` and streamed to the UI |
| **RAG & vector DB** | `backend/app/services/retrieval.py`: pgvector + Postgres full-text, fused with Reciprocal Rank Fusion, then foreign-key graph expansion; verified examples retrieved as few-shot memory |
| **MCP** | `backend/app/mcp_server.py`: `list_connections`, `get_schema`, `ask_database`, `run_readonly_sql`, `analyze_query_performance` |
| **AI automation** | Evals (`backend/app/evals/`): execution-accuracy suite, run from UI or CLI, tracked over time |

## Architecture

```
Next.js 14 (3001) ──REST + SSE──▶ FastAPI (8001) ──▶ app DB: Postgres + pgvector (5434)
                                     │                 connections · schema embeddings · chats · memory · evals
                                     ├──▶ Gemini API (free tier) or Ollama: chat / tool calls / JSON
                                     ├──▶ Ollama nomic-embed-text: embeddings (always local)
                                     └──▶ target DB (read-only): your database, or Pagila sample (5435)
```

Safety layers, outermost first:
1. **SQL guard** (`sql_guard.py`, sqlglot): one statement, SELECT/WITH only, blocks writes and
   `SELECT INTO`/`FOR UPDATE`/dangerous functions, and adds a LIMIT.
2. **Read-only transaction** + `statement_timeout`, always rolled back.
3. **Read-only DB role** (the sample DB connects as `qp_readonly`; do the same for your databases).

Connection URLs are Fernet-encrypted at rest. The LLM sees the schema and at most 3 sample rows per table
it inspects (`ALLOW_SAMPLE_ROWS=false` turns that off). It never receives full result sets.

## Setup

Prerequisites: Docker, Python 3.11, Node 18+, [Ollama](https://ollama.com) with `nomic-embed-text`.

```bash
# 1. Databases (app DB + Pagila sample DB with hypopg); first start loads ~13 MB of sample data
docker compose up -d --build

# 2. Ollama embeddings (and llama3.2 if you want the fully-local LLM mode)
ollama pull nomic-embed-text

# 3. Backend
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set GEMINI_API_KEY and SECRET_KEY (command in the file)
alembic upgrade head
python -m app.scripts.check_llm   # verifies your Gemini key + function calling
uvicorn app.main:app --reload --port 8001

# 4. Frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev            # http://localhost:3001
```

On the home page, click **Connect a database → Use the sample database**.

## Using it

- **Ask**: chat with your data. Expand **Agent trace** to see retrieved tables, every tool call and
  self-corrections. Switch between table and chart views and export CSV. Click 👍 on a correct answer to
  save it to memory.
- **Schema**: interactive ER diagram (React Flow + dagre). Click a table for columns, relationships and sample rows.
- **SQL Editor**: Monaco with schema-aware autocomplete, ⌘↵ to run, **Fix with AI** on errors.
- **Doctor**: EXPLAIN (ANALYZE) → plan tree with hot spots → AI diagnosis → index suggestions measured with
  **hypothetical indexes** (hypopg; nothing is created).
- **Memory**: manage the verified question → SQL examples the agent retrieves.
- **Evals**: run the 22-question Pagila suite; compare models and memory on/off.
- **⌘K**: command palette for asking, navigating, recent chats, saved queries and tables.

### Evals from the CLI

```bash
cd backend
python -m app.evals.run --connection-id 1            # memory on
python -m app.evals.run --connection-id 1 --no-memory
```

Questions are paced (`--pace`, default 4 s) to stay under free-tier rate limits. A run takes roughly
22 × 4 Gemini requests.

### MCP server (Claude Code example)

```bash
claude mcp add querypilot -- \
  /ABSOLUTE/PATH/querypilot/backend/.venv/bin/python /ABSOLUTE/PATH/querypilot/backend/app/mcp_server.py
```

Then ask Claude Code something like *"Using querypilot, which film categories bring in the most revenue?"*

## Free-tier notes

- Gemini free-tier limits are per minute and per day. The provider retries 429s with backoff, and the UI
  shows "rate limited, retrying in Ns". If you hit the daily cap, set `GEMINI_MODEL` to another model
  your key can use (`python -m app.scripts.check_llm` lists them), or switch to `LLM_PROVIDER=ollama`.
- Embeddings never touch an API: they run locally on Ollama, so indexing a big schema is free.
