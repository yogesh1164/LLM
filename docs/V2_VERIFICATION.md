# V2 development checkpoint verification

## Continuation verification: 2026-10-24

Branch and all three required checkpoint commits verified before changes.
Existing uncommitted work was reviewed, completed and tested. No account/ownership
schema changes, production writes, pushes, merges, deployments or paid AI calls.

| Check | Actual result |
|---|---|
| Focused backend regression run | **41 passed**; interruption recovery, workflow and request limits; Ruff passes |
| Full Windows backend suite | **217 passed, 1 XFAIL** in 58.01s; Ruff and pip check pass |
| Full Linux rebuilt-image suite | **217 passed, 1 XFAIL** in 25.75s; no network, read-only root, disposable tmpfs and SQLite, no database mounts |
| Sandbox limitation | Initial focused run: 27 passed, 1 temp-directory permission error. Host rerun: 28 passed before six additional progress regression cases were added |
| Frontend source | ESLint, TypeScript, encoding and production build pass |
| Image builds | Separate backend/frontend `v2-review-hardening` tags built; V1 `:local` tags untouched |
| Image scans | Backend: **9 high / 0 critical**, four Debian source packages. Frontend: **8 high / 0 critical**, three Debian source packages. Release gate remains blocked; no exceptions |
| Runtime helper permissions | Corrected root inspection passes on both rebuilt images: no setuid/setgid regular files; users remain UID 10001/1000 |
| Frontend runtime | Network-isolated non-root container with read-only root: HTTP 200, no browser localhost API, no npm/Corepack/Yarn |
| Static infrastructure | Both Compose configurations validate; both Dockerfiles pass Hadolint at error threshold |
| Git history secrets | Redacted Gitleaks: 14 commits, no leaks before the new checkpoint |
| Candidate configured-secret scan | 88 candidate source files passed; private environment files and operational evidence remain excluded |
| V1 HTTPS read-only check | Explicit local CA validation: root/health/ready 200; dashboard 401 unauthenticated and 200 authenticated |
| Database preservation | Development ID `3eea02ed0717`, production ID `20505198dfda`; start times and volume mounts unchanged during this continuation |
| Remote CI | Still not run; branch remains unpushed |

New ignored evidence: `backups/v2-backend-resume-build.log`,
`v2-frontend-resume-build.log`, `v2-resume-linux-test-build.log`,
`v2-backend-resume-scout.sarif`, `v2-frontend-resume-scout.sarif` and existing
`v2-hardening-image-check.py` / `.mjs` inspection helpers. No operational artifacts
are to be committed. See [vendor/runtime triage](V2_IMAGE_TRIAGE.md) for all nine CVEs.

Rebuilt review image IDs: backend
`sha256:44b73e8c70e254225408b3c501d5d960fe7981edbb3168a5b2cc5619f00673b5`,
frontend `sha256:56f5d714fa61a3dab6ef45bd8e323a5732327d10a99e1866126ae26e6e08dd9d`.

## Historical verification: 2026-10-23

Date: 2026-10-23. Branch: `feature/v2-production-hardening`; base `6bd5b32`.
This is a development checkpoint, not a production release. No V2 deployment,
production writes, migrations, credential changes, pushes or merges were made.

| Check | Verified result |
|---|---|
| Initial baseline | 110 passed, 1 XFAIL; first sandbox run had a Windows temp permission error, host rerun passed |
| Final Windows full backend suite | **183 passed, 1 XFAIL** with constrained dependencies; Ruff and pip check pass |
| Linux V2 backend image tests | **183 passed, 1 XFAIL**, in-memory SQLite, fake provider key, no live AI calls or production volume mounts |
| Linux initial harness correction | Explicit test GEMINI_MODEL overrode a default-settings test; removed test-only override, no model/code expectation changed |
| Cancellation limitation | Existing synchronous worker XFAIL unchanged; bounded worker/queued cancellation tests added |
| Frontend | ESLint, TypeScript, encoding and Next.js standalone production build pass |
| Frontend review runtime | Network-isolated, no host ports: HTTP 200; no browser `localhost:8000`; npm/Corepack/Yarn absent |
| Docker | Both separate `:v2-review` app images built; production tags/containers not replaced; final constraint-pinned backend build is recorded in ignored build log |
| Static infrastructure | Production Compose and optional application limits validate; Hadolint error-threshold checks and actionlint pass before final checkpoint |
| Python dependencies | Initial two unique advisories (certifi, pytest) fixed locally; subsequent pip-audit zero known vulnerabilities. Runtime production certifi already 2026.10.23 |
| npm audit | Zero known vulnerabilities in frontend lockfile |
| Image vulnerability scans | **FAIL / unresolved**: backend 9 high advisories, frontend reduced from 18 to 8 high advisories after removing unused package managers. All remaining reported as not fixed; no critical findings in these scans |
| Secrets | Existing 11-commit Git history and 82-file candidate export passed redacted Gitleaks; configured-secret scan passed; final staged checks required before checkpoint commits |
| Existing production HTTPS | Explicit Caddy CA validation: root/health/ready 200; dashboard unauthenticated 401 and authorized 200; read-only requests |
| Development DB | `llm-postgres-1` ID/start time and `llm_agentflow-postgres` mount unchanged; no writes/restarts/volume operations |
| Production DB | Independently mounted `agentflow-private_postgres-data`, healthy; no migration, restore or data changes |
| Remote CI | Not run: branch has not been pushed; local syntax/tool checks do not prove hosted Actions success |

## Remaining image findings

Shared Debian findings: CVE-2026-53613, CVE-2026-78409, CVE-2026-82560,
CVE-2026-78410, CVE-2026-78408, CVE-2026-53615, CVE-2026-85091,
CVE-2026-76642. Backend additionally reports CVE-2026-84782 (OpenSSL).
Scanner severities are not an exploitability assessment. Review vendor advisories,
runtime reachability and supported patched bases; do not blanket-ignore findings.
The GitHub image job uses Grype, which may report a different set from local Scout.

## Evidence retained locally (ignored)

- `backups/v2-python-audit.json`, `v2-python-audit-fixed.json`
- `backups/v2-npm-audit.json`
- `backups/v2-backend-scout.sarif`, `v2-frontend-scout-final.sarif`
- `backups/v2-backend-build-constraints.log`, `v2-frontend-build-final.log`
- `backups/v2-review-check.py`, `v2-source-scan/`, `v2-frontend-runtime.mjs`

Do not commit these operational artifacts. The review helper's export directory
is intentionally create-once; rerunning requires a fresh name, not deleting it.

## Change inventory

- CI: `.github/workflows/ci.yml`, `.github/dependabot.yml`.
- Backend: `app/config.py`, `main.py`, `research.py`, `workflow.py`,
  `custom_agents.py`, `custom_workflows.py`, new `provider_capacity.py`,
  `observability.py`, inactive `auth_foundation.py`.
- Tests: new `test_provider_capacity.py`, `test_observability.py`,
  `test_auth_foundation.py`, `test_security_boundaries.py`.
- Dependencies/images: `backend/pyproject.toml`, `backend/constraints.txt`,
  both Dockerfiles, `backend/.dockerignore`.
- Frontend: safe image/citation rendering in `ResultsPanel.tsx`, new `error.tsx`.
- Operations: `.env.production.example`, optional `deploy/compose.limits.yml`;
  actual `.env`/`.env.production` unchanged.
- Docs: README, DEPLOYMENT, V2_SECURITY_AUDIT, V2_ARCHITECTURE,
  V2_VERIFICATION and V2_CHECKPOINT.

Verdict: **V2 is not production/multi-user ready.** Safe foundations are tested;
account activation, ownership migration, durable jobs and unresolved image
vulnerabilities remain gates. Existing V1 private services remain running.
