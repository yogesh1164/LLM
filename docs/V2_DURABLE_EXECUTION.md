# Durable execution foundation

Status: implemented behind `DURABLE_EXECUTION_ENABLED=false` (default). Development
only; not deployed. Based on local checkpoint `89958d4`. No existing database was
migrated. No account/ownership cutover or provider SDK rewrite is included.

## Decisions and scope

Keep the request-owned synchronous Gemini integration, rather than introducing a
queue. Add a PostgreSQL journal that can identify abandoned executions and prevent
duplicate admission for a caller's logical submission. Losing a lease terminates
local orchestration; it never transfers the job to a replacement worker.

The implementation covers all paid entry points: fixed execute, collaborate and
stream, saved-agent execute, and saved-workflow execute. Legacy mode and its
existing first-response contracts remain available with the flag disabled. In
durable mode, successful first responses retain those bodies/SSE events and add
`X-Execution-ID` and `Location` headers. CORS permits `Idempotency-Key` and exposes
these response headers. Existing bearer authentication protects journal reads.

The enabled API's idempotency requirement is an explicit contract change. Current
browser components do not manage durable keys or handle duplicate-202 responses.
**Do not enable durable mode for the existing UI deployment yet.** A UI follow-up
must keep a key through uncertain HTTP/SSE completion, handle 202 by inspecting
history, and require a deliberate new intent before choosing a new key. No
automatic per-fetch key generation or HTTP retry has been introduced.

## Additive storage

`0006_durable_executions`, following `0005_custom_workflows`, creates one table and
an expiry index. It changes no legacy table columns and backfills no data.

- Unique `(scope, key_digest)` reserves the logical submission across processes.
  The current scope is the single legacy workspace, not a user identity. Accounts
  mode must replace this scope with an authorized owner boundary before activation.
- Store SHA-256 digests of the validated key and canonical operation/task/resource
  input, never raw keys, bearer tokens or another copy of the prompt. A key is
  16-128 ASCII letters/digits/underscore/hyphen. Clients should use random UUIDs.
- Store a random worker lease token, DB-clock expiry, heartbeat/creation/completion
  timestamps, terminal state, and a sticky provider-dispatch-intent flag.
- At most one nullable FK links the task, saved-agent execution or workflow run.
  Each target link is unique. `ON DELETE SET NULL` retains the journal tombstone
  after history deletion so deleting results cannot make a key executable again.

Reservation commits before target creation. Target creation and journal attachment
share a transaction. A crash in the gap leaves only a journal reservation, which
expires as `interrupted` / `not_started`. If recovery wins before attachment, the
target-creation transaction fails its lease check and rolls back. No provider call
is permitted without a committed target link. This deliberately favors durable
duplicate protection over retaining a key for an invalid submission.

There is no automatic tombstone expiry, reclaim, attempt increment or queue. The
same key is permanently one-use. An operational retention policy is a future
decision. Migration downgrade refuses to erase the journal; application rollback
can leave this additive table present, but old execution code cannot enforce its
keys. No downgrade or migration has been applied to existing databases.

## Admission and HTTP behavior

In enabled mode:

1. Authentication and request validation run normally. Missing/invalid keys return
   428 without a provider call.
2. PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` admits one lease owner. A matching
   retry returns 202 plus the original journal descriptor and status location; it
   never creates another target or calls Gemini, even after failure or deletion.
3. A different operation, task or resource with the same key returns 409. Separate
   fixed execute/collaborate/stream routes are different operations, so switching
   routes with the same key also fails closed. Editing a saved definition does not
   turn a previously used key into a new execution.
4. `GET /api/executions/{id}` returns state, target IDs, workflow/task result URL,
   retry classification and the explicit `automatic_replay=false`. Saved-agent
   results remain in the existing agent history endpoint, matched by execution ID.

202 is a lookup response, not a queue acknowledgement or a replay of the original
response body. In-flight duplicates need not wait for the original request.
Different keys represent distinct intents and can still incur duplicate costs;
there is no content-based deduplication or exactly-once billing guarantee.

## Leases and guarded writes

Defaults: 60-second lease, 5-second heartbeat, 15-second recovery interval. Settings
require a heartbeat shorter than one third of the lease. PostgreSQL uses
`clock_timestamp()` rather than worker clocks or the transaction-start timestamp.
SQLite support exists for isolated tests, not distributed production execution.

Every execution-state write locks the journal row with `FOR UPDATE`, validates its
running state, token and unexpired lease, and retains the lock through the target
write transaction. Stage starts, stage completions/failures, parent partial/final
writes and saved-agent/workflow writes are guarded. Dispatch intent is committed
before entering the provider adapter. The synchronous Gemini worker checks the
lease again after executor queueing and before constructing the SDK client.

There is no lock across a network call. A worker that resumes after recovery cannot
start another stage or overwrite terminal/partial records. A call already beyond
its dispatch check may finish at the provider; losing ownership discards late
results rather than resurrecting the execution. The ordinary synchronous thread
cancellation limitation and its existing strict XFAIL are preserved.

Heartbeats span the entire HTTP/SSE execution lifetime. A heartbeat error cancels
local orchestration. Closing the streaming consumer explicitly closes the original
event generator and cancels its request worker before finalizing the lease. Durable
Gemini attempts disable application retries, even for 503, in addition to the
existing single SDK HTTP attempt. Legacy-mode retry behavior is preserved.

## Recovery and guarantees

Enabled startup verifies that the journal schema exists, then recovers expired
leases. It performs no DDL. Missing schema or unavailable DB fails startup. A
periodic task continues recovery so live leases at startup can expire later.
Recover at most 100 rows per sweep using `FOR UPDATE SKIP LOCKED`; multiple sweepers
can share the work. Background DB failures log a fixed message and retry later.

For each expired lease, recovery atomically:

- Preserves an already completed parent and marks the journal `completed`, covering
  a crash after parent completion but before journal finalization.
- Otherwise terminalizes abandoned running/pending parents/stages/steps as
  `interrupted`, retaining completed outputs, tokens and available cost data.
- Reconstructs fixed-workflow partial outputs and token totals from committed stage
  rows, including a crash between stage completion and parent aggregate commits.
  Restores the last committed custom-workflow output from ordered completed steps.
- Finalizes the journal without ever invoking a provider or scheduling a retry.

With a reachable DB, active recovery process, available locks and no large backlog,
abandoned journaled work is detected after lease expiry plus the sweep interval
(defaults approximately 75 seconds after the last successful renewal). This is not
a hard availability SLA. `SKIP LOCKED` defers locked rows to a subsequent sweep.
Legacy records without journal entries are deliberately untouched: their process
ownership cannot be inferred safely, and no live bulk status repair is authorized.

| Classification | Meaning | Allowed behavior |
|---|---|---|
| `not_started`, terminal failure/interruption | No provider adapter dispatch intent was committed | Descriptor says `safe_to_resubmit=true`; only an explicit new key can create a new attempt |
| `do_not_replay` | A provider may have been invoked, including partial completion | No automatic retry, lease takeover or replay; inspect committed history and reconcile provider usage |
| Completed target | Final result committed | Same-key lookup returns its journal/target; never executes again |

The intent marker is conservative: adapter validation/capacity failure after marking
may be classified uncertain even if no actual request reached Gemini. Recovery is
status/data reconciliation, not automatic continuation from the next step.

## Failure limits

- Provider billing/output not committed before a crash cannot be reconstructed.
  Never invent token totals for unknown calls. Committed stage token usage survives.
- Process pause, event-loop starvation or DB outage can cause false interruption.
  Fencing prevents later mutations; synchronous in-flight work can still cost money.
- DB lock waits/deadlocks or recovery downtime delay detection. No global/distributed
  provider admission limit is added; existing per-process bounds still apply.
- DB restore to an older backup can lose journal reservations as well as results.
  Do not blindly resubmit keys after restore. Tombstone retention/backup policy is
  part of any future rollout and rollback decision.
- Existing UI key lifecycle, accounts/owner isolation, live migration and deployment
  remain outside this checkpoint. Durable mode does not make the app multi-user.

## Verification approach

Offline SQLite/API tests cover missing/conflicting/matching keys across all entry
points, periodic/startup recovery, heartbeat failure, stream disconnect, stale
writes, unknown outcomes, deleted-result tombstones, partial aggregates, abrupt
process exit and the additive migration. SDK stubs prove no automatic durable retry
and no dispatch from an expired queued worker.

PostgreSQL tests use a new no-network container with tmpfs storage and no host
ports/volumes. Each test creates a randomly named schema, applies migrations only
there and removes only that fixture schema. Concurrent submitters admit one fake
provider call; competing recovery workers finalize each expired journal once;
locked rows are deferred. Tests also cover a PostgreSQL child-process crash,
heartbeat progress, FK tombstones and untouched legacy fixture data across 0006.
The explicit fixture URL is required; tests never fall back to an application DB.

CI has a dedicated disposable PostgreSQL job. Local full-suite results are recorded
in V2_VERIFICATION.md; hosted CI has not run because no push is authorized.

Implementation references:
[PostgreSQL row locks](https://www.postgresql.org/docs/16/explicit-locking.html),
[PostgreSQL actual clock](https://www.postgresql.org/docs/16/functions-datetime.html),
[SQLAlchemy PostgreSQL upsert](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert).
