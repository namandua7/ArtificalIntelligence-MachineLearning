"use client";

import Editor, { type OnMount } from "@monaco-editor/react";
import type { editor as MonacoEditor, Position } from "monaco-editor";
import { useEffect, useRef, useState } from "react";

import type { Schema } from "@/lib/api";

type Monaco = Parameters<OnMount>[1];
type EditorInstance = Parameters<OnMount>[0];

const THEME = "querypilot-dark";

function defineTheme(monaco: Monaco) {
  monaco.editor.defineTheme(THEME, {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "keyword", foreground: "c4b5fd", fontStyle: "bold" },
      { token: "string", foreground: "6ee7b7" },
      { token: "number", foreground: "fcd34d" },
      { token: "comment", foreground: "71717a", fontStyle: "italic" },
      { token: "operator", foreground: "a1a1aa" },
    ],
    colors: {
      "editor.background": "#0b0b0e",
      "editor.lineHighlightBackground": "#17171c",
      "editorLineNumber.foreground": "#3f3f46",
      "editorLineNumber.activeForeground": "#a1a1aa",
      "editor.selectionBackground": "#8b5cf640",
      "editorCursor.foreground": "#a78bfa",
      "editorWidget.background": "#111115",
      "editorSuggestWidget.background": "#111115",
      "editorSuggestWidget.border": "#27272e",
      "editorSuggestWidget.selectedBackground": "#26263a",
    },
  });
}

export function SqlEditor({
  value,
  onChange,
  onRun,
  schema,
  height = "100%",
  readOnly = false,
}: {
  value: string;
  onChange?: (value: string) => void;
  onRun?: () => void;
  schema?: Schema | null;
  height?: string | number;
  readOnly?: boolean;
}) {
  const [monaco, setMonaco] = useState<Monaco | null>(null);
  const editorRef = useRef<EditorInstance | null>(null);
  const onRunRef = useRef(onRun);
  onRunRef.current = onRun;

  // Schema-aware autocomplete: tables everywhere, columns of tables mentioned in the query first.
  useEffect(() => {
    if (!monaco || !schema) return;
    const disposable = monaco.languages.registerCompletionItemProvider("sql", {
      triggerCharacters: [".", " "],
      provideCompletionItems(model: MonacoEditor.ITextModel, position: Position) {
        const word = model.getWordUntilPosition(position);
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: word.endColumn,
        };
        const text = model.getValue().toLowerCase();
        const kinds = monaco.languages.CompletionItemKind;
        const suggestions = schema.tables.flatMap((t) => {
          const mentioned = text.includes(t.name.toLowerCase());
          return [
            {
              label: t.name,
              kind: t.kind === "view" ? kinds.Interface : kinds.Struct,
              detail: `${t.kind} · ${t.columns.length} columns`,
              insertText: t.name,
              range,
              sortText: `1${t.name}`,
            },
            ...t.columns.map((c) => ({
              label: { label: c.name, description: t.name },
              kind: kinds.Field,
              detail: `${c.type}${c.pk ? " · PK" : ""}${c.fk ? ` → ${c.fk}` : ""}`,
              insertText: c.name,
              range,
              sortText: `${mentioned ? "0" : "2"}${c.name}`,
            })),
          ];
        });
        return { suggestions };
      },
    });
    return () => disposable.dispose();
  }, [monaco, schema]);

  const handleMount: OnMount = (editor, instance) => {
    editorRef.current = editor;
    defineTheme(instance);
    instance.editor.setTheme(THEME);
    editor.addCommand(instance.KeyMod.CtrlCmd | instance.KeyCode.Enter, () => onRunRef.current?.());
    setMonaco(instance);
    editor.focus();
  };

  return (
    <Editor
      height={height}
      language="sql"
      value={value}
      theme="vs-dark"
      onChange={(v) => onChange?.(v ?? "")}
      onMount={handleMount}
      loading={<div className="p-4 text-xs text-muted">Loading editor…</div>}
      options={{
        readOnly,
        minimap: { enabled: false },
        fontSize: 13,
        fontFamily: "var(--font-mono), ui-monospace, monospace",
        fontLigatures: true,
        lineNumbersMinChars: 3,
        scrollBeyondLastLine: false,
        padding: { top: 12, bottom: 12 },
        renderLineHighlight: "line",
        wordWrap: "on",
        tabSize: 2,
        automaticLayout: true,
        suggest: { showWords: false },
      }}
    />
  );
}
