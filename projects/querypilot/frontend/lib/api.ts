export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

// --- Types -----------------------------------------------------------------------------------

export type Meta = {
  llm: { provider: string; model: string; configured: boolean };
  sampleConnectionUrl: string;
  allowSampleRows: boolean;
  statementTimeoutMs: number;
  maxResultRows: number;
};

export type IndexStatus = "pending" | "indexing" | "ready" | "error";

export type Connection = {
  id: number;
  name: string;
  dialect: string;
  displayUrl: string;
  indexStatus: IndexStatus;
  indexError: string | null;
  tableCount: number;
  lastIndexedAt: string | null;
  createdAt: string;
};

export type Column = {
  name: string;
  type: string;
  nullable: boolean;
  pk: boolean;
  fk: string | null;
  comment: string | null;
};

export type Table = {
  name: string;
  kind: "table" | "view";
  comment: string | null;
  rowEstimate: number | null;
  columns: Column[];
};

export type Relation = { fromTable: string; fromColumn: string; toTable: string; toColumn: string };

export type Schema = { tables: Table[]; relations: Relation[] };

export type QueryResult = {
  sql: string;
  columns: string[];
  rows: unknown[][];
  rowCount: number;
  truncated: boolean;
  durationMs: number;
  limitAdded: boolean;
};

export type ChartSpec = { type: "bar" | "line" | "area" | "pie" | "none"; x?: string; y?: string[] };

export type AgentStep = {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  ok?: boolean;
  summary?: string;
  error?: string;
  durationMs?: number;
};

export type Retrieval = {
  tables: { name: string; score: number; reason: "match" | "join" }[];
  examples: { question: string; similarity: number }[];
};

export type AssistantPayload = {
  pending?: boolean;
  sql?: string;
  chart?: ChartSpec;
  steps?: AgentStep[];
  attempts?: number;
  retrieval?: Retrieval;
  result?: QueryResult;
  error?: string;
  feedback?: "up" | "down";
  savedQueryId?: number | null;
};

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  payload: AssistantPayload | null;
  createdAt: string;
};

export type Conversation = { id: number; title: string; createdAt: string };
export type ConversationDetail = Conversation & { messages: ChatMessage[] };

export type SavedQuery = { id: number; question: string; sql: string; verified: boolean; createdAt: string };

export type Suggestion = {
  kind: "index" | "rewrite" | "other";
  title: string;
  detail: string;
  sql: string;
  hypothetical?: { costBefore: number; costAfter: number; improvementPct: number; indexUsed: boolean };
  hypotheticalError?: string;
  rewriteCost?: { costBefore: number; costAfter: number; improvementPct: number };
  rewriteError?: string;
};

export type PlanNode = {
  "Node Type": string;
  "Relation Name"?: string;
  Alias?: string;
  "Index Name"?: string;
  "Join Type"?: string;
  "Total Cost": number;
  "Startup Cost": number;
  "Plan Rows": number;
  "Actual Rows"?: number;
  "Actual Total Time"?: number;
  "Actual Loops"?: number;
  Filter?: string;
  "Index Cond"?: string;
  "Hash Cond"?: string;
  "Rows Removed by Filter"?: number;
  Plans?: PlanNode[];
};

export type Diagnosis = {
  plan: { Plan: PlanNode; "Execution Time"?: number; "Planning Time"?: number };
  stats: { totalCost: number; planRows: number; executionMs: number | null; planningMs: number | null };
  summary: string;
  bottlenecks: string[];
  suggestions: Suggestion[];
  hypopg: boolean;
};

export type EvalRun = {
  id: number;
  dataset: string;
  status: "running" | "done" | "error";
  useMemory: boolean;
  model: string;
  total: number;
  completed: number;
  passed: number;
  accuracy: number | null;
  error: string | null;
  createdAt: string;
};

export type EvalResult = {
  id: number;
  question: string;
  goldSql: string;
  predictedSql: string | null;
  passed: boolean;
  steps: number;
  durationMs: number;
  error: string | null;
};

export type EvalRunDetail = EvalRun & { results: EvalResult[] };

// --- HTTP helpers ----------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `Can't reach the QueryPilot API at ${API_URL}. Is the backend running?`);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : res.statusText;
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

// --- Endpoints -------------------------------------------------------------------------------

export const api = {
  meta: () => request<Meta>("/api/meta"),

  listConnections: () => request<Connection[]>("/api/connections"),
  getConnection: (id: number) => request<Connection>(`/api/connections/${id}`),
  testConnection: (url: string) =>
    post<{ ok: boolean; version: string | null; error: string | null }>("/api/connections/test", { url }),
  createConnection: (name: string, url: string) => post<Connection>("/api/connections", { name, url }),
  reindex: (id: number) => post<Connection>(`/api/connections/${id}/reindex`),
  deleteConnection: (id: number) => request<void>(`/api/connections/${id}`, { method: "DELETE" }),

  schema: (id: number) => request<Schema>(`/api/connections/${id}/schema`),
  sampleRows: (id: number, table: string) =>
    request<QueryResult>(`/api/connections/${id}/schema/tables/${encodeURIComponent(table)}/sample`),

  runQuery: (id: number, sql: string) => post<QueryResult>(`/api/connections/${id}/query`, { sql }),
  formatSql: (sql: string) => post<{ sql: string }>("/api/query/format", { sql }),
  fixSql: (id: number, sql: string, error: string) =>
    post<{ sql: string; explanation: string }>(`/api/connections/${id}/query/fix`, { sql, error }),

  conversations: (id: number) => request<Conversation[]>(`/api/connections/${id}/conversations`),
  conversation: (conversationId: number) => request<ConversationDetail>(`/api/conversations/${conversationId}`),
  deleteConversation: (conversationId: number) =>
    request<void>(`/api/conversations/${conversationId}`, { method: "DELETE" }),
  feedback: (messageId: number, verified: boolean) =>
    post<{ savedQueryId: number | null }>(`/api/messages/${messageId}/feedback`, { verified }),

  doctor: (id: number, sql: string, analyze: boolean) =>
    post<Diagnosis>(`/api/connections/${id}/doctor`, { sql, analyze }),

  memory: (id: number) => request<SavedQuery[]>(`/api/connections/${id}/memory`),
  createMemory: (id: number, question: string, sql: string) =>
    post<SavedQuery>(`/api/connections/${id}/memory`, { question, sql }),
  updateMemory: (savedId: number, patch: Partial<Pick<SavedQuery, "question" | "sql" | "verified">>) =>
    request<SavedQuery>(`/api/memory/${savedId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteMemory: (savedId: number) => request<void>(`/api/memory/${savedId}`, { method: "DELETE" }),

  evalDatasets: () => request<{ name: string; size: number }[]>("/api/evals/datasets"),
  evalRuns: (id: number) => request<EvalRun[]>(`/api/connections/${id}/evals`),
  startEval: (id: number, dataset: string, useMemory: boolean) =>
    post<EvalRun>(`/api/connections/${id}/evals`, { dataset, useMemory }),
  evalRun: (runId: number) => request<EvalRunDetail>(`/api/evals/${runId}`),
};

// --- Chat streaming (SSE over POST) ----------------------------------------------------------

export type ChatEventHandlers = {
  onMeta?: (d: { conversationId: number; messageId: number; title: string }) => void;
  onStatus?: (d: { text: string }) => void;
  onRetrieval?: (d: Retrieval) => void;
  onThought?: (d: { text: string }) => void;
  onStep?: (d: AgentStep) => void;
  onStepResult?: (d: AgentStep) => void;
  onResult?: (d: QueryResult) => void;
  onAnswer?: (d: { sql: string; explanation: string; chart: ChartSpec; steps: AgentStep[]; attempts: number }) => void;
  onError?: (d: { message: string }) => void;
  onDone?: (d: { messageId: number }) => void;
};

const HANDLER_FOR: Record<string, keyof ChatEventHandlers> = {
  meta: "onMeta",
  status: "onStatus",
  retrieval: "onRetrieval",
  thought: "onThought",
  step: "onStep",
  step_result: "onStepResult",
  result: "onResult",
  answer: "onAnswer",
  error: "onError",
  done: "onDone",
};

/** EventSource can't POST, so read the body stream and split SSE frames on blank lines. */
export async function streamChat(
  connectionId: number,
  question: string,
  conversationId: number | null,
  handlers: ChatEventHandlers,
  signal?: AbortSignal
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/connections/${connectionId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, conversationId }),
      signal,
    });
  } catch (err) {
    if ((err as Error).name !== "AbortError") {
      handlers.onError?.({ message: `Can't reach the QueryPilot API at ${API_URL}.` });
    }
    return;
  }
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    handlers.onError?.({ message: body?.detail ?? `Request failed (${res.status})` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (frame: string) => {
    let event = "message";
    let data = "";
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    const key = HANDLER_FOR[event];
    if (!key || !data) return;
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (handlers[key] as ((d: any) => void) | undefined)?.(JSON.parse(data));
    } catch {
      // ignore malformed frame
    }
  };

  try {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep = buffer.indexOf("\n\n");
      while (sep !== -1) {
        dispatch(buffer.slice(0, sep));
        buffer = buffer.slice(sep + 2);
        sep = buffer.indexOf("\n\n");
      }
    }
  } catch (err) {
    if ((err as Error).name !== "AbortError") handlers.onError?.({ message: "Stream interrupted." });
  }
}
