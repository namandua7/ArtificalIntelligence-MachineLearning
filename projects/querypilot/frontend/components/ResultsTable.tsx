"use client";

import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";

type Row = Record<string, unknown>;

function Cell({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-muted/60 italic">null</span>;
  if (typeof value === "number") return <span className="tabular-nums text-amber-200">{value.toLocaleString("en-US", { maximumFractionDigits: 4 })}</span>;
  if (typeof value === "boolean") return <span className="text-accent-2">{String(value)}</span>;
  if (typeof value === "object") return <span className="text-muted">{JSON.stringify(value)}</span>;
  const s = String(value);
  return <span title={s.length > 60 ? s : undefined}>{s.length > 80 ? `${s.slice(0, 80)}…` : s}</span>;
}

export function ResultsTable({
  columns,
  rows,
  pageSize = 50,
  className,
}: {
  columns: string[];
  rows: unknown[][];
  pageSize?: number;
  className?: string;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);

  // Column names can repeat (e.g. two "name" columns); key by index.
  const data = useMemo<Row[]>(
    () => rows.map((r) => Object.fromEntries(r.map((v, i) => [`c${i}`, v]))),
    [rows]
  );
  const defs = useMemo<ColumnDef<Row>[]>(
    () =>
      columns.map((name, i) => ({
        id: `c${i}`,
        accessorKey: `c${i}`,
        header: name,
        cell: (ctx) => <Cell value={ctx.getValue()} />,
        sortUndefined: "last",
      })),
    [columns]
  );

  const table = useReactTable({
    data,
    columns: defs,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize } },
  });

  const pageCount = table.getPageCount();

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full border-collapse text-left text-[12.5px]">
          <thead className="sticky top-0 z-10 bg-elevated">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                <th className="w-10 border-b border-border px-2 py-2 text-right font-mono text-[11px] font-normal text-muted/60">#</th>
                {hg.headers.map((h) => {
                  const sorted = h.column.getIsSorted();
                  return (
                    <th
                      key={h.id}
                      onClick={h.column.getToggleSortingHandler()}
                      className="cursor-pointer select-none whitespace-nowrap border-b border-border px-3 py-2 font-mono text-[11.5px] font-medium text-muted hover:text-fg"
                    >
                      <span className="inline-flex items-center gap-1">
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {sorted === "asc" && <ArrowUp className="h-3 w-3" />}
                        {sorted === "desc" && <ArrowDown className="h-3 w-3" />}
                      </span>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-b border-border/50 last:border-0 hover:bg-elevated/40">
                <td className="px-2 py-1.5 text-right font-mono text-[11px] text-muted/50">{row.index + 1}</td>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="whitespace-nowrap px-3 py-1.5">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length + 1} className="px-3 py-8 text-center text-muted">
                  No rows
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {pageCount > 1 && (
        <div className="flex items-center justify-end gap-2 pt-2 text-xs text-muted">
          <span>
            Page {table.getState().pagination.pageIndex + 1} of {pageCount}
          </span>
          <button
            className="rounded-md border border-border p-1 hover:text-fg disabled:opacity-40"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <button
            className="rounded-md border border-border p-1 hover:text-fg disabled:opacity-40"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
