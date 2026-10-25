# Hosted Grype HIGH inventory — 2026-10-25 review

This is a transcription of the **2026-10-25 hosted CI scan of source commit
`0aab361564f35979e92d4472998fb24687167e71`**, run
[40164676589](https://github.com/yogesh1164/LLM/actions/runs/40164676589).
Grype was **0.97.1**, vulnerability DB **v6.1.10**, built
**2026-10-24 17:45:29 UTC** (downloaded DB file timestamp
2026-10-24 00:30:17 UTC). The Ubuntu 24.04 runner built `linux/amd64`
images. The Grype image-read digest was backend
`sha256:4429d275428e696213093d4ae528a98b5c239a174b989c49d8345322f6ef0807`
and frontend
`sha256:265bfefc68d18ba6511d06cec0e63847f2307c5d8bfd15d201c975fea038feb9`.
The CI log reports **55 backend / 54 frontend HIGH package matches**, each
representing **14 distinct HIGH CVE IDs, 0 CRITICAL**. All HIGH matches are
Debian `deb` packages; no HIGH application dependency was listed. The count of
package matches must not be confused with the count of CVE IDs.
The prior [c08ceed run](https://github.com/yogesh1164/LLM/actions/runs/40104665005)
also found the same 14 IDs and 55/54 package matches at backend digest
`sha256:d7d89a76b751c0926e7dd85261ab42a19de18e47316cb8df6e87a6397732a2bc`
and frontend digest
`sha256:2708926d25b756a6216bf2966dc5163c9c0d679c4105cae3515e62925544bd6c`
with Grype 0.97.1 / DB v6.1.10 built 2026-10-23 06:30:15 UTC.

| CVE ID | Debian source | Affected binary packages in both images, except where noted |
|---|---|---|
| CVE-2025-69720 | ncurses 6.5+20250216-2 | libtinfo6, ncurses-base, ncurses-bin; backend also libncursesw6 |
| CVE-2026-102010 | gcc-14 14.2.0-19 | gcc-14-base, libgcc-s1, libstdc++6 |
| CVE-2026-19499 | glibc 2.41-12+deb13u4 | libc-bin, libc6 |
| CVE-2026-5435 | glibc 2.41-12+deb13u4 | libc-bin, libc6 |
| CVE-2026-54369 | acl 2.3.2-2+b1 | libacl1 |
| CVE-2026-54370 | acl 2.3.2-2+b1 | libacl1 |
| CVE-2026-76642 | util-linux 2.41.5-0+deb13u1 | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux |
| CVE-2026-78408 | util-linux 2.41.5-0+deb13u1 | same nine binary packages |
| CVE-2026-78409 | util-linux 2.41.5-0+deb13u1 | same nine binary packages |
| CVE-2026-78410 | util-linux 2.41.5-0+deb13u1 | same nine binary packages |
| CVE-2026-82560 | perl 5.40.1-6+deb13u1 | perl-base |
| CVE-2026-85091 | zlib 1:1.3.dfsg+really1.3.1-1+b1 | zlib1g |
| CVE-2026-9538 | perl 5.40.1-6+deb13u1 | perl-base |
| CVE-2026-95619 | gcc-14 14.2.0-19 | gcc-14-base, libgcc-s1, libstdc++6 |

For the util-linux family, Grype records `bsdutils` with epoch `1:` and
`login` as `1:4.16.0-2+really2.41.5-0+deb13u1`; the other listed binaries
carry `2.41.5-0+deb13u1`. This table groups binary packages by the reported
source and does not claim that every binary exposes the vulnerable function.
The log's fix column says `(won't fix)` for all these package matches except
zlib, for which it lists no fix. That is scanner data, not a vendor waiver.

Debian's current Trixie tracking pages mark all 14 listed CVEs unresolved for
their respective sources: [ncurses](https://security-tracker.debian.org/tracker/source-package/ncurses),
[gcc-14](https://security-tracker.debian.org/tracker/source-package/gcc-14),
[glibc](https://security-tracker.debian.org/tracker/source-package/glibc),
[acl](https://security-tracker.debian.org/tracker/source-package/acl),
[util-linux](https://security-tracker.debian.org/tracker/source-package/util-linux),
[perl](https://security-tracker.debian.org/tracker/source-package/perl), and
[zlib](https://security-tracker.debian.org/tracker/CVE-2026-85091). Some are
marked `no DSA`; that is **not** a patched Trixie package or release approval.
Newer versions in Forky/Sid are not supported Trixie fixes. No minimal supported
package update was identified, so no speculative package replacement or image
rebuild was attempted.

The earlier Docker Scout 1.26.0 reports at separate backend
`sha256:5bd868922bf34d44126f4b8c97243216d5cf5245c48d1243b7b3260046077c26`
and frontend
`sha256:1b07add53c68f430329b58cc8f00920c9ef4f5baa3909405e030750c457fbfe6`
image IDs found one HIGH (zlib) and zero CRITICAL per image. These are
**different images and scan dates**, so the 14-vs-1 difference is not a
like-for-like scanner discrepancy. The hosted Grype images were ephemeral and
were not published; exact-digest rescans and same-digest Scout comparison are
unverified. The CI table has no source-layer field; the Dockerfiles have no
runtime `apt install`, so base-image inheritance is a strong inference, not a
verified per-package layer attribution. The local Docker daemon was unavailable
on 2026-10-25; no final-candidate image build, package inspection, smoke check,
or rescan occurred in this continuation. **After-remediation counts: unverified;
no remediation was applied.** Preserve the HIGH gate and all findings.

Next security decision: obtain supported Trixie corrections or vendor
applicability decisions, rebuild isolated review images, inspect final-layer
packages, and compare both scanners against the **same immutable digest** and
current databases. If a release is contemplated with unresolved findings,
the operator must explicitly review each residual exposure and approve a scoped,
expiring risk decision; engineering has not accepted one. Existing non-root,
capability-drop, private-ingress and no-new-privileges controls reduce exposure
but do not patch the binaries. The zlib-specific source review and unresolved
Debian classification are in [the zlib assessment](V2_ZLIB_RISK_ASSESSMENT.md).
