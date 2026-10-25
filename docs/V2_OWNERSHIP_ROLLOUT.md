# Legacy record ownership inventory and explicit mapping

An [empty selection template](V2_OWNERSHIP_SELECTION_TEMPLATE.json) is provided
for an operator review. It has no account or component assignment and is not a
valid apply manifest. Leaving `mappings` empty keeps all legacy components
unassigned and inaccessible to ordinary users at activation; administrators
also cannot access null-owned content through normal account-scoped endpoints.
The operator must separately review provenance and approve any future mapping.

Prepared tooling; no existing database was inspected or modified and no production
owner was selected. Migration `0007_accounts_ownership` remains unchanged: it adds
nullable owner foreign keys and account/audit tables without assigning any row.
Null ownership is quarantined from authenticated users, including administrators.

Latest synthetic verification passed: Windows full suite included the mapping and
migration tests; the focused PostgreSQL ownership suite passed **7 tests, 0
skipped**, covering multi-account isolation/quarantine, transaction guards,
concurrent apply and read-only pre-0007 inventories. These tests do not inventory
or assign real production records. The account mapping and ownership manifest still
require an operator-selected account, provenance review, exact digest approval,
and a separately authorized execution window.

The original whole-workspace `plan-ownership`/`assign-ownership` remains supported
for an explicitly selected administrator. Assignment now also requires the exact
`--confirm-manifest-digest`. It must not be used when different legacy records
belong to different accounts. Use the component mapping below for that case.

## What must stay together

The read-only inventory groups graph-connected records into ownership components.
A task and its stages/journal form one component. Custom agents, their executions,
workflows referencing them, workflow steps/runs, historical run steps and journals
are linked through existing foreign keys. If an agent is shared by several
workflows, those workflows belong to the same component. The tool never silently
copies an agent or splits shared history to accommodate a requested mapping.

The inventory contains IDs, counts, content digests, existing owner IDs and the
ID/login/role/enabled state of possible accounts. It exports no prompts, results,
password hashes, sessions or credentials. Treat even this metadata as restricted
operator information. `component_id` identifies the connected row set; the separate
`inventory_digest` binds its current contents, owners, accounts and database/schema.

Only complete, finished, wholly unassigned components can be assigned. Running or
pending executions must first be drained/reconciled under a separate approved
procedure. Components with mixed or conflicting ownership require investigation;
already assigned records are never reassigned. Orphan relationships fail inventory
generation. An enabled member or administrator can be an explicit mapping target;
an administrator gains no content access to components mapped to other users.

## Operator preparation and approval

The following are PowerShell 5.1 examples, executed only in an explicitly authorized
operator session after database identity, backup readiness, maintenance window and
the intended role/credential have been independently confirmed. No connection
string or password belongs in argv or these manifests. Load the selected
`DATABASE_URL` through the approved protected credential mechanism; never use the
runtime role for assignment. Follow [database roles](V2_DATABASE_ROLES.md) and
[encrypted recovery](V2_ENCRYPTED_BACKUP_RUNBOOK.md). These examples are not
authorization to read or change a production database.

Use a new protected output directory and filenames; output files are opened with
exclusive creation and cannot overwrite a previous reviewed artifact. The CLI
checks the explicit database name, PostgreSQL and revision 0007 before proceeding.
Inventory, mapping planning and verification run in read-only transactions.

`inventory-ownership` also supports a **pre-upgrade database at 0005 or 0006**.
At 0005 it exports all eight existing content tables plus revision metadata (nine
tables); at 0006 it additionally includes the durable journal (ten tables).
Identifiers/counts/content hashes come from the actual pre-upgrade rows. Owners
are represented as **virtual null values in memory** for component review; no
column, account table or row is created. The export explicitly sets
`phase=before_accounts`, `mappings_available=false`, `virtual_null_owners=true`
and an empty account list. It cannot finalize or authorize an assignment because
no approved account mapping exists yet.

After a separately authorized upgrade to 0007 and offline account provisioning,
export a **fresh** account-aware inventory with the same command and begin the
mapping review below. Pre-upgrade inventory digests cannot substitute for that
post-upgrade plan/review gate. All planning/application/verification commands
other than inventory require 0007. No production upgrade is performed here.

```powershell
Push-Location backend
try {
    .\.venv\Scripts\python.exe -m app.account_operator --expect-database agentflow inventory-ownership --output C:\protected\ownership-inventory.json
} finally { Pop-Location }
```

The operator must review actual record provenance outside the tool's metadata
export, choose the destination accounts, and obtain explicit approval from the
responsible owner. Do not infer ownership from first registration, ordering,
record timestamps or account role. If provenance is unresolved, leave that entire
component unmapped and quarantined. Do not enable broad bearer access to bypass it.

Create a selection file using the **actual approved inventory digest, component
IDs and account IDs/logins**. The example deliberately uses placeholders; it is
not executable approval and chooses no real account:

```json
{
  "inventory_digest": "EXACT_REVIEWED_INVENTORY_DIGEST",
  "unmapped": "quarantine",
  "mappings": [
    {
      "component_id": "EXPLICITLY_SELECTED_COMPONENT_DIGEST",
      "owner_id": "EXPLICITLY_APPROVED_ACCOUNT_UUID",
      "confirm_login": "exact-approved-account-login"
    }
  ]
}
```

Add an independent entry for each approved complete component, including entries
for different accounts where appropriate. Duplicate components, unknown accounts,
disabled accounts and mismatched login confirmations are rejected. Unmapped
components remain unchanged. Re-scoping legacy execution keys is checked for
collisions with other keys for the selected destination; collisions require
reconciliation, never provider replay or silent key replacement.

```powershell
Push-Location backend
try {
    .\.venv\Scripts\python.exe -m app.account_operator --expect-database agentflow plan-mapping --selection C:\protected\ownership-selection.json --output C:\protected\ownership-approved-manifest.json
} finally { Pop-Location }
```

Review the complete generated manifest, its component IDs/record IDs/counts,
account IDs/exact logins, database/schema identity and `manifest_digest`.
Record approval of that exact canonical digest and the unmapped quarantine choice
in the operator's decision record. This digest is an integrity/staleness guard,
not a digital signature or an automatic source of authorization. Protect both
the manifest and external approval evidence from modification. Any changed data,
account choice or inventory requires a fresh plan and renewed approval.

## Explicit application and verification

The default apply command is a dry run. Even the dry run requires the exact digest
and approval reference, but does not mutate records:

```powershell
Push-Location backend
try {
    .\.venv\Scripts\python.exe -m app.account_operator --expect-database agentflow apply-mapping --manifest C:\protected\ownership-approved-manifest.json --confirm-manifest-digest EXACT_APPROVED_MANIFEST_DIGEST --approval EXPLICIT_OPERATOR_DECISION_REFERENCE
} finally { Pop-Location }
```

Only after explicit operator authorization, append `--apply` to that exact command.
The tool obtains transaction-scoped table locks with a five-second lock deadline,
checks the reviewed inventory again, assigns only the selected root rows, updates
each selected journal's scope to its owner, records one append-only audit row per
component and verifies the expected owner/content/counts. Children inherit access
through their approved parent relationships. All changes commit together; any
validation, collision, lock or database error aborts the transaction.

```powershell
Push-Location backend
try {
    .\.venv\Scripts\python.exe -m app.account_operator --expect-database agentflow verify-mapping --manifest C:\protected\ownership-approved-manifest.json --confirm-manifest-digest EXACT_APPROVED_MANIFEST_DIGEST
} finally { Pop-Location }
```

An identical successful apply is repeatable and returns zero assigned rows only
after checking existing audit rows, every approved record, its owner and journal
scope. It does not create duplicate approval records. Partial audit state, missing
records, changed owned content or modified owner/scope causes verification failure;
never delete audit rows or clear ownership to force a repeat through.

After application, run private account acceptance for every mapped account,
cross-user denial, quarantine denial and owned journal retrieval. Inventory a
second time to reconcile selected and remaining components. Preserve the original
manifest, digest approval, before/after inventory, encrypted recovery checkpoint
and verification output together under the operator's retention/access policy.
No real approval, account selection, retention destination or production assignment
is supplied by this engineering work.

## Failure and recovery

On stale review, wrong digest, unknown/disabled account, incomplete component,
key collision or lock timeout, stop and investigate; no partial application should
commit. Regenerate the inventory only after the cause is understood. Do not use
database overrides or edit a checksum merely to bypass a failed approval check.

There is no automatic unassign/reassign or downgrade command. If an approved map
was factually wrong, quiesce access, preserve current state and audit evidence,
and obtain a separately reviewed correction/recovery plan. A restore must target a
new isolated database and be reconciled before any traffic switch. Never restore
over a live database or delete journals/audit records to make ownership appear
unassigned. V1 bearer mode is not a safe rollback for an owned database.

## Verification scope

Synthetic tests cover two explicitly mapped accounts (including a member), a
third denied account, unmapped quarantine, connected agent/workflow history,
owner-linked journals, content/count preservation, stale/tampered/incorrect
approval, duplicate/incomplete mappings, active/mixed-owner components, key
collisions, rollback, repeat audit verification and revoked scope detection.
PostgreSQL tests use only new per-test schemas in the explicitly named disposable
fixture, including transactional guards and competing apply workers. No real
database inventory, provenance judgment or production ownership decision has
been made. Current executed counts are recorded by the release verification
report; this runbook does not treat prepared production steps as completed.
