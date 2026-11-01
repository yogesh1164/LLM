# AgentFlow AI v2.0 operator risk review

Review date: 2026-11-01
Candidate: `0c1c6924704aa7a2fefa1755db2db590ff4991fe` on
`feature/v2-production-hardening`
Decision: **NOT READY**

## Container findings

The latest available hosted Grype evidence is from 2026-10-25, for different
source commit `0aab361564f35979e92d4472998fb24687167e71` and ephemeral image
digests recorded in [V2_GRYPE_CVE_INVENTORY.md](V2_GRYPE_CVE_INVENTORY.md).
It reports 14 distinct HIGH CVEs per image, zero CRITICAL, with Grype 0.97.1
and vulnerability database v6.1.10. It is not evidence about images built from
this current candidate. The older Docker Scout 1-HIGH result used other image
digests and is not a like-for-like comparison. No current-candidate digest,
scanner database, rescan, or hosted CI result is available; findings are open,
not accepted, and unsuppressed.

The findings map to these Debian binary packages and source versions:

| Source package/version | Binary packages in the recorded scan | CVEs |
|---|---|---|
| ncurses `6.5+20250216-2` | `libtinfo6`, `ncurses-base`, `ncurses-bin`; backend also `libncursesw6` | CVE-2025-69720 |
| gcc-14 `14.2.0-19` | `gcc-14-base`, `libgcc-s1`, `libstdc++6` | CVE-2026-102010, CVE-2026-95619 |
| glibc `2.41-12+deb13u4` | `libc-bin`, `libc6` | CVE-2026-19499, CVE-2026-5435 |
| acl `2.3.2-2+b1` | `libacl1` | CVE-2026-54369, CVE-2026-54370 |
| util-linux `2.41.5-0+deb13u1` | `bsdutils`, `libblkid1`, `liblastlog2-2`, `libmount1`, `libsmartcols1`, `libuuid1`, `login`, `mount`, `util-linux` | CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410 |
| perl `5.40.1-6+deb13u1` | `perl-base` | CVE-2026-82560, CVE-2026-9538 |
| zlib `1:1.3.dfsg+really1.3.1-1+b1` | `zlib1g` | CVE-2026-85091 |

Grype's recorded fix column says `won't fix` for the first six source groups
and has no fix version for zlib. This is scanner evidence, not a vendor waiver.
No exploit proof or function-level reachability review is recorded for the
non-zlib findings; package presence and unresolved HIGH classification are the
evidence. The zlib review found no application calls to `gzprintf`, `gzvprintf`,
`gzwrite`, or nonblocking gzip output, but Python zlib and Node's embedded zlib
are present and that review does not establish non-exploitability. Debian's
current tracker page still marks Trixie's zlib vulnerable; it identifies a fix
in Sid, not a supported Trixie update. [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091),
[Trixie package version](https://packages.debian.org/trixie/amd64/zlib1g).

Recorded controls reduce exposure: backend non-root UID, read-only filesystem,
tmpfs scratch, dropped capabilities and no-new-privileges; frontend non-root
runtime, dropped capabilities and no-new-privileges; private ingress, HTTPS,
request limits, and application authorization boundaries. These are
compensating controls only. They do not fix the binaries or satisfy the HIGH
gate. Do not accept residual risk without a named security approver, scope,
expiry, monitoring date and documented rationale for every finding.

## Remaining release risks

- **Security decision / external vendor status:** no supported compatible Trixie
  updates were evidenced for the recorded findings; current-candidate rebuild,
  same-digest Grype/Scout comparison and current scanner databases remain
  necessary. Obtain fixes or explicit security-risk approval before release.
- **External service / operator credentials:** rclone's `agentflow-gdrive`
  OAuth is known to fail. Real Drive transfer, independent download, checksum,
  decrypt and isolated restore are unverified. Follow the OAuth steps in
  [V2_ENCRYPTED_BACKUP_RUNBOOK.md](V2_ENCRYPTED_BACKUP_RUNBOOK.md), then obtain
  explicit approval for a synthetic-only transfer and restore drill.
- **Production approval:** last documented read-only production inventory found
  the shared `agentflow` role SUPERUSER, CREATEDB, CREATEROLE, REPLICATION and
  BYPASSRLS at revision 0005. The role replacement plan is not approved or ready
  to apply. New isolated PostgreSQL 16 rehearsal and an approved encrypted
  recovery point are required before production role changes.
- **Production approval:** apply migrations 0006 and 0007 through the separately
  approved migration role, provision the initial administrator securely, enable
  account/durable flags only after controlled acceptance. Keep all legacy rows
  unassigned and quarantined per the operator's decision.
- **Hosted CI:** no GitHub Actions result is confirmed for this exact candidate.
  Current local CLI access was denied when it tried to read the user's GitHub
  CLI configuration. CI must pass for the eventual release commit, including
  the image security gate.

## Local checks on 2026-11-01

Frontend ESLint, TypeScript, encoding, production build and Playwright results,
plus backend tests and static checks, are recorded in
[V2_RELEASE_EVIDENCE.md](V2_RELEASE_EVIDENCE.md) after the current verification
run completes. Docker is unavailable in this environment; image builds/scans,
isolated PostgreSQL 16, Compose validation, backup recovery rehearsal and
deployment rollback rehearsal could not be rerun here. No production resource,
volume, database, environment file, credential, Drive remote or legacy record
was changed. No paid Gemini request was made.

## Operator decision

**Do not release or cut over.** Minimum approvals/evidence still needed:

1. Resolve all HIGH findings with supported fixes, or obtain documented
   risk-acceptance for the exact immutable candidate images.
2. Repair rclone OAuth privately; choose and restrict the Drive destination and
   scope; authorize the synthetic-only upload/download/recovery acceptance.
3. Approve the database role and credential rotation plan, encrypted restore
   checkpoint, migration window, and rollback/traffic-switch plan.
4. Approve account/authentication and durable-execution activation. Leave legacy
   records quarantined unless a separate record-specific ownership approval is
   made.
5. Pass hosted CI and production acceptance on the exact reviewed release
   candidate. No deployment authorization is implied by this review.
