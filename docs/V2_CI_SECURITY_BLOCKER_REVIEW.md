# AgentFlow AI v2.0 CI security blocker review

## Current security gate status — 2026-11-02

Review source: `5049730e3fd5ae3dec9286844058e43b29805322` on
`feature/v2-production-hardening`. Local branch and origin branch matched at
review start; the working tree was clean. No production service, database,
volume, credential, or image tag was changed. Hosted PR run
[41464303432](https://github.com/yogesh1164/LLM/actions/runs/41464303432)
and push run [41464293507](https://github.com/yogesh1164/LLM/actions/runs/41464293507)
ran against this exact source and both failed the same three security gates:
`dependency-audit`, `images (backend)`, and `images (frontend)`. All other
jobs passed.

| Hosted image | Exact digest | Grype / DB | Unique HIGH | CRITICAL | Gate |
|---|---|---|---:|---:|---|
| Backend | `sha256:99b88399e56bf820645a4b4ba51eea976027ca53b0133e46a0de2f6184ab8679` | 0.97.1 / v6.1.10; Grype reports database built 2026-11-02T06:26:52Z | 18 | 0 | Fail |
| Frontend | `sha256:331fed84e05b1170603d4d7ac398d9555d0fa3f0ec155a53daddfba2a1b66a77` | 0.97.1 / same DB archive | 18 | 0 | Fail |

Archive label: `vulnerability-db_v6.1.10_2026-11-02T00:22:47Z_1793600812`. The DB archive SHA-256 was
`68063965a3a023acd330a65a0740976c81f8e13902824134b447deee97a0d838`.
The 15 previously reported HIGH Debian CVEs remain, and the current DB added
three HIGH SQLite CVEs to both images: `CVE-2026-119373`, `CVE-2026-119374`,
and `CVE-2026-119379` on `libsqlite3-0 3.46.1-7+deb13u2`. Debian's tracker
marks Trixie vulnerable and shows no fixed Debian version; the upstream fixes
are in SQLite 3.54.0. CVE-119373 requires crafted FTS5 data plus a prefix
MATCH; CVE-119374 requires a crafted corrupt FTS5 index and secure deletion;
CVE-119379 requires a crafted changeset through the session extension. The
backend production configuration uses PostgreSQL, and no app route imports or
accepts SQLite database files. SQLite remains available in the backend
runtime through Python's standard library and is used in test configurations;
the image findings therefore remain open, with limited demonstrated app
reachability rather than an accepted risk. The Node frontend has no app code
using the distro SQLite library.

The same scans also reported 32 distinct MEDIUM CVEs per image, plus 6 LOW and 25 NEGLIGIBLE; the full parsed package-to-CVE/version/fix inventory is retained in `docs/security/evidence/2026-11-02/hosted-grype-findings.json` with raw source logs. This leaves additional moderate package findings for review beyond the 16 npm instances. Their per-CVE package group, runtime notes, and Debian tracker references are recorded in `V2_SECURITY_DISPOSITION.md`. `The dependency audit found 16 moderate npm instances, all linked to
`GHSA-g3hv-75wg-m249` / `CVE-2026-118764`, and zero high/critical npm findings.
The vulnerable copies are development-only ESLint/TypeScript tooling. A
compatible fixed 10.x minimatch release and compatible parent range were not
available at review time. No override or audit threshold change was applied.

Current artifacts are retained under
[`docs/security/evidence/2026-11-02`](security/evidence/2026-11-02): raw hosted
job logs, run metadata, npm audit JSON and dependency-tree evidence, plus a
parsed Grype package-match JSON export. The CI action emitted only text tables,
not native Grype JSON/SBOM/full package inventory; the parsed export is
explicitly labeled and raw logs are retained. The local verified Grype v0.121.0
binary's database update could not complete from this workstation, so no
updated local Grype scan is claimed. The exact hosted digest scans above are
the fresh baseline. An isolated local backend and frontend candidate image
build succeeded; frontend build reported the same 16 moderate npm advisories.

Local frontend lint, TypeScript, encoding, and Playwright checks passed;
Playwright reported 29 passed and 3 skipped and exited in 33.9 seconds with
the isolated `NEXT_DIST_DIR` setting, reproducing no shutdown hang. Hosted CI
also passed backend tests, durable PostgreSQL tests, least-privilege PostgreSQL
tests, encrypted backup, frontend tests/build, secrets, and Compose validation.

The official refreshed Python Trixie base tag inspected for this review uses
digest `sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30`
and the same relevant Debian revisions as the current pinned base (including
OpenSSL `3.5.7-1~deb13u3`, gzip `1.13-1+deb13u1`, util-linux
`2.41.5-0+deb13u1`, and zlib `1:1.3.dfsg+really1.3.1-1+b1`). Updating the
pin would not address the findings; no unsupported suite mixing or unnecessary
package removal was performed. The hosted current scan is the authoritative
package baseline; counts from other digests/scanners are not compared as if
they were the same image.

Decision remains **NOT READY**. Do not waive the npm or image gates. Recheck
the Debian/SQLite trackers and npm parent dependency compatibility by
2026-11-09, or earlier if any upstream package release or advisory correction
appears. Do not start public production or private beta pending verified fixes
or a named security owner's explicit, scoped decision record.

Review date: 2026-11-01
Branch: `feature/v2-production-hardening`
Local source: `f5251a44ed290778848d0b94df9b161d3f901d6e`
Hosted source (latest push and PR): `f5251a44ed290778848d0b94df9b161d3f901d6e`
Decision: **NOT READY**

## Latest hosted CI verification

Push run [41321951030](https://github.com/yogesh1164/LLM/actions/runs/41321951030)
and PR run [41321955135](https://github.com/yogesh1164/LLM/actions/runs/41321955135)
ran on the current source. All jobs passed except `dependency-audit`,
`images (backend)`, and `images (frontend)`. The dependency job reports 16
moderate minimatch instances. Both image jobs ran Grype 0.97.1 with the same
DB archive `vulnerability-db_v6.1.10_2026-11-01T00:24:34Z_1793514012`,
SHA-256 `d0e1af9e6491440e1a671d0a0aafc32c5c7cb5cda787dcec3482799ef298f31c`.

| Event | Image | Hosted manifest digest | Distinct HIGH | Distinct CRITICAL |
|---|---|---|---:|---:|
| Push | Backend | `sha256:47ad336d3d19cbb830ff38f84c99245565939a689e8e0e5da6c5966958c1c180` | 15 | 0 |
| Push | Frontend | `sha256:97dbdadfac48f4c2c0fe8712ac009d250d73849b8ca304eb9adb8692639fb899` | 15 | 0 |
| PR | Backend | `sha256:7f972212d8ca07df0c8fab9ba5366fb244d795b314700f840430f97e0d2008bf` | 15 | 0 |
| PR | Frontend | `sha256:7905a8ade1a7b639957c24a3777ff9cc8295bfca2bc4690e5655c5fea7a7ea92` | 15 | 0 |

Each hosted image gate reports the same 15 shared Debian CVEs listed below.
These hosted image digests are ephemeral and differ from the local candidate
digests in the next section. Do not combine their finding counts. The hosted
reports do not contain the local candidate's generic OpenSSL/gzip CPE matches;
same-digest comparison against those hosted images is unavailable because the
images were not published. The HIGH gates still fail for both images.

Since the prior review, npm registry checks show `minimatch@11.0.3` is the
latest overall version, but `10.2.6` remains the last 10.x release. The latest
`@typescript-eslint/typescript-estree@8.72.1` still declares `minimatch
^10.2.2`; no compatible fixed package was available. Disposable `apt-get
update` checks against both pinned Python and Node Trixie base digests show no
newer candidate for the reported installed Trixie package set. No image rebuild
was justified because there was no supported package change to apply.

Frontend `npm ci` completed successfully in an isolated archive of this commit.
`npm audit` returned 16 moderate findings and exit 1; ESLint, TypeScript,
production build, and Playwright passed (29 passed, 3 skipped). No source or
lockfile dependency change was made.

## Candidate scan evidence

Reproduced locally with Grype 0.97.1 and imported vulnerability DB schema 6,
version v6.1.10, built `2026-11-01T06:20:12Z`. Grype scanned the local candidate
OCI manifests by digest; the reports are retained outside the repository at
`%TEMP%\agentflow-backend-521-current.json` and
`%TEMP%\agentflow-frontend-521-current.json`.

| Image | Manifest digest | Distinct HIGH | Distinct CRITICAL |
|---|---|---:|---:|
| Backend | `sha256:527c784ec206261c3ab3fc6249c298edbb2013891b177ff7aff0ab3eeae7f76f` | 27 | 2 |
| Frontend | `sha256:327a9782549d0ef8bb6e8a1287560440f9bd8e441067b61a2549bcb4f6661a83` | 16 | 0 |

The local report's package evidence includes `openssl` binary 3.5.7 at
`/usr/bin/openssl`, matched as `cpe-match`; the backend OS packages are
`openssl` and `libssl3t64` `3.5.7-1~deb13u3`. Debian's official tracker and
DSA-6465-1 mark the reported OpenSSL IDs fixed in Trixie at that revision.
The OpenSSL IDs are HIGH `CVE-2026-18798`, `CVE-2026-63076`,
`CVE-2026-14457`, `CVE-2026-63072`, `CVE-2026-84782`, `CVE-2026-14456`,
`CVE-2026-54873`, `CVE-2026-54874`, `CVE-2026-84784`, `CVE-2026-63075`,
`CVE-2026-72897`, and CRITICAL `CVE-2026-63073`, `CVE-2026-75803`.
These are strong package-version/backport evidence of generic CPE false
positives, not an Anchore adjudication. Keep raw matches and CI gate intact
until scanner data is corrected or a separately authorized decision is made.
See [Debian OpenSSL tracker](https://security-tracker.debian.org/tracker/source-package/openssl),
[DSA-6465-1](https://security-tracker.debian.org/tracker/DSA-6465-1), and
[DSA-6531-1](https://security-tracker.debian.org/tracker/DSA-6531-1).

Both images contain Debian `gzip` `1.13-1+deb13u1`; Grype identifies the
upstream `gzip` 1.13 binary at `/usr/bin/gzip` and reports HIGH
`CVE-2026-41992` as a CPE match. Debian marks the installed Trixie revision
fixed ([Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-41992)).
As with OpenSSL, retain the raw finding while requesting advisory/matcher
reconciliation.

The remaining 15 shared Debian HIGH IDs are
`CVE-2025-69720`, `CVE-2026-102010`, `CVE-2026-19499`, `CVE-2026-5435`,
`CVE-2026-54369`, `CVE-2026-54370`, `CVE-2026-76642`, `CVE-2026-78408`,
`CVE-2026-78409`, `CVE-2026-78410`, `CVE-2026-82560`, `CVE-2026-84243`,
`CVE-2026-85091`, `CVE-2026-9538`, and `CVE-2026-95619`.
They match Trixie packages `ncurses`, `gcc-14`, `glibc`, `acl`, `util-linux`,
`perl`, and `zlib`. The Debian tracker marks the affected Trixie package
revisions vulnerable or without a Trixie fix; some advisories are marked no-DSA
or postponed, which is not a fix or risk acceptance. A disposable container's
authenticated Trixie `apt` metadata had no newer candidate for the installed
versions. No unsupported distribution packages were mixed into the images.
See [Debian trackers: ncurses](https://security-tracker.debian.org/tracker/source-package/ncurses),
[gcc-14](https://security-tracker.debian.org/tracker/source-package/gcc-14),
[glibc](https://security-tracker.debian.org/tracker/source-package/glibc),
[acl](https://security-tracker.debian.org/tracker/source-package/acl),
[util-linux](https://security-tracker.debian.org/tracker/source-package/util-linux),
[perl](https://security-tracker.debian.org/tracker/source-package/perl), and
[zlib](https://security-tracker.debian.org/tracker/CVE-2026-85091).

### Advisory correction path

For OpenSSL/gzip, submit a reproducible report to
[Anchore Grype](https://github.com/anchore/grype/issues) with the exact image
digest, Grype and DB versions, raw match details, a minimal SBOM, Debian binary
and source package revisions, and the linked Debian fixed status. Ask Anchore
to trace the CPE/advisory record to its provider and correct the source mapping;
Grype's DB is assembled from upstream feeds by
[Vunnel](https://github.com/anchore/vunnel). Do not add a local ignore rule,
severity exception, or VEX suppression. No report has been filed from this
workspace.

## npm minimatch audit

`npm audit --json` exits 1 with 16 moderate instances of
`GHSA-g3hv-75wg-m249` / `CVE-2026-118764`, zero high/critical findings. The
lockfile places `minimatch@10.2.6` below
`@typescript-eslint/typescript-estree@8.71.2` (declared range `^10.2.2`); that
package is part of the ESLint / `eslint-config-next` development dependency
chain. There is no published minimatch 10.x release after 10.2.6. The
maintainer advisory identifies 10.2.6 as affected and 11.0.1 as patched, while
the GitHub audit database currently applies the broad `<11.0.1` range to the
3.1.5 copy too. Upgrading to 11 violates the upstream parent range and has not
been validated for this toolchain; forcing it would be an unsupported override.
Latest `@typescript-eslint/typescript-estree` still declares `^10.2.2`.

The affected-version mismatch should be raised with the
[GitHub Advisory Database](https://github.com/github/advisory-database/issues)
and the minimatch maintainer's
[advisory](https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249),
including the installed tree, advisory's affected code path, and lockfile
reproduction. A related public clarification request is
[advisory-database issue 10811](https://github.com/github/advisory-database/issues/10811).
No override, security-gate change, or incompatible upgrade was applied.

## CI disposition and next action

Latest hosted push run [41316291820](https://github.com/yogesh1164/LLM/actions/runs/41316291820)
and PR run [41316295540](https://github.com/yogesh1164/LLM/actions/runs/41316295540)
are for the remote source `8decc508...`; their dependency-audit and backend /
frontend image gates remain failed. The local `521e1b5` candidate has not been
hosted or pushed, so no hosted CI result exists for it. The package corrections
above are evidence-backed, but these raw Grype results still exceed the HIGH
threshold and the npm audit remains failing. No finding is accepted or waived.

Release remains blocked pending a Grype/source-advisory correction for the
patched OpenSSL and gzip packages, vendor-supported Trixie remediation for the
15 shared Debian findings or a separately authorized security disposition,
and a compatible upstream minimatch release/advisory correction. Rebuild and
rescan both exact image digests against the same pinned scanner/DB before
reconsidering the image gate.
