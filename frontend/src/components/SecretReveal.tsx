import type { TenantSecretRevealed } from "@/api/tenants";
import { CopyField } from "@/components/CopyField";

/** Shown once, after creation or rotation. The secret cannot be read back, so
 *  this panel is deliberately hard to dismiss by accident. */
export function SecretReveal({
  revealed,
  onDone,
}: {
  revealed: TenantSecretRevealed;
  onDone: () => void;
}) {
  const shared = Boolean(revealed.tenant.connection?.agent_group);

  return (
    <div className="rounded-lg border border-accent/40 bg-ink-800 p-6">
      <h2 className="text-base font-semibold">
        {revealed.tenant.name} is onboarded
      </h2>
      <p className="mt-1 text-sm text-dim">
        This secret is shown once and cannot be read back. Copy it now — if you lose it,
        rotate the secret and reinstall.
      </p>

      <CopyField label="Ingest secret" value={revealed.ingest_secret} />
      <CopyField label="Ingest URL" value={revealed.ingest_url} />

      <div className="mt-6 border-t border-line pt-4">
        <h3 className="text-sm font-medium">Run this on the client&rsquo;s manager</h3>
        <p className="mt-1 text-sm text-dim">
          From the <span className="data">deploy/wazuh</span> directory, as root.
        </p>
        <CopyField label="Install command" value={revealed.install_command} multiline />

        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-dim transition hover:text-text">
            Or add the block to ossec.conf by hand
          </summary>
          <CopyField
            label="Integration block"
            value={revealed.integration_block}
            multiline
          />
        </details>

        {!shared && (
          <p className="mt-4 rounded border border-line bg-ink-900 p-3 text-sm text-dim">
            No agent group is set for this client. On a shared manager that sends{" "}
            <em>every</em> alert on the manager to this client. Set an agent group unless
            this manager serves only them.
          </p>
        )}
      </div>

      <button
        onClick={onDone}
        className="mt-6 rounded bg-accent px-3 py-2 text-sm font-medium text-ink-900 transition hover:brightness-110"
      >
        I&rsquo;ve copied the secret
      </button>
    </div>
  );
}
