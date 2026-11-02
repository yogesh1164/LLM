# Local frontend API development

The Next.js development server binds to `localhost` and proxies `/api/*` to the
private Caddy listener at `https://localhost:8443`. The proxy uses the hostname
`localhost` for TLS, preserves cookies and response statuses, and keeps TLS
certificate verification enabled. Production builds continue to use
`NEXT_PUBLIC_API_BASE_URL` as before.

## Trust the local Caddy CA for Node.js

If Node.js does not trust the private Caddy CA, export only its public root
certificate and configure this development process to trust that certificate.
Do not use `NODE_TLS_REJECT_UNAUTHORIZED=0`.

From the repository root in PowerShell:

```powershell
$caDirectory = Join-Path $env:LOCALAPPDATA 'AgentFlow'
New-Item -ItemType Directory -Force -Path $caDirectory | Out-Null
docker compose -p agentflow-private -f compose.production.yml --env-file .env.production cp proxy:/data/caddy/pki/authorities/local/root.crt (Join-Path $caDirectory 'agentflow-local-root.crt')
Get-FileHash (Join-Path $caDirectory 'agentflow-local-root.crt') -Algorithm SHA256
```

Verify the SHA256 fingerprint against the expected fingerprint from the
operator who manages this local deployment. Then start the frontend:

```powershell
$env:NODE_EXTRA_CA_CERTS = Join-Path $env:LOCALAPPDATA 'AgentFlow\agentflow-local-root.crt'
Set-Location frontend
npm.cmd run dev -- --port 3001
```

`NODE_EXTRA_CA_CERTS` adds this CA to Node.js trust for this process only; normal
certificate validation remains on. To use an already trusted Caddy CA, omit
`NODE_EXTRA_CA_CERTS`. Open <http://localhost:3001>.

The proxy maps the local page's same-origin `Origin` to Caddy's configured
`https://localhost:8443` origin for the backend's exact-origin check. The
backend still requires the login verification header and validates the
session-bound CSRF token on account mutations. Cross-origin `Origin` headers
are forwarded unchanged and fail the backend check.
