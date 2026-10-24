# V2 production-readiness evidence — 2026-10-24

**NOT READY.** This is an undeployed release candidate on
`feature/v2-production-hardening`, continued from `62234f9`.
Production/development databases, roles, volumes, services and real environment
files remain unchanged. Nothing was pushed, merged, deployed or publicly exposed;
all provider calls in the engineering fixtures were offline doubles.

## Latest blocker-resolution continuation — 2026-10-24

This status supersedes the image IDs and test counts below where they differ.
Latest local base commit before this uncommitted continuation:
`2c1e7d1ef2f9af9244564f2370cdcc0a16325e91`. Engineering completion estimate:
**96% complete / 4% remaining**; release remains **NOT READY**. No checkpoint has
yet been created for the continuation.

| Workstream | Latest evidence and disposition |
|---|---|
| Container CVE | Backend `sha256:5bd868922bf34d44126f4b8c97243216d5cf5245c48d1243b7b3260046077c26`: 1 HIGH, 0 CRITICAL, 6 MEDIUM, 27 LOW. Frontend `sha256:1b07add53c68f430329b58cc8f00920c9ef4f5baa3909405e030750c457fbfe6`: 1 HIGH, 0 CRITICAL, 1 MEDIUM, 26 LOW. Both HIGH findings are CVE-2026-85091; neither is accepted or suppressed. |
| Backup | Age/X25519 streaming passed 300 MiB authenticated round-trip and separate local retrieval. Synthetic PostgreSQL restore matched 15 tables at 0007. Delivery evidence states `off_host_verified: false`; no destination or schedule is configured. |
| Database roles | Read-only catalog evidence found the audited `agentflow` role has SUPERUSER, CREATEDB, CREATEROLE, REPLICATION and BYPASSRLS; revision was 0005. A commented offline plan exists, but `ready_to_apply` is false. No role or grant changed. |
| Ownership | Synthetic mapping, quarantine, stale-manifest, ownership-isolation and concurrent-apply checks passed. No production records were inventoried for assignment or assigned. |
| Repository | Candidate secret/private-key scan passed for 30 intended files; redacted Gitleaks candidate scan passed and history scan found no leaks across 9 `main..HEAD` commits. Changes remain uncommitted; final diff review and local checkpoint are pending. |

Debian tracker still lists Trixie as vulnerable/unfixed and signed package metadata
offered no newer Trixie zlib. Upstream has a corrective commit, but no supported
Debian package fix was available in the checked repository. Debian tracker history
records that the security team retained the affected status conservatively while
awaiting upstream/maintainer confirmation; package-source comparison suggests a
classification mismatch but does not clear the scanner finding or Node's embedded
copy. Risk remains **unresolved and not accepted**.

The previous checkpoint estimate was 95%. The latest estimate above is **96%
complete / 4% remaining**, not a test pass ratio or release approval. Remaining
engineering effort is roughly **8-16 hours**, excluding vendor patch/adjudication
waiting, operator approvals, destination procurement and maintenance windows.
Provider cancellation/unknown outcomes and distributed budgets remain documented
limits.

## Workstream disposition

| Workstream | Implemented and verified | Remaining gate / status |
|---|---|---|
| A: container findings | Rebuilt independent backend candidate after account fixes; fresh Scout of both final candidates; exact package/base/runtime identities; signed Debian index availability check; fail-closed immutable-image scan tool and tests | **Blocked:** CVE-2026-85091, one HIGH per image; no supported Trixie package offered, no waiver |
| B: database roles | Separate migrator/runtime/backup/operator design, inventory/SQL tooling, explicit grants, ownership/default ACLs/search path; actual SQLAlchemy API/journal/auth tests and denied privileges | **Tested in isolation:** production role credentials, old-role cleanup and rollout require approval |
| C: encrypted backups | Binary-safe custom-format archive, authenticated encryption, checksums, exclusive local delivery, decryption/restore, key generation, freshness/failure monitor and tests | **Tested in isolation:** no off-host destination configured; custody, ACLs, schedule/alerts, retention and representative-size recovery acceptance outstanding |
| D: combined rehearsal | Synthetic legacy upgrades, offline account/durable browser exercise, role-separated runtime and local encrypted disaster recovery; crash/ownership recovery covered by PostgreSQL suites | **Isolated acceptance only:** actual private deployment topology, trusted client HTTPS and off-host recovery remain operator acceptance |
| E: focused security audit | Argon2/session/Origin/CSRF/throttling/ownership tests, safe Markdown and telemetry inspection, request-body limits, static/dependency/image/secret checks; corrected account production-error boundary and duplicate rate admission | **Residual findings retained:** image CVE, per-process admission/budgets, synchronous provider cancellation, absent restrictive script CSP |
| F: automation/runbooks | Read-only preflight, inactive role overlay, role/backup/security/combined cutover/rollback/recovery/monitoring runbooks, CI role and encrypted synthetic-backup jobs | **Prepared, not activated:** hosted CI and scheduled operational jobs have not run |
| G: tests | Full offline platform suites plus dedicated privilege, encrypted restore and browser exercises; exact results below | Known XFAIL and explicitly guarded fixture skips retained |
| H/I: reconciliation/checkpoint | Verification and rollout documents updated to this continuation; source review is ongoing | Final candidate/history secret scans and local checkpoint are pending; no remote publication or production approval implied |

## Security findings and final image identities

| Candidate | Immutable image ID | HIGH / CRITICAL | Other Scout findings |
|---|---|---|---|
| Backend `v2-four-blockers-review` | `sha256:5bd868922bf34d44126f4b8c97243216d5cf5245c48d1243b7b3260046077c26` | **1 / 0** | 6 MEDIUM, 27 LOW |
| Frontend `v2-four-blockers-review` | `sha256:1b07add53c68f430329b58cc8f00920c9ef4f5baa3909405e030750c457fbfe6` | **1 / 0** | 1 MEDIUM, 26 LOW |

Both HIGH findings are **CVE-2026-85091**. Fresh Scout SARIF source is Debian,
affected range `>0`, fixed version `not fixed`; the installed shared package is
`zlib1g:amd64 1:1.3.dfsg+really1.3.1-1+b1`. The component is present. Source
applicability mismatch evidence is not vendor adjudication or a clean scan.
See [finding disposition and monitoring](V2_SECURITY_DISPOSITION.md) and
[image triage](V2_IMAGE_TRIAGE.md). No CVE suppression was added.

## Verification and limits

Current detailed counts and ignored evidence locations are maintained at the top
of [V2_VERIFICATION.md](V2_VERIFICATION.md). Lower sections there are historical.
Full suites include offline mocked providers; no result proves live Gemini
availability, paid-call cancellation or production migration/traffic behavior.
The preserved XFAIL concerns synchronous provider cancellation. SQLAlchemy's 18
SQLite expression-index reflection warnings do not stand in for PostgreSQL tests.

An additional isolated TLS/application-rollback drill ran the actual prior
account-aware image `v2-accounts-resume-review` without a current application-source
bind mount, in production mode with durable disabled and final frontend behind Caddy. A
synthetic CA trusted only within its SSLContext verified page/ready 200, anonymous
dashboard 401 and docs 404. All 15 table snapshots, one owned legacy task and one
committed journal survived. Trusted HTTPS login, authenticated reads, CSRF logout,
revoked-cookie rejection and production cookie flags passed with a urllib cookie
client. Actual-browser acceptance on the intended production ingress and any
different rollback image still require verification. V1 bearer mode must never
serve owned multi-user records as normal rollback.

Backup testing proves authenticated encryption and exact synthetic restore, not
real remote storage or a measured production RPO/RTO. Fernet archives are capped
at **256 MiB**; larger real backups require a reviewed streaming adapter and
another recovery drill. Logical backups do not implement WAL/PITR. Restores use
new empty, explicitly named isolated targets and rebuild reviewed ownership/ACLs.

The runtime database role can access multiple users' application rows through SQL;
ownership is enforced by the application, not PostgreSQL RLS. Runtime cannot
provision accounts, change account roles/enabled flags or assign legacy ownership.
Use approved offline migration/operator credentials for those operations.

Frontend security inspection found raw HTML disabled, model images rendered as
text and safe citation URL filtering. Account sessions stay in HttpOnly cookies;
CSRF is in client memory and account metadata/idempotency records use sessionStorage.
Legacy bearer sessionStorage remains an inactive-for-accounts compatibility risk.
Caddy has nosniff, no-referrer, frame denial and API no-store; no restrictive script
CSP is claimed. A nonce-based Next CSP needs separate compatibility/browser review.

## Remaining operator decisions

1. Resolve the zlib finding with supported remediation/vendor adjudication, or
   explicitly accept a time-limited, named-owner security risk for both images.
2. Approve database/server identity, role credentials and rotation, old-role
   privilege cleanup and migration/operator secret custody.
3. Select the real off-host destination and encrypted transport, key custody/ACLs,
   retention/immutability, schedule/failure alerts, backup-size limit and RPO/RTO.
4. Approve legacy record-to-owner manifests, administrative identities and
   account-recovery custodians. No real records were assigned here.
5. Accept hosted CI, private HTTPS/client trust, intended-topology and independent
   restore evidence; select maintenance window and rollback thresholds.
6. Authorize production migrations, authentication activation, durable activation,
   deployment, any separately bounded paid acceptance, and final release acceptance.

Use [database rollout](V2_DATABASE_ROLES.md),
[encrypted backup/recovery](V2_ENCRYPTED_BACKUP_RUNBOOK.md), and
[combined cutover/rollback/emergency monitoring](V2_COMBINED_RELEASE_RUNBOOK.md).
No command in these documents is permission to perform production cutover.
