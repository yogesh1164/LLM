# V2 review-image vulnerability triage

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
