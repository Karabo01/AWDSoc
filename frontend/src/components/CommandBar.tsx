import { ChevronDown, Columns3 } from "lucide-react";
import { type ComponentType, type ReactNode, useEffect, useRef, useState } from "react";

/** The toolbar above a grid.
 *
 *  Actions stay visible and go *disabled* when they do not apply, rather than
 *  appearing on selection. A control that only exists once you have already
 *  worked out you can select rows teaches nobody that bulk actions exist; a
 *  greyed one advertises the capability and costs a row of chrome. */
export function CommandBar({ children }: { children: ReactNode }) {
  return (
    <div
      role="toolbar"
      className="flex flex-wrap items-center gap-1 border-b border-line pb-2"
    >
      {children}
    </div>
  );
}

export function Command({
  icon: Icon,
  label,
  onClick,
  disabled,
  danger,
  busy,
}: {
  icon: ComponentType<{ size?: number | string; className?: string }>;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  busy?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || busy}
      title={label}
      className={`flex items-center gap-1.5 rounded px-2 py-1.5 text-xs transition disabled:cursor-not-allowed disabled:opacity-40 ${
        danger
          ? "text-[color:var(--sev-crit)] hover:bg-ink-700"
          : "text-dim hover:bg-ink-700 hover:text-text"
      }`}
    >
      <Icon size={14} className={`shrink-0 ${busy ? "animate-pulse" : ""}`} />
      {label}
    </button>
  );
}

export function CommandDivider() {
  return <span aria-hidden className="mx-1 h-4 w-px shrink-0 bg-[color:var(--line)]" />;
}

export interface ColumnOption {
  key: string;
  label: string;
  /** Columns the grid cannot function without are offered but not removable. */
  locked?: boolean;
}

/** The column chooser. Selection is per browser, not per account — it is a
 *  view preference, and round-tripping it through the API would be a write on
 *  every checkbox. */
export function ColumnChooser({
  columns,
  hidden,
  onToggle,
}: {
  columns: ColumnOption[];
  hidden: Set<string>;
  onToggle: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocument(event: MouseEvent) {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    }
    function onEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocument);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onDocument);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open]);

  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded px-2 py-1.5 text-xs text-dim transition hover:bg-ink-700 hover:text-text"
      >
        <Columns3 size={14} />
        Columns
        <ChevronDown size={12} />
      </button>

      {open && (
        <div className="absolute right-0 z-30 mt-1 w-52 rounded border border-line bg-ink-800 p-1 shadow-lg">
          {columns.map((column) => (
            <label
              key={column.key}
              className={`flex items-center gap-2 rounded px-2 py-1.5 text-xs ${
                column.locked ? "text-dim" : "cursor-pointer hover:bg-ink-700"
              }`}
            >
              <input
                type="checkbox"
                checked={!hidden.has(column.key)}
                disabled={column.locked}
                onChange={() => onToggle(column.key)}
              />
              {column.label}
              {column.locked && <span className="ml-auto text-[10px]">always</span>}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
