"""Read-only private HTTPS checks. No provider requests, token output or TLS bypass."""

import argparse
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("v1", "durable", "disabled"), required=True)
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    context = ssl.create_default_context(cafile=str(root / "backups/agentflow-private-root.crt"))
    token = dotenv_values(root / ".env.production", interpolate=False).get("API_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("Production bearer token is not configured")
    checks = [("/", False, 200), ("/api/health", False, 200), ("/api/ready", False, 200),
              ("/api/dashboard", False, 401), ("/api/dashboard", True, 200)]
    journal_path = "/api/executions/" + str(uuid4())
    if options.mode != "v1":
        checks += [(journal_path, False, 401), (journal_path, True, 404 if options.mode == "durable" else 503)]
    results = []
    for path, authenticated, expected in checks:
        request = urllib.request.Request("https://localhost:8443" + path,
                    headers={"Authorization": "Bearer " + token} if authenticated else {})
        try:
            response = urllib.request.urlopen(request, context=context, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            if response.status != expected:
                raise RuntimeError("Private HTTPS status check failed")
            if path == journal_path and authenticated:
                detail = json.load(response).get("detail")
                if detail != ("Execution not found" if options.mode == "durable" else "Durable execution is disabled"):
                    raise RuntimeError("Private execution-mode check failed")
        results.append({"path": path, "authenticated": authenticated, "status": expected})
    print(json.dumps({"private_https_checks": results, "paid_requests": 0}))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never dump credentials, private responses or certificate contents.
        raise SystemExit("Private HTTPS checks failed. Verify service health, token and trusted CA using an authorized session.") from None
