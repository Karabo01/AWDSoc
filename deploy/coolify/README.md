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
