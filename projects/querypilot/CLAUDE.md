# CLAUDE.md

Architecture and conventions for QueryPilot, for future Claude Code sessions. User-facing setup is in README.md.

## Layout

```
querypilot/
  docker-compose.yml        # app-db (pgvector pg16, :5434) + sample-db (Pagila on pg18 + hypopg, :5435)
  sample-db/                # Dockerfile + init SQL; 03-readonly-user.sql creates role qp_readonly
  backend/                  # FastAPI, Python 3.11, sync SQLAlchemy 2
    app/
      config.py             # Settings; .env resolved relative to backend/ (MCP clients have no cwd)
      models.py             # Connection, SchemaTable, SchemaRelation, Conversation, Message,
                            # QueryRun, SavedQuery, EvalRun, EvalResult
      schemas.py            # Pydantic I/O, CamelModel → camelCase JSON
      llm/                  # provider-neutral interface (base.py) + gemini.py + ollama_provider.py
      services/
        sql_guard.py        # sqlglot validation: single SELECT, no writes, LIMIT injection
        target.py           # ALL access to user databases: read-only cursor, introspection, EXPLAIN, hypopg
        indexing.py         # introspect → per-table summary text → embed → schema_tables/relations
        retrieval.py        # vector + full-text, RRF, FK expansion; few-shot examples from saved_queries
        agent.py            # tool-calling loop; yields AgentEvent (the chat SSE, evals and MCP all consume it)
        doctor.py           # EXPLAIN + structured LLM diagnosis + hypopg/rewrite cost measurement
        memory.py           # save verified question→SQL pairs (embedded as *query*)
        schema_text.py      # compact one-line-per-table schema for the LLM prompt (≈3x fewer tokens than summary_text)
        glossary.py         # semantic layer: business terms → definition + SQL, injected into the prompt
        profiling.py        # which columns get distinct values listed at index time (pure selection logic)
        consistency.py      # self-consistency: independent candidate SQLs, compared by result
        compare.py          # result equivalence, shared by evals and consistency
        drivers.py          # "why did X change": per-segment contribution to a period delta (pure)
        insights.py         # deterministic key facts from a result + LLM takeaways/follow-ups
        sandbox.py + sandbox_runner.py  # pandas analysis in a locked-down subprocess (agent tool run_python)
        cache.py            # in-memory answer cache, invalidated per connection with cache.bump()
      routers/              # thin HTTP layer; deps.py has get_connection / get_ready_connection
      evals/                # datasets/*.json (question, gold_sql, difficulty, category), runner.py,
                            # analysis.py (breakdown/compare/gate, pure), run.py (CLI + CI gate)
      tests/                # pytest (backend/): pure logic only; run `.venv/bin/python -m pytest`
      mcp_server.py         # MCPServer (mcp 2.x; FastMCP was renamed), stdio
      scripts/check_llm.py
  frontend/                 # Next.js 14 App Router, TS strict, Tailwind, dark-only design tokens
    app/page.tsx            # connections home
    app/c/[id]/             # workspace: layout.tsx (sidebar + ⌘K) and ask/schema/editor/doctor/memory/evals
    components/             # ui/ primitives, AgentTimeline, AssistantMessage, ResultView/Table/Chart,
                            # SchemaDiagram (reactflow+dagre), SqlEditor (Monaco), PlanTree, CommandPalette
    lib/api.ts              # every backend call + streamChat (manual SSE over POST)
```

## Invariants: don't break these

- **Every query against a target DB goes through `services/target.py`**, which runs `guard_select` and then
  executes on a raw DBAPI cursor inside `SET TRANSACTION READ ONLY` with `statement_timeout`, always
  rolled back. Never use SQLAlchemy `text()` on user SQL: `%` and `:name` would be treated as bind params.
- Target DB connection URLs are stored only Fernet-encrypted (`services/crypto.py`, `SECRET_KEY`).
  Changing `SECRET_KEY` makes existing connections undecryptable.
- `run_agent` is the single agent implementation. Chat (SSE), evals and MCP all iterate its events;
  add features there, not in a caller.
- Gemini turns are replayed from `LLMTurn.raw` (the original `Content`) so thought signatures survive
  multi-step tool calling. Don't rebuild model turns from text.
- Structured-output schemas sent to Gemini go through `_inline_refs` (no `$defs`/`$ref`).
- **Anything that changes what an answer should be must call `cache.bump(connection_id)`** (glossary, memory,
  re-index already do). Evals pass `use_cache=False`; a cached replay would measure the cache, not the agent.
- `run_python` code only ever runs through `services/sandbox.py` (subprocess, AST allowlist, rlimits, timeout).
  It is defence in depth, not a security boundary; never `exec` model-written code in the API process.
- Value profiling and `find_values` send column values to the LLM, so they honour `ALLOW_SAMPLE_ROWS` and skip
  columns whose names look personal (`profiling.SENSITIVE`). Keep it that way when adding profiled columns.
- Numbers shown as facts/drivers/confidence are computed in Python, never by the LLM (`drivers.py`,
  `insights.compute_facts`, `consistency.check`). The LLM only phrases them.
- MCP tools must raise `ToolError` (via `_expected_errors()`) for anything the model should see; mcp 2.x
  hides other exceptions behind a generic message. Never print to stdout in code the MCP server imports.

## Data flows

**Indexing** (connection create / reindex, FastAPI BackgroundTasks): `target.introspect` (pg_catalog
queries; skips partitions, includes views) → `build_summary` per table (this text is both what's embedded
and what the LLM sees) → Ollama `nomic-embed-text` with the `search_document:` prefix → `schema_tables`
(`embedding` 768-dim, `tsv` English tsvector) + `schema_relations`. Status: pending → indexing → ready|error.

**Ask** (`POST /api/connections/{id}/chat`, SSE): routes create the user and placeholder assistant
`Message`, then `_stream` (own DB session) runs `run_agent` and persists the payload at the end. Events:
`meta, status, retrieval, step, step_result, thought, result, analysis, drivers, confidence, answer, error, done`.
`answer` carries `timing`, `confidence`, `analyses`, `drivers`, `cached`; `chat.py` persists them in the message payload. Frame format
`event: <name>\ndata: <json>\n\n`. If you change it, update `streamChat` in `frontend/lib/api.ts`.

**Fast path** (`settings.fast_path`): for ordinary questions `_run_agent` makes ONE `generate_structured` call
(`FastAnswer`: sql, explanation, chart) with the compact `FAST_TEMPLATE` prompt, runs the SQL itself and finishes.
Only if that SQL errors or returns 0 rows does it fall into the tool loop, seeded with the failure. Questions that
match `_ANALYSIS_RE`/`_DRIVERS_RE` skip it. A malformed structured reply (`LLMOutputError`) also falls back to the loop.

**Token budget** (free-tier Gemini): the prompt shows `compact_table` lines (never `summary_text`), at most
`TOP_K=4`/`MAX_TABLES=7` retrieved tables, 2 few-shot examples, 60 other-table names, 2 history turns, 5 preview rows.
Gemini calls run with `thinking_level=MINIMAL` and capped `max_output_tokens`. `answer.timing` reports `tokensIn/Out`
(providers call `record_usage`; `_blocking` binds the counter into the worker thread's context). Verify is off by
default because it multiplies calls. Default model: `gemini-3.5-flash-lite` (2.5-* models 404 for new keys).

**Embeddings run on CPU** (`OLLAMA_EMBED_ON_CPU`): moving nomic-embed-text between GPU and CPU forces a 10-30 s reload,
and it competes with other GPU apps. Keep every embed call on the same setting.

**Agent tools** (`agent.py` `TOOLS`): `search_schema`, `get_table_details`, `find_values` (fuzzy distinct values),
`run_sql`, `analyze_drivers` (root cause), `run_python` (pandas sandbox), `final_answer`. Handlers that produce UI
artefacts push events onto `state.events`; the loop flushes them after each handler.

**Self-consistency** (`verify`): after the primary SQL runs, `consistency.check` writes N more candidates at
temperature 0.8 (no sight of the primary), runs them, and `confidence` = how many return the same values.
Default per `SELF_CONSISTENCY` (auto: gemini on, ollama off); the composer has a Verify toggle.

**Evals gate**: `python -m app.evals.run --connection-id 1 --baseline latest --max-drop 0.05 --no-regressions
--min-accuracy 0.7` exits 1 when a gate fails (2 if the run errored). `--model` evaluates another chat model.

**Memory**: 👍 → `/api/messages/{id}/feedback` → `save_query` (formatted SQL, question embedded with the
`search_query:` prefix). Retrieval uses verified examples with similarity ≥ 0.55.

## Conventions

- New endpoint: schema in `schemas.py` (CamelModel), thin route in `routers/`, logic in `services/`.
  Register new routers in `main.py`'s loop.
- Model change → `alembic revision --autogenerate`, then add `import pgvector.sqlalchemy` by hand if a
  Vector column is involved (see 0001). Autogenerate wants to drop `ix_schema_tables_tsv` (the GIN index is
  created by hand in 0001 and isn't in the model): delete that line from every new migration.
- Frontend pages under `c/[id]` are client components using `useWorkspace()` (connection, schema, meta).
  Wrap anything using `useSearchParams` in `<Suspense>`. Add backend calls to `lib/api.ts` only.
- Colors come from CSS variables in `globals.css` via Tailwind tokens (`bg`, `panel`, `elevated`, `border`,
  `fg`, `muted`, `accent`, `accent-2`, `ok`, `warn`, `danger`). Don't hard-code hex in components
  (chart series colors in `ResultChart.tsx` are the exception).
- Eval datasets: `backend/app/evals/datasets/<name>.json`, a list of `{question, gold_sql}`. Gold SQL
  should return only the columns needed to verify the answer (matching ignores names/order/extra columns),
  and avoid ties at LIMIT boundaries.
- Ports: 5434 app DB, 5435 sample DB, 8001 API, 3001 UI (the sibling demo-ai-assistant uses 5433/8000/3000).
