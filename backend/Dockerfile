# syntax=docker/dockerfile:1
FROM python:3.12-slim-trixie@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --upgrade "pip==26.2.2"
COPY pyproject.toml constraints.txt ./
COPY app ./app
# Preserve the working Gemini SDK. Include the existing optional OpenAI provider.
RUN /opt/venv/bin/pip install --constraint constraints.txt '.[openai]' 'google-genai==2.31.0'

FROM python:3.12-slim-trixie@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 agentflow && useradd --uid 10001 --gid agentflow --no-create-home agentflow
RUN python -m pip install --no-cache-dir --upgrade "pip==26.2.2"
WORKDIR /app/backend
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
# No runtime operation needs setuid/setgid helpers. Keep package metadata intact
# for scanners; this reduces privilege-escalation paths, not advisory counts.
RUN find / -xdev -type f -perm /6000 -exec chmod a-s {} +
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=3)"
# One worker preserves the existing in-memory limiter. Never trust arbitrary forwarded IPs.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers", "--no-access-log"]
