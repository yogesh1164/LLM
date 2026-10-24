# V2 review-image vulnerability triage

## Latest rebuilt candidates and vendor-status review — 2026-10-24

The newest immutable review images were scanned by Docker Scout 1.26.0 after
verifying the expected image IDs. Backend `sha256:5bd868922bf34d44126f4b8c97243216d5cf5245c48d1243b7b3260046077c26` (amd64, uid 10001, Debian `zlib1g 1:1.3.dfsg+really1.3.1-1+b1`) reports **1 HIGH, 0 CRITICAL, 6 MEDIUM, 27 LOW**. Frontend `sha256:1b07add53c68f430329b58cc8f00920c9ef4f5baa3909405e030750c457fbfe6` (amd64, user `node`, same system zlib package) reports **1 HIGH, 0 CRITICAL, 1 MEDIUM, 26 LOW**. The sole HIGH in each is CVE-2026-85091. Both gates fail.

Rechecking Debian's tracker and security-tracker history found a genuine
classification dispute: the CVE description identifies the nonblocking gz writer
code introduced after upstream v1.3.1, and the packaged Trixie source comparison
does not contain `gz_vacate` or `state->again`; however, the Debian security team
explicitly recorded that it conservatively kept Trixie affected while awaiting
upstream/maintainer confirmation because it believed the overflow could predate
that code. Therefore this is **not** a proven false positive. The current Debian
tracker still marks Trixie vulnerable/unfixed; signed Trixie package metadata
offers no newer candidate. Upstream has a corrective commit, but no supported
Debian package carrying it was available. The Node embedded zlib copy has not been
vendor-adjudicated. Keep the combined finding **UNRESOLVED / NOT ACCEPTED**; do not
suppress it. See the [formal assessment](V2_ZLIB_RISK_ASSESSMENT.md).

Primary references: [Debian CVE tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091), [Debian security-tracker status rationale](https://mail-archive.com/debian-security-tracker-commits%40alioth-lists.debian.net/msg86712.html), [upstream fix](https://github.com/madler/zlib/commit/df84af25dc1942490e1d1c899a07619152a46148), and [upstream introduction of nonblocking gzip I/O](https://github.com/madler/zlib/commit/81cc0bebedd935daeb81b0b6e475d8786b51af3d).

## Final production-readiness scan: 2026-10-24

Fresh scans of backend `v2-mission-review` and frontend
`v2-accounts-resume-review` reproduce **1 HIGH / 0 CRITICAL each**,
**CVE-2026-85091**. The backend was rebuilt after two account middleware fixes;
the unchanged frontend image was rescanned. Final IDs, affected packages,
scanner ranges/source, signed-index package availability, runtime exposure and
vendor monitoring are in [security disposition](V2_SECURITY_DISPOSITION.md).
`deploy/image_security.py` retains full SARIF and returns exit 2 for this blocked
gate. No supported newer Trixie zlib package was offered. No finding was waived.

## Current Trixie review: 2026-10-24

The current Dockerfiles use pinned Python 3.12 / Node 22 Trixie bases. Separate
`v2-accounts-resume-review` image builds pass. Scout reports **one HIGH and zero
CRITICAL in each image**, reduced from nine backend/eight frontend highs on the
earlier Bookworm images. All currently reported findings are CVE-2026-85091 for
Debian zlib. No suppression, metadata deletion, scanner override or waiver exists.
The high-severity release gate remains **blocked**.

Primary-source investigation found:

- Installed backend package: `zlib1g 1:1.3.dfsg+really1.3.1-1+b1`; runtime 1.3.1.
  Its `/usr/lib/x86_64-linux-gnu/libz.so.1.3.1` SHA-256 is
  `85590dd58edf5445e18bc7193e5ebc01ac5841f1ae187e97705a662e90c6421e`.
  Final inspection confirms the frontend's Debian libz has the identical hash.
- Downloaded Debian source archives match their `.dsc` SHA-256 entries. All five
  `gz*.[ch]` source files match upstream v1.3.1 byte for byte. Neither `gz_vacate`
  nor `state->again` occurs in those files. The Debian patch series is empty.
- In that older writer, negative `write()` results produce fatal `Z_ERRNO`;
  `gzvprintf` returns when compression fails before its following `memmove`.
  The later retryable non-blocking implementation is a materially different path.
- Debian's CVE description names versions 1.3.1.2-1.3.2 and links the introducing
  [upstream commit](https://github.com/madler/zlib/commit/81cc0bebedd935daeb81b0b6e475d8786b51af3d),
  yet its [tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091)
  still classifies the Trixie package as vulnerable/unfixed.

This supports a possible affected-version classification mismatch; it is **not**
accepted vendor adjudication, proof for every embedded copy, or a clean scan.
Source retrieval used HTTPS and hashes from the Debian `.dsc`; independent signed
index/signature verification was not performed. Evidence is retained locally at
`backups/v2-zlib-source-evidence/report.json`, including source hashes. Upstream
source was read, not patched or installed. No vendor issue/comment was submitted.

Backend Python reports OpenSSL 3.5.7; frontend Node reports OpenSSL 3.5.9 and its
separate embedded zlib `1.3.1-e00f703`. The Node embedded copy is outside the Debian
binary comparison. Both final images retain package metadata and have no
setuid/setgid regular files. Obtain a vendor-supported correction/patched package
or a separately accepted applicability review; do not silently waive the gate.

## Historical Bookworm investigation

Reviewed 2026-10-24. Scope: separate, undeployed `v2-review-hardening` images
on the existing Bookworm digest pins. These findings do not describe a newly
scanned V1 production image. No scanner exceptions or package metadata removal.

## Vendor status and runtime evidence

| Findings | Vendor status | Review-image evidence and disposition |
|---|---|---|
| util-linux: CVE-2026-53613, CVE-2026-78409, CVE-2026-78410, CVE-2026-76642 | Bookworm remains vulnerable. Trixie fixes 53613 but retains the other three. | Privileged mount paths require local execution and additional fstab authorization. Both images have an unconfigured fstab. All regular-file setuid/setgid bits are now removed at build time. This reduces privilege-escalation paths; it does not patch the package. |
| util-linux: CVE-2026-78408 | Bookworm and Trixie remain vulnerable. | Requires privileged use of `nsenter --join-cgroup`. `nsenter` remains installed; application code does not invoke it. Existing app Compose settings drop all capabilities and prohibit new privileges. No host namespace access is configured. Retain the finding. |
| util-linux: CVE-2026-53615 | Bookworm vulnerable; Trixie fixed. | Crafted partition probing in libblkid. No application disk-image probing or host block-device mounts found. This is source/configuration reachability evidence, not an exploit test. |
| perl: CVE-2026-82560 | Debian still lists Bookworm, Trixie and unstable as vulnerable. | Both images contain `perl-base`; `/usr/share/perl/5.36/Pod/Text.pm` is absent. Application code does not format Perl POD. The source-package finding remains pending stronger component-level confirmation/vendor correction. |
| zlib: CVE-2026-85091 | Debian marks Bookworm/Trixie vulnerable; its own description gives affected versions 1.3.1.2–1.3.2. | Installed Debian zlib is 1.2.13 in both images; Python confirms runtime 1.2.13. Node reports its separate embedded zlib `1.3.1-e00f703`. The mismatch merits vendor clarification; no suppression or claim of a patched package. |
| OpenSSL: CVE-2026-84782 (backend only in Scout) | Bookworm 3.0.22 remains vulnerable. Upstream fixes 3.0.23 require premium support; supported 3.5 fixes are available. | Python uses OpenSSL 3.0.22. The advisory concerns DTLS; inspected application/provider transports use HTTP(S), with no DTLS code found. Frontend Node separately reports OpenSSL 3.5.9. Lack of an observed application DTLS path is not package remediation. |

Vendor references, checked on the review date:

- [Debian 53613](https://security-tracker.debian.org/tracker/CVE-2026-53613),
  [78409](https://security-tracker.debian.org/tracker/CVE-2026-78409),
  [78410](https://security-tracker.debian.org/tracker/CVE-2026-78410),
  [76642](https://security-tracker.debian.org/tracker/CVE-2026-76642),
  [78408](https://security-tracker.debian.org/tracker/CVE-2026-78408),
  [53615](https://security-tracker.debian.org/tracker/CVE-2026-53615).
- [Debian Perl](https://security-tracker.debian.org/tracker/CVE-2026-82560).
- [Debian zlib](https://security-tracker.debian.org/tracker/CVE-2026-85091)
  and [upstream affected-range discussion](https://github.com/madler/zlib/issues/1310).
- [Debian OpenSSL](https://security-tracker.debian.org/tracker/CVE-2026-84782)
  and [upstream advisory](https://openssl-library.org/news/secadv/20260929.txt).

## Remediation and release gate

Removing privileged mode bits is defense in depth. Package versions and scanner
visibility are preserved. Do not claim that this reduces advisory counts.
The image gate remains blocked while high findings remain.

A blanket distro upgrade is insufficient: Trixie still has util-linux, Perl and
zlib findings. The next image experiment should use separate tags and evaluate
a supported patched base plus a minimal runtime component set. Preserve the
Python minor version and Gemini 2.31.0; test native wheels, migrations on isolated
fixtures, TLS trust, non-root/read-only operation and frontend HTTP behavior.
Do not mix unstable Debian packages into Bookworm or force-remove essential
packages merely to alter scan results. Any component exception needs precise
version/path evidence and review; no such exception is enabled here.

## Inspection method and limits

Review containers have no network, no published ports, no database mounts and
read-only image filesystems. Verify image users separately from a root filesystem
walk: the walk needs root's normal read capabilities to inspect protected package
directories. Earlier walks as the app user or with all capabilities dropped failed
on unreadable directories; the corrected inspection passes on both images.
The walk skips other devices and symlinks and checks all regular-file setuid/setgid
mode bits. It is a configuration assertion, not a vulnerability exploit test.

Fresh Scout reports are retained under ignored `backups/`. Scout's normal report
generation exit code does not establish gate success: inspect high/critical
counts. The hosted Grype gate has not run because this branch has not been pushed.
