# AWDTECH SOC Console



A multi-tenant SOC console with Wazuh as the detection engine, operated by

AWDTECH as a managed service. [DESIGN.md](DESIGN.md) is the build spec; this file

is how to run what exists.



**Status: M2 (Tenant onboarding).** Schema, auth, app shell, tenant CRUD with

encrypted Wazuh credentials, SLA policy, and the manager-side installer. No ingest yet —

that is M3.



## Local development



```bash

docker compose -f docker-compose.dev.yml up -d      # postgres + redis



cd backend

python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"

cp .env.example .env                                 # then fill in the secrets

.venv/Scripts/python -m app.cli generate-key         # ENCRYPTION_KEY

.venv/Scripts/alembic upgrade head

.venv/Scripts/python -m app.cli create-user --email you@awdtech.co.za \

  --name "Your Name" --role platform_admin

.venv/Scripts/uvicorn app.main:app --reload



# separate shell

.venv/Scripts/arq app.workers.consumer.WorkerSettings



cd ../frontend

npm install && npm run dev                           # proxies /api to :8000

```



On Linux or macOS the paths are `.venv/bin/...`.



## Tests



```bash

cd backend && .venv/Scripts/python -m pytest && .venv/Scripts/python -m ruff check app tests

cd frontend && npm run build          # tsc -b is the type check

```



## Layout



| Path | What |

|---|---|

| `backend/app/models/` | Schema, mirroring the DDL in the initial migration |

| `backend/app/security.py` | Password hashing and JWT minting; tenancy claims |

| `backend/app/deps/` | `auth`, `rbac`, `tenancy` â€” enforcement lives here, not in handlers |

| `backend/app/workers/` | arq worker: heartbeat, partition maintenance |

| `backend/alembic/versions/0001_initial_schema.py` | Full schema as explicit DDL |

| `frontend/src/` | React shell, auth store, tenant switcher |

| `deploy/wazuh/` | The integrator and its installer, run on a client's manager |

| `deploy/coolify/` | Production deployment |



## Two invariants worth knowing before you touch anything



**Tenancy comes from the token and nowhere else.** A client user's token carries

a fixed `tenant_id`; a staff token carries `is_staff` plus an `active_tenant`

that is a UUID or null meaning all-clients. Switching clients reissues the token.

No endpoint takes a tenant parameter, and `tests/test_app.py` fails the build if

one appears.



**The console never writes to Wazuh and never queries an indexer.** Alerts arrive

by push. Agent and rule data is pulled from each tenant's Manager API and cached,

and every consumer of it tolerates staleness.

