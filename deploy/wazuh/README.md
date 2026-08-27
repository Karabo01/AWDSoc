# Wazuh-side install

Two files, and they must ship together — the installer copies the integrator from
its own directory.

| File | What |
|---|---|
| `custom-awd-console` | The integrator. Runs once per alert, posts it to the console. |
| `install.sh` | Installs the integrator and writes the tenant's `<integration>` block. |

## Onboarding a client

Onboard them in the console first (**Clients → Onboard a client**). The reveal
panel hands you the exact command, filled in. It looks like this:

```bash
sudo ./install.sh --slug acme-corp --secret <secret> \
  --url https://console.awdtech.co.za --level 7 --group acme-corp
```

`--group` is **required on a shared manager**, which is the default topology. It
must match the client's agent group. The group filter is the only thing routing
that client's alerts to that client's URL: an agent in the wrong group produces
correctly signed alerts attributed to the wrong client, and the console cannot
detect that at ingest. Omit `--group` only when the manager serves exactly one
client.

Re-running is safe. The installer replaces only this tenant's block, marked by
`<!-- awdsoc:<slug>:begin -->` … `:end`, and leaves other tenants' blocks alone.
It backs up `ossec.conf` first and restores the backup if the manager will not
restart.

## The one rule in `custom-awd-console`

It must never block and never raise. The Wazuh integrator forks a process per
alert, so a hung script becomes a fork bomb on the client's manager and a
crashing one fills their logs during exactly the incident you need them reading.
Every failure path ends in `exit 0`; failures go to
`/var/ossec/logs/integrations.log`.

Retries are deliberately asymmetric: a 5xx or a transport error is retried twice
with backoff, but a **4xx is never retried**. A bad signature, a stale clock, an
unknown slug and a blocked IP all return 401, and none of them fix themselves —
retrying only burns forks.

## Verifying

```bash
tail -f /var/ossec/logs/integrations.log
```

Silence is success. The console's **Test connection** button checks the Manager
API in the other direction, including whether the agent group exists and how many
agents are in it.
