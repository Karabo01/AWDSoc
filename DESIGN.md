# AWDTECH SOC Console — design document

A Microsoft Sentinel-style multi-tenant SOC console with Wazuh as the detection engine, operated by AWDTECH as a managed service.

*Working title.* Pick a product name before M1 — it ends up in the JWT issuer, container names, the customer-facing domain, and the integrator script name.

This document is the build spec. It is written to be read by Claude Code at the start of a session and referenced throughout. Where it says **decided**, do not re-litigate. Where it says **open**, ask before choosing.

---

## 1. Scope

### What this is

A user plane on top of Wazuh. Wazuh keeps doing detection, collection, and storage. This platform adds the SOC workflow Wazuh's dashboard does not have: incidents, entity pivoting, case management, and analyst triage.

It is a **multi-tenant MSSP product from day one**. AWDTECH analysts work across every client; each client sees only their own environment. Every choice below assumes a public-internet-facing deployment serving several client Wazuh environments — not a single internal console.

This is a standalone product. It shares no code, schema, or auth with any other AWDTECH platform.

### In scope for v1

| Capability | Notes |
|---|---|
| Multi-tenant onboarding | One tenant per client environment |
| Real-time alert ingestion | Wazuh integrator pushes to a per-tenant webhook |
| ECS normalisation | Platform-side, versioned, replayable |
| Entity extraction and pivoting | `related.*` arrays drive entity pages |
| Incident grouping and case management | Status, severity, assignment, timeline, comments |
| Cross-tenant analyst queue | The core MSSP surface |
| Incident SLA | Per-tenant response and resolution targets by severity, counted down in the queue, paused while awaiting client feedback |
| Agent inventory | Read-through to each tenant's Wazuh Manager API |
| MITRE ATT&CK coverage | Derived from `rule.mitre.*` on observed alerts |
| Audit log | Every state change on an incident |

### Explicitly out of scope for v1

- **Hunting.** No query surface, no archive indexing, no OpenSearch client in the backend. Do not enable `logall_json`.
- **Scheduled analytics rules.** All evaluation is real-time in each tenant's Wazuh manager. No scheduler, no Sigma compiler, no rule authoring UI.
- **SOAR / playbooks.** v2. Design the incident model so actions can attach later; build none of it now.
- **Workbooks / custom dashboards.** One fixed overview page.
- **Billing and metering.** Track alert volume per tenant so it can be billed later, but build no billing.
- **Client login.** **Decided:** v1 is staff-only. Clients get reports; only AWDTECH analysts sign in. The four roles, `staff_tenant_access`, and `incident_comments.visibility` all stay in the schema and are already built, so client access is additive work in v1.1 rather than a refactor. Nothing in v1 may assume the reader is staff — the queue renders without the tenant chip for a client token, and `client_viewer` must never receive an internal comment. Those paths ship untested by real users, so keep the isolation tests honest.

Aggregation detections (brute force, low-and-slow, impossible travel) live in each tenant's Wazuh ruleset as `frequency` / `timeframe` / `if_matched_sid` rules. That is the deliberate consequence of real-time-only evaluation. The console consumes their output like any other alert.

---

## 2. Architecture

```
   AWDTECH analyst ─┐
   client user ─────┼── HTTPS ──▶ ┌───────────────────────────────────┐
                                  │  Coolify host (user plane)        │
                                  │                                   │
                                  │  web     React + Vite + nginx     │
                                  │   │                               │
                                  │   ▼                               │
                                  │  api     FastAPI (ASGI) ──▶ postgres
                                  │   │  │                            │
                                  │   │  └────▶ redis ◀── worker (arq)│
                                  └───▲──────────────────────┬────────┘
                                      │                      │
              ┌───────────────────────┴──┐                   │ Manager API
              │  per-tenant alert push   │                   │ per tenant
              │  (Wazuh integrator)      │                   │
   ┌──────────┴──────┐  ┌────────────────┴─┐  ┌──────────────▼────────┐
   │ Client A Wazuh  │  │ Client B Wazuh   │  │ Client C Wazuh        │
   │ manager+indexer │  │ manager+indexer  │  │ manager+indexer       │
   └─────────────────┘  └──────────────────┘  └───────────────────────┘
```

**Decided:** the console never writes to Wazuh in v1 and never queries any indexer. Alerts arrive by push. Agent and rule data is pulled from each tenant's Manager API and cached. One-directional coupling means a client's Wazuh upgrade cannot break the console's data model.

### Two tenancy topologies, both supported

| Topology | When | How |
|---|---|---|
| **Shared manager** — **the default** | AWDTECH runs one manager serving several clients | One `<integration>` block *per tenant*, each with a `<group>` filter matching that client's agent group, each posting to its own tenant URL |
| **Dedicated manager** | Client owns their Wazuh, brings compliance requirements, or outgrows the shared manager | One `<integration>` block posting to that tenant's ingest URL |

The Wazuh integrator's `<group>` filter is what makes the shared case work without any routing logic in the console. Ingest is always addressed to a specific tenant by URL; the console never has to infer tenancy from alert content.

**Decided: shared is the default for the first cohort**, on cost — a Wazuh indexer per client is the largest infrastructure line, and the console supports both topologies either way, so this is a runbook decision rather than a code one. It carries two obligations that dedicated would have given for free:

1. **Every aggregation rule must be group-scoped.** `frequency` / `timeframe` / `if_matched_sid` rules on a shared manager count over the whole manager's event stream. A brute-force rule that does not constrain itself to one agent group correlates across clients and fires on traffic the tenant never saw. Scope each rule to its group and test it per tenant; a rule that cannot be scoped belongs on a dedicated manager.
2. **A mis-grouped agent is a cross-tenant leak, and it happens upstream of every ingest protection.** The `<group>` filter decides which tenant's URL an alert is posted to, so an agent in the wrong group produces alerts that are correctly signed, correctly tenanted by URL, and attributed to the wrong client. The console cannot catch this at ingest. It can catch it on agent sync (M7): agent IDs are unique within a manager, so the same `agent_id` appearing under two tenants that share a `base_url` is a misgrouping. Flag it on the overview and refuse to silently accept it.

### Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic | Async throughout matters on an ingest path |
| Database | PostgreSQL 16 | `jsonb` for raw alerts, GIN for `related.*`, native partitioning for retention |
| Queue | Redis 7 Streams | Consumer groups give at-least-once delivery with acks |
| Worker | arq | Async-native, far less operational surface than Celery |
| Frontend | React 18, TypeScript, Vite, Tailwind, TanStack Query, React Router, Zustand | Fast to build, no SSR needed for an authenticated tool |
| Live updates | Server-sent events | Survives Traefik without websocket config |
| Auth | Local JWT, argon2id | No external IdP dependency in v1 |

---

## 3. Trust boundary

Two flows cross it, in opposite directions, per tenant.

### Inbound: alerts

Each tenant's manager POSTs to `https://<console-host>/api/v1/ingest/wazuh/{tenant_slug}`. Public by necessity.

Protection, all four required:

1. **Tenant slug in the path.** Never infer tenancy from the payload.
2. **HMAC-SHA256 signature.** Header `X-AWD-Signature: sha256=<hex>` over the raw body, keyed with that tenant's `ingest_secret`. Signed payload is `f"{timestamp}.{body}"`. Compare with `hmac.compare_digest`.
3. **Replay window.** Header `X-AWD-Timestamp` (unix seconds). Reject skew over 300 seconds.
4. **Per-tenant source IP allowlist.** Stored in `tenants.ingest_cidrs`, not in env — each client's manager has a different egress address.

**Uniform failure.** An unknown slug, a bad signature, and a disallowed IP must all return `401` after the same amount of work — perform a dummy HMAC computation on the unknown-tenant path so response timing does not enumerate tenants.

The handler validates, `XADD`s to Redis, and returns `202`. Target under 10 ms. No database write on the request path beyond the cached tenant lookup — if Postgres is degraded, ingestion must keep buffering.

Rate limit per tenant at the ingest endpoint. One client's alert storm must not starve another's.

### Outbound: Manager API

**Decided:** the Coolify host has a static egress IP. Each client exposes their Wazuh Manager API (`:55000`) through their own reverse proxy on a dedicated hostname, restricted by source IP to that egress address. No WireGuard sidecar, no VPN client in the container.

Per tenant, AWDTECH gets a dedicated Wazuh API user with read-only RBAC (`agent:read`, `rules:read`, `manager:read`). Never reuse `wazuh-wui`.

Connection details live in `wazuh_connections`, one row per tenant. **Passwords are encrypted at rest** with AES-256-GCM using a key from `ENCRYPTION_KEY` (32 bytes, base64). Store `nonce || ciphertext || tag` plus a `key_version` column so rotation is possible without a migration. Decrypt only inside the Manager API client, never in a serialiser, and never return the field from any endpoint.

**Degradation:** every Manager API call is cached and every consumer tolerates staleness. If a client's manager is unreachable, their agent pages show cached data with an explicit "last synced" timestamp, and the tenant is flagged as degraded on the overview. Alert ingestion is unaffected — it does not touch the Manager API.

---

## 4. Data model

Every table holding customer data carries `tenant_id` and every query filters on it. This is enforced by a SQLAlchemy session-level filter plus a test that runs against the whole route table, not by discipline.

```sql
create extension if not exists "pgcrypto";
create extension if not exists "citext";

create table tenants (
  id            uuid primary key default gen_random_uuid(),
  slug          text not null unique,          -- appears in the ingest URL
  name          text not null,
  status        text not null default 'active'
                  check (status in ('active','suspended','offboarding')),
  ingest_secret text not null,                 -- HMAC key, rotatable
  ingest_cidrs  cidr[] not null default '{}',
  alert_floor   smallint not null default 7,   -- min rule.level accepted
  grouping_window_minutes integer not null default 30,
  created_at    timestamptz not null default now()
);

create table wazuh_connections (
  tenant_id       uuid primary key references tenants(id) on delete cascade,
  base_url        text not null,               -- https://wazuh-a.client.co.za
  username        text not null,
  password_enc    bytea not null,              -- AES-256-GCM
  key_version     integer not null default 1,
  verify_ssl      boolean not null default true,
  agent_group     text,                        -- set only on a shared manager
  last_sync_at    timestamptz,
  last_sync_error text
);

-- AWDTECH staff have tenant_id NULL and is_staff true.
-- Client users have a fixed tenant_id and is_staff false.
create table users (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid references tenants(id) on delete cascade,
  is_staff      boolean not null default false,
  email         citext not null unique,
  password_hash text not null,
  full_name     text not null,
  role          text not null check (role in
                  ('platform_admin','soc_analyst','client_admin','client_viewer')),
  is_active     boolean not null default true,
  last_login_at timestamptz,
  created_at    timestamptz not null default now(),
  check ((is_staff and tenant_id is null) or (not is_staff and tenant_id is not null))
);

-- Optional narrowing: which tenants a staff member may see.
-- Empty set for a user means all tenants.
create table staff_tenant_access (
  user_id   uuid not null references users(id) on delete cascade,
  tenant_id uuid not null references tenants(id) on delete cascade,
  primary key (user_id, tenant_id)
);

-- Cached projection of each tenant's Manager API. Never authoritative.
create table agents (
  tenant_id      uuid not null references tenants(id) on delete cascade,
  agent_id       text not null,
  name           text not null,
  ip             inet,
  os_platform    text,
  os_name        text,
  version        text,
  status         text,
  groups         text[] not null default '{}',
  last_keepalive timestamptz,
  synced_at      timestamptz not null default now(),
  primary key (tenant_id, agent_id)
);
```

### Alerts — partitioned for a 90-day life

**Decided:** 90-day retention on raw alerts. That makes native monthly partitioning mandatory, not optional — deleting tens of millions of rows with `DELETE` will not hold up.

Partitioning changes two things you cannot work around: every unique constraint must include the partition key, and the primary key becomes composite.

```sql
create table alerts (
  id            uuid not null default gen_random_uuid(),
  tenant_id     uuid not null,
  wazuh_id      text not null,               -- alert.id, e.g. 1724668800.123456
  timestamp     timestamptz not null,        -- alert time, not receipt time
  received_at   timestamptz not null default now(),

  rule_id       integer not null,
  rule_level    smallint not null,
  rule_desc     text not null,
  rule_groups   text[] not null default '{}',
  mitre_ids     text[] not null default '{}',
  mitre_tactics text[] not null default '{}',

  agent_id      text,
  agent_name    text,

  ecs           jsonb not null,              -- normalised document
  raw           jsonb not null,              -- verbatim Wazuh alert
  map_version   integer not null,

  related_ip    inet[] not null default '{}',
  related_user  text[] not null default '{}',
  related_host  text[] not null default '{}',
  related_hash  text[] not null default '{}',

  fingerprint   text not null,
  incident_id   uuid,                        -- no FK: see note below

  primary key (id, timestamp),
  unique (tenant_id, wazuh_id, timestamp)
) partition by range (timestamp);

create index on alerts (tenant_id, timestamp desc);
create index on alerts (tenant_id, incident_id);
create index on alerts (tenant_id, rule_id, timestamp desc);
create index on alerts (tenant_id, fingerprint, timestamp desc);
create index on alerts using gin (related_ip);
create index on alerts using gin (related_user);
create index on alerts using gin (related_host);
create index on alerts using gin (related_hash);
create index on alerts using gin (ecs jsonb_path_ops);
```

`incident_id` carries **no foreign key**. Incidents outlive alerts by design; a real FK would either block partition drops or cascade damage into closed cases. Referential integrity here is the application's job, and orphaned `incident_id` values on dropped partitions are expected, not a bug.

Use `pg_partman` with `premake = 3` and `retention = '90 days'`, `retention_keep_table = false`. Run its maintenance from the worker on a daily schedule, not from cron on the host — Coolify hosts get rebuilt.

### Incidents

```sql
create table incidents (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  number        bigint not null,             -- per-tenant sequential, user-facing
  title         text not null,
  status        text not null default 'new'
                  check (status in ('new','active','pending','resolved','false_positive')),
  severity      smallint not null,           -- max rule_level across members
  classification text,
  assignee_id   uuid references users(id) on delete set null,

  fingerprint   text not null,
  first_seen    timestamptz not null,
  last_seen     timestamptz not null,

  -- SLA. Deadlines are absolute timestamps that get pushed forward each time
  -- the clock is paused, so they stay indexable and the queue can simply order
  -- by them. A closed case keeps the clock it was actually judged under.
  sla_respond_by     timestamptz,
  sla_resolve_by     timestamptz,
  sla_paused_at      timestamptz,          -- non-null while the clock is stopped
  sla_paused_seconds integer not null default 0,
  first_response_at  timestamptz,

  alert_count   integer not null default 0,
  rule_summary  jsonb not null default '{}', -- {rule_id: count}
  evidence      jsonb not null default '{}', -- see below
  related_incident_id uuid references incidents(id) on delete set null,

  closed_at     timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (tenant_id, number)
);

create index on incidents (tenant_id, status, last_seen desc);
create index on incidents (status, last_seen desc);   -- cross-tenant staff queue
create index on incidents (tenant_id, assignee_id, status);
create unique index on incidents (tenant_id, fingerprint)
  where status in ('new','active','pending');
-- Drives the breach-imminent queue ordering, cross-tenant. A paused incident is
-- not ticking and must not appear in it.
create index on incidents (sla_respond_by)
  where first_response_at is null and sla_paused_at is null
    and status in ('new','active','pending');
create index on incidents (sla_resolve_by)
  where sla_paused_at is null and status in ('new','active','pending');

-- Contractual response times, per tenant, by severity band. The row with the
-- highest severity_min not exceeding the incident's severity wins.
create table tenant_slas (
  tenant_id       uuid not null references tenants(id) on delete cascade,
  severity_min    smallint not null,     -- 0-15, on the Wazuh rule level ramp
  respond_minutes integer not null,
  resolve_minutes integer not null,
  primary key (tenant_id, severity_min)
);
```

**The SLA clock.** Five rules, because the ambiguous cases are where this gets argued with a client later:

- **It starts at `first_seen`**, not at incident creation. The client's exposure began when the alert fired, and on a busy manager those differ.
- **`first_response_at` is stamped once**, by whichever comes first: a status change out of `new`, an assignment, or a comment. Opening a case is not a response; doing something to it is.
- **The clock stops in `pending`.** **Decided:** `pending` means *awaiting client feedback*, and contractual time does not run while AWDTECH is blocked on the client. Rather than accumulate elapsed time, push the deadlines forward — on entering `pending` set `sla_paused_at = now()`; on leaving it, add `now() - sla_paused_at` to both `sla_respond_by` and `sla_resolve_by`, add the same delta to `sla_paused_seconds`, and null `sla_paused_at`. The deadlines stay absolute timestamps, so the queue still orders by a single indexed column and the countdown is still a subtraction.
- **Rising severity re-tightens the clock, but only until it is answered.** Severity is the max rule level across members, so an incident can escalate as alerts attach. On any severity increase while `first_response_at` is null, recompute `sla_respond_by = first_seen + new_target + sla_paused_seconds` — the accumulator is what keeps a re-tightened deadline from silently clawing back time the client already held. Once `first_response_at` is set, both deadlines freeze.
- **Every pause is auditable, because every pause is billable.** A paused clock cannot breach, so parking a case in `pending` is the one status change with money attached to it. Write both transitions to `audit_log`, show total held time on the case view (`sla_paused_seconds`), and expect to be asked to justify it. Do not let an incident enter `pending` without a client-visible comment — if nobody asked the client anything, the console is not waiting on them.

Breach is derived, never stored. While the clock runs, an incident is in response breach when `sla_respond_by` has passed with `first_response_at` still null, and in resolution breach when `sla_resolve_by` has passed while open. While paused, both deadlines and `sla_paused_at` are frozen, so the test is `sla_paused_at > sla_respond_by` — it had already breached before the pause, and a pause cannot un-breach it. For a closed case, compare `first_response_at` and `closed_at` against the deadlines as they stood. Storing a breach flag means a worker sweep that can lag, and a lagging breach flag is worse than none. A tenant with no `tenant_slas` rows has no SLA: the deadline columns stay null and the queue shows no countdown.

One consequence to watch: narrowing `pending` to *awaiting client* leaves no waiting state whose clock keeps running. If analysts need to park a case on a vendor, a maintenance window, or an internal dependency, that is a **new status** rather than a reuse of `pending` — and it is a check-constraint migration, so decide it before M5 rather than discovering it in triage.

**`evidence` is what makes 90-day retention survivable.** When an alert attaches to an incident, write a trimmed snapshot into `evidence`: the first alert's normalised ECS, the most recent one, and the entity set. Member alerts vanish at 90 days; a resolved case from four months ago must still show what it was about. Cap the snapshot at 32 KB and never store the full `raw`.

```sql
create table entities (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  type        text not null check (type in ('ip','user','host','hash','process','file')),
  value       text not null,
  first_seen  timestamptz not null,
  last_seen   timestamptz not null,
  alert_count integer not null default 0,
  notes       text,
  unique (tenant_id, type, value)
);
create index on entities (tenant_id, type, last_seen desc);

create table incident_entities (
  incident_id uuid not null references incidents(id) on delete cascade,
  entity_id   uuid not null references entities(id) on delete cascade,
  role        text,                          -- 'source' | 'target' | 'observed'
  primary key (incident_id, entity_id)
);

create table incident_comments (
  id          uuid primary key default gen_random_uuid(),
  incident_id uuid not null references incidents(id) on delete cascade,
  user_id     uuid not null references users(id),
  body        text not null,
  visibility  text not null default 'internal'
                check (visibility in ('internal','client')),
  created_at  timestamptz not null default now()
);

create table audit_log (
  id          bigserial primary key,
  tenant_id   uuid references tenants(id) on delete cascade,
  user_id     uuid references users(id),
  action      text not null,                 -- 'incident.status_changed'
  target_type text not null,
  target_id   uuid,
  detail      jsonb not null default '{}',
  created_at  timestamptz not null default now()
);
create index on audit_log (tenant_id, created_at desc);
create index on audit_log (tenant_id, target_type, target_id);

-- Daily rollup, for billing later and for the overview now.
create table ingest_stats (
  tenant_id   uuid not null references tenants(id) on delete cascade,
  day         date not null,
  alert_count bigint not null default 0,
  bytes_in    bigint not null default 0,
  primary key (tenant_id, day)
);
```

`incident_comments.visibility` exists because clients can log in. An analyst's working notes and a client-facing update are different things and must not be the same field.

**Retention summary:** alerts 90 days (partition drop). Incidents, entities, comments — indefinite. `audit_log` 13 months. `ingest_stats` indefinite; it is tiny.

---

## 5. ECS normalisation

**Decided:** ECS, not OCSF. Platform-side — not in decoders, not in an OpenSearch ingest pipeline. Client Wazuh instances will be at different versions and will get upgraded without telling you; the console's schema must not be collateral.

### The mapping is data, not code

`app/normalisation/maps/v1.yaml`:

```yaml
version: 1
defaults:
  "@timestamp":        [timestamp]
  event.severity:      [rule.level]
  event.code:          [rule.id]
  host.name:           [agent.name]
  threat.technique.id: [rule.mitre.id]
  threat.tactic.name:  [rule.mitre.tactic]

  source.ip:
    - data.srcip
    - data.win.eventdata.ipAddress
    - data.aws.sourceIPAddress
    - data.office365.ClientIP
    - data.gcp.jsonPayload.sourceIP
  source.port:
    - data.srcport
    - data.win.eventdata.ipPort
  destination.ip:
    - data.dstip
    - data.win.eventdata.destinationIp
  user.name:
    - data.srcuser
    - data.dstuser
    - data.win.eventdata.targetUserName
    - data.win.eventdata.subjectUserName
    - data.office365.UserId
  process.name:
    - data.win.eventdata.image
    - data.audit.exe
  process.parent.name:
    - data.win.eventdata.parentImage
  process.command_line:
    - data.win.eventdata.commandLine
  file.path:
    - syscheck.path
    - data.win.eventdata.targetFilename
  file.hash.sha256:
    - syscheck.sha256_after
  file.hash.md5:
    - syscheck.md5_after

# Overrides selected by rule.groups membership, merged over defaults.
overrides:
  - match_groups: [office365]
    fields:
      event.provider: [data.office365.Workload]
      user.name:      [data.office365.UserId]
  - match_groups: [fortigate]
    fields:
      network.protocol: [data.proto]
  - match_groups: [syscheck]
    fields:
      event.category: { const: file }
```

First non-null path per field wins. Overrides merge over defaults, matched by `rule.groups` intersection. Adding FortiGate or a new O365 subscription is a YAML edit, not a code change.

**Decided: the normalised document is stored with flat dotted keys** (`{"source.ip": "41.1.2.3"}`), not nested objects. It keeps a containment query a single GIN lookup on `ecs jsonb_path_ops`, and it keeps the map file and the stored document readable as the same shape — what you write in the YAML is literally what you see in the inspector. The `related.*` arrays are separate columns regardless, so nothing about entity pivoting depends on this choice.

Two sentinel values on `map_version` distinguish states that otherwise look alike in a query: **`0` means not normalised yet**, **`-1` means normalisation was attempted and threw**. Conflating them would leave the reprocess endpoint unable to tell a backlog from a bug.

The map is global, not per-tenant. Onboarding a client with an unusual decoder means extending the shared map, which benefits every tenant. Resist per-tenant maps — they fragment the entity model and make the pivot useless.

### `related.*` is the point

After extraction, walk the normalised document and collect every value of each type into the flat arrays, regardless of role:

- `related_ip` — every IP anywhere in the document, including a regex sweep over `full_log` for rule groups known to embed them
- `related_user` — every username; lowercase for matching, store as observed
- `related_host` — `agent.name`, `host.name`, any hostname field
- `related_hash` — all hash values

Type is inferred from value shape for addresses and hashes, and from field name for usernames and hostnames — a username is not knowable by looking at it. Loopback, unspecified and reserved addresses are dropped: an entity page for `127.0.0.1` is noise in every tenant. Private ranges are kept, because `10.x` is exactly what an analyst pivots on during lateral movement. The `full_log` regex sweep is driven by an allowlist of rule groups in the map rather than run over every alert, which would be both expensive and noisy.

One query on `related_ip @> ARRAY['41.x.x.x'::inet]` returns every alert touching that address whether it was source, destination, or buried in a log line. That array is the entire basis of the entity pages. Without it you have an alert list; with it you have a pivotable graph.

### Versioning and replay

`map_version` is stored on every row. When the mapping changes, bump it and use `POST /api/v1/admin/reprocess` to re-run normalisation from the `raw` column across a time range for one tenant or all. Never mutate `raw`. Note the ceiling: replay only reaches back 90 days.

### Failure mode

Normalisation must never drop an alert. If extraction throws, log it, write the row with `ecs = {}` and `map_version = -1`, and continue. A malformed decoder on one client must not stop the pipeline for every client. Surface the count of `map_version = -1` rows per tenant on the overview.

---

## 6. Incident grouping

Real-time only means grouping happens on arrival, in the worker, one alert at a time. No batch pass.

### Fingerprint

```
fingerprint = sha256(f"{tenant_id}|{rule_id}|{agent_id}|{primary_entity}")
```

`primary_entity` resolves by first match: `source.ip` → `user.name` → `host.name` → `""`. Deliberately coarse. Coarse grouping produces fewer, fatter incidents, which is the right failure mode for an MSSP — an analyst covering six clients would rather open one incident with forty alerts than forty incidents.

`tenant_id` is inside the hash, so two clients can never share an incident.

### Attach or create

```
on alert:
  open = SELECT incidents
         WHERE tenant_id = ? AND fingerprint = ?
           AND status IN ('new','active','pending')

  if open and (alert.timestamp - open.last_seen) <= tenant.grouping_window:
      attach; last_seen = max(...); alert_count += 1
      severity = max(severity, alert.rule_level)
      rule_summary[rule_id] += 1
      update evidence snapshot
      upsert entities, link to incident
  else:
      create incident (number = nextval per tenant, status 'new')
      if a resolved incident with this fingerprint exists in the last 7 days:
          set related_incident_id
```

The partial unique index on `(tenant_id, fingerprint) where status in (...)` makes "one open incident per fingerprint" a database invariant rather than an application hope. Handle the conflict by retrying the attach path.

**Reopening is never automatic.** An alert after resolution creates a new incident linked to the old one, so the analyst sees "this recurred" rather than a closed case silently springing back open.

### Alert floor

`tenants.alert_floor` defaults to 7, and the same value is set in that client's `<integration>` block so the traffic never leaves their manager. The database column exists so the console can display and validate it — enforcement is at the source.

---

## 7. API surface

All routes under `/api/v1`. JWT bearer except ingest and auth.

**Tenant scoping is derived from the token, never from a request body.** A client user's token carries a fixed `tenant_id`. A staff token carries `is_staff: true` plus an `active_tenant` that is either a UUID or `null` meaning all-tenants. Switching tenants issues a new token; there is no `?tenant_id=` parameter anywhere.

```
POST   /ingest/wazuh/{tenant_slug}       HMAC-authenticated, returns 202

POST   /auth/login                       → access + refresh
POST   /auth/refresh
POST   /auth/logout
GET    /auth/me                          includes accessible tenants for staff
POST   /auth/switch-tenant               staff only; body {tenant_id | null}

GET    /incidents                        filters: status, severity_min, assignee,
                                         entity_type + entity_value, from, to, q.
                                         Staff with active_tenant=null get all
                                         accessible tenants, each row carrying
                                         tenant name and slug.
GET    /incidents/{id}
PATCH  /incidents/{id}                   status, severity, assignee, title, classification
GET    /incidents/{id}/alerts            paginated, newest first
GET    /incidents/{id}/timeline          alerts + comments + audit, merged
POST   /incidents/{id}/comments          visibility: internal | client
GET    /incidents/stream                 SSE, scoped to the token

GET    /alerts                           filters mirror /incidents, plus rule_id
GET    /alerts/{id}                      normalised ecs + raw

GET    /entities                         filters: type, q, last_seen_after
GET    /entities/{type}/{value}
GET    /entities/{type}/{value}/alerts   the related.* pivot
GET    /entities/{type}/{value}/incidents
PATCH  /entities/{type}/{value}          notes only

GET    /agents                           from cache, includes synced_at
GET    /agents/{agent_id}
GET    /agents/{agent_id}/alerts
POST   /agents/sync                      staff only

GET    /rules/{rule_id}                  read-through to the tenant's manager, cached 1h
GET    /coverage/mitre
GET    /overview                         per-tenant, or a fleet view for staff

GET    /tenants                          platform_admin only
POST   /tenants                          creates tenant + ingest secret + connection
PATCH  /tenants/{id}
POST   /tenants/{id}/rotate-secret       returns the new secret once, never again
POST   /tenants/{id}/test-connection     validates Manager API reachability
GET    /tenants/{id}/sla                 severity bands and response targets
PUT    /tenants/{id}/sla                 platform_admin; replaces the whole policy

GET    /audit                            platform_admin, or client_admin for own tenant
POST   /admin/reprocess                  platform_admin; body {tenant_id?, from, to}
```

### Pagination

Cursor-based on `(timestamp, id)` throughout. Offset pagination on a table growing by thousands of rows an hour produces duplicate and skipped rows during paging. Do not use `LIMIT/OFFSET` on `alerts` or `incidents`.

### RBAC

| Role | Scope | Can |
|---|---|---|
| `platform_admin` | AWDTECH | Everything, including tenant management and `/admin/*` |
| `soc_analyst` | AWDTECH | Cross-tenant read, incident triage, comments, agent sync |
| `client_admin` | One tenant | Own tenant's incidents, comments, own users, own audit log |
| `client_viewer` | One tenant | Read-only, and never sees `visibility='internal'` comments |

Enforce with a FastAPI dependency, not with checks scattered through handlers.

---

## 8. Frontend

### Routes

```
/login
/                          overview (fleet view for staff, tenant view for clients)
/incidents                 queue — the default working surface
/incidents/:tenant/:number case view
/alerts
/alerts/:id                raw + normalised inspector
/entities
/entities/:type/:value
/agents
/agents/:id
/coverage
/settings/tenants          platform_admin
/settings/users
/settings/audit
```

### The cross-tenant queue is the product

Everything else is secondary. For a staff user it must support: an "All clients" mode alongside per-tenant, a visible tenant chip on every row, filter by status and severity without a page reload, keyboard navigation (`j`/`k` move, `Enter` open, `a` assign to self, `r` resolve), bulk selection, and a live count that does not reorder the list under the analyst's cursor. Where a tenant has an SLA, each row carries a countdown to the nearest deadline, and a paused clock reads as a quiet "Paused" chip rather than a frozen timer — a stopped countdown that looks like a running one is how an analyst misses a case that came back.

New incidents arriving over SSE go into a "3 new incidents" pill at the top that the analyst clicks to merge in. Never auto-insert into a list someone is reading.

For a client user the same component renders without the tenant chip and without the switcher. One queue, two audiences — do not build two.

### Visual direction

Dark-first. Analysts stare at this for eight-hour shifts, so the base is deep blue-grey ink rather than black; pure black with bright accents causes halation and is the most common mistake in SOC tooling.

```
--ink-900   #0D131E   page
--ink-800   #141C2A   surface
--ink-700   #1C2637   raised surface
--line      #26314A   hairline borders
--text      #E2E7F0
--text-dim  #8792A8
--accent    #E0A32E   interactive, focus rings, active nav
```

**Signature element — severity is the Wazuh rule level, not a three-tier badge.** Every incident and alert carries a numeric chip showing `0`–`15` on a continuous ramp, because that number is what the ruleset asserts and analysts already reason in it. Collapsing 15 levels to low/medium/high discards information the engine gave you free.

```
 0–6   --text-dim on --ink-700
 7–9   #E0A32E on rgba(224,163,46,.12)
10–12  #E8743B on rgba(232,116,59,.12)
13–15  #E0435F on rgba(224,67,95,.14)
```

Tenant identity gets a second, quieter channel: a 3px left border on queue rows in a per-tenant hue assigned at onboarding, plus the tenant chip. Colour alone never carries it — the chip is always present.

Type: `Geist` for UI, `JetBrains Mono` for all alert data — timestamps, IPs, hashes, rule IDs, raw JSON. Machine output should look like machine output; mono makes hashes and addresses scannable by column.

Restraint everywhere else. No gradients, no glassmorphism, no animated backgrounds. Transitions on hover and focus only, 120 ms. Respect `prefers-reduced-motion`.

### Copy

Name things by what the analyst controls. "Assign to me", not "Set assignee". "Resolve", not "Update status". The button that says "Resolve" produces a toast that says "Resolved". Client-visible comments are labelled "Share with client", not "visibility: client". Empty states point at the next action: an empty queue reads "No open incidents. Alerts below level 7 aren't ingested — change the threshold in this client's integration settings if you're expecting more." Errors say what broke and what to do, and do not apologise.

---

## 9. Deployment on Coolify

One Coolify project, five resources.

| Resource | Type | Notes |
|---|---|---|
| `postgres` | Coolify managed PostgreSQL 16 | Daily backups; `pg_partman` installed |
| `redis` | Coolify managed Redis 7 | `appendonly yes` |
| `api` | Dockerfile from `/backend` | Domain, path `/api` |
| `worker` | Same image, command override | No domain, no exposed port |
| `web` | Dockerfile from `/frontend` | Same domain, path `/` |

Traefik terminates TLS via Let's Encrypt. Route `/api` to `api:8000`, everything else to `web:80`. Same origin means no CORS and cookies just work.

**Coolify's managed Postgres image may not ship `pg_partman`.** Verify before M1. If it doesn't, run Postgres as a custom Dockerfile resource built from `postgres:16` with the extension added, or fall back to a worker task that creates and drops partitions with plain DDL — the logic is thirty lines and one less dependency.

### Environment

```
# api + worker
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
JWT_SECRET=
JWT_ACCESS_TTL=900
JWT_REFRESH_TTL=1209600
ENCRYPTION_KEY=                 # 32 bytes base64, for Wazuh credentials
ENCRYPTION_KEY_VERSION=1

INGEST_MAX_SKEW_SECONDS=300
INGEST_RATE_LIMIT_PER_TENANT=500/second
ALERT_RETENTION_DAYS=90
NORMALISATION_MAP_VERSION=1
WAZUH_SYNC_INTERVAL=300

# web (build-time)
VITE_API_BASE=/api/v1
```

Per-tenant values — ingest secrets, CIDRs, Wazuh credentials, alert floor, grouping window — live in the database. Onboarding a client must never require a redeploy.

### Health checks

- `api`: `GET /healthz` checks Postgres and Redis, returns 200 or 503. Coolify uses this for zero-downtime deploys.
- `worker`: heartbeat key in Redis with a 60 s TTL; `/healthz` reports worker liveness as a field but does not fail on it.
- `GET /readyz` additionally reports per-tenant Manager API reachability, for monitoring only. **Never gate deploys on a client's network being up.**

### Migrations

Alembic runs as a Coolify pre-deploy command on `api` only. The `worker` must not run migrations — two containers racing `alembic upgrade head` will deadlock.

---

## 10. Wazuh-side configuration

Per tenant. Nothing here changes detection behaviour; it only adds an outbound push.

`/var/ossec/etc/ossec.conf` on that client's manager:

```xml
<integration>
  <name>custom-awd-console</name>
  <hook_url>https://console.awdtech.co.za/api/v1/ingest/wazuh/acme-corp</hook_url>
  <api_key>THE_TENANT_INGEST_SECRET</api_key>
  <level>7</level>
  <alert_format>json</alert_format>
</integration>
```

On a **shared** manager, add one block per tenant, each with a `<group>` filter matching that client's agent group and its own slug in the URL:

```xml
<integration>
  <name>custom-awd-console</name>
  <hook_url>https://console.awdtech.co.za/api/v1/ingest/wazuh/beta-ltd</hook_url>
  <api_key>BETA_TENANT_SECRET</api_key>
  <group>beta-ltd</group>
  <level>7</level>
  <alert_format>json</alert_format>
</integration>
```

`/var/ossec/integrations/custom-awd-console` — owned `root:wazuh`, mode `750`. The integrator invokes it with `argv[1]` = path to the alert JSON file, `argv[2]` = api_key, `argv[3]` = hook_url. The script must:

1. Read and parse the alert file
2. `payload = json.dumps(alert, separators=(',',':'))`
3. `ts = str(int(time.time()))`
4. `sig = hmac.new(key, f"{ts}.{payload}".encode(), sha256).hexdigest()`
5. POST with `X-AWD-Timestamp: {ts}`, `X-AWD-Signature: sha256={sig}`, `Content-Type: application/json`
6. Timeout at 5 seconds, retry twice with backoff, then give up silently

**Never let the script block or raise.** The integrator forks a process per alert; a hung script becomes a fork bomb on a client's manager. Wrap everything in a top-level try/except that exits 0.

Ship it at `deploy/wazuh/custom-awd-console` with an installer that takes the slug and secret as arguments, so onboarding is one command run on the client's manager.

### Known limit

Fork-per-alert caps sustained throughput in the low hundreds of alerts per second per manager, and the level 7 floor keeps normal operation well under it. **On a shared manager that ceiling is shared too.** The console's per-tenant ingest rate limit protects the console, not the manager: one client's storm forks against the same process table as everyone else's alerts, and the tenants sharing that manager slow down together. This is the cost of the shared default, and it is the signal to move a noisy client onto a dedicated manager. If a storm exceeds it, that manager slows — a detection-engine problem, not a console problem. The v2 answer is a sidecar that tails `alerts.json` and batches. Do not build it pre-emptively, but **make the ingest endpoint accept either a single alert object or an array from day one** so the sidecar can arrive without an API change.

---

## 11. Repository layout

```
├── DESIGN.md
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── crypto.py            AES-GCM envelope for tenant credentials
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── api/v1/              incidents.py, alerts.py, entities.py,
│   │   │                        agents.py, ingest.py, auth.py,
│   │   │                        tenants.py, admin.py
│   │   ├── deps/                auth.py, tenancy.py, rbac.py
│   │   ├── normalisation/
│   │   │   ├── engine.py
│   │   │   ├── related.py
│   │   │   └── maps/v1.yaml
│   │   ├── incidents/           grouping.py, entities.py, evidence.py
│   │   ├── wazuh/               manager_client.py, cache.py, sync.py
│   │   └── workers/             consumer.py, tasks.py, partitions.py
│   ├── alembic/
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── routes/
│   │   ├── components/
│   │   ├── api/
│   │   ├── hooks/
│   │   └── styles/tokens.css
│   ├── Dockerfile
│   └── nginx.conf
└── deploy/
    ├── wazuh/custom-awd-console
    ├── wazuh/install.sh
    └── coolify/README.md
```

---

## 12. Build order

Each milestone ends somewhere demonstrable. Do not start the next until the current one runs.

**M1 — Skeleton.** FastAPI, Postgres with the full schema and partitioning, Alembic, JWT auth with all four roles, staff tenant switching, `/healthz`. React shell with login, protected routing, tenant switcher in the header. Deployed to Coolify over HTTPS.

**M2 — Tenant onboarding.** Tenant CRUD, secret generation and rotation, encrypted Wazuh credential storage, `test-connection`, per-tenant SLA policy. The installer script for the manager side, defaulting to the shared-manager runbook: create the agent group, add the tenant's `<integration>` block with its `<group>` filter, verify no existing agent moved groups. Success criterion: onboarding a client is a form plus one command on the shared manager.

**M3 — Ingest.** Per-tenant webhook with HMAC, timestamp, and CIDR enforcement, uniform failure timing, per-tenant rate limiting. Redis stream producer, worker consumer writing raw alerts with `ecs = {}`. Success criterion: a real alert from a real client manager lands in Postgres, correctly tenanted.

**M4 — Normalisation.** YAML map engine, `related.*` extraction, `map_version`, replay endpoint. Alert list and inspector showing raw and normalised side by side. Fixture corpus captured from live managers — Windows security, syscheck, O365, FortiGate at minimum.

**M5 — Incidents.** Fingerprinting, grouping, entity upsert, evidence snapshots, the cross-tenant queue, case view, comments with visibility, status transitions, audit log. SLA clock: deadlines on creation, `first_response_at` stamping, pause and resume across `pending`, recompute on escalation, breach derived in the queue query and surfaced as a countdown. This is where it becomes a product.

**M6 — Entities.** Entity index, entity page, pivots against the GIN indexes. Verify query plans on a partitioned table with at least a million rows before calling it done.

**M7 — Manager integration.** Per-tenant agent sync worker, agent pages, rule read-through, MITRE coverage, fleet overview with per-tenant health.

**M8 — Analyst polish.** SSE live updates, keyboard navigation, bulk actions, empty and error states, reduced-motion pass, mobile layout for the queue.

**v1.1 — Client access.** Client user provisioning, the client-facing queue, and the client view of comments. Deliberately after launch; the schema and roles already carry it.

---

## 13. Testing

- **Tenancy isolation is the highest-stakes test surface.** Seed three tenants, then loop over the route table asserting every list endpoint returns only the caller's rows, that a client token cannot reach another tenant's resource by ID, and that `client_viewer` never receives an internal comment. Generate it from the routes so a new endpoint cannot be added without being covered.
- **Normalisation** is the highest-value one. Keep a fixture corpus of real alert JSON, one file per decoder family, asserting ECS output field by field. Every mapping bug found in production becomes a fixture.
- **Grouping** needs property tests: N alerts with the same fingerprint inside the window produce exactly one incident with `alert_count == N`. Include concurrent arrival — the partial unique index will fire.
- **Ingest auth** needs negative tests: unknown slug, wrong signature, stale timestamp, replayed body, disallowed IP. All return 401 without touching Redis, in comparable time.
- **Partition lifecycle** needs a test that creates a partition, ages it past 90 days, runs maintenance, and asserts the partition is gone and the parent still queries cleanly.
- **Credential encryption** needs a round-trip test plus an assertion that `password_enc` never appears in any serialised API response.

---

## 14. Open decisions

All four are now resolved. Do not re-litigate.

**Resolved earlier:** standalone product (not part of any existing platform); static egress IP available, so IP allowlisting with no VPN sidecar; AWDTECH MSSP, multi-tenant, public-facing; 90-day alert retention.

**Resolved 2026-08-27:**

1. **Per-client topology — shared manager with agent groups, as the default.** One AWDTECH-run manager per cohort, one `<integration>` block per tenant filtered by that client's agent group. Chosen on cost: a Wazuh indexer per client is the largest infrastructure line. Dedicated managers remain fully supported for clients who own their Wazuh, carry compliance requirements, or grow noisy enough to threaten the shared fork-per-alert ceiling. See §2 for the two obligations this creates — group-scoped aggregation rules, and agent-group validation on sync — and §10 for the shared throughput ceiling.
2. **Client login — staff-only at launch.** Clients get reports; AWDTECH analysts use the console. The roles, `staff_tenant_access`, and comment visibility stay in the schema and are already built, so client access is additive work in v1.1. This removes nothing from M1.
3. **Incident SLA — full, from M5, and the clock stops while awaiting client feedback.** Per-tenant contractual response and resolution targets by severity band in `tenant_slas`; deadlines stored on the incident as absolute timestamps and pushed forward on resume; `sla_paused_seconds` accumulated for reporting; breach derived, never stored; countdown in the queue. `pending` now means specifically *awaiting client feedback* — see §4 for the five clock rules, and for the one loose end this creates: there is no longer a waiting state whose clock keeps running, and adding one is a check-constraint migration best done before M5.
4. **Console hostname — one shared domain for all clients.** Per-tenant subdomains buy nothing here: tenancy is carried in the token, so a subdomain adds wildcard TLS and per-tenant cookie scoping without adding isolation.
