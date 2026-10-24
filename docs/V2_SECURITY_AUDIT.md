# V2 security audit

## Final focused audit continuation: 2026-10-24

Current evidence supersedes the historical snapshots below:
[release evidence](V2_RELEASE_EVIDENCE.md), [verification](V2_VERIFICATION.md),
[image disposition](V2_SECURITY_DISPOSITION.md),
[database role design](V2_DATABASE_ROLES.md), and
[encrypted recovery](V2_ENCRYPTED_BACKUP_RUNBOOK.md).

The audit exercised Argon2/login throttling, cookie/session expiry and revocation,
Origin/CSRF, enumeration-safe credential errors, recovery, every protected route,
owner/admin/IDOR boundaries, null-owner quarantine, journal owner/recovery and
spoofing. Reviewed request-body limits, explicit CORS, SQLAlchemy/static SQL
construction, safe provider errors, allowlisted JSON logging, client session storage,
Markdown HTML/URL/image handling, Docker users/capabilities/filesystem defaults,
private TLS headers, dependency inventory and fresh image advisories. Found and
fixed account fixed-workflow double admission and the missing account production
exception boundary; regression tests cover quota behavior and secret-bearing errors.

Runtime database permissions and encrypted disaster recovery are now implemented
and verified **in isolation**, including inherited column-ACL revocation, forbidden
role/DDL operations and exact restored snapshots. Operational production acceptance
remains open. Backend/frontend image gates still show **one HIGH / zero CRITICAL
each**; no patch, suppression, waiver or production-ready claim. Script CSP,
multi-replica budgets, provider cancellation and actual off-host operations retain
the explicit limitations recorded in release evidence.

## Continuation update: 2026-10-24

The historical findings below describe the baseline and earlier checkpoints.
Current opt-in account mode enforces cookie sessions, exact Origin/CSRF,
database login throttling and ownership across API resources and durable journals.
Admin is not a content superuser. Migration 0007 leaves legacy data unassigned;
offline assignment requires a reviewed manifest. Shared bearer mode is still the
default and remains unsuitable for multi-user access. See
[account operations and residual gates](V2_ACCOUNTS_ROLLOUT.md).
Both review Dockerfiles now use pinned Trixie images. Final advisory evidence and
remaining zlib gate are in [V2_IMAGE_TRIAGE.md](V2_IMAGE_TRIAGE.md).

Current release residuals: **one HIGH zlib finding per review image, zero CRITICAL**;
runtime DB role separation and encrypted off-host backup operations remain open;
production account cutover and hosted CI acceptance remain unexecuted. Current
local tests are 319 Linux backend passes plus one known XFAIL and 32 combined
frontend passes. Account-aware PostgreSQL subprocess recovery is now verified.
The source classification mismatch is evidence for vendor review, not a waiver.

## Historical baseline findings

Audit date: 2026-10-23. Starting revision: `6bd5b32` (merged private MVP).
`main` was clean, fetched, and 0 commits ahead/behind `origin/main` before creating
`feature/v2-production-hardening`. No live schema, credential or volume changes.
This is a source/configuration audit and offline verification, not a penetration
test or certification of multi-user readiness. V1 runtime evidence in DEPLOYMENT.md
is historical; it does not validate the new feature branch.

## Prioritized findings

| Severity | Evidence | Risk and disposition |
|---|---|---|
| Critical for multi-user use | `backend/app/main.py:require_api_token`; `backend/app/database.py:Task`, `CustomAgent`, `CustomWorkflow`, runs | Every bearer holder can read/change/delete all data. No users, roles or ownership. Remains a single-user deployment. Account/ownership cutover is approval-gated; see V2_ARCHITECTURE.md. |
| Critical dependency advisory | Installed `certifi==2026.7.22`; backend manifest lacked a security floor | Compromised CA chain can enable TLS interception by an on-path attacker. Fixed manifest to `certifi>=2026.10.19`, local environment now 2026.10.23; runtime image must be inspected/released separately. [GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2). |
| High | `compose.production.yml:x-backend` / `postgres.environment` | Same `agentflow` bootstrap role for migrations and runtime; previously verified superuser. Keep private. Separate NOLOGIN owner, migration login and runtime DML role before wider access. No live role changes authorized. |
| High | `backend/app/research.py:generate_gemini_stage` | Coroutine timeout cannot stop the synchronous SDK worker. Added process-local admission guard (default 4) retaining capacity until the actual worker exits; saturated attempts fail without new SDK calls. Cancellation XFAIL remains. Multiple processes still multiply capacity. |
| High in existing deployment; opt-in V2 mitigation tested | `backend/app/durable_execution.py`; execution routers; additive migration 0006 | New database journal admits one worker per caller key, fences expired writers, and recovers journaled expiries without provider replay. Disabled by default; no existing DB migrated. Legacy unjournaled records remain untouched. See V2_DURABLE_EXECUTION.md for unknown-outcome limits and pending browser/API rollout contract. |
| Medium | `frontend/src/app/api.ts`; `page.tsx` | Shared bearer in sessionStorage readable by same-origin JavaScript; no per-user revocation, expiration or audit identity. Inactive cookie primitives are not a deployed login system. |
| Medium | `backend/app/main.py:_check_rate_limit`; Docker Uvicorn command | Per-process IP limit aggregates all users behind Caddy. Forwarded headers are deliberately untrusted. No global or per-user budget across replicas. Keep one worker/replica; do not enable arbitrary proxy headers. |
| Medium | `backend/app/custom_agents.py:_execute_saved_agent` | Cancelled requests left execution `running`; now cancellation persists terminal status and re-raises, offline tested. Process crashes are a separate unresolved case. |
| Medium | `backend/app/main.py` logging; SDK loggers | Free-form SDK logs can include raw URLs/errors/private content. Production formatter now permits only structured numeric metrics, generated UUIDs, registered route templates and fixed categories; discards raw messages, exception text and unknown fields. External process/server startup logs still need operational review. |
| Medium | `frontend/src/app/ResultsPanel.tsx` | Model Markdown could load external images, leaking client address/referrer or contacting internal browser-reachable hosts. Images now render as text; citations use existing safe URL filter. Raw HTML remains disabled. |
| Medium | `backend/app/agents.py`, `workflow.py`, `custom_workflows.py` | User tasks, search material and preceding model outputs are untrusted context. Prompt instructions are not authorization. No arbitrary shell/SQL tool is exposed; grounding is explicit opt-in. Model output must not trigger privileged actions. Injection-resistant correctness is not guaranteed. |
| Medium | Dockerfiles, Python dependencies, Compose image tags | V2 app base images are now digest pinned; runtime versions are constrained from the tested Linux image. Gemini remains 2.31.0. Constraints are not hash-verified; build tools and Compose infrastructure tags remain follow-ups. |
| High, unresolved | V2 review image Docker Scout reports | Backend: 9 high advisories across 4 Debian packages. Frontend: initially 18 across 10 packages; removing unused runtime npm/Corepack/Yarn reduced this to 8 across 3 Debian packages. Runtime setuid/setgid bits now removed and vendor/reachability evidence recorded in V2_IMAGE_TRIAGE.md. These mitigations do not patch packages. No suppressions; image security gate remains a release blocker. |
| Medium, mitigated in V2 source | `app/request_limits.py`, `main.py` | Default 256 KiB API body cap before JSON parsing or endpoint effects, including undeclared/chunked bodies; malformed/duplicate Content-Length rejected. Limit responses retain CORS, no-store and request IDs. This is a per-request byte budget, not a slow-client/global admission limit. |
| Medium | `DEPLOYMENT.md` backup procedure | Verified local recovery does not supply encrypted off-host retention, automated schedules or measured RPO/RTO. Dumps contain private content. Operator-selected destination/key custody required; no upload/schedule configured. |
| Moderate dependency advisory | Installed pytest 8.4.2, old `<9` constraint | UNIX temporary-directory issue; changed development constraint to >=9.0.3,<10; tested 9.1.1. Not a runtime dependency. [GHSA-6w46-j5rx-g56g](https://github.com/advisories/GHSA-6w46-j5rx-g56g). |
| Low/operational | Caddy internal CA, local bind; `deploy/Caddyfile` | Private root trust must be explicit per device. Listener remains loopback-only. No automatic Windows trust-store changes. No remote client/private DNS verification in this phase. |

## Route and data boundary inventory

All `/api/*` routes except health/ready use the global bearer middleware. CORS
preflights are handled outside it; this does not authorize a subsequent mutation.
The route inventory test expands FastAPI's included routers and verifies both
missing and invalid bearer rejection for every documented sensitive route/method.

| Surface | Operations | Data model / current boundary |
|---|---|---|
| `/api/health`, `/api/ready` | GET | Public minimal status; readiness executes DB probe, no environment dump |
| `/api/dashboard` | GET | Task history/counts/usage; shared workspace |
| `/api/tasks/{task_id}` | GET, DELETE | Tasks and stage outputs; deletion cascades |
| `/api/workflows/{collaborate,execute,stream}` | POST | Original five-stage execution; start rate limited, timeout bounded |
| `/api/agents`, `/{agent_id}` | GET, POST, PATCH, DELETE | CustomAgent; global case-insensitive name uniqueness |
| `/api/agents/options`, `/{agent_id}/duplicate` | GET / POST | Configured models, copy definition; builtin identifiers protected |
| `/api/agents/{agent_id}/execute`, `/executions` | POST / GET | CustomAgentExecution; rate limited, provider/model validation |
| `/api/custom-workflows`, `/{workflow_id}` | GET, POST, PUT, DELETE | Workflow definitions and ordered steps; referenced agents checked |
| `/api/custom-workflows/{workflow_id}/execute`, `/runs` | POST / GET | Persistent run and step snapshots; partial outputs preserved |
| `/api/custom-workflows/runs/{run_id}` | GET | Historical run even if definition deleted; needs its own owner |
| Reports / Knowledge Base | UI only | Reports derive from task output; no separate knowledge-base table/API found |

SQLAlchemy queries bind values; the inspected `text()` uses are static readiness
and index expressions, not concatenated request SQL. UUIDs, lengths, provider/model
allowlists and field ranges constrain inputs. List endpoints and request-body
transport size previously lacked comprehensive resource budgets. V2 now bounds API
body bytes; pagination, concurrent request budgets and slow-client handling remain
before broader access. Model-call limits count stages; retries add upstream calls.

Production docs are disabled in FastAPI and blocked by Caddy. Explicit HTTPS CORS
origins are validated; credentialed CORS is off in bearer mode. API responses now
also have no-store at the application layer. Postgres/backend/frontend ports are
not published. App containers run non-root and drop capabilities; PostgreSQL and
Caddy image defaults need separate least-privilege validation before changes.

## Scan scope and interpretation

`npm audit` on the current lockfile found zero vulnerabilities. Initial Python
audit found two unique advisories across certifi and pytest (pytest was duplicated
in tool output). Follow-up scan found zero known vulnerabilities after local fixes;
editable local `agentflow-api` is intentionally excluded from package advisory lookup.
Advisories change over time. These checks do not scan OS packages or prove absence
of vulnerabilities. CI includes image scanning and full-history redacted secret
scanning; remotely executed Actions results must not be claimed before a push.

No secrets should appear in committed reports. `.env`, `.env.production`, backups,
certificates, private keys and dumps remain excluded. CI uses disposable fake
values, no production secrets, no `pull_request_target`, no self-hosted runners,
no image push and no deployment. Action refs are immutable SHA pins verified from
upstream tags; Gitleaks, Hadolint and actionlint tooling images are digest pinned.
The Grype action's downloaded scanner and build tooling still need stricter version management.
