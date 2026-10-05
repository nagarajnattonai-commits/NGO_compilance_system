"""Bounded, read-only production smoke checks using only the standard library."""
import argparse
import json
import os
import urllib.error
import urllib.request


def get(url: str, *, cookie: str = "") -> tuple[int, bytes]:
    headers = {"User-Agent": "setu-release-smoke/1"}
    if cookie:
        headers["Cookie"] = "setu_session=" + cookie
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read(65536)
    except urllib.error.HTTPError as error:
        return error.code, error.read(65536)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Setu production smoke checks")
    parser.add_argument("--web", required=True, help="public HTTPS web origin")
    parser.add_argument("--api", required=True, help="API origin reachable by the operator")
    args = parser.parse_args()
    if not args.web.startswith("https://") or not args.api.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise SystemExit("Smoke targets must use HTTPS except explicit loopback rehearsal")
    checks = []
    for name, url, expected in (
        ("web", args.web.rstrip("/") + "/login", {200}),
        ("health", args.api.rstrip("/") + "/health", {200}),
        ("ready", args.api.rstrip("/") + "/ready", {200}),
        ("unauthenticated-auth-boundary", args.api.rstrip("/") + "/api/v1/auth/me", {401}),
    ):
        status, body = get(url)
        checks.append({"check": name, "status": status, "passed": status in expected})
        if name in {"health", "ready"} and status == 200:
            try:
                checks[-1]["reported_status"] = json.loads(body).get("status", "")
            except (ValueError, AttributeError):
                checks[-1]["passed"] = False
    session = os.getenv("SETU_SMOKE_SESSION", "")
    if session:
        status, _ = get(args.api.rstrip("/") + "/api/v1/auth/me", cookie=session)
        checks.append({"check": "authorized-session", "status": status, "passed": status == 200})
    else:
        checks.append({"check": "authorized-session", "status": "NOT_VERIFIED", "passed": True})
    print(json.dumps({"checks": checks}, separators=(",", ":")))
    if not all(item["passed"] for item in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
