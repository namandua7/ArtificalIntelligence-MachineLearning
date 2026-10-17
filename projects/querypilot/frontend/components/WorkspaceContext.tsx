"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import type { Connection, Meta, Schema } from "@/lib/api";
import { api } from "@/lib/api";

type Workspace = {
  connectionId: number;
  connection: Connection | null;
  connections: Connection[];
  schema: Schema | null;
  meta: Meta | null;
  error: string | null;
  reloadSchema: () => Promise<void>;
  conversationsVersion: number;
  bumpConversations: () => void;
};

const WorkspaceContext = createContext<Workspace | null>(null);

export function WorkspaceProvider({ connectionId, children }: { connectionId: number; children: ReactNode }) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [schema, setSchema] = useState<Schema | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conversationsVersion, setConversationsVersion] = useState(0);

  const reloadSchema = useCallback(async () => {
    try {
      setSchema(await api.schema(connectionId));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [connectionId]);

  useEffect(() => {
    setConnection(null);
    setSchema(null);
    setError(null);
    api.getConnection(connectionId).then(setConnection).catch((err) => setError(err.message));
    api.listConnections().then(setConnections).catch(() => undefined);
    api.meta().then(setMeta).catch(() => undefined);
    reloadSchema();
  }, [connectionId, reloadSchema]);

  return (
    <WorkspaceContext.Provider
      value={{
        connectionId,
        connection,
        connections,
        schema,
        meta,
        error,
        reloadSchema,
        conversationsVersion,
        bumpConversations: () => setConversationsVersion((v) => v + 1),
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): Workspace {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return ctx;
}
