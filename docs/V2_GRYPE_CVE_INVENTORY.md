## Latest hosted and isolated candidate scans — 2026-11-01

The newest hosted runs on source `8decc5082a80fb4af4919d7a3b7d0b10e628ace5` were push [41316291820](https://github.com/yogesh1164/LLM/actions/runs/41316291820) and PR [41316295540](https://github.com/yogesh1164/LLM/actions/runs/41316295540). Grype was 0.97.1. Both used vulnerability DB `vulnerability-db_v6.1.10_2026-11-01T00:24:34Z_1793514012` with archive SHA-256 `d0e1af9e6491440e1a671d0a0aafc32c5c7cb5cda787dcec3482799ef298f31c`.

| Event | Image | Hosted manifest digest | Distinct HIGH | Distinct CRITICAL |
|---|---|---|---:|---:|
| Push | Backend | `sha256:6fb7cc12c378b59b5394dd86facc075b1afd3414a13d842571b7297bcffda5f2` | 15 | 1 |
| PR | Backend | `sha256:45f56184740551dadbce1e825347d322a7599ddfb6573d984a49feb9b9adcab1` | 15 | 1 |
| Push | Frontend | `sha256:c313a11c3891efa3c65cde53d453bdcce1aacb5818edc0892f244ae290621205` | 15 | 0 |
| PR | Frontend | `sha256:1bec8bdd8e0c0bc1ef875584352cb898c16bb0c629f058f9a7a1fd7e72c1c48a` | 15 | 0 |

The hosted backend CRITICAL is `CVE-2026-115557` on Python 3.12.15; Grype reports 3.12.16 fixed. This motivated updating only the supported Python patch base. The hosted HIGH IDs are the 15 shared Debian IDs listed above in the prior scan record; no pyasn1 HIGHs appeared after the 0.6.5 pin. The dependency job’s Python `pip-audit` step passed; the subsequent npm audit step failed on the minimatch advisory documented in `V2_RELEASE_EVIDENCE.md`.

### Rebuilt local candidate manifests

Local builds used the same Grype 0.97.1 executable and the checksum-verified hosted DB archive above. Grype scanned each image by its exact OCI manifest digest:

| Candidate | Base | Manifest digest | Grype findings (unique CVE IDs) |
|---|---|---|---|
| Backend | Python 3.12.16, official slim Trixie digest `sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159` | `sha256:527c784ec206261c3ab3fc6249c298edbb2013891b177ff7aff0ab3eeae7f76f` | 27 HIGH, 2 CRITICAL |
| Frontend | Node 22.23.4, official slim Trixie digest `sha256:2117f713a417f3aff682148ee11aa1bb2249d198a604732d18a0b4c4829c4e33` | `sha256:327a9782549d0ef8bb6e8a1287560440f9bd8e441067b61a2549bcb4f6661a83` | 16 HIGH, 0 CRITICAL |

Backend candidate also reports Python 3.12.16, pip 26.2.2 and pyasn1 0.6.5; the prior Python critical and pyasn1 GHSAs are absent. The 15 shared Debian HIGH CVE IDs remain: CVE-2025-69720, CVE-2026-102010, CVE-2026-19499, CVE-2026-5435, CVE-2026-54369, CVE-2026-54370, CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410, CVE-2026-82560, CVE-2026-84243, CVE-2026-85091, CVE-2026-9538 and CVE-2026-95619. Grype reports no fixed Trixie package versions for these matches (or marks them `won't fix`); no package downgrade or suppression was used.

The local backend adds 11 HIGH and 2 CRITICAL generic CPE matches against the `openssl` executable version 3.5.7: CVE-2026-18798, CVE-2026-63076, CVE-2026-14457, CVE-2026-63072, CVE-2026-84782, CVE-2026-14456, CVE-2026-54873, CVE-2026-54874, CVE-2026-84784, CVE-2026-63075, CVE-2026-72897 (HIGH), and CVE-2026-63073 and CVE-2026-75803 (CRITICAL). The frontend does not contain that executable. Both local reports add a HIGH generic CPE match against gzip 1.13 (`CVE-2026-41992`). The actual installed Debian revisions are `openssl 3.5.7-1~deb13u3`, `libssl3t64 3.5.7-1~deb13u3`, and `gzip 1.13-1+deb13u1`. Debian’s security tracker marks the OpenSSL advisories fixed in Trixie at revision `3.5.7-1~deb13u3` (DSA-6465-1 and DSA-6531-1), and CVE-2026-41992 fixed in Trixie at gzip `1.13-1+deb13u1`. See [Debian OpenSSL tracker](https://security-tracker.debian.org/tracker/source-package/openssl), [DSA-6465-1](https://security-tracker.debian.org/tracker/DSA-6465-1), [DSA-6531-1](https://security-tracker.debian.org/tracker/DSA-6531-1), and [Debian CVE-2026-41992](https://security-tracker.debian.org/tracker/CVE-2026-41992). The runtime-stage system pip was also upgraded to 26.2.2 after the first scan found the base image’s separate pip 25.0.1; the final backend report has no pip or pyasn1 matches. These vendor status records conflict with Grype’s generic CPE matches; the raw scanner findings remain unsuppressed and the image gate is still failing pending an authorized scanner finding reconciliation. This is not a risk acceptance or a claim that CI passed.

# Hosted Grype HIGH inventory — 2026-10-25 review

## Latest hosted scan — 2026-11-01, source `c7125f07`

Push run [41314507014](https://github.com/yogesh1164/LLM/actions/runs/41314507014)
and pull-request run
[41314511005](https://github.com/yogesh1164/LLM/actions/runs/41314511005) built
and scanned the exact same source commit. Both image builds and Dockerfile lint
steps succeeded; only Grype's configured HIGH cutoff failed. Grype was 0.97.1
with vulnerability DB v6.1.10 built `2026-11-01T06:20:12Z`.

| Event | Image | Grype image-read digest | Result |
|---|---|---|---|
| Push | Backend | `sha256:eca9f251560b3060cb98be940872bc850bb5803edf008a80c499c29fc718bf64` | 15 distinct HIGH CVEs plus 4 HIGH GHSAs; 0 CRITICAL |
| Push | Frontend | `sha256:869d78d271d77ecbe762148ee11aa1bb2249d198a604732d18a0b4c4829c4e33` | 15 distinct HIGH CVEs; 0 CRITICAL |
| Pull request | Backend | `sha256:9c78986c337b76a9628a9e71cbe7dcdf27201dc5b5b746994fc41b6c4484d4d3` | Same HIGH IDs; 0 CRITICAL |
| Pull request | Frontend | `sha256:ce50e146d4e6501daf88254b1774a9e641bd2778810f37b7d3277e85c592d5a1` | Same HIGH IDs; 0 CRITICAL |

The 15 HIGH CVE IDs in **both** images are CVE-2025-69720,
CVE-2026-102010, CVE-2026-19499, CVE-2026-5435, CVE-2026-54369,
CVE-2026-54370, CVE-2026-76642, CVE-2026-78408, CVE-2026-78409,
CVE-2026-78410, CVE-2026-82560, CVE-2026-84243, CVE-2026-85091,
CVE-2026-9538 and CVE-2026-95619. The backend additionally contains
`pyasn1 0.6.4`, matched to four HIGH GHSAs: GHSA-9m75-vc3g-4x39,
GHSA-fm9c-5rcf-2q5p, GHSA-2qm8-x737-gmw5 and GHSA-mm57-4v3p-rchx.
Grype lists `0.6.5` as the fix for all four. The reviewed
[pyasn1 advisory](https://github.com/advisories/GHSA-2qm8-x737-gmw5) and
[PyPI 0.6.5 release](https://pypi.org/project/pyasn1/0.6.5/) confirm the
patched version. The repository constraint is now `pyasn1==0.6.5`; an isolated
clean dependency environment reports no known Python advisories after that
change. The Dockerfile builder now explicitly
upgrades its bundled pip 25.0.1 to 26.2.2, which is above all pip fix versions
reported by this scan. These source changes have **not** been rebuilt or
rescanned in a container because the local Docker daemon is unavailable.

The Debian HIGH matches use these installed versions: `perl-base`
`5.40.1-6+deb13u1`; `zlib1g` `1:1.3.dfsg+really1.3.1-1+b1`; ncurses
`6.5+20250216-2`; gcc runtime `14.2.0-19`; glibc
`2.41-12+deb13u4`; acl `2.3.2-2+b1`; and util-linux
`2.41.5-0+deb13u1`. The CVE/package mapping is the table in the historical
inventory below, plus new `CVE-2026-84243` on `libc-bin` and `libc6` at glibc
`2.41-12+deb13u4`. Grype lists `(won't fix)` or no fixed version for these
Debian matches. Current Debian trackers mark the relevant Trixie packages
vulnerable; fixes shown for some source packages are in Forky/Sid, not supported
Trixie updates. For `CVE-2026-84243`, Debian marks glibc vulnerable in Trixie,
Forky and Sid, with no fixed version ([Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-84243)).
The package fix for pyasn1 is the only
supported direct remediation identified in these scans. No Debian package was
substituted and no advisory was suppressed.

The same backend scan also reports pip 25.0.1 medium-severity GHSAs with fixes
25.3, 26.0, 26.1, 26.1.2 or 26.2.0. The builder upgrade to pip 26.2.2 is above
those versions; the image result still needs a rebuild to verify it. The latest
Grype logs are the authoritative source for package rows and digests; this
inventory does not claim the source changes cleared any image gate.

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

## Current hosted baseline - 2026-11-02

The exact-source hosted PR 41464303432 and push 41464293507 used Grype 0.97.1 and DB v6.1.10 (archive label `vulnerability-db_v6.1.10_2026-11-02T00:22:47Z_1793600812`; Grype reports installed DB built `2026-11-02T06:26:52Z`), archive SHA-256 `68063965a3a023acd330a65a0740976c81f8e13902824134b447deee97a0d838`. Backend digest: `sha256:99b88399e56bf820645a4b4ba51eea976027ca53b0133e46a0de2f6184ab8679`; frontend digest: `sha256:331fed84e05b1170603d4d7ac398d9555d0fa3f0ec155a53daddfba2a1b66a77`. Each scan found 18 unique HIGH and zero CRITICAL CVEs.

Three SQLite HIGH findings are new in both images, in addition to the 15 previous shared Debian IDs:

| CVE | Package/version | Debian Trixie status | Trigger / reachability |
|---|---|---|---|
| CVE-2026-119373 | `libsqlite3-0 3.46.1-7+deb13u2` | Vulnerable; no Debian fix listed. Upstream fix 3.54.0. | Crafted negative rowids in FTS5 `detail=none` plus prefix MATCH. Production app uses PostgreSQL, no SQLite file input. |
| CVE-2026-119374 | `libsqlite3-0 3.46.1-7+deb13u2` | Vulnerable; no Debian fix listed. Upstream fix 3.54.0. | Crafted corrupt FTS5 index plus secure-delete. No app SQLite file input identified. |
| CVE-2026-119379 | `libsqlite3-0 3.46.1-7+deb13u2` | Vulnerable; no Debian fix listed. Upstream fix 3.54.0. | Crafted changeset through SQLite session extension. No app changeset ingestion identified. |

Debian vendor records: [119373](https://security-tracker.debian.org/tracker/CVE-2026-119373), [119374](https://security-tracker.debian.org/tracker/CVE-2026-119374), [119379](https://security-tracker.debian.org/tracker/CVE-2026-119379). Limited app reachability is not remediation or risk acceptance. Full logs and parsed CVE/package JSON are in `security/evidence/2026-11-02`; action output was text only, with no native JSON/SBOM. See the current CI blocker review for complete status.
