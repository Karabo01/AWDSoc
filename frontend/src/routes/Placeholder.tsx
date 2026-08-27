/** Routes reserved now so navigation and deep links are stable while the
 *  milestones behind them land. */
export function Placeholder({ title, milestone }: { title: string; milestone: string }) {
  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="text-lg font-semibold">{title}</h1>
      <p className="mt-2 text-sm text-dim">Lands in {milestone}.</p>
    </div>
  );
}
