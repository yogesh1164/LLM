# AgentFlow AI

For the separate private deployment stack, audit findings, security boundaries,
backup/restore procedures, and verification commands, see [DEPLOYMENT.md](DEPLOYMENT.md).
The private container stack and live five-stage Gemini workflow have been tested
locally. See the runbook's verification results and limitations before use.

AgentFlow runs a bounded Orchestrator → Research → Analysis → Report → Review workflow through a provider-independent stage interface. Gemini is the default provider and uses Google's `google-genai` SDK directly. OpenAI remains an optional provider backed by the OpenAI Agents SDK. Gemini Research can use Google Search grounding when explicitly enabled and returns only source URLs supplied in provider citation metadata. AgentFlow does not run user supplied commands or expose arbitrary system tools.

## Requirements

- Node.js 20.9+
- Python 3.11+
- Docker Desktop (or an existing PostgreSQL 14+ database)
- A Gemini API key (default), or an OpenAI API key when `AI_PROVIDER=openai`
- A private API access token configured as `API_ACCESS_TOKEN`

## Local setup (Windows PowerShell)

From the project root:

```powershell
Copy-Item .env.example .env
# Set API_ACCESS_TOKEN and GEMINI_API_KEY. Keep both server side and never commit .env.
# Generate a token with:
[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
docker compose up -d postgres
```

Install backend dependencies and create the database schema:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,openai]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In another terminal, install and run the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. API docs are available at http://localhost:8000/docs. The frontend connects to `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`) and asks for the server token. The token stays in the current browser session.

For an existing PostgreSQL instance, set `DATABASE_URL` in root `.env`, for example `postgresql+psycopg://user:password@localhost:5432/agentflow`, before running `alembic upgrade head` and the backend. Run new migrations with `alembic upgrade head` from the backend folder.

Google Search grounding is disabled by default to avoid unexpected grounding usage charges. Enable it with `GEMINI_SEARCH_GROUNDING_ENABLED=true` only after checking the model and project tier. Current Google pricing documentation lists Search grounding as unavailable on the free tier for Gemini 3.8 Flash; paid tier projects include a monthly allowance and may be charged for additional search queries.

## APIs

- `GET /api/health` health status.
- `GET /api/ready` checks that the API can reach PostgreSQL.
- `GET /api/dashboard` persisted task totals and the latest 50 executions, including stage details and measured usage.
- `POST /api/workflows/execute` synchronous workflow execution, retaining the prior route and result fields with additional task ID, sources, token and cost fields.
- `POST /api/workflows/stream` executes the same workflow and streams actual stage transitions and final result as Server-Sent Events. The client submits with `fetch` and reads the event stream.
- `POST /api/workflows/collaborate` retains the original Research/Analysis response shape for existing clients.
- `GET /api/agents` lists saved custom agent configurations; `GET /api/agents/{id}` retrieves one configuration.
- `DELETE /api/tasks/{task_id}` permanently deletes a task and its saved stage outputs.
- `POST /api/agents`, `PATCH /api/agents/{id}`, `POST /api/agents/{id}/duplicate` and `DELETE /api/agents/{id}` manage custom configurations. `GET /api/agents/options` lists provider/model choices configured on the server.

Open **Agent Studio** in the dashboard to create, edit, duplicate, enable, disable, or delete custom configurations. The five built-in stages are shown separately and protected. Custom configurations are persisted only; they do not participate in workflow execution or change its stage sequence.

Workflow prompts are capped at 1,000 characters. The default total workflow timeout is 600 seconds; each agent call is limited to 90 seconds (Review defaults to 180), stage output to 12,000 characters, stage input to 40,000 characters, and each workflow to five model calls. Configure these with `WORKFLOW_TIMEOUT_SECONDS`, `AGENT_TIMEOUT_SECONDS`, `MAX_STAGE_OUTPUT_CHARS`, `MAX_STAGE_INPUT_CHARS`, and `MAX_MODEL_CALLS_PER_WORKFLOW`. Inputs exceeding the stage input limit fail explicitly instead of being silently truncated. Gemini retries transient HTTP 503 and non-quota HTTP 429 responses up to two times by default, with bounded exponential backoff and jitter; retries share the current stage and workflow deadline. Configure `PROVIDER_RETRY_ATTEMPTS`, `PROVIDER_RETRY_BASE_DELAY_SECONDS`, and `PROVIDER_RETRY_MAX_DELAY_SECONDS`. Quota, authentication, and timeout failures are not retried. The in-process per-IP rate limit defaults to 10 requests per minute and has a bounded address map; use a shared gateway/Redis limiter for multi-instance deployment.

Task prompts and outputs do not expire by default. Set `TASK_RETENTION_DAYS` to a positive value to remove tasks older than that many days when a new workflow starts. Users can also delete individual runs in **Tasks & Execution**.

## Token usage and estimated cost

Input and output token counts are reported when the provider supplies usage. OpenAI estimates use the configured `INPUT_TOKEN_COST_PER_MILLION`, `CACHED_INPUT_TOKEN_COST_PER_MILLION` and `OUTPUT_TOKEN_COST_PER_MILLION` rates. Gemini cost is shown as unavailable because the API does not report billing tier and Google Search grounding charges. Check [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) before enabling grounding; Google lists search grounding as unavailable on the free tier and offers a free request allowance on paid tier.

## Verification

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
```

Tests use an isolated in-memory SQLite database to exercise persistence without requiring PostgreSQL. For a local PostgreSQL migration check, start the Compose service, set up `.env`, then run `alembic upgrade head`.

From `frontend`:

```powershell
npm run lint
npx tsc --noEmit
npm run build
```

## Current boundaries

- Gemini uses the `google-genai` SDK directly for model runs and optional native Google Search grounding. OpenAI uses the Agents SDK default provider and its hosted `WebSearchTool` when enabled. Gemini search availability depends on Google Search grounding access for the API project. Automated regression tests make no live provider calls.
- Agent stages and task results persist in PostgreSQL after migrations are applied. Data and agent routes require the configured bearer token. This is a single shared access token, not per-user identity or multi-tenant authorization. Health and readiness checks are public.
- Data and agent routes require the configured bearer token. This is a single shared access token, not per-user identity or multi-tenant authorization. Health and readiness checks are public.
- SSE reports real stage transitions and the final result; it does not stream partial model tokens.
- Usage is measured after each agent run when available. Gemini cost and search charges are not estimated because actual billing tier and grounding charges are not included in the response.
- Knowledge ingestion, schedules, persistent conversational memory, custom agent assignment to workflows, approvals for external actions, and a visual workflow editor are not implemented. Agent Studio stores custom configurations only; enabled custom agents do not run in the fixed workflow. Task prompts and outputs have no automatic expiry, so add a retention policy before storing sensitive production data. Current tools are read-only web search and model calls; no sensitive or irreversible action tool is enabled.
- Agent Studio stores custom configurations only; enabled custom agents do not run in the fixed workflow. Task prompts and outputs have no automatic expiry, so add a retention policy before storing sensitive production data.
