## Focused CI follow-up — 2026-11-01, source `8decc508`

Latest local and remote branch refs were both `8decc5082a80fb4af4919d7a3b7d0b10e628ace5` before this focused follow-up. Push run [41316291820](https://github.com/yogesh1164/LLM/actions/runs/41316291820) and PR run [41316295540](https://github.com/yogesh1164/LLM/actions/runs/41316295540) both completed with exactly three failed job types: `dependency-audit`, `images (backend)`, and `images (frontend)`. The backend/frontend functional jobs, PostgreSQL jobs, encrypted-backup drill, Compose validation and hosted secret scan passed in both runs.

The hosted dependency job passed `pip-audit` on both events. The failure is `npm audit --audit-level=low`: 16 moderate instances of GHSA-g3hv-75wg-m249 through minimatch 3.1.5 and 10.2.6. The advisory lists minimatch 11.0.1 as fixed; the installed consumers use incompatible 3.x/10.x APIs/ranges. A runtime probe of minimatch 11.0.1 confirmed its CommonJS export is an object rather than the callable v3 export. `npm audit fix --force` proposed a breaking `@eslint/eslintrc` downgrade. No override, forced upgrade, dependency removal, threshold change or scan bypass was made. This remains an actual CI blocker pending a compatible upstream release or a separately reviewed toolchain migration.

Hosted Grype used 0.97.1 and DB archive `vulnerability-db_v6.1.10_2026-11-01T00:24:34Z_1793514012` (SHA-256 `d0e1af9e6491440e1a671d0a0aafc32c5c7cb5cda787dcec3482799ef298f31c`). Push backend manifest digest was `sha256:6fb7cc12c378b59b5394dd86facc075b1afd3414a13d842571b7297bcffda5f2`; PR backend was `sha256:45f56184740551dadbce1e825347d322a7599ddfb6573d984a49feb9b9adcab1`. Each had 15 distinct HIGH CVEs and one CRITICAL, `CVE-2026-115557`, on Python 3.12.15 (Grype listed 3.12.16 as fixed). Push frontend was `sha256:c313a11c3891efa3c65cde53d453bdcce1aacb5818edc0892f244ae290621205`; PR frontend was `sha256:1bec8bdd8e0c0bc1ef875584352cb898c16bb0c629f058f9a7a1fd7e72c1c48a`. Each had 15 HIGH and zero CRITICAL. Full hosted package/CVE inventory is in [V2_GRYPE_CVE_INVENTORY.md](V2_GRYPE_CVE_INVENTORY.md).

Safe base updates were applied to the local candidate: Python slim Trixie is pinned to official manifest `sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159` (Python 3.12.16); Node 22 slim Trixie is pinned to `sha256:2117f713a417f3aff682ac8f5bc2ebbdf1beed51f36e67ab1e0fd3866b6d2d8f` (Node 22.23.4). Both candidate images built. Backend reports system and virtualenv `pip 26.2.2`, `pyasn1 0.6.5`; the final Grype report has no pip or pyasn1 matches; `/api/health` and `/api/ready` returned 200. Frontend image build passed and `/` returned 200. Candidate image manifest digests and refreshed Grype result are recorded in the CVE inventory below. The candidate still fails the raw HIGH/CRITICAL cutoff; no findings are suppressed.

Focused verification: backend suite **347 passed, 36 skipped, 1 XFAIL**; frontend **29 passed, 3 skipped**; frontend lint, TypeScript, encoding check and production image build passed. Python audit passed on hosted push and PR; npm audit remains failing as described. Candidate local Grype scan ran with the exact hosted Grype version and verified DB checksum. Hosted GitHub CI for the new local checkpoint is pending because no push was made. No production systems, credentials, volumes or environment files were changed; no provider calls were made.

# V2 production-readiness evidence — 2026-10-25

## Focused GitHub CI failure follow-up — 2026-11-01

Inspected push run [41314507014](https://github.com/yogesh1164/LLM/actions/runs/41314507014)
and PR run [41314511005](https://github.com/yogesh1164/LLM/actions/runs/41314511005),
both for source commit `c7125f07e2af2d58923450850d7f860150a7a680`. The failed
jobs are `dependency-audit`, `images (backend)` and `images (frontend)` in both
runs. Image Dockerfile lint/build steps succeeded; Grype failed at the configured
HIGH cutoff. Exact scan digests, DB version, CVEs and package versions are in
[V2_GRYPE_CVE_INVENTORY.md](V2_GRYPE_CVE_INVENTORY.md).

The hosted Python audit identified `pyasn1 0.6.4` with four HIGH advisories,
all fixed in 0.6.5. `backend/constraints.txt` now pins 0.6.5. The hosted run
stopped at that failing command, so its npm audit step was skipped. Local npm
audit found 16 moderate instances of GHSA-g3hv-75wg-m249 through minimatch
3.1.5 and 10.2.6 in the ESLint toolchain. The only advisory-wide fixed version
reported is minimatch 11.0.1; current consumers declare incompatible 3.x/10.x
ranges. `npm audit fix --dry-run` did not produce a nonbreaking fix and proposed
a breaking ESLint config downgrade under `--force`; no override, downgrade or
audit threshold change was applied ([minimatch advisory](https://github.com/advisories/GHSA-g3hv-75wg-m249)).
This is an additional unresolved dependency-audit blocker that hosted CI did not reach.

The backend image scan also reports pip 25.0.1 with several MEDIUM GHSAs and
fixed versions up to 26.2.0. `backend/Dockerfile` now upgrades the builder
virtual environment pip to 26.2.2. This source-level change and the pyasn1
upgrade have not been rebuilt/scanned locally: the Docker Desktop daemon is
unavailable. Debian base-package HIGH findings remain unresolved with no
supported Trixie fixes in the current inventory. The scanner gate was not
weakened or suppressed.

Verification after the dependency changes: backend suite **347 passed, 36
skipped, 1 XFAIL**; backup suite **31 passed, 6 skipped**; Ruff and `pip check`
passed; a fresh isolated Python 3.12 environment matching CI dependencies with
the updated pyasn1 and pip 26.2.2 reported **no known Python vulnerabilities**.
The existing GitHub frontend job passed lint, TypeScript, encoding, production
build and Playwright on source `c7125f0`; local `npm audit --audit-level=low`
failed on the unresolved minimatch advisory. `npm audit fix --dry-run` and
current Grype scan results were reviewed; no frontend dependency change was
made. Local candidate image builds and scans could not run because Docker is
unavailable.

No push, merge, deployment, production change or paid provider call occurred.
Gitleaks 8.24.3 scanned the complete Git history (24 commits) and the four
modified source/evidence files staged in a temporary scan directory; both scans
reported no leaks. The verified local checkpoint is recorded in Git.

The following release review predates inspection of the latest hosted CI logs;
the focused follow-up above supersedes its CI and image findings.

## Final release-blocker review — 2026-11-01

Reviewed candidate: `0c1c6924704aa7a2fefa1755db2db590ff4991fe` on
`feature/v2-production-hardening` (same as `origin/feature/v2-production-hardening`
at inspection). Worktree was clean before this review. Current release status:
**NOT READY**. Operator-facing dispositions and required approvals are in
[V2_FINAL_OPERATOR_RISK_REVIEW.md](V2_FINAL_OPERATOR_RISK_REVIEW.md).

| Check | Result on this candidate |
|---|---|
| Backend regression | **347 passed, 36 skipped, 1 XFAIL**, 72.32 s; 46 SQLAlchemy reflection warnings. PostgreSQL/Docker-guarded coverage did not run in this host session. |
| Backend static/dependencies | Ruff passed for `backend deploy ops`; `pip check` passed. |
| Frontend static/build | ESLint passed; TypeScript `tsc --noEmit` passed; encoding check passed for 9 files; Next.js 16.4.2 production build passed. |
| Frontend integration | Playwright enumerated all 32 cases but did not return a summary or exit after the cases completed. The process was interrupted. **Current-run result is incomplete and not counted as a pass.** |
| Docker/PostgreSQL/image security | Docker CLI/daemon unavailable. No isolated PostgreSQL 16 rerun, candidate image build/smoke, Compose validation, Grype scan, same-digest scanner comparison, backup/restore container rehearsal or deployment rollback rehearsal was possible. |
| GitHub hosted CI | **Pending/unconfirmed for this exact commit.** GitHub CLI could not read its user configuration (access denied); no claim is made that current hosted CI passed. |
| Backup and Drive | Existing local synthetic age/restore and local-rclone adapter evidence remains valid for its documented scope. No OAuth repair, Google Drive transfer/readback or independent off-host restore was performed. |
| Production state | No database, role, credential, service, volume, real environment file, legacy record, or production backup was accessed or changed. No production launch or provider request occurred. |

The most recent hosted Grype evidence remains the 2026-10-25 scan of different
source commit `0aab361564f35979e92d4472998fb24687167e71` and different ephemeral
image digests. It reported 14 HIGH CVEs per image, zero CRITICAL, using Grype
0.97.1 and DB v6.1.10. Those counts are not current-candidate scan results.
No supported package changes were applied. On 2026-11-01 Debian's tracker still
marked Trixie's zlib package vulnerable and showed a fix only in Sid; all
findings remain unsuppressed and unaccepted. See the precise inventory and
[operator risk review](V2_FINAL_OPERATOR_RISK_REVIEW.md).

Google Drive is pending private OAuth repair, an operator-selected `drive.file`
compatible folder/scope, explicit synthetic transfer authorization, and a
successful download/checksum/decryption/isolated restore. Production database
role changes remain unapproved; the last documented read-only catalog showed
the legacy application role overprivileged at revision 0005. Migrations 0006
and 0007, account activation, administrator provisioning and durable execution
remain production-inactive. Legacy data remains unassigned and quarantined.

No GitHub hosted result is verified for this exact commit. This review changes
only the two release-evidence documents; the changes are prepared for a local
documentation checkpoint. Release remains **NOT READY** pending security
disposition, real off-host recovery acceptance, approved least-privilege role
rollout, controlled migration/auth activation, successful exact-candidate CI and
production acceptance.

## Five-blocker engineering continuation — 2026-10-25

Baseline `0aab361564f35979e92d4472998fb24687167e71` was clean on
`feature/v2-production-hardening`; the remote branch matched it. No production
or development database, service, volume, environment file, Google account,
backup or ownership record was changed. No push, merge, deployment, OAuth
exchange or paid Gemini request occurred.

| Gate | Current result |
|---|---|
| Image security | Hosted CI at `0aab361`: [run 40164676589](https://github.com/yogesh1164/LLM/actions/runs/40164676589) and [run 40164674211](https://github.com/yogesh1164/LLM/actions/runs/40164674211) each passed eight jobs and failed the two image HIGH gates. Latest Grype 0.97.1 / DB v6.1.10 found **14 distinct HIGH CVEs, 0 CRITICAL** per image (55 backend and 54 frontend affected-package rows). Full IDs, versions, digests, fix status and the non-equivalent older Scout comparison are in [the inventory](V2_GRYPE_CVE_INVENTORY.md). Debian has no supported Trixie fixes for these findings as checked; no image rebuild or waiver. |
| Google Drive | Local adapter accepts only canonical age-named ciphertext and matching manifest. New report-path protection and readback-failure test pass. OAuth credentials await operator repair; Drive delivery and off-host recovery are **BLOCKED BY OPERATOR / UNVERIFIED**. `drive.file` may not access the web-created folder; operator destination/scope decision required. |
| Playwright | Two full Windows runs each **29 passed, 3 guarded skips, 0 failed**, normal process exit (42.2 s and 30.4 s). The earlier teardown hang was not reproduced; no timeout or test skip was added. |
| PostgreSQL roles | Offline role and migration package reviewed; previous disposable PostgreSQL 16 and hosted CI tests passed. Local Docker daemon unavailable, so no new PostgreSQL fixture run. Production remains revision 0005 with overprivileged shared role per last read-only audit; rollout not approved. |
| Legacy ownership | Empty quarantine selection template added. Prior synthetic ownership, isolation, replay and concurrency tests remain valid; Windows full suite passed. Production legacy records remain unassigned and quarantined. |
| Local regression | Windows backend/backup **377 passed, 42 skipped, 1 XFAIL**; focused rclone **11 passed**. Ruff, pip check, ESLint, TypeScript, encoding, frontend production build and quiet Compose config passed; npm audit found 0 vulnerabilities. Local pip-audit module and Docker daemon unavailable; hosted CI passed dependency audit, containerized tests, Compose, Hadolint and secret scan at `0aab361`. |

Engineering completion estimate remains **96%** because the release-critical
security, live off-host recovery and production activation gates are unresolved.
Status: **NOT READY**. Required operator decisions are Drive credential/destination
authorization, a supported security remediation or explicit scoped risk decision,
production role/credential/migration activation approval and recovery plan. The
operator has chosen to leave legacy records unassigned; no mapping approval is
needed to preserve quarantine, but account access to those records remains absent.

## Earlier recovery continuation — 2026-10-25

Recovered the six uncommitted source/test/doc files from the interrupted session
without resetting them. No production/development database, role, volume, service,
real environment file, Google Drive account, or real backup was accessed or
changed. No push, merge, deployment, OAuth exchange or paid provider call occurred.
Engineering estimate remains **96% complete**; release remains **NOT READY**.

The rclone adapter now uses `copyto` for the one canonical `.age` artifact and
`check --download --one-way` on the two containing folders, filtered to that exact
filename. A real rclone v1.75.1 local-only remote with a temporary, credential-free
config verified the command sequence and full readback. The first local trial
exposed that `rclone check` rejects file-to-file paths; that implementation error
was corrected. The successful local trial used synthetic bytes with an age header
and matching test manifest, so it validates transfer plumbing only. Previous
authenticated age encryption/recovery evidence remains below. Actual Google Drive
delivery and independent off-host recovery are **NOT VERIFIED**.

GitHub Actions was inspected read-only for two completed runs of the pushed
`c08ceeda4ea93a3113e5daa30ca2199481c48cf9` checkpoint:
[run 40104661375](https://github.com/yogesh1164/LLM/actions/runs/40104661375)
and [run 40104665005](https://github.com/yogesh1164/LLM/actions/runs/40104665005).
In each run, backend, frontend/Playwright, least-privilege PostgreSQL, durable
PostgreSQL, synthetic encrypted backup/restore, dependency audit, Compose and
secret-scan jobs **passed**. Both backend and frontend image jobs **failed** at
Anchore/Grype's high-severity gate after successful lint/build steps. These runs
do not cover the new unpushed rclone adapter.

Grype listed **14 distinct HIGH CVE IDs per image, 0 CRITICAL** in the hosted
image logs: CVE-2025-69720, CVE-2026-102010, CVE-2026-19499,
CVE-2026-5435, CVE-2026-54369, CVE-2026-54370, CVE-2026-76642,
CVE-2026-78408, CVE-2026-78409, CVE-2026-78410, CVE-2026-82560,
CVE-2026-85091, CVE-2026-9538 and CVE-2026-95619. Multiple packages can map
to one ID. The earlier immutable-image Docker Scout report below counted one
HIGH per image; scanner coverage/classification differs. **All hosted findings
remain open, unsuppressed and unaccepted.** Grype identified `zlib1g`
`1:1.3.dfsg+really1.3.1-1+b1` in both images. On 2026-10-25 the
[Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091)
still marks Trixie vulnerable/unfixed, and the
[Debian package page](https://packages.debian.org/trixie/amd64/zlib1g)
still lists that amd64 package. There was no supported zlib package remediation
to justify a rebuild. No image was rebuilt or rescanned in this continuation.

PostgreSQL role readiness and legacy ownership remain verified only in the
synthetic/isolated evidence below. Production legacy records stay unassigned.
The new local checkpoint is source preparation, not approval for credentials,
roles, backup scheduling/retention, ownership mapping, auth/durable activation,
image-risk acceptance or production cutover.

**NOT READY.** This is an undeployed release candidate on
`feature/v2-production-hardening`, continued from `62234f9`.
Production/development databases, roles, volumes, services and real environment
files remain unchanged. Nothing was pushed, merged, deployed or publicly exposed;
all provider calls in the engineering fixtures were offline doubles.

## Previous continuation — 2026-10-24

This session started from clean checkpoint `c08ceeda4ea93a3113e5daa30ca2199481c48cf9`.
The branch is pushed: a read-only `git ls-remote` confirmed GitHub's branch ref
matched that commit. No code push, merge, production access, OAuth authentication,
Drive access, backup upload, database mutation, paid provider call or deployment
occurred in this continuation.

| Workstream | Current result |
|---|---|
| rclone preparation | Added an opt-in adapter restricted to one canonical `.age` file with a matching manifest; mocked copy and full `rclone check --download` tests passed. PowerShell 5.1 invocation and separate download/decrypt/new-database restore steps documented. Actual Drive transfer, readback and recovery remain **NOT VERIFIED**. Retention remains operator-managed; adapter has no remote deletion path. |
| Windows regression | **376 passed, 43 skipped, 1 XFAIL**, 46 SQLite reflection warnings, 52.96s. Skips include PostgreSQL and guarded Linux/image fixtures. The retained XFAIL is synchronous provider cancellation. |
| Backup/transfer regression | **24 passed**, covering mocked rclone adapter, local encryption delivery and retention. Ruff passed on the changed Python files and the whole backend/deploy/ops tree. `pip check` passed. |
| Frontend | ESLint, TypeScript, encoding check, production build passed. Playwright reported **29 passed, 3 guarded skips**; the runner hung during teardown after all listed tests, so it was interrupted before a final process exit. No paid provider calls. npm audit: **0 vulnerabilities**. |
| PostgreSQL | No isolated server/container is available in this session. Previous isolated PostgreSQL role, authentication, journal, restore and ownership results remain documented below; no database was touched. |
| Image security | Docker/Scout are unavailable here; no image was rebuilt or rescanned. Prior immutable review-image scans still report one HIGH CVE-2026-85091 per image, zero CRITICAL. Debian tracker on this date still marks Trixie vulnerable/unfixed; published amd64 package remains `1:1.3.dfsg+really1.3.1-1+b1`. No remediation or waiver. |
| GitHub CI | Remote branch presence verified. Hosted Actions could not be fetched, so workflow status/failures remain **UNVERIFIED**. |
| Python advisory audit | `pip-audit` is not installed in the available Windows venv; prior final-image audit remains the only recorded Python audit result. |

Hosted Actions and the Drive destination require later verification. This is not
production readiness. Current local checkpoint and full result details are in
[V2_CHECKPOINT.md](V2_CHECKPOINT.md) and [V2_VERIFICATION.md](V2_VERIFICATION.md).

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

## Current verification addendum - 2026-11-02

At review start, `feature/v2-production-hardening`, local HEAD and origin pointed to `5049730e3fd5ae3dec9286844058e43b29805322`; worktree was clean. Hosted [push 41464293507](https://github.com/yogesh1164/LLM/actions/runs/41464293507) and [PR 41464303432](https://github.com/yogesh1164/LLM/actions/runs/41464303432) fail `dependency-audit` and both image security jobs; all other jobs pass. Current Grype is 18 HIGH / 0 CRITICAL per image, on exact digests and DB metadata recorded in `V2_CI_SECURITY_BLOCKER_REVIEW.md`. npm audit is 16 moderate instances / 0 high / 0 critical, one minimatch advisory in dev tooling. No CVE or threshold was suppressed.

Local frontend ESLint, TypeScript, encoding checks passed. Isolated backend and frontend candidate Docker builds passed; first isolated-network frontend attempt failed transient npm `ECONNRESET`, host-network retry passed. Local Playwright: 29 passed, 3 skipped, 33.9 seconds, normal exit using isolated `NEXT_DIST_DIR=.next-playwright-security-20261102`; no previous shutdown hang reproduced. Hosted CI passed backend unit, durable Postgres, least-privilege Postgres, backup, frontend, secrets and Compose jobs. Grype v0.121.0 was verified locally, but its DB update could not complete; no local fresh-database scan is claimed. Exact hosted digest scans are the fresh image baseline.

`security/evidence/2026-11-02` contains npm audit/tree JSON, hosted run metadata and raw job logs. Parsed Grype findings are derived from text logs because the current action did not emit JSON/SBOM. No production tag, service, database, volume, environment file or credential was modified.
