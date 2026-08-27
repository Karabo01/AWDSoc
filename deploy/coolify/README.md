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
openssl rand -hex 32      # JWT_SECRET
openssl rand -base64 32   # ENCRYPTION_KEY
```

The two forms differ and both matter. `JWT_SECRET` is any string of at least 32
bytes — hex is used here because it contains nothing an env-var pipeline can
mangle. `ENCRYPTION_KEY` **must be base64 that decodes to exactly 32 bytes**, so
`-base64 32` is correct and `-hex 32` is not.

Set both on **`api` and `worker`, identically**. The API refuses to start in
`ENVIRONMENT=production` with a short, default or missing value, and the error
names the command to run. Do not work around it with `ENVIRONMENT=development`:
a guessable signing key forges every token in the product.

`ENCRYPTION_KEY` decrypts every stored Wazuh password. Lose it and you re-enter
every client's credentials; change it and you must re-encrypt them. Put both in
a password manager before pasting them into Coolify.

## 3. Managed resources

New project, then add **PostgreSQL 16** and **Redis 7**, and enable daily
backups on Postgres.

On the Redis resource, put this in the **Redis Conf** textarea on the General
page, then start it:

```
appendonly yes
appendfsync everysec
```

Redis holds the ingest buffer — alerts already answered with `202` that the
worker has not yet written to Postgres. The manager considers those delivered
and will never resend them, so with only RDB snapshots a Redis restart loses
them permanently. `everysec` caps that at about a second; `always` fsyncs every
write and will hurt on a small host.

Set the Postgres **Initial Database** and password before the first start.
Postgres only applies them when it initialises an empty volume — change them
afterwards and Coolify's fields drift from the actual credentials.

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

Same repository and build context as `api` - the same image, a different role.

| Setting | Value |
|---|---|
| `APP_ROLE` env var | `worker` |
| Domain | none |
| Port | none |
| Pre-deploy command | **none** |

Everything else in the environment matches `api` exactly, including
`DATABASE_URL`, `REDIS_URL`, `ENCRYPTION_KEY` and `JWT_SECRET`.

**The role is an environment variable, not a start-command override.** Coolify
applies custom start commands inconsistently to Dockerfile builds, and the
failure is silent: the worker boots as a second copy of the API, the stack
reports healthy, ingest returns `202`, and nothing ever writes an alert to
Postgres. `APP_ROLE` cannot be applied halfway.

Confirm after deploying - the logs must show arq, not uvicorn:

```bash
docker logs --tail 20 <worker-container>
```

`Uvicorn running on http://0.0.0.0:8000` there means `APP_ROLE` did not reach the
container. arq logs its function list and the ingest consumer announces itself
with `ingest consumer ... started`.

The worker is not optional. It runs the ingest consumer, so with it stopped
alerts buffer in Redis up to `INGEST_STREAM_MAXLEN` and then the oldest are
dropped. It also runs partition maintenance and reprocess jobs.

The worker must never run migrations: two containers racing
`alembic upgrade head` will deadlock.

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

Set these on the `api` resource **before the first deploy** and it creates
itself, no shell required:

```
BOOTSTRAP_ADMIN_EMAIL=you@awdtech.co.za
BOOTSTRAP_ADMIN_PASSWORD=           # blank generates one
```

Leave the password blank and one is generated and written **once** to the `api`
logs - search them for `bootstrap password`. This only runs when the users table
is empty, so it is inert on every later deploy and cannot alter an existing
account.

**Remove both variables once you have signed in.** Nothing consumes them again,
and a password sitting in the environment is a standing risk.

If the app is already deployed, or you would rather not put it in the
environment, create it by hand. Coolify's web terminal rides a websocket that
drops often - SSH to the host and go around it:

```bash
docker ps --format '{{.Names}}'
docker exec -it <api-container> python -m app.cli create-user \
  --email you@awdtech.co.za --name "Your Name" --role platform_admin
```

That same route is the reliable way to reach `psql` and `redis-cli`:

```bash
docker exec -it <postgres-container> psql -U awdsoc -d postgres
docker exec -it <redis-container> redis-cli -a '<password>' ping
```

## 9. Verify before onboarding anyone

```bash
curl https://soc.awdtech.co.za/api/healthz
```

**`/api/healthz`, not `/healthz`.** Traefik routes `/api` to the API and
everything else to the web container, so the bare path returns the SPA. The root
`/healthz` still exists for Coolify's container probe, which never goes through
Traefik - that is what the health check field on the `api` resource should use.

Four things must be true:

| Field | Meaning if wrong |
|---|---|
| `postgres.ok` | see `target`, `auth`, `resolves` below |
| `redis.ok` | same three fields |
| `schema.ready` | migrations never ran - the pre-deploy command is missing |
| `worker.alive` | `APP_ROLE=worker` did not reach the worker container |

`schema.revision` should show the latest migration. If `schema.ready` is false,
the API is running against an empty database: `select 1` succeeds, so nothing
else reveals it until the first query fails.

```bash
docker exec <api-container> alembic upgrade head
docker exec <api-container> alembic current
```

Then set **Pre-deploy command** on the `api` resource to `alembic upgrade head`
so it applies on every deploy. Never on the worker.

### Reading the connection diagnostics

`postgres` and `redis` each report `target`, `auth` and `resolves`, which
between them name the fault without needing a shell:

| `resolves` | `auth` | error | cause |
|---|---|---|---|
| `false` | - | any | wrong hostname, or the container is not running |
| `true` | `false` | `AuthenticationError` | no password in the URL |
| `true` | `true` | `AuthenticationError` | wrong password |
| `true` | `true` | `ConnectionError` | name resolves but nothing is listening |

Coolify names database containers by UUID, so a recreated resource gets a **new
hostname and a new password**. Both must be copied into `api` and `worker`.

Sign in at `https://soc.awdtech.co.za`.

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

---

# Deploying on the dev host (4 cores / 8 GB / 100 GB)

The console runs on its own VPS; Wazuh and the RMM stay on theirs. This is the
topology the trust boundary in DESIGN.md §3 assumes — alerts arrive over the
public internet, and the Manager API is reached outbound over it — so nothing
here is a workaround.

## Sizing

| Resource | RAM |
|---|---|
| `postgres` | 1–2 GB |
| `redis` | see the cap below |
| `api` | 300–400 MB |
| `worker` | 300–400 MB |
| `web` | ~20 MB |

Roughly 2–3 GB steady state. On 8 GB that leaves room, but two defaults are
sized for a production cohort and must come down, and one build-time risk needs
handling.

### Lower the Redis stream cap

`INGEST_STREAM_MAXLEN` defaults to 1,000,000 entries — at ~3 KB an alert that is
~3 GB of Redis if the worker ever stops, which on an 8 GB host is fatal rather
than merely slow.

```
INGEST_STREAM_MAXLEN=50000
```

~150 MB worst case, still hours of buffer at six agents.

### Lower the connection pools

`api` and `worker` each hold their own pool, and every Postgres connection costs
the server several MB. The defaults give 60 potential connections.

```
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
```

### Add swap before the first deploy

Coolify builds images on the host. The frontend build (`tsc` plus Vite) wants
1–2 GB on its own, and it runs while Postgres, Redis, `api` and `worker` are
already resident. On 8 GB that is the most likely OOM in the whole deployment,
and it kills a running service rather than failing the build.

```bash
fallocate -l 4G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

Disk is not a concern: 90 days of alerts with `raw` and every index is
single-digit GB at this volume, against 100 GB.

## Outbound: reaching the Wazuh Manager API

On the Wazuh host, create a **dedicated read-only API user** — `agent:read`,
`rules:read`, `manager:read`. Never reuse `wazuh-wui`.

Restrict port 55000 to the console's egress address. Find it from inside the
`api` container, not from your laptop:

```bash
curl -s https://ifconfig.me
```

Then set the tenant's connection to `https://<wazuh-host>:55000`, with
`verify_ssl: false` while the API still has its self-signed certificate. Use
**Test connection** before onboarding — it also confirms the agent group exists,
which is the check that matters on a shared manager.

## Inbound: set the CIDR allowlist properly

With the two hosts separated, the address the console observes is the Wazuh
host's real egress address, so the allowlist works as designed from day one. Get
it from the manager itself:

```bash
curl -s https://ifconfig.me
```

Set `ingest_cidrs` to that `/32`. If alerts stop arriving, the `api` logs name
the address that was actually seen:

```
ingest rejected: slug=... reason=disallowed_ip ip=<what we saw>
```

## Moving to the production host later

**Keep `soc.awdtech.co.za` pointed here now and take the name with you.** The
hostname is baked into every client's `hook_url`, so if it does not change, the
move is a DNS record and nothing on any manager needs touching.

The move is then:

1. Deploy the same five resources on the new host, **with the same
   `ENCRYPTION_KEY` and `JWT_SECRET`**.
2. `pg_dump` the console database and restore it there.
3. Repoint DNS. Re-issue TLS.
4. Update each tenant's `ingest_cidrs` only if the *Wazuh* host moved too.

**`ENCRYPTION_KEY` is the one that bites.** It decrypts every stored Wazuh
password. Generate a fresh one on the new host and every credential in the
restored database becomes unrecoverable ciphertext — the API will refuse to
decrypt them rather than fail silently, but the only fix is re-entering them by
hand. Carry the key across with the data.
