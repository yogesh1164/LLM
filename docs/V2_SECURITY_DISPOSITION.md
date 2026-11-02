# V2 security finding disposition and patch monitoring

Reviewed 2026-10-24. Release status: **NOT READY** while the image HIGH gate
is unresolved. No waiver, suppression, VEX override or production change is enabled.

## CVE-2026-85091

Fresh Docker Scout 1.26.0 reports retain **1 HIGH / 0 CRITICAL per image**.
The advisory source is Debian (`s=debian` in each SARIF rule's `helpUri`),
with source-package affected range `>0`, fixed version `not fixed`.
Backend additionally has 6 MEDIUM / 27 LOW; frontend 1 MEDIUM / 26 LOW.
These lower findings remain visible and are not excluded from the reports.

Both final runtimes contain `zlib1g:amd64`, version
`1:1.3.dfsg+really1.3.1-1+b1`, architecture amd64. This is a present shared
library, not an absent-package finding. Python loads zlib 1.3.1; Node separately
reports embedded zlib `1.3.1-e00f703`. Previous source comparison does not prove
the embedded Node copy unaffected.

Pinned base manifests:

- Backend: Python 3.12 slim Trixie,
  `sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704`.
- Frontend: Node 22 Trixie slim,
  `sha256:8eb619e402eaede1748a3c8173bffab391592812e85136452f781741c7242ddf`.

Debian's [tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091)
and [bug 1146895](https://bugs.debian.org/1146895) still mark Trixie unfixed.
The stated upstream range starts at 1.3.1.2; the
[upstream fix](https://github.com/madler/zlib/commit/df84af25dc1942490e1d1c899a07619152a46148)
changes the nonblocking gzip writer. The retained 1.3.1 source comparison in
V2_IMAGE_TRIAGE.md supports a possible classification mismatch only.

In a disposable container, `apt-get update -qq` verified the configured Debian
repository signatures and `apt-cache policy zlib1g` returned the installed version
as the candidate; no newer supported package was offered. This authenticates the
availability check, not the previously downloaded source archives. The runtime
image strips changelogs upstream; the retained source Debian tar's changelog
starts with the May 2024 1.3.1 upstream update and has no entry fixing this CVE.
No Debian package was installed or modified, and no unstable package was mixed in.

## Exposure and controls

Source review found no application use of `gzprintf`, `gzvprintf`, `gzwrite`,
or nonblocking gzip-output devices. Python's zlib and Node's embedded deflate
remain runtime components. This is reachability review, not an exploit proof or
a vendor-supported exclusion. Keep the unresolved finding visible.

Current backend has non-root uid 10001, read-only filesystem, tmpfs scratch,
all capabilities dropped and no-new-privileges. Frontend runs as node and drops
capabilities with no-new-privileges in Compose; its production filesystem is
not configured read-only. Both Dockerfiles remove setuid/setgid regular-file bits
and retain package metadata. No shell/host device or writable source mount is
provided to the application. Maintain private-only ingress, exact HTTPS origins,
request-body limits, ownership checks and input/output budgets. These controls
reduce exposure; none is presented as a zlib patch.

## Reproduce and monitor

Use the backend Python environment and a **new** ignored evidence directory:

```powershell
$reviewId = docker image inspect agentflow-backend:v2-mission-review --format '{{.Id}}'
backend\.venv\Scripts\python.exe deploy\image_security.py --image agentflow-backend:v2-mission-review --expected-image-id $reviewId --output backups\operator-backend-scan
$scanExit = $LASTEXITCODE
# 0 = high/critical gate passed; 2 = known findings; 1 = failed verification.
```

Repeat with frontend `v2-accounts-resume-review` and a different output directory.
The tool checks the selected immutable ID, invokes fresh Scout advisory lookup,
retains SARIF plus a summary, and inspects the package in a networkless,
read-only disposable container. It never uploads an image or alters services.
Scanner network access retrieves advisory data; no real database is involved.

Check the Debian tracker/bug, official base tags and signed Trixie/security package
indexes at least weekly and before every candidate acceptance. Existing scheduled
CI also rebuilds/scans weekly after an authorized push; hosted CI has not run for
this local checkpoint. When a supported fix is available: pin its base digest,
build independent review tags, inspect final package versions, run offline suites,
TLS/CA/non-root/readonly smoke checks and rerun this gate for both images.

The operator must either obtain vendor-supported remediation/adjudication or
approve a separate, explicit, time-limited risk disposition covering both shared
and embedded copies, with a named owner, expiry and review date. No such risk
acceptance is recorded. Do not treat this runbook or successful app tests as one.

## Current hosted scan and complete package match register - 2026-11-02

In addition to 18 unique HIGH CVEs, each exact hosted image scan reported 32 unique MEDIUM, 6 LOW, and 25 NEGLIGIBLE CVEs. Backend package-level rows: 180; frontend: 178. These are vulnerability matches, not unique affected components. All severities and affected Debian binary package/version/fix fields parsed from the hosted table are in `docs/security/evidence/2026-11-02/hosted-grype-findings.json`; raw unmodified job logs are beside it. The source action did not emit its native JSON, so the parsed data should be checked against the raw log before making per-package decisions.

The 32 MEDIUM CVEs (same set in each image) group by installed Debian package as follows. CVE links point to the official Debian tracker record; descriptions, affected code and release status are on those records. Grype listed `(won't fix)` for the package matches except where its table left the fix column blank. This means no scanner fixed version was reported; it is not a vendor risk acceptance.

| Component in final image | Installed version(s) | MEDIUM CVEs | Runtime/reachability notes |
|---|---|---|---|
| util-linux binaries/libraries | `2.41.5-0+deb13u1`; `login 1:4.16.0-2+really2.41.5-0+deb13u1` | [CVE-2026-3184](https://security-tracker.debian.org/tracker/CVE-2026-3184) | Local mount/helper and fstab option paths. Containers run non-root; Compose drops capabilities; Dockerfiles remove setuid bits. App does not invoke mount helpers. |
| tar | `1.35+dfsg-3.1` | [CVE-2026-5704](https://security-tracker.debian.org/tracker/CVE-2026-5704), [CVE-2026-18508](https://security-tracker.debian.org/tracker/CVE-2026-18508), [CVE-2026-18477](https://security-tracker.debian.org/tracker/CVE-2026-18477) | Archive parser conditions; app source does not invoke system `tar` or Perl `Archive::Tar`. No archive upload/restore route identified. |
| GCC 14 / C++ runtime | `14.2.0-19` | [CVE-2026-114691](https://security-tracker.debian.org/tracker/CVE-2026-114691), [CVE-2026-115455](https://security-tracker.debian.org/tracker/CVE-2026-115455), [CVE-2026-114690](https://security-tracker.debian.org/tracker/CVE-2026-114690) | Specific C++ runtime input/code paths; application source is Python/TypeScript and has no C++ modules. Package remains present in both images. |
| glibc | `2.41-12+deb13u4` | [CVE-2026-6238](https://security-tracker.debian.org/tracker/CVE-2026-6238), [CVE-2026-80489](https://security-tracker.debian.org/tracker/CVE-2026-80489), [CVE-2026-77117](https://security-tracker.debian.org/tracker/CVE-2026-77117), [CVE-2026-8674](https://security-tracker.debian.org/tracker/CVE-2026-8674), [CVE-2026-6791](https://security-tracker.debian.org/tracker/CVE-2026-6791), [CVE-2026-19542](https://security-tracker.debian.org/tracker/CVE-2026-19542), [CVE-2026-89092](https://security-tracker.debian.org/tracker/CVE-2026-89092), [CVE-2026-86805](https://security-tracker.debian.org/tracker/CVE-2026-86805), [CVE-2026-18374](https://security-tracker.debian.org/tracker/CVE-2026-18374) | Core runtime is loaded; each advisory has a narrower affected libc function/condition. No blanket claim of non-reachability is made; app/network input-to-function paths need per-advisory review before any launch. |
| libpam-modules | `1.7.0-5` | [CVE-2026-54411](https://security-tracker.debian.org/tracker/CVE-2026-54411) | PAM local authentication module; FastAPI/Next.js authenticate through application sessions, not PAM. No PAM caller in source. |
| zlib | `1:1.3.dfsg+really1.3.1-1+b1` | [CVE-2026-27171](https://security-tracker.debian.org/tracker/CVE-2026-27171) | Shared library is present and loaded; advisory-specific affected API path was not found in app source. See the separate CVE-2026-85091 review for gzip writer analysis; do not infer this advisory is the same issue. |
| ncurses | `6.5+20250216-2` | [CVE-2025-6141](https://security-tracker.debian.org/tracker/CVE-2025-6141) | ncurses utility/library path; app does not invoke ncurses/infocmp. |
| perl-base | `5.40.1-6+deb13u1` | [CVE-2026-15534](https://security-tracker.debian.org/tracker/CVE-2026-15534) | Requires a roughly 286 MB attacker-controlled regex subject and a matching pattern with 15 participating nodes. Perl is present, but no app path invokes Perl. |
| systemd shared library | `257.13-1~deb13u1` | [CVE-2026-15059](https://security-tracker.debian.org/tracker/CVE-2026-15059), [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | Image includes shared library, but no systemd service manager runs in the application container; app source has no direct systemd API. |
| SQLite | `3.46.1-7+deb13u2` | [CVE-2026-119371](https://security-tracker.debian.org/tracker/CVE-2026-119371), [CVE-2026-119372](https://security-tracker.debian.org/tracker/CVE-2026-119372), [CVE-2026-119375](https://security-tracker.debian.org/tracker/CVE-2026-119375), [CVE-2026-119376](https://security-tracker.debian.org/tracker/CVE-2026-119376), [CVE-2026-119378](https://security-tracker.debian.org/tracker/CVE-2026-119378), [CVE-2026-119591](https://security-tracker.debian.org/tracker/CVE-2026-119591), [CVE-2026-50812](https://security-tracker.debian.org/tracker/CVE-2026-50812), [CVE-2026-50813](https://security-tracker.debian.org/tracker/CVE-2026-50813) | Backend can use SQLite in tests and dialect-specific code, but production is configured for PostgreSQL and accepts no SQLite database upload. Frontend has no SQLite app code. Each malformed DB/API prerequisite remains advisory-specific. |
| libattr | `1:2.5.2-3` | [CVE-2026-54371](https://security-tracker.debian.org/tracker/CVE-2026-54371) | Local filesystem extended-attribute path; app does not call libattr. Non-root runtime and dropped capabilities reduce privilege impact. |
| bzip2 | `1.0.8-6` | [CVE-2026-42250](https://security-tracker.debian.org/tracker/CVE-2026-42250) | Shared compression library; no app source call to bzip2 was found. Exact affected API/input preconditions remain in linked vendor record. |

This register records package presence and observed application entry points; it
is not a formal exploitability proof. Findings with a specific unreachable
local/helper path have limited demonstrated exposure but remain unresolved.
The glibc and other generally loaded shared-library matches need advisory-by-
advisory reachability validation. Security owner approval is still required
before any residual risk decision. Review by 2026-11-09; earlier if Debian,
upstream or scanner advisory data changes.

## High-severity reachability register - current hosted image baseline

All of these HIGH matches are present in the hosted final-image package inventory. For source package/version and scanner fix fields, see the 180/178 package rows in the retained JSON. Debian tracker records currently list no fixed Trixie version for these findings. The linked records include the issue descriptions and any newer-suite fixes; no unsupported suite was introduced. Local candidate runtime probes showed UIDs 10001 (`agentflow`) and 1000 (`node`), no setuid/setgid regular files, and the following specific exposed components:

| CVE(s) | Installed package/version | Trigger prerequisite and application assessment |
|---|---|---|
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | ncurses `6.5+20250216-2` | Stack overflow in `infocmp` parsing crafted terminal data. `/usr/bin/infocmp` exists, but app code does not launch it and containers run non-root. |
| [CVE-2026-102010](https://security-tracker.debian.org/tracker/CVE-2026-102010), [CVE-2026-95619](https://security-tracker.debian.org/tracker/CVE-2026-95619) | GCC 14 runtime `14.2.0-19` (`libstdc++6`, `libgcc-s1`) | Require specific C++ `erase_if`/heap or aligned-allocation code paths and suitable triggering input. App source is Python/TypeScript with no bundled C++ modules; the runtime library remains in both images. |
| [CVE-2026-19499](https://security-tracker.debian.org/tracker/CVE-2026-19499), [CVE-2026-5435](https://security-tracker.debian.org/tracker/CVE-2026-5435) | glibc `2.41-12+deb13u4` | `strfmon` right-width buffer condition; deprecated DNS TSIG printing functions. App source has no calls to these APIs. glibc is a loaded core runtime; no advisory-specific caller path was identified. |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369), [CVE-2026-54370](https://security-tracker.debian.org/tracker/CVE-2026-54370) | acl `2.3.2-2+b1` | Local symlink replacement race against privileged path-based ACL operations. App does not call ACL APIs; runtime is non-root and all setuid/setgid file bits were removed. |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642), [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408), [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409), [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | util-linux `2.41.5-0+deb13u1` and its libraries | Require privileged mount/nsenter operations, attacker-controlled mount/fstab options or a privileged operator. Binaries are present but app does not invoke them; no setuid bits, root, or mount capabilities are provided to the app. |
| [CVE-2026-82560](https://security-tracker.debian.org/tracker/CVE-2026-82560) | perl-base `5.40.1-6+deb13u1` | Formatting hostile POD causes CPU/memory exhaustion. Perl exists, but `Pod/Text.pm` is absent from both final images and app code does not invoke Perl. Scanner source-package match does not demonstrate the vulnerable module is installed. |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | perl-base `5.40.1-6+deb13u1` | `Archive::Tar` allocation exhaustion from crafted oversized tar entry. `Archive/Tar.pm` is absent from both final images; app code does not invoke Perl or system tar. This is a package/source mapping discrepancy candidate; retain the finding pending scanner/vendor reconciliation. |
| [CVE-2026-84243](https://security-tracker.debian.org/tracker/CVE-2026-84243) | glibc `2.41-12+deb13u4` | Requires attacker influence over `LANGUAGE` and locale of a process calling gettext, enabling arbitrary catalog loads. The locale/environment is deployment-controlled, not request-controlled; no app path changes it. glibc is still present and loaded. |
| [CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091) | zlib `1:1.3.dfsg+really1.3.1-1+b1` | Requires nonblocking `gzwrite` stall followed by `gzprintf`/`gzvprintf` using stale buffers. Source review found no app calls to these APIs. Python zlib and Node's separate embedded copy remain; Debian marks Trixie vulnerable and this is not cleared by the source review. See the dedicated CVE section above. |
| [CVE-2026-119373](https://security-tracker.debian.org/tracker/CVE-2026-119373), [CVE-2026-119374](https://security-tracker.debian.org/tracker/CVE-2026-119374), [CVE-2026-119379](https://security-tracker.debian.org/tracker/CVE-2026-119379) | SQLite `3.46.1-7+deb13u2` | Crafted FTS5 database/prefix query, secure-delete of corrupt index, or malicious session changeset. Python SQLite support exists for test paths; production database is PostgreSQL and there is no database-file upload or changeset endpoint. Findings remain open. |

These are exposure assessments, not exploit proofs. Function-level absence and
non-root controls provide limited-exposure evidence for several rows; they do
not remove the package findings. The two Perl module absences and generic CPE
OpenSSL/gzip discrepancies should be taken to the scanner/advisory maintainers
with exact image digest and raw match. Do not suppress without the authorized
security owner's documented decision. Reassess on a supported Trixie patch or
by 2026-11-09, whichever comes first.
