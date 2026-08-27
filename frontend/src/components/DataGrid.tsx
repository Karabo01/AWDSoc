import { ChevronDown, ChevronUp } from "lucide-react";
import type { ReactNode } from "react";

/** Grid chrome shared by every list in the console.
 *
 *  The header is a raised surface rather than a bare row, and it sticks — on a
 *  queue you scroll through, a header that leaves the viewport means guessing
 *  which column you are reading. */

export const gridCell = "px-3 py-1.5 align-middle";

export function GridHead({ children }: { children: ReactNode }) {
  return (
    <thead className="sticky top-0 z-10 bg-ink-800">
      <tr className="border-b border-line text-left text-dim">{children}</tr>
    </thead>
  );
}

export function Th({
  children,
  className = "",
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <th className={`px-3 py-2 text-xs font-medium ${className}`}>{children}</th>
  );
}

/** A sortable header.
 *
 *  Sorting is applied by the server, not to the rows already loaded. Sorting an
 *  infinite list client-side reorders only what happens to be fetched, which
 *  looks like it worked and is wrong the moment you scroll. */
export function SortTh({
  label,
  sortKey,
  active,
  order,
  onSort,
  className = "",
}: {
  label: string;
  sortKey: string;
  active: string;
  order: "asc" | "desc";
  onSort: (key: string) => void;
  className?: string;
}) {
  const isActive = active === sortKey;
  return (
    <th className={`px-3 py-2 text-xs font-medium ${className}`}>
      <button
        onClick={() => onSort(sortKey)}
        aria-sort={isActive ? (order === "asc" ? "ascending" : "descending") : "none"}
        className={`flex items-center gap-1 transition hover:text-text ${
          isActive ? "text-text" : ""
        }`}
      >
        {label}
        {isActive ? (
          order === "asc" ? (
            <ChevronUp size={12} />
          ) : (
            <ChevronDown size={12} />
          )
        ) : (
          <ChevronDown size={12} className="opacity-0" aria-hidden />
        )}
      </button>
    </th>
  );
}

export function GridShell({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-auto rounded-lg border border-line">{children}</div>
  );
}
