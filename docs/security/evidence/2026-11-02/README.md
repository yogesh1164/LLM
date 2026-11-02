# Evidence index - 2026-11-02

Source reviewed: `5049730e3fd5ae3dec9286844058e43b29805322` (`feature/v2-production-hardening`). Local and origin refs matched at investigation start. No production service, database, volume, image tag, environment file, or credential was changed.

## Hosted runs

- `github-push-run-41464293507.json` and `github-pr-run-41464303432.json`: run/job status and timestamps.
- `github-action-logs-2026-11-02.zip`: four captured `gh run view --log` outputs for the PR backend functional job, backend/frontend image jobs, and dependency-audit job. Extract to review. They are source text logs, not native Grype JSON.
- `hosted-grype-findings.json`: all parsed package rows from the two image job tables. Reconcile rows against the archived logs before use; this is not native Grype JSON/SBOM. Backend digest: `sha256:99b88399e56bf820645a4b4ba51eea976027ca53b0133e46a0de2f6184ab8679`; frontend digest: `sha256:331fed84e05b1170603d4d7ac398d9555d0fa3f0ec155a53daddfba2a1b66a77`. Grype 0.97.1, DB v6.1.10, archive label `vulnerability-db_v6.1.10_2026-11-02T00:22:47Z_1793600812`, installed build reported `2026-11-02T06:26:52Z`, archive SHA-256 `68063965a3a023acd330a65a0740976c81f8e13902824134b447deee97a0d838`.

## npm evidence

- `npm-audit.json`: `npm audit --json` from clean isolated `npm ci`, exit 1, 16 moderate, no high/critical.
- `npm-minimatch-tree.json`: `npm ls minimatch --all --json`.
- `npm-minimatch-explain.txt`: `npm explain minimatch`.
- Affected copies are in development-only lint/TypeScript tooling. Compatible parent ranges require minimatch 10.x; no override or force upgrade was performed.

## Local and hosted verification

- `npm ci` completed in a temporary isolated copy of package metadata; the checked-out frontend dependency tree was not changed.
- Local candidate backend and frontend Docker builds passed. Frontend's first default-network attempt returned npm `ECONNRESET`; its host-network retry passed, including Next.js production build and TypeScript.
- Frontend ESLint, `tsc --noEmit`, and encoding check passed. Local Playwright: 29 passed, 3 skipped, 33.9 seconds, normal exit with `NEXT_DIST_DIR=.next-playwright-security-20261102`; prior shutdown hang did not reproduce.
- Hosted backend tests: 347 passed, 36 skipped, 1 xfailed, 46 warnings; encrypted-backup tests: 37 passed. Ruff and `pip check` passed. Hosted durable PostgreSQL, least-privilege PostgreSQL, frontend, secrets and Compose jobs passed.
- Local Grype 0.121.0 version was verified. Its database update attempts stalled and were canceled before database status or scan output was available, so it was not used to claim current findings. Current counts come from the hosted exact-digest scans.
- `runtime-probes.json`: isolated local candidate runtime inspection. Both images ran non-root and had no setuid/setgid regular files. The Perl modules implicated in two findings were absent. Frontend health check passed in a `network=none`, no-port, no-volume container. Backend health endpoint was not run because it requires a database; its configured check and runtime user were inspected. No existing service was touched.

Image results: backend 18 unique HIGH / 0 CRITICAL; frontend 18 unique HIGH / 0 CRITICAL. Each also had 32 unique MEDIUM, 6 LOW and 25 NEGLIGIBLE database matches. None is suppressed or accepted.