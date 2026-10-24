# Account and durable execution production preparation

Status, 2026-10-24: implemented and tested in isolation; not deployed. This
procedure does not authorize a production migration, environment edit or cutover.
Keep existing databases, volumes, credentials and the V1 service unchanged.

## Implemented contract

`AUTH_MODE` defaults to `legacy_bearer`. Explicit `accounts` mode rejects bearer
fallback. There is no registration, invitation or password-reset HTTP API.
An operator creates accounts through `python -m app.account_operator`; passwords
are read twice from an interactive terminal, never from arguments or files.
Administrators do not have access to other members' content.

Production sessions use `__Host-agentflow_session`, Secure, HttpOnly,
SameSite=Strict, Path=/ and no Domain. Development uses `agentflow_session_dev`
without Secure. Absolute lifetime is 12 hours and idle lifetime 30 minutes.
Only session/CSRF digests are stored. Login rotates the presented session;
password change/reset and disable revoke all sessions for that account.
Mutations require exact allowed Origin and session-bound `X-CSRF-Token`.
Login requires exact Origin and `X-AgentFlow-Login: 1`. This custom-header check
replaces the earlier proposed pre-auth session design. Shared database admission
allows five attempts per normalized login and 60 globally per five minutes;
two concurrent password hashing operations are admitted per process.

The browser keeps CSRF in memory and uses cookies for authentication. It removes
the legacy token on entry to account mode, unmounts private content after 401,
and notifies other tabs of identity changes without reloading the sending tab.
Non-secret, owner-tagged execution metadata can survive sign-out for recovery;
a different account clears it before mounting its workspace. Recovery never
automatically resubmits a potentially billed operation.

## Migration and ownership review

`0007_accounts_ownership` follows `0006_durable_executions`. It adds users,
sessions, login buckets, account audit, ownership-assignment audit and nullable
indexed owner foreign keys on tasks, agents, agent executions, workflows,
workflow runs and durable journals. Stage/step access derives from parents.
Agent names are unique per owner; null legacy owners retain a separate unique
index. Existing data stays unassigned and invisible in account mode. The
migration never selects an owner or creates a user. Downgrade refuses data loss.

Before an approved cutover, rehearse on a newly restored isolated target:

1. Record source database identity, revision, image IDs, row counts and fresh
   binary-safe backup evidence. Resolve unfinished/unknown provider outcomes.
2. Apply the explicitly reviewed revision `0007_accounts_ownership`. Do not use
   an unreviewed `upgrade head`: head now includes account/ownership changes.
3. Bootstrap the explicitly selected administrator through the interactive CLI.
   All commands require `--expect-database DATABASE_NAME`; mutations require an
   approval reference. Bootstrap refuses a nonempty account table.
4. Either retain null ownership in quarantine, or obtain approval for a specific
   whole-workspace assignment. `plan-ownership --owner-id UUID --output FILE`
   creates a new manifest containing IDs/counts/digests. Review it before
   `assign-ownership --manifest FILE --confirm-login LOGIN --approval REF --apply`.
   No `--apply` means no assignment. Stale/tampered manifests, foreign references,
   running executions and a non-admin target are refused. Assignment is atomic
   and a repeat of the identical manifest verifies ownership and returns zero.
5. Add members using `add-member --login LOGIN --approval REF`. Confirm A/B/Admin
   isolation for list/detail/mutation/history, nested references, journal status
   and same-key durable retries. Review production HTTPS cookie and Origin checks.
6. Enable accounts only in separately approved deployment configuration. Current
   Compose retains its required legacy token interpolation; account middleware
   ignores that bearer. Configuration preparation/secret changes are a future
   operator step. Do not weaken the base Compose guard to bypass configuration.

Readiness requires PostgreSQL in production, revision 0007, an enabled admin,
owner columns, consistent resource relationships and owner/journal scopes.
Legacy mode refuses startup once owned content exists. Do not run old unrestricted
bearer code against account data or keep a second legacy route into that database.

## Rollback and remaining release gates

Do not downgrade 0007, remove owners, stamp revisions or overwrite an existing
database. Retain the original target; restore an approved backup into a new
isolated target, reconcile post-cutover writes, and review which code can read it
safely before any traffic switch. Durable-only rollout remains separately
documented in [V2_DURABLE_ROLLOUT.md](V2_DURABLE_ROLLOUT.md), pinned to revision 0006.

Release remains blocked by the image high-severity gate, production ownership and
cutover decisions, runtime DB role separation, encrypted off-host backup/key
custody/retention, and operational acceptance. Keep one worker/replica; provider
admission and execution rate limits are not distributed account spending budgets.
The synchronous Gemini cancellation XFAIL still describes possible upstream cost.
Remote CI/branch protection and production HTTPS isolation checks require future
operator execution. Passing local tests does not authorize deployment.

## Repeatable offline verification

From `backend`, run `.\.venv\Scripts\python.exe -m tests.verify_accounts_runtime`.
The harness creates only fresh tmpfs PostgreSQL and separate review API containers,
mounts source read-only, uses the guarded fake provider, and runs all frontend
tests including three actual account/durable browser paths. It stops only its own
identified containers and leaves ignored evidence under `backups`. No restore,
existing volume, real dotenv file or paid API is used. Other PostgreSQL tests
require the strictly validated `DURABLE_TEST_DATABASE_URL` fixture identity.
