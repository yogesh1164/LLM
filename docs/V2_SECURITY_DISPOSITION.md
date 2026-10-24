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
