"use client";

/**
 * Multi-file drag-and-drop zone for bulk CV upload.
 *
 * Supports PDF, DOCX, and TXT. Shows per-file chips with remove. Fires
 * `onFilesChange` so the parent form controls the actual upload.
 */

import { useCallback, useRef, useState } from "react";

interface Props {
  onFilesChange: (files: File[]) => void;
  disabled?: boolean;
  maxFiles?: number;
}

const ACCEPTED = ".pdf,.docx,.txt";
const ACCEPTED_SET = new Set(["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"]);

export function BulkUploadDropzone({ onFilesChange, disabled, maxFiles = 100 }: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const arr = Array.from(incoming).filter(
        (f) =>
          ACCEPTED_SET.has(f.type) ||
          f.name.endsWith(".pdf") ||
          f.name.endsWith(".docx") ||
          f.name.endsWith(".txt"),
      );
      setFiles((prev) => {
        const merged = [...prev, ...arr].slice(0, maxFiles);
        onFilesChange(merged);
        return merged;
      });
    },
    [maxFiles, onFilesChange],
  );

  const removeFile = useCallback(
    (idx: number) => {
      setFiles((prev) => {
        const next = prev.filter((_, i) => i !== idx);
        onFilesChange(next);
        return next;
      });
    },
    [onFilesChange],
  );

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (!disabled) addFiles(e.dataTransfer.files);
        }}
        onClick={() => !disabled && inputRef.current?.click()}
        className={`border-2 border-dashed rounded-card p-8 text-center cursor-pointer transition-colors
          ${dragOver ? "border-axis-magenta bg-axis-magenta/5" : "border-axis-divider hover:border-axis-magenta/40"}
          ${disabled ? "opacity-50 pointer-events-none" : ""}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          multiple
          className="hidden"
          disabled={disabled}
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <p className="text-axis-ink font-semibold mb-1">
          Drop CVs here or click to browse
        </p>
        <p className="text-xs text-axis-muted">
          PDF, DOCX, or TXT. Up to {maxFiles} files.
        </p>
      </div>

      {files.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {files.map((f, i) => (
            <span
              key={`${f.name}-${i}`}
              className="inline-flex items-center gap-1 bg-axis-surface border border-axis-divider rounded px-2 py-1 text-xs"
            >
              {f.name}
              {!disabled && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFile(i);
                  }}
                  className="text-red-400 hover:text-red-600 ml-1"
                >
                  x
                </button>
              )}
            </span>
          ))}
          <span className="text-[11px] text-axis-muted self-center ml-2">
            {files.length} file{files.length !== 1 ? "s" : ""} selected
          </span>
        </div>
      )}
    </div>
  );
}
