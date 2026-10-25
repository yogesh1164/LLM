# CVE-2026-85091 — vulnerability assessment and pending acceptance

## 2026-10-25 review

Debian still marks Trixie `zlib1g 1:1.3.dfsg+really1.3.1-1+b1` vulnerable
and has [no fixed version](https://security-tracker.debian.org/tracker/CVE-2026-85091).
Hosted Grype 0.97.1 at `0aab361` also reports this HIGH in both images, among
13 other distinct HIGH IDs per image. Its backend/frontend image digests and
the full [package inventory](V2_GRYPE_CVE_INVENTORY.md) differ from the earlier
local Scout images below. No vendor adjudication, approved exception, supported
patch or new image scan has changed the **UNRESOLVED / NOT ACCEPTED** status.

Assessment ID: AF-V2-ZLIB-20261024. Status: **UNRESOLVED / NOT ACCEPTED**.
Prepared by engineering; no operator signature or security exception is implied.
Scope: independently built V2 backend/frontend review images, not a scan or change
to the running V1 deployment. Reassess before cutover and whenever either image changes.

Latest rebuilt candidates were rescanned after verifying immutable IDs:
backend `sha256:5bd868922bf34d44126f4b8c97243216d5cf5245c48d1243b7b3260046077c26`
and frontend `sha256:1b07add53c68f430329b58cc8f00920c9ef4f5baa3909405e030750c457fbfe6`.
Their latest counts are 1 HIGH/0 CRITICAL each (backend 6 MEDIUM/27 LOW;
frontend 1 MEDIUM/26 LOW). Full reports are ignored local evidence under
`backups/v2-four-rescan-{backend,frontend}/`.

## Evidence and classification

| Question | Evidence / conclusion |
|---|---|
| Present component | Both runtimes contain `zlib1g:amd64 1:1.3.dfsg+really1.3.1-1+b1`, architecture amd64. The component is present. |
| Runtime versions | Python loads system zlib 1.3.1. Node v22.23.4 reports a separate embedded `1.3.1-e00f703`; the system-library comparison does not adjudicate that copy. |
| Fresh scanner result | Docker Scout 1.26.0: 1 HIGH, 0 CRITICAL per image; CVE-2026-85091. SARIF security-severity 8.3, Debian source affected range `>0`, fixed version `not fixed`. Lower findings remain visible. |
| Vendor status | Debian's current tracker still marks Trixie and unstable unfixed. Its Oct. 3 tracker-history rationale says it conservatively retained Trixie as affected while awaiting upstream/maintainer confirmation because the overflow might predate nonblocking operations. This conflicts with the CVE's stated range and source comparison; do not infer a vendor false-positive disposition. |
| Package availability | A fresh signed-index update of trixie, trixie-updates and trixie-security succeeded with insecure repositories prohibited and any update failure fatal. Installed and candidate zlib versions are identical. |
| Supported base availability | Registry checks show the official Python 3.12 slim Trixie and Node 22 Trixie slim tags still resolve to the pinned index digests below. No newer base in these supported tracks was offered. |
| Changelog | Retained Debian source changelog starts with the May 2024 upstream 1.3.1 update; no fix for this CVE. The runtime base strips installed changelogs. |
| Source applicability | Earlier retained Debian/upstream comparison found matching 1.3.1 gzip writer sources without the later `gz_vacate`/retry-state implementation. Archive hashes match the downloaded `.dsc`, but those source downloads were not independently authenticated through a signed source index. |

The conflicting affected-range evidence supports a **suspected version-range
mismatch**, not a demonstrated complete-image false positive. Debian's security
team explicitly retained Trixie as affected conservatively pending confirmation;
the current tracker remains vulnerable/unfixed. No vendor adjudication, embedded
Node-copy proof or clean scanner result exists. Classification: **unresolved
HIGH**. Resolved findings: none. Approved false-positive dispositions: none. No
suppression, VEX override, package-metadata deletion, unsupported package
replacement or locally invented zlib patch was used.

Pinned base index digests:

- Python: `sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704`.
- Node: `sha256:8eb619e402eaede1748a3c8173bffab391592812e85136452f781741c7242ddf`.

Final application image identities and scan counts are recorded in the current
[release evidence](V2_RELEASE_EVIDENCE.md); acceptance must bind to those exact
immutable IDs, not mutable tag names.

## Exposure, likelihood and impact

The advisory describes native heap corruption requiring a particular sequence
of nonblocking gzip-output writes and formatted gzip writes after a stall.
Source searches of `backend/app` and `frontend/src` found no application use of
`gzopen`, `gzwrite`, `gzprintf` or `gzvprintf`, and no gzip-output device handling.
The application exposes workflow/account HTTP APIs rather than arbitrary native
compression calls, uploaded native programs, shell commands or device access.
Compression routines remain in dependencies; absence of direct source references
does not prove every library path unreachable.

Engineering likelihood assessment: **low observed direct reachability, incomplete
applicability confidence** under the current private-ingress configuration. This
is a qualitative source/configuration assessment, not an exploit test or revised
CVSS score. No malicious proof of concept was executed against services. Public
exposure, new compressed-file features, native extensions or process compromise
would require immediate reassessment.

Potential impact, if reachable: **high**. Native memory corruption can terminate
the affected process and may compromise data or execution within its container;
code execution for these exact binaries has not been demonstrated here. Backend
process compromise could expose provider credentials and all application rows
accessible to the shared runtime DB role. Least privilege limits DDL/admin rights,
but application ownership checks are not PostgreSQL RLS containment. Frontend
process compromise could affect served application content. Container isolation
reduces host exposure without eliminating application impact.

Residual assessment: **release-blocking uncertainty remains**. Functional tests,
private access and suspected version mismatch do not clear the HIGH finding.

## Applicable controls and verification

- Keep ingress private; no new public listener was created.
- Backend runs as uid 10001 with read-only root, tmpfs scratch, dropped capabilities
  and no-new-privileges. Frontend runs as node with dropped capabilities and
  no-new-privileges; production Compose does not claim its filesystem read-only.
- Both final Dockerfiles remove setuid/setgid regular-file bits while retaining
  package metadata. Networkless root inspections found none in the prior final
  images; rebuilt candidates are rescanned before checkpoint.
- Preserve Origin/CSRF, authentication/ownership, body-size and execution budgets.
  Do not add gzip writer/device APIs or arbitrary execution tooling as a workaround.
- Use separate migration/runtime/backup credentials; never expose migration or
  operator credentials through a shared application environment file.
- Maintain recoverable encrypted backups, image rollback references and redacted
  monitoring. Recovery does not remediate a vulnerable binary.

These controls mitigate exposure and impact; none patches zlib.

## Required disposition and monitoring

Preferred disposition is a supported vendor patch or vendor-confirmed corrected
classification, followed by base/package pin review, independent image rebuild,
final-layer version inspection, offline regression/TLS/CA checks and fresh scans
of both images. Do not mix unstable Debian packages into Trixie or clear the gate
using an unreviewed distro migration.

Check the Debian tracker/bug, official base manifests and signed package indexes
weekly and before every acceptance. Retain scanner output and image IDs; assign a
named monitoring owner before cutover. Existing scheduled CI is prepared but has
not run remotely for this checkpoint. Escalate a new reachable path or exploit
report immediately. A temporary exception, if separately approved, must expire
and trigger review rather than silently become permanent.

## Operator decision form — UNSIGNED

Decision: **pending**. Do not fill or approve this on behalf of the operator.

| Required approval field | Operator entry |
|---|---|
| Exact backend and frontend immutable IDs | Pending |
| Decision: wait/remediate or time-limited risk acceptance | Pending |
| Business justification and private deployment scope | Pending |
| Accepted native-memory/application-data residual risk | Pending |
| Evidence reviewed, including embedded Node-copy uncertainty | Pending |
| Required compensating controls and verification owner | Pending |
| Patch/advisory monitoring owner and review cadence | Pending |
| Expiry date, review date and withdrawal triggers | Pending |
| Authorized security/business approver and approval reference | Pending |
| Approval timestamp | Pending |

Approval would apply only to the recorded scope/IDs and would not authorize
database changes, ownership assignment, feature activation or deployment.

References: [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091),
[Debian bug](https://bugs.debian.org/1146895),
[Debian security-tracker status rationale](https://mail-archive.com/debian-security-tracker-commits%40alioth-lists.debian.net/msg86712.html),
[upstream correction](https://github.com/madler/zlib/commit/df84af25dc1942490e1d1c899a07619152a46148).
Fresh ignored evidence: `backups/v2-four-blockers-image-{backend,frontend}/`,
`backups/v2-four-zlib-policy.log`, `backups/v2-four-{python,node}-base.json`.
Earlier source comparison: `backups/v2-zlib-source-evidence/report.json`.
