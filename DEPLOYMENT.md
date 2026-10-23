# Private deployment preparation

Status: private containers, HTTPS, authentication, PostgreSQL recovery, restart
persistence and the live five-stage Gemini workflow have been verified locally.
The initial credential rejection was resolved by recreating only the backend
after the production env file had been corrected externally. No credential file
or provider integration was changed by the agent. Development data was untouched.
Labeled QA records remain in production. Browser HTTPS access and authentication
have been confirmed by the operator; the remaining UI checklist is manual.

## Source audit

- Branch: `stabilize/mvp-production`. `docker-compose.yml` is development-only:
  PostgreSQL 16, database/user/password `agentflow`, host port 5432, persistent
  `agentflow-postgres` volume, and `pg_isready` health check. It is unchanged.
- Backend local start: from `backend`, `uvicorn app.main:app --reload --port 8000`.
  Alembic migrations are separate (`alembic upgrade head`). No automatic schema
  creation is performed by app startup. Python here is 3.12.10.
- Frontend local start: from `frontend`, `npm.cmd run dev`; conventional production
  start is `npm.cmd run build` then `npm.cmd start`. Container output uses Next's
  standalone `node server.js`. Installed Next version here is 16.4.2.
- `backend/app/config.py` reads root `.env` through Pydantic Settings. Environment
  variables take precedence. `frontend/src/app/api.ts` uses the build-time
  `NEXT_PUBLIC_API_BASE_URL`, defaulting to `http://localhost:8000`.
- Every `/api/` path except `/api/health` and `/api/ready` requires the shared
  bearer token via middleware, including task deletion, saved agents, custom
  workflows, their execution, and execution history. Token comparison is constant
  time. A missing server token fails closed with 503.
- Original execute/collaborate/stream routes and custom agent/workflow execution
  routes share a bounded, in-process per-client rate limiter. The default is
  10 execution requests per minute. CRUD and failed authentication are not rate
  limited. One process/one backend replica is required for these semantics.
- CORS allows configured origins, Authorization and Content-Type, no cookies.
  Development defaults are localhost/127.0.0.1 on port 3000. Origin validation
  now rejects wildcards, credentials, paths, and malformed ports; production also
  requires HTTPS and at least one origin. Legacy `FRONTEND_ORIGIN` is supported
  in source but deliberately cleared by the production Compose file.
- Public liveness: `GET /api/health`; public readiness: `GET /api/ready` runs a
  database `SELECT 1`. Readiness does not verify migration head, provider access,
  token validity, quotas, or a successful workflow.
- No Dockerfiles, HTTPS proxy, production Compose, or deployment runbook existed
  before this change. API docs were public; raw original-workflow errors could
  enter persisted stage records and SSE events. Production now disables docs,
  suppresses raw provider diagnostics, and uses safe stage failure messages.
- Installed `google-genai` is 2.31.0. The existing source fallback model differs
  from the working `.env.example` model. Source provider/model behavior is left
  intact; production explicitly fixes `gemini-3.5-flash-lite` and SDK 2.31.0.

## Stack and secrets

Use ONLY `compose.production.yml`, always with the explicit project and env file
shown below. Never merge with `docker-compose.yml`. The new project creates
`agentflow-private_postgres-data`; it does not reuse the development volume.
If that project name/volume already exists, inspect it before startup and choose
an unused project name consistently for all commands. Do not attach any existing
database volume for experimentation.

Only Caddy publishes a port: `127.0.0.1:8443` (HTTPS). PostgreSQL, FastAPI and
Next.js have no published ports. PostgreSQL has an internal network shared only
with the backend/tools. Caddy routes `/api/*` unchanged to FastAPI and everything
else to Next.js. Empty `NEXT_PUBLIC_API_BASE_URL` is baked into the container's
browser bundle for same-origin requests. The frontend gets no server secrets.

Backend and frontend run as non-root users. Backend has a read-only filesystem,
temporary `/tmp`, dropped capabilities and one Uvicorn worker. App images include
health checks; Caddy waits for both apps to be healthy. Backend readiness will
still pass before migrations, so the explicit migration step is mandatory.

Create `.env.production` only if absent; never overwrite `.env`:

```powershell
Set-Location C:\seamdigitech\LLM
if (Test-Path .env.production) { throw '.env.production already exists; edit it deliberately' }
Copy-Item .env.production.example .env.production
# PowerShell 5.1-compatible generation; keep the result private, never log it.
# Generate independently for each secret, or use a password manager's hex generator.
$secretBytes = New-Object byte[] 32
$secretGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $secretGenerator.GetBytes($secretBytes) } finally { $secretGenerator.Dispose() }
$generatedSecret = -join ($secretBytes | ForEach-Object { $_.ToString('x2') })
```

Edit `.env.production` in your editor, filling the two independent random values
and the existing Gemini API key. The database password MUST be hexadecimal for
the supplied interpolated SQLAlchemy URL; arbitrary passwords need proper URL
encoding and a separately configured URL. Keep file access restricted to the
operator account, encrypted at rest where available. Do not paste secrets in
command arguments, logs, screenshots, issue reports, or browser build variables.
Do not run `docker compose config` without `--quiet`: it prints interpolated
secrets. Container environment variables remain visible to Docker administrators;
this MVP does not provide a managed secret vault. The backend receives the
production env file at runtime, never at image build time. Build contexts exclude
local dotenv files, virtual environments, and build caches.

Compose requires token, Gemini key, database password, HTTPS origin, and TLS
hostname. Production settings also reject missing/short token and missing provider
key. Use actual secret values, not example placeholders. `POSTGRES_PASSWORD` only
initializes an empty volume; editing it later does not rotate an existing DB
role's password. Plan credential rotation separately, with a backup first.

| Variables | Purpose / production behavior |
| --- | --- |
| `POSTGRES_PASSWORD` | Independent random hex DB password; Compose constructs `DATABASE_URL` for internal host `postgres` |
| `API_ACCESS_TOKEN`, `GEMINI_API_KEY` | Required secrets; never `NEXT_PUBLIC_*` |
| `APP_ENV` | Forced `production`; docs/OpenAPI disabled and errors sanitized |
| `AI_PROVIDER`, `GEMINI_MODEL` | Forced `gemini`, `gemini-3.5-flash-lite` |
| `SITE_HOST`, `FRONTEND_ORIGINS` | TLS hostname without scheme/port; exact HTTPS browser origin including port |
| `NEXT_PUBLIC_API_BASE_URL` | Forced empty at image build for same origin; changing runtime env cannot change bundled JS |
| `GEMINI_SEARCH_GROUNDING_ENABLED` | Default false; preserves explicit opt-in |
| `RATE_LIMIT_PER_MINUTE`, `TASK_RETENTION_DAYS` | Default 10 / 0; retention 0 means no automatic expiry |
| `WORKFLOW_TIMEOUT_SECONDS`, `AGENT_TIMEOUT_SECONDS` | Defaults 600 / 90 |
| `ORCHESTRATOR_TIMEOUT_SECONDS`, `RESEARCH_TIMEOUT_SECONDS`, `ANALYSIS_TIMEOUT_SECONDS`, `REPORT_TIMEOUT_SECONDS`, `REVIEW_TIMEOUT_SECONDS` | Per-stage overrides; production example sets Research 90, Review 180 |
| `PROVIDER_RETRY_ATTEMPTS`, `PROVIDER_RETRY_BASE_DELAY_SECONDS`, `PROVIDER_RETRY_MAX_DELAY_SECONDS` | Production example uses 0 retries; remaining defaults 0.5 / 4 |
| `MAX_STAGE_OUTPUT_CHARS`, `MAX_STAGE_INPUT_CHARS`, `MAX_MODEL_CALLS_PER_WORKFLOW` | Defaults 12000 / 40000 / 5 |
| `CUSTOM_AGENT_TIMEOUT_SECONDS`, `CUSTOM_AGENT_MAX_INPUT_TOKENS` | Defaults 90 / 8000 |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_WEB_SEARCH_ENABLED` | Existing optional provider settings; not needed for this Gemini deployment |
| `INPUT_TOKEN_COST_PER_MILLION`, `CACHED_INPUT_TOKEN_COST_PER_MILLION`, `OUTPUT_TOKEN_COST_PER_MILLION` | Existing optional estimates; Gemini cost remains unavailable |

## Local container verification (operator runbook; results below)

Prerequisite: Docker Engine/Desktop with Linux containers and Docker Compose v2
supporting `up --wait`. Run from the repository root on the required branch:

```powershell
git branch --show-current
git status --short
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production config --quiet
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production build backend frontend
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production run --rm --no-deps proxy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
# Inspect existing volumes first. Do not attach, reset, or delete any existing data.
docker volume ls
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production up -d --wait postgres
```

If this database is not new, take and verify a backup BEFORE migrations (below).
For an existing running stack, use a maintenance window: stop app traffic and
the backend before taking the pre-upgrade backup and applying migrations. Keep
PostgreSQL running. Do not start the apps again until migration succeeds.
Migrations intentionally require an operator command; they are not a startup
side effect. Review schema changes first; never run an automatic downgrade on
existing data.

```powershell
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production run --rm migrate
if ($LASTEXITCODE -ne 0) { throw 'Migration failed; leave the apps stopped and investigate' }
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production up -d --wait backend frontend proxy
if ($LASTEXITCODE -ne 0) { throw 'Application startup or health checks failed' }
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production ps
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production run --rm migrate alembic current
```

For local verification leave `SITE_HOST=localhost` and
`FRONTEND_ORIGINS=https://localhost:8443`. Caddy issues certificates from its
private CA. Copy only its public root certificate, verify its fingerprint, and
trust it deliberately in the browser/OS of authorized clients:

```powershell
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production cp proxy:/data/caddy/pki/authorities/local/root.crt ./agentflow-local-root.crt
Get-FileHash ./agentflow-local-root.crt -Algorithm SHA256
# curl uses this CA explicitly, without changing the system trust store:
curl.exe --cacert ./agentflow-local-root.crt https://localhost:8443/api/health
curl.exe --cacert ./agentflow-local-root.crt https://localhost:8443/api/ready
curl.exe --cacert ./agentflow-local-root.crt -i https://localhost:8443/api/dashboard
curl.exe --cacert ./agentflow-local-root.crt -i https://localhost:8443/docs
```

Expect health/ready 200, dashboard 401 without a token, docs 404. In the browser,
verify TLS trust, enter the shared token, check dashboard and saved configurations,
run one approved low-cost original workflow and one custom workflow, confirm SSE
updates and history, and verify unauthorized requests fail. Restart only the
backend and confirm history survives. Do not delete real tasks to test deletion.
Exercise 429 behavior using mocked-provider tests first; do not generate paid
requests merely to reach the limit. Verify database port 5432 and app ports
8000/3000 are absent from this stack's host mappings.

Do not use `curl -k` or send the bearer token over HTTP. The Caddy data volume
contains private CA keys: restrict Docker access and protect backups of that
volume. A hostname change requires updating the exact CORS origin. For eventual
VPN/LAN access choose an authorized private interface binding and a private DNS
hostname, configure firewall rules, trust the private CA on those devices, and
test from an authorized client. No domain/hosting provider is assumed. For an
operator-supplied certificate replace `tls internal` with mounted certificate/key
paths; keep keys outside Git. No public listener is enabled by this configuration.

## Backup (read-only against the source DB)

Run from the root. Confirm the project and database before starting. The commands
below back up the new private stack; to back up development use its existing
Compose file/project deliberately. Never point a restore command at either
live database. Dumps include prompts, outputs, and saved configurations; store
encrypted copies off-host, restrict access, define retention, and test restores.

Use `pg_dump` inside PostgreSQL 16 over its local Unix socket. No password is
embedded in scripts or command lines. Do not weaken authentication on a real
database if local authentication has been customized; supply a protected
`PGPASSFILE` instead. Use a file and `docker compose cp`, not a PowerShell binary
pipeline/redirection, which can corrupt archives on older PowerShell versions.

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
$backupStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$backupName = "agentflow-$backupStamp.dump"
$backupPath = Join-Path (Resolve-Path backups) $backupName
if (Test-Path $backupPath) { throw 'Backup file already exists' }
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production exec -T postgres pg_dump -U agentflow -d agentflow --format=custom --no-owner --no-acl --file /tmp/$backupName
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed; do not use this backup' }
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production exec -T postgres pg_restore --list /tmp/$backupName
if ($LASTEXITCODE -ne 0) { throw 'Archive listing failed' }
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production cp "postgres:/tmp/$backupName" $backupPath
if ($LASTEXITCODE -ne 0) { throw 'Archive copy failed' }
Get-Item $backupPath | Select-Object Name, Length
Get-FileHash $backupPath -Algorithm SHA256
```

Save the checksum, UTC backup time, Git SHA (`git rev-parse HEAD`), PostgreSQL
version, and migration revision with the encrypted backup. `pg_dump` is a
consistent snapshot while writes continue; it excludes cluster roles and Caddy
CA keys. Archive listing alone does not prove restorability. Temporary archive
files remain in the container `/tmp`; remove only the specific archive manually
after secure off-host verification if desired. Monitor disk space.

## Restore verification in an isolated database

`deploy/compose.restore.yml` is a separate, networkless PostgreSQL server with
tmpfs data, no ports and no persistent volume. It has no access to either live
DB. Check sufficient RAM/disk for the restore. Use an unused project name below;
never substitute a live Compose file. Start a fresh drill; if this project already
exists, choose a new unique project name consistently rather than clearing it.

```powershell
# Set this to a chosen verified archive; compare its saved checksum first.
$restoreArchive = (Resolve-Path ./backups/agentflow-REPLACE-TIMESTAMP.dump).Path
Get-FileHash $restoreArchive -Algorithm SHA256
docker compose -p agentflow-restorecheck -f deploy/compose.restore.yml config --quiet
docker compose -p agentflow-restorecheck -f deploy/compose.restore.yml up -d --wait
docker compose -p agentflow-restorecheck -f deploy/compose.restore.yml cp $restoreArchive restorecheck:/tmp/restore.dump
if ($LASTEXITCODE -ne 0) { throw 'Restore copy failed' }
docker compose -p agentflow-restorecheck -f deploy/compose.restore.yml exec -T restorecheck pg_restore --list /tmp/restore.dump
if ($LASTEXITCODE -ne 0) { throw 'Archive listing failed' }
docker compose -p agentflow-restorecheck -f deploy/compose.restore.yml exec -T restorecheck pg_restore -U restorecheck -d restorecheck --exit-on-error --single-transaction --no-owner --no-acl /tmp/restore.dump
if ($LASTEXITCODE -ne 0) { throw 'Restore failed; backup is not verified' }
docker compose -p agentflow-restorecheck -f deploy/compose.restore.yml exec -T restorecheck psql -U restorecheck -d restorecheck -v ON_ERROR_STOP=1 -c '\dt' -c 'SELECT * FROM alembic_version;' -c 'SELECT count(*) FROM tasks;' -c 'SELECT count(*) FROM agent_executions;'
if ($LASTEXITCODE -ne 0) { throw 'Database verification failed' }
# Keep this drill running for inspection. Do not stop/remove it without approval:
# its tmpfs database is lost when its container stops.
```

Check all expected tables, migration version, representative task/stage and custom
configuration records against the snapshot. For a full recovery drill, connect a
separate isolated application stack and verify UI/history before accepting the
backup. Never restore on top of a live database or use `pg_restore --clean` there.
Actual recovery requires a separate change plan: freeze writes, preserve the
original database/volume, restore into a fresh target, verify, switch connection
configuration deliberately, and retain the old data for rollback. These commands
do not perform cutover. Never delete existing volumes or run Compose's volume
deletion option.

## Security limitations and remaining gates

- Shared bearer token grants every holder the same read/write/delete access.
  There are no individual accounts, roles, audit attribution, MFA, or tenant
  boundaries. Rotate by changing server configuration and recreating backend;
  all browser users must reconnect. No login architecture was added.
- Browser `sessionStorage` is tab-scoped, JavaScript-readable storage. XSS,
  malicious browser extensions, or a compromised device can steal the token.
  HTTPS protects transit, not those cases. Do not save the token in bundles,
  URLs, localStorage, or deployment examples. CSP needs a separately tested policy
  compatible with Next.js before being enforced; it is not configured here.
- Uvicorn ignores forwarded IPs. Through Caddy, execution limits aggregate at
  the proxy address. This is conservative for a private MVP but may throttle
  multiple users together. A future trusted-proxy setup must ensure the backend
  is unreachable except through that proxy and reject spoofed forwarding headers.
  Multiple processes/replicas require a shared rate limiter. Do not scale this
  stack without addressing those limitations.
- Health/readiness are intentionally public and reveal only status. API docs
  and schema are disabled in production and blocked at the proxy. The static
  frontend shell is public to clients that can reach the listener.
- Production failures omit raw provider/DB exceptions from responses and original
  workflow stage storage/events. Historical records and model-generated outputs
  can still contain sensitive content; hardening does not scrub existing data.
  SDK/system startup diagnostics should be treated as sensitive operator logs.
- Development Compose still exposes its database with development credentials.
  Keep it local, protect the host firewall, and do not use it for production.
- The official PostgreSQL image creates `POSTGRES_USER` as a database superuser.
  This initial private stack uses that role for the app, so an app compromise has
  broad database privileges. Provision and test a separate restricted runtime
  role, keeping schema migrations under a separate owner, before widening access.
- Decide prompt/output retention, backup encryption/storage/schedule, authorized
  clients, certificate trust/renewal, and private network access before use.
- Local image builds, startup, PostgreSQL recovery, restart persistence,
  authenticated APIs, CORS, TLS, SSE error delivery and successful live five-stage
  Gemini execution have passed. Browser HTTPS and authentication were subsequently
  confirmed by the operator. Remaining UI checks, remote private-client access
  and image vulnerability scans remain unverified; no browser automation surface
  was available to the agent.
- Frontend uses its committed npm lockfile. Backend dependencies other than the
  Gemini SDK retain existing version ranges; base images use floating version
  tags. Record resolved versions and tested image digests for reproducible rollout.
- The expected synchronous Gemini cancellation XFAIL remains; cancellation does
  not stop an already-running synchronous provider thread. No async rewrite was
  attempted.

## Application checks

These tests use isolated in-memory SQLite and mocked AI providers; they do not
validate PostgreSQL, network Gemini calls, or containers.

```powershell
Set-Location C:\seamdigitech\LLM\backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
Set-Location ..\frontend
npm.cmd run lint
node node_modules/typescript/bin/tsc --noEmit
npm.cmd run build
npm.cmd run check:encoding
Set-Location ..
git diff --check
git status --short
git diff --stat
```

Official configuration references: [Next.js standalone output](https://nextjs.org/docs/app/api-reference/config/next-config-js/output),
[Compose startup and health dependencies](https://docs.docker.com/compose/how-tos/startup-order/),
[Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[Caddy private TLS](https://caddyserver.com/docs/caddyfile/directives/tls#internal),
[PostgreSQL 16 pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html),
and [PostgreSQL 16 pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html).

## Local verification results (2026-10-23)

| Check | Result |
| --- | --- |
| Backend pytest, final run with `-p no:cacheprovider` | 110 passed, 1 expected failure; includes 18 production security tests |
| Ruff | Passed |
| ESLint (`npm.cmd run lint`) | Passed |
| TypeScript (`node node_modules/typescript/bin/tsc --noEmit`) | Passed |
| Next.js production build | Passed, Next 16.4.2, standalone output and same-origin API; Linux Docker image also builds |
| Frontend encoding check | Passed (8 files covered by existing script) |
| Git whitespace check | Passed; Git reports normal LF/CRLF conversion warnings |
| Docker Compose config / image builds / startup | Passed with host Docker CLI; PostgreSQL/backend/frontend healthy, Caddy running and serving HTTPS; live Caddy configuration validation passed |
| PostgreSQL schema | Nine public tables; `0005_custom_workflows`; no migration rerun |
| Backup | 17406-byte custom archive; checksum below matched before restore and inside restore container |
| Recovery | Original restore exit 0 with no warnings; original and fresh populated-QA backups restored into separate isolated databases; all nine tables, revision and row counts match |
| Persistence | QA records survived app restarts and an in-place production PostgreSQL restart on the same container/volume; development DB was not restarted |
| HTTPS/API | Client explicitly trusting Caddy CA passed hostname/chain verification; health/ready 200, protected APIs 401 without/with invalid token and 200 with valid token; docs 404 |
| CORS / proxy limiting | Allowed/disallowed origin checks passed; proxy-wide 429 observed despite changing forwarded-IP headers; health stayed available |
| Browser JS | Ten actual container JS chunks checked; no `localhost:8000` reference |
| Production CRUD/failures | Two labeled agents and one two-agent workflow created and retained disabled; disabled execution returns 409 safely |
| Mocked execution in built backend image | Standalone custom execution, two-stage sequential execution, five-stage SSE and sanitized provider failure passed with real authentication and QA-only PostgreSQL records; no model calls |
| Live Gemini/SSE | Initial request failed with upstream HTTP 400 and `ProviderRequestError`; one separately authorized follow-up after backend credential refresh completed all five stages, each upstream HTTP 200. Retries 0, grounding off; result and all five stages persisted |
| Browser UI / remote private client | Operator confirmed browser HTTPS and authentication; remaining UI checklist and remote private clients not independently tested; agent did not modify Windows CA trust |
| Runtime security | App UIDs 10001/1000; configured-secret scan of runtime logs passed; application DB role remains superuser |

The first pytest attempt had 91 passed, 1 XFAIL and 1 setup error because Windows
blocked pytest's temporary directory. The permitted rerun passed; its cache
directory warning was removed by disabling pytest cache in the final run.
PowerShell blocked `npm.ps1`; using `npm.cmd` allowed lint/build without changing
execution policy. The generated `next-env.d.ts` change from the build was reverted
to keep the review focused. No dependency manifests/lockfiles were changed.

## Verified recovery and retained QA artifacts

Backup: `backups/agentflow-20261023T165856720Z-03f87601.dump`.
SHA-256: `3545D5FC45CBF76362D7677517030586A5DB01584AFBB3ED3C5D53EFAB122981`.
Its metadata, checksum and archive listing remain beside it, all Git-ignored.
Restore container: `agentflow-restoreverify-20261023170646-restorecheck-1`, project
`agentflow-restoreverify-20261023170646`. It remains running, network mode `none`,
no ports, tmpfs storage, no production/development volume attached. Do not stop
or remove it without authorization: stopping destroys its temporary database.
The original snapshot had only the Alembic row; all application tables were empty.
A second binary-safe backup of the populated QA state was then verified:
`backups/agentflow-post-qa-20261023T171627620472Z.dump`, 19628 bytes, SHA-256
`43BB873F58ED12992558F4865DB7E5DD2F7E1A0111CABAF9692312CFE1B0415B`.
Its archive listing and source/Windows hash comparison passed. It was restored
into NEW database `qa_recovery_20261023171627` inside the same networkless restore
container; all nine table row counts and migration revision matched production.
Both restore databases are retained. No development content was copied.
This verifies populated synthetic QA recovery; it does not test recovery of the
valuable development workload, which was never accessed or modified.

Production QA label: `QA private deployment 20261023T171112Z`. Two disabled agents
and one disabled workflow remain. Three original task records (one live failure,
one mocked success, one mocked failure), seven stage rows, one mocked custom
execution, and one mocked sequential run with two steps remain. Nothing was
deleted. IDs and detailed verification evidence are recorded locally in ignored
`backups/private-verification-results.json`. The offline harness temporarily
enabled only its own QA definitions and disabled them afterward. An initial
harness cleanup-order assertion was corrected without replaying executions.

## Safe stopping, troubleshooting and rollback

Stop only application traffic/services, keeping PostgreSQL available for backups:

```powershell
docker --context desktop-linux compose -p agentflow-private -f compose.production.yml --env-file .env.production stop proxy frontend backend
```

Restart after resolving configuration issues without recreating PostgreSQL:

```powershell
docker --context desktop-linux compose -p agentflow-private -f compose.production.yml --env-file .env.production config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed' }
docker --context desktop-linux compose -p agentflow-private -f compose.production.yml --env-file .env.production up -d --no-deps --wait backend frontend proxy
if ($LASTEXITCODE -ne 0) { throw 'Application startup failed' }
```

Docker access: the sandbox identity `CodexSandboxOffline` cannot access the
per-user CLI. Use normal host PowerShell or the approved host execution path:
`C:\Users\dhanu\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`.
Docker Engine 29.8.2, Compose v5.6.0 and Desktop 4.95.0 were confirmed. Do not
reinstall Docker merely because sandbox detection fails.

Gemini rejection diagnosis and resolution: retained logs show upstream HTTP 400
Bad Request and the application's `ProviderRequestError`. The public error
classification identified an invalid/rejected key; the underlying SDK subtype
and raw response body were not retained, so neither is claimed as recovered.
On follow-up, `.env.production` already matched the development key, but the
running backend still held the old value. The file was not edited by the agent.
Only backend was recreated to load the corrected value. One additional authorized
live smoke completed Orchestrator, Research, Analysis, Report and Review with five
HTTP 200 provider responses, no retries, 1185 reported tokens, in 110.41 seconds.
Task `b85fee51-4c12-465c-b99f-d54beb7559ff` and its five completed stage rows were
retrieved from production history. The model remains `gemini-3.5-flash-lite` and
SDK 2.31.0. This confirms corrected credential access, supported model and request
format for that test; it does not guarantee future quota or provider availability.
Other containers and database volumes were unchanged. Sanitized evidence is in
ignored `backups/gemini-followup-smoke.json`. Both authorized live requests have
been used; do not replay the verification scripts or send additional paid tests.

Certificate errors: obtain/verify the CA fingerprint and trust the public root
on approved devices manually, or pass `--cacert` as shown earlier. Do not disable
certificate verification or automatically install CA roots. The verified listener
is loopback-only; VPN/LAN access still requires a separately reviewed binding,
private DNS, firewall and client test.

Rollback: before a future image change, record current image IDs and tag them
with a unique rollback tag (`docker image tag`), preserve this Compose revision,
and take/verify a fresh backup. On an application regression, stop only the app
services, restore the reviewed configuration in a separate working checkout,
retag the saved image IDs as `agentflow-backend:local` and
`agentflow-frontend:local`, and recreate only backend/frontend/proxy. Verify
readiness and authenticated history before resuming. Do not rebuild rollback
tags, attach development storage, downgrade schemas automatically, or restore
over a live database. Schema rollback needs a fresh isolated restore and an
explicit cutover plan preserving the original volume.

Release verdict: **READY WITH EXPLICIT LIMITATIONS** for controlled use of the
verified loopback-only private stack. Live Gemini passes; the operator confirmed
browser HTTPS/authentication. The remaining UI checklist is manual.
Shared-token/sessionStorage risks, aggregate proxy rate limiting and superuser
runtime DB permissions remain. Before widening use, separate runtime database
permissions from migration ownership and establish encrypted off-host backups.

Final release review: full backend suite rerun with 110 passed and 1 expected
failure; Ruff, ESLint, TypeScript and standalone frontend production build passed.
Read-only HTTPS checks confirmed health/readiness, protected APIs, disabled docs
and the persisted live smoke result. Development container identity, start time
and volume mounts matched the earlier baseline. No production DB writes or new
provider calls were made during this review. The index remained empty; six
modified and ten new candidate files passed review and configured-secret scans.

## Manual browser checklist

1. Verify the public CA root `backups/agentflow-private-root.crt`. Its SHA-256 is
   `EAC1265E5A9EF18DE45505A9783E088FEB1441695807AFD6E1E605459DD69C79`.
   If you trust this private CA, manually add only its public root to the browser
   or current-user trusted root store. Never import/share its private key. No
   trust-store changes were made automatically.
2. Open `https://localhost:8443`; confirm the certificate is trusted and matches
   localhost. Do not bypass certificate warnings.
3. Enter the private bearer token locally. Verify dashboard, Agent Studio,
   Workflows and Tasks & Execution load. Never paste the token into chat.
4. In DevTools Network, confirm requests target same-origin `/api/*`, without
   `localhost:8000`, mixed content or CORS errors. Inspect the saved successful
   follow-up task and its five completed stages; no new paid execution is needed.
5. Refresh and confirm history remains available; check the browser console for
   errors. Remember the token is JavaScript-readable sessionStorage, scoped to
   the browser tab. Keep the retained QA agents/workflow disabled.
