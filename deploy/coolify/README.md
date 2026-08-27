# Deploying to Coolify

One project, five resources. Traefik terminates TLS; `/api` routes to `api:8000`
and everything else to `web:80`, so the console is same-origin and there is no
CORS anywhere in the codebase.

| Resource   | Type                        | Notes                                    |
|------------|-----------------------------|------------------------------------------|
| `postgres` | Managed PostgreSQL 16       | Daily backups                            |
| `redis`    | Managed Redis 7             | `appendonly yes`                         |
| `api`      | Dockerfile from `/backend`  | Domain, path `/api`                      |
| `worker`   | Same image, command override| No domain, no exposed port               |
| `web`      | Dockerfile from `/frontend` | Same domain, path `/`                    |

## Worker command override

```
arq app.workers.consumer.WorkerSettings
```

## Migrations

Set as a **pre-deploy command on `api` only**:

```
alembic upgrade head
```

The worker must never run migrations. Two containers racing `alembic upgrade head`
will deadlock.

## Partitions

`alerts` is partitioned monthly on `timestamp`. The initial migration creates the
current month plus three, and the worker's daily `maintain_partitions` job keeps
them rolling and drops anything wholly past `ALERT_RETENTION_DAYS`.

This is plain DDL in `app/workers/partitions.py` rather than `pg_partman`, because
Coolify's managed Postgres image is not guaranteed to ship the extension and the
whole job is thirty lines with one less dependency. If you later move to
`pg_partman`, drop the cron job — do not run both.

Never run partition maintenance from cron on the host. Coolify hosts get rebuilt.

## Health checks

- `api` → `GET /healthz`. Checks Postgres and Redis, 200 or 503. Coolify gates
  zero-downtime deploys on this. Worker liveness is reported but never fails it.
- `GET /readyz` is for monitoring only. Per-tenant Manager API reachability lands
  in M7 and must never gate a deploy — a client's network being down is not our
  outage.

## Required environment

Copy `backend/.env.example`. Generate the two secrets before the first deploy:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET
python -m app.cli generate-key                                  # ENCRYPTION_KEY
```

The API refuses to start in `ENVIRONMENT=production` with a short or default
`JWT_SECRET`, or with no `ENCRYPTION_KEY`. That is deliberate.

Per-tenant values — ingest secrets, CIDRs, Wazuh credentials, alert floor,
grouping window — live in the database. Onboarding a client never requires a
redeploy.

## First user

Once `api` is up, from a shell on that container:

```bash
python -m app.cli create-user --email you@awdtech.co.za \
  --name "Your Name" --role platform_admin
```

---

# Deploying soc.awdtech.co.za, in order

## 1. DNS

Point `soc.awdtech.co.za` at the Coolify host's public IP (an `A` record).
Let's Encrypt validates over HTTP, so this must resolve **before** the first
deploy or TLS issuance fails and Traefik serves its default certificate.

## 2. Generate the two secrets once, and keep them

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
```

The first is `JWT_SECRET`, the second `ENCRYPTION_KEY`.

`ENCRYPTION_KEY` decrypts every stored Wazuh password. Lose it and you re-enter
every client's credentials; change it and you must re-encrypt them. Put both in
a password manager before pasting them into Coolify.

## 3. Managed resources

New project, then add **PostgreSQL 16** and **Redis 7**. Set `appendonly yes` on
Redis and enable daily backups on Postgres.

Take the internal connection strings Coolify gives you. **`DATABASE_URL` must use
the asyncpg driver** — Coolify hands you a `postgresql://` URL and the API will
not start with it:

```
postgresql+asyncpg://user:pass@postgres:5432/dbname
```

## 4. `api`

Repository resource, build context `/backend`.

| Setting | Value |
|---|---|
| Domain | `https://soc.awdtech.co.za` |
| Path | `/api` |
| Port | `8000` |
| Health check | `/healthz` |
| Pre-deploy command | `alembic upgrade head` |

Environment: everything in `backend/.env.example`, with
`ENVIRONMENT=production` and `CONSOLE_BASE_URL=https://soc.awdtech.co.za`.

## 5. `worker`

Same repository and build context as `api` — the same image, a different
command.

| Setting | Value |
|---|---|
| Command override | `arq app.workers.consumer.WorkerSettings` |
| Domain | none |
| Port | none |
| Pre-deploy command | **none** |

Same environment as `api`. The worker must never run migrations: two containers
racing `alembic upgrade head` will deadlock.

The worker is not optional. It runs the ingest consumer, so with it stopped
alerts buffer in Redis up to `INGEST_STREAM_MAXLEN` and then the oldest are
dropped. It also runs partition maintenance and reprocess jobs.

## 6. `web`

Repository resource, build context `/frontend`.

| Setting | Value |
|---|---|
| Domain | `https://soc.awdtech.co.za` |
| Path | `/` |
| Port | `80` |

## 7. Deploy in dependency order

`postgres` → `redis` → `api` (migrations run here) → `worker` → `web`.

## 8. First user

From a terminal on the `api` container:

```bash
python -m app.cli create-user --email you@awdtech.co.za \
  --name "Your Name" --role platform_admin
```

## 9. Verify before onboarding anyone

```bash
curl https://soc.awdtech.co.za/healthz
```

`postgres.ok`, `redis.ok` and `worker.alive` must all be true. Sign in at
`https://soc.awdtech.co.za`.

---

# Ingest

**`CONSOLE_BASE_URL` must be right before you onboard anyone.** It is baked into
the `hook_url` of every client's integration block. Wrong, and you get a tenant
that looks correctly configured and never delivers.

**Clocks must agree.** Ingest rejects any timestamp more than
`INGEST_MAX_SKEW_SECONDS` (300s) from the console's own. A manager whose clock
has drifted has every alert rejected as stale, and the rejection is a
deliberately uninformative 401. Run NTP on both ends.

**Proxy hops.** `INGEST_TRUSTED_PROXY_HOPS=1` assumes Traefik is the only proxy
in front of the API. The source address is read from the *right* of
`X-Forwarded-For`, because that is the entry Traefik itself observed — reading
the leftmost would let a caller spoof its own address and walk through the
per-tenant CIDR allowlist. Put a CDN in front and you must raise this number to
match.

`/healthz` reports `ingest_backlog`. Growing with `worker.alive` true means the
writer is behind; growing with it false means alerts are queuing, not arriving.

## Onboarding smoke test

1. Sign in, **Clients → Onboard a client**, copy the install command from the
   reveal panel. The ingest secret is shown once and cannot be read back.
2. Run it on that client's manager as root, from `deploy/wazuh/`.
3. Confirm the block landed in `/var/ossec/etc/ossec.conf` and the manager
   restarted.
4. Trigger an alert at or above the tenant's floor — repeated `ssh` failures
   against a monitored host are the easy one.
5. Watch `/var/ossec/logs/integrations.log` on the manager. Silence is success;
   a line there names the failure.
6. Check the console overview, or `GET /api/v1/ingest/status`. The client should
   leave the "never delivered" state within seconds, and an incident should
   appear in the queue.

If step 6 stays silent, check in this order: **clock skew**, then
`CONSOLE_BASE_URL` in the installed block, then the CIDR allowlist against the
manager's real egress address, then the `<group>` filter.

# After the first client

Set an SLA policy per tenant (**Clients → SLA**) or the queue shows no
countdown — a tenant with no bands has no SLA by design.

Watch `failed to normalise` on the overview. A decoder the map does not cover
lands with `map_version = -1`; fix `app/normalisation/maps/v1.yaml`, redeploy,
then `POST /api/v1/admin/reprocess` over the affected range to backfill.
