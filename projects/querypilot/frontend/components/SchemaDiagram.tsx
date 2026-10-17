"use client";

import dagre from "dagre";
import { Eye, KeyRound, Link2 } from "lucide-react";
import { memo, useEffect, useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  useReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";

import type { Schema, Table } from "@/lib/api";
import { cn, formatNumber } from "@/lib/utils";

const NODE_WIDTH = 250;
const HEADER_HEIGHT = 40;
const ROW_HEIGHT = 22;
const MAX_COLUMNS = 12;

type TableNodeData = { table: Table; dimmed: boolean; selected: boolean };

function nodeHeight(t: Table) {
  const shown = Math.min(t.columns.length, MAX_COLUMNS);
  return HEADER_HEIGHT + shown * ROW_HEIGHT + (t.columns.length > MAX_COLUMNS ? ROW_HEIGHT : 0) + 8;
}

const TableNode = memo(function TableNode({ data }: NodeProps<TableNodeData>) {
  const { table, dimmed, selected } = data;
  const isView = table.kind === "view";
  return (
    <div
      style={{ width: NODE_WIDTH }}
      className={cn(
        "overflow-hidden rounded-xl border bg-panel/95 shadow-xl shadow-black/30 backdrop-blur transition-all",
        selected ? "border-accent ring-2 ring-accent/30" : isView ? "border-accent-2/30" : "border-border",
        dimmed && "opacity-25"
      )}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-accent/70" />
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-accent/70" />
      <div
        className={cn(
          "flex items-center gap-2 border-b border-border px-3",
          isView ? "bg-accent-2/10" : "bg-gradient-to-r from-accent/15 to-transparent"
        )}
        style={{ height: HEADER_HEIGHT }}
      >
        {isView && <Eye className="h-3.5 w-3.5 text-accent-2" />}
        <span className="truncate font-mono text-[12.5px] font-semibold">{table.name}</span>
        {table.rowEstimate !== null && !isView && (
          <span className="ml-auto shrink-0 text-[10px] text-muted">{formatNumber(table.rowEstimate)} rows</span>
        )}
      </div>
      <div className="py-1">
        {table.columns.slice(0, MAX_COLUMNS).map((c) => (
          <div key={c.name} className="flex items-center gap-1.5 px-3" style={{ height: ROW_HEIGHT }}>
            <span className="w-3.5 shrink-0">
              {c.pk ? (
                <KeyRound className="h-3 w-3 text-warn" />
              ) : c.fk ? (
                <Link2 className="h-3 w-3 text-accent" />
              ) : null}
            </span>
            <span className={cn("truncate font-mono text-[11.5px]", c.pk ? "text-fg" : "text-fg/80")}>{c.name}</span>
            <span className="ml-auto truncate pl-2 font-mono text-[10px] text-muted/80">{c.type.replace("timestamp with time zone", "timestamptz").replace("character varying", "varchar")}</span>
          </div>
        ))}
        {table.columns.length > MAX_COLUMNS && (
          <div className="px-3 text-[10.5px] text-muted" style={{ height: ROW_HEIGHT, lineHeight: `${ROW_HEIGHT}px` }}>
            + {table.columns.length - MAX_COLUMNS} more columns
          </div>
        )}
      </div>
    </div>
  );
});

const NODE_TYPES = { table: TableNode };

function layout(schema: Schema, showViews: boolean): { nodes: Node<TableNodeData>[]; edges: Edge[] } {
  const tables = schema.tables.filter((t) => showViews || t.kind === "table");
  const names = new Set(tables.map((t) => t.name));
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 110, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  tables.forEach((t) => g.setNode(t.name, { width: NODE_WIDTH, height: nodeHeight(t) }));

  const seen = new Set<string>();
  const edges: Edge[] = [];
  for (const r of schema.relations) {
    if (!names.has(r.fromTable) || !names.has(r.toTable) || r.fromTable === r.toTable) continue;
    const id = `${r.fromTable}.${r.fromColumn}->${r.toTable}`;
    if (seen.has(id)) continue;
    seen.add(id);
    // Point from the referenced (parent) table to the child so dagre ranks parents left.
    g.setEdge(r.toTable, r.fromTable);
    edges.push({
      id,
      source: r.toTable,
      target: r.fromTable,
      type: "smoothstep",
      label: r.fromColumn,
      labelStyle: { fill: "rgb(148 148 160)", fontSize: 10, fontFamily: "var(--font-mono)" },
      labelBgStyle: { fill: "rgb(17 17 21)" },
      labelBgPadding: [4, 2],
      style: { stroke: "rgb(139 92 246 / 0.55)", strokeWidth: 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: "rgb(139 92 246)", width: 14, height: 14 },
    });
  }
  dagre.layout(g);

  const nodes = tables.map((t) => {
    const p = g.node(t.name);
    return {
      id: t.name,
      type: "table",
      position: { x: p.x - NODE_WIDTH / 2, y: p.y - nodeHeight(t) / 2 },
      data: { table: t, dimmed: false, selected: false },
    };
  });
  return { nodes, edges };
}

function DiagramInner({
  schema,
  showViews,
  search,
  selected,
  onSelect,
}: {
  schema: Schema;
  showViews: boolean;
  search: string;
  selected: string | null;
  onSelect: (name: string | null) => void;
}) {
  const { fitView, setCenter, getNode } = useReactFlow();
  const base = useMemo(() => layout(schema, showViews), [schema, showViews]);

  const q = search.trim().toLowerCase();
  const neighbours = useMemo(() => {
    if (!selected) return null;
    const set = new Set([selected]);
    schema.relations.forEach((r) => {
      if (r.fromTable === selected) set.add(r.toTable);
      if (r.toTable === selected) set.add(r.fromTable);
    });
    return set;
  }, [selected, schema.relations]);

  const nodes = useMemo(
    () =>
      base.nodes.map((n) => {
        const matches = q
          ? n.id.toLowerCase().includes(q) || n.data.table.columns.some((c) => c.name.toLowerCase().includes(q))
          : true;
        const inFocus = neighbours ? neighbours.has(n.id) : true;
        return { ...n, data: { ...n.data, dimmed: !matches || !inFocus, selected: n.id === selected } };
      }),
    [base.nodes, q, neighbours, selected]
  );

  const edges = useMemo(
    () =>
      base.edges.map((e) => {
        const active = selected && (e.source === selected || e.target === selected);
        return {
          ...e,
          animated: Boolean(active),
          style: {
            ...e.style,
            opacity: selected && !active ? 0.12 : 1,
            stroke: active ? "rgb(34 211 238)" : (e.style?.stroke as string),
          },
        };
      }),
    [base.edges, selected]
  );

  useEffect(() => {
    const id = setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 50);
    return () => clearTimeout(id);
  }, [base, fitView]);

  useEffect(() => {
    if (!selected) return;
    const n = getNode(selected);
    // Offset right so the node isn't hidden behind the ~420px details panel.
    if (n) setCenter(n.position.x + NODE_WIDTH / 2 + 210, n.position.y + 120, { zoom: 1, duration: 500 });
  }, [selected, getNode, setCenter]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      onNodeClick={(_, n) => onSelect(n.id)}
      onPaneClick={() => onSelect(null)}
      minZoom={0.1}
      maxZoom={1.6}
      proOptions={{ hideAttribution: true }}
      nodesConnectable={false}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="rgb(63 63 70)" />
      <Controls showInteractive={false} position="bottom-left" />
      <MiniMap
        pannable
        zoomable
        nodeColor={(n) => ((n.data as TableNodeData).table.kind === "view" ? "#22d3ee55" : "#8b5cf680")}
        maskColor="rgb(9 9 11 / 0.7)"
        position="bottom-right"
      />
    </ReactFlow>
  );
}

export function SchemaDiagram(props: {
  schema: Schema;
  showViews: boolean;
  search: string;
  selected: string | null;
  onSelect: (name: string | null) => void;
}) {
  return (
    <ReactFlowProvider>
      <DiagramInner {...props} />
    </ReactFlowProvider>
  );
}
