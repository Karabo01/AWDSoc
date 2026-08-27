import { useState } from "react";

export function CopyField({
  label,
  value,
  multiline = false,
}: {
  label: string;
  value: string;
  multiline?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-dim">{label}</span>
        <button
          type="button"
          onClick={() => void copy()}
          className="rounded border border-line px-2 py-0.5 text-xs text-dim transition hover:text-text"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {multiline ? (
        <pre className="data mt-1 max-h-64 overflow-auto rounded border border-line bg-ink-900 p-3 text-xs leading-relaxed">
          {value}
        </pre>
      ) : (
        <p className="data mt-1 break-all rounded border border-line bg-ink-900 p-2 text-xs">
          {value}
        </p>
      )}
    </div>
  );
}
