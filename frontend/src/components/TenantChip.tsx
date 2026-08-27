/** Tenant identity always travels as a chip. The 3px colour border is a second,
 *  quieter channel — colour alone never carries it. */
export function TenantChip({
  name,
  colour,
}: {
  name: string | null;
  colour: string | null;
}) {
  if (!name) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded bg-ink-700 px-1.5 py-0.5 text-xs text-dim">
      <span
        aria-hidden
        className="h-2.5 w-[3px] rounded-sm"
        style={{ background: colour ?? "var(--line)" }}
      />
      {name}
    </span>
  );
}
