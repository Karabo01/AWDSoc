/** The signature element: the Wazuh rule level itself, 0-15, on a continuous
 *  ramp. Analysts already reason in this number; collapsing it to low/medium/
 *  high throws away information the ruleset gave us free. */
export function SeverityChip({ level }: { level: number }) {
  const band =
    level >= 13
      ? "text-[color:var(--sev-crit)] bg-[rgba(224,67,95,0.14)]"
      : level >= 10
        ? "text-[color:var(--sev-high)] bg-[rgba(232,116,59,0.12)]"
        : level >= 7
          ? "text-[color:var(--sev-med)] bg-[rgba(224,163,46,0.12)]"
          : "text-dim bg-ink-700";

  return (
    <span
      className={`data inline-flex h-6 min-w-[1.75rem] items-center justify-center rounded px-1.5 text-xs font-medium tabular-nums ${band}`}
      title={`Wazuh rule level ${level}`}
    >
      {level}
    </span>
  );
}
