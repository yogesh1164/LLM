# V2 architecture and migration decision

Status: proposed account/ownership cutover, not enabled. The working bearer MVP
is preserved. `auth_foundation.py` is a tested, inactive library; there are no
registration/login routes or user tables yet. Do not describe its unit tests as
multi-user API integration coverage.

## Decision requiring approval

Recommended: invite-only registration, bootstrap one explicitly identified Admin,
then assign legacy workspace data to that Admin using an approved ID manifest.
Alternative: quarantine unassigned legacy data, visible only through the isolated
legacy deployment until an explicit import. Never map records to the first user
who registers. No ownership backfill or production migration is authorized by
merely merging the foundation.

Keep an explicit deployment mode: `legacy_bearer` or `accounts`. No implicit
fallback from an invalid cookie to a shared bearer. Account mode must refuse
startup until schema/owner consistency checks pass. Keep the V1 image available
for rollback, not a parallel route into the multi-user data plane.

## Account design after decision

- `users`: UUID, normalized unique login/email, Argon2id password hash, role
  Admin/Member, enabled, created/updated timestamps. No public role assignment.
- Invite-only registration consumes a hashed, single-use, expiring invite in the
  same transaction as creating a Member. Admin bootstrap via an offline one-time
  command with interactive input, never a password in command-line args.
- `sessions`: hash of 256-bit random opaque token, user FK, independent hashed
  CSRF secret, created/last-seen, absolute expiry, idle expiry, revoked_at.
  Proposed 12h absolute/30m idle, adjustable downward. Only token digest stored.
- Cookie `__Host-agentflow_session`: Secure, HttpOnly, SameSite=Strict, Path=/,
  no Domain. Rotation at login/privilege changes; logout transaction revokes first
  then clears cookie. Disable user revokes sessions. No JWT in browser storage.
- Mutations require exact allowed Origin plus `X-CSRF-Token` matched to session
  digest. Login/registration require a short-lived pre-auth session and CSRF check
  to prevent login CSRF; logout is POST. No tokens in URL/query strings.
- Generic credential failures; nonexistent accounts verify a dummy Argon2 hash.
  Limit login attempts by normalized account and global/client bucket, bound
  concurrent hashes (default Argon2 uses ~64MiB each). PostgreSQL-backed limits
  for replicas; no Redis required. Trusted-client-IP design must precede IP limits.
- Auth dependency loads a current enabled user, session validity and server-side
  role. Ownership lookup scopes SQL queries before returning any resource.
  Admin manages accounts/diagnostics; Admin is not implicit access to user content.
  Separate audited break-glass content access would require another decision.
- Frontend same-origin cookie fetches; CSRF in memory, profile endpoint, login
  gate and logout, 401 clears private cached state. Preserve dark mode and current
  agent/workflow components. Server enforces authorization, not the UI gate.

Inactive primitives already test Argon2 verification, cookie flags/clear, session
expiry/revocation decisions, CSRF rejection, roles and owner checks. They do not
provide session storage, login limits or a complete account service.

## Expand/backfill/enforce migration plan (not applied)

1. Take a fresh binary-safe backup; validate archive, SHA-256 and isolated restore.
   Inventory row counts, orphan foreign keys and legacy IDs without exporting prompts.
2. Add users/sessions/invites and nullable indexed owner_id to tasks, custom_agents,
   custom_workflows, custom_agent_executions and custom_workflow_runs. No automatic
   backfill. Runs need independent owners because workflow deletion sets FK null.
3. Derive stages/steps through their owning parent. Require workflow and all agent
   references to share owner; check snapshot creation and duplicated resources too.
   Replace global agent-name uniqueness with owner+lower(name) only after backfill.
   Reports inherit task ownership; no invented knowledge-base schema.
4. On an isolated restored database, apply operator-approved legacy ID->owner
   manifest in a transaction; compare counts, constraints and digests. Null ownership
   must be inaccessible in accounts mode. Never delete/reassign live records implicitly.
5. Add per-owner filters to list/get/update/delete/duplicate/execute/history/dashboard
   queries and aggregate metrics. Reject foreign resource references with 404.
   Test A/B/Admin boundaries, nested references, disabled users, sessions, concurrent
   invite redemption, CSRF, malformed IDs and direct history/run access on PostgreSQL.
6. Enforce NOT NULL and required constraints only after zero orphan/unassigned rows
   are proven and approved. Deploy accounts mode in a separate isolated rehearsal.
7. Explicit cutover approval: backup again, brief write freeze, migration, single
   accounts backend, health+auth+isolation checks, then traffic. Retain original volume.
   No automatic downgrade/backfill reversal: restore into a new isolated target and
   reconcile post-cutover writes before switching. Older code cannot safely read
   multi-user records through an unrestricted bearer path.

## Durable execution foundation (implemented, opt-in, not deployed)

See [V2_DURABLE_EXECUTION.md](V2_DURABLE_EXECUTION.md) for the implemented journal,
lease/fencing protocol, API contract, additive 0006 migration, recovery guarantees
and known failure cases. Defaults remain off. No existing database has been migrated.
The backend has startup/periodic expiry detection and one-use idempotency keys;
recovery never replays a paid call. Current browser key/202 handling remains a rollout
prerequisite. Account/ownership approval is still pending independently.

The original design below remains context for future owner-aware jobs/continuation;
it is not a claim that a resumable background queue has been implemented.

Execution currently persists steps and partial results, but the request owns work.
Add a jobs table with owner, operation, request digest, unique(owner, operation,
idempotency_key), state, lease owner/expiry, heartbeat, attempt and result FK.
Within one transaction, reserve idempotency key and job. Conflicting payloads
return 409; matching retries return original job. Bounded admission, no unlimited
queue. Recover expired leases as interrupted, preserving partial results; never
auto-replay a potentially billed request with unknown provider outcome.

Retries remain limited to transient 503/selected 429 with jitter and stage/total
budgets. Daily quota/auth/model errors must not retry. Process-local provider
capacity now bounds live synchronous workers including cancelled callers; it is
not a durable queue or distributed limiter. The documented synchronous-cancellation
XFAIL remains. A cancelled task may still incur upstream cost until SDK timeout.

2026-10-24 offline verification expands interruption coverage at multiple stage
positions, including transport progress failures and a child process exiting without
cleanup. Committed output/token history survives and reads do not trigger replay.
Completed stages retain their status if a progress consumer fails. The process-exit
test explicitly demonstrates that unfinished records still remain `running`; these
tests at checkpoint 89958d4 did not implement leases or idempotency. The newer
foundation adds journaled lease recovery and duplicate protection, not a durable
queue or automatic continuation.

## Deployment and observability decisions

JSON logging allows only generated IDs, registered route templates, status and
numeric metrics. SDK messages/tracebacks/private prompts are omitted. Request
durations include complete SSE lifetimes; readiness latency and status are visible
as request events. Five-stage execution records include durations/token counts;
Gemini monetary estimates stay unavailable until operator-approved model prices
and grounding accounting exist. Do not label guessed prices as billed cost.

Admin diagnostics must wait for actual Admin authorization. No new global metrics
endpoint exposing users/providers is added. Central aggregation, alert thresholds,
log retention and OpenTelemetry exporting remain future operator decisions.

Least-privilege PostgreSQL: separate schema-owner NOLOGIN role, migration login,
runtime login with CONNECT/USAGE and DML on app tables/sequences; revoke CREATE
and superuser/createdb/createrole. Set default privileges as the migration owner.
Use separate runtime/migration URLs only after credential rotation and grants are
tested on isolated restored data. Do not embed passwords in scripts or blindly
change POSTGRES_USER on an initialized volume.

Proposed backup service target: daily encrypted off-host backups (RPO <=24h),
30-day retention and monthly restore drills targeting RTO <=4h. These are proposed,
not achieved guarantees. Destination, encryption key custodian and retention
approval are prerequisites; no automated uploads or deletions have been configured.

## References

- [GitHub workflow security](https://docs.github.com/en/actions/reference/security/secure-use)
- [Argon2-cffi usage and memory requirements](https://argon2-cffi.readthedocs.io/en/stable/howto.html)
- [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
