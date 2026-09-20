#!/usr/bin/env python3
"""Verify a deployed RivalRadar backend.

Run this against the Render URL once the service is up::

    python scripts/verify_production.py https://rivalradar-api.onrender.com

Add the site origin to check CORS the way a browser would::

    python scripts/verify_production.py https://rivalradar-api.onrender.com \\
        --origin https://YOUR_USERNAME.github.io

By default this only reads. Pass ``--scan`` to additionally run one real scan
of a real tracked page, which is the only way to prove the scraper, the diff
engine and OpenRouter are all working end to end. That costs one free-tier
LLM call and writes real records, so it is opt-in.

Nothing here prints a secret: the checks assert on shapes and status codes,
never on key or URL values.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

TIMEOUT = 90  # free instances cold-start slowly

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"  [{status}] {name}" + (f": {detail}" if detail else ""), flush=True)


def request(
    url: str, *, method: str = "GET", body: dict | None = None, origin: str | None = None
) -> tuple[int, dict, dict]:
    """Return (status, headers, parsed-json-or-{})."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", "replace")
            return response.status, dict(response.headers), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, dict(exc.headers), json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, dict(exc.headers), {"detail": raw[:200]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="Render backend URL, no trailing slash")
    parser.add_argument("--origin", help="Frontend origin to test CORS against")
    parser.add_argument(
        "--scan", action="store_true", help="Run one real scan (uses a free-tier LLM call)"
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"\nVerifying {base}\n")

    # --- 1. Health ------------------------------------------------------
    print("Health")
    try:
        status, _headers, health = request(f"{base}/health")
    except Exception as exc:  # noqa: BLE001
        record(FAIL, "GET /health", f"unreachable: {exc.__class__.__name__}")
        print("\nThe service is not answering. Nothing else can be checked.\n")
        return 1

    record(PASS if status == 200 else FAIL, "GET /health", f"HTTP {status}")
    record(
        PASS if health.get("status") == "ok" else FAIL,
        "status is ok",
        str(health.get("status")),
    )

    env = str(health.get("environment", ""))
    record(PASS if env == "production" else WARN, "ENVIRONMENT=production", env or "unset")

    # --- 2. Database ----------------------------------------------------
    print("\nDatabase")
    db = health.get("database") or {}
    record(PASS if db.get("connected") else FAIL, "database reachable", str(db.get("connected")))
    backend = str(db.get("backend", ""))
    record(
        PASS if backend == "postgresql" else FAIL,
        "using PostgreSQL",
        backend or "unknown",
    )

    # --- 3. Secret hygiene ----------------------------------------------
    print("\nSecret hygiene")
    blob = json.dumps(health)
    leaks = [
        marker
        for marker in ("://", "password", "@", "sk-or-", "postgres:")
        if marker in blob
    ]
    record(
        PASS if not leaks else FAIL,
        "no credentials in /health",
        "found " + ", ".join(leaks) if leaks else "clean",
    )

    # --- 4. Real data, not demo -----------------------------------------
    print("\nData")
    record(
        PASS if health.get("demo_mode") is False else FAIL,
        "DEMO_MODE is off",
        str(health.get("demo_mode")),
    )

    status, _h, competitors = request(f"{base}/api/competitors")
    is_list = isinstance(competitors, list)
    record(PASS if status == 200 and is_list else FAIL, "GET /api/competitors", f"HTTP {status}")
    if is_list:
        record(PASS, "competitors tracked", str(len(competitors)))
        demo = [c for c in competitors if c.get("is_demo")]
        record(
            PASS if not demo else FAIL,
            "no fictional demo competitors",
            f"{len(demo)} demo records" if demo else "none",
        )

    status, _h, stats = request(f"{base}/api/stats")
    record(PASS if status == 200 else FAIL, "GET /api/stats", f"HTTP {status}")
    if status == 200:
        record(
            PASS,
            "funnel counted from stored records",
            f"{stats.get('raw_changes', 0)} raw -> "
            f"{stats.get('meaningful_changes', 0)} meaningful "
            f"({stats.get('noise_reduction', 0)}% removed)",
        )

    # --- 5. LLM ---------------------------------------------------------
    print("\nLLM")
    provider = str(health.get("llm_provider", ""))
    record(
        PASS if provider == "openrouter" else WARN,
        "provider is OpenRouter",
        provider or "unset",
    )
    record(
        PASS if health.get("llm_is_llm") else WARN,
        "a real model is configured",
        "yes" if health.get("llm_is_llm") else "falling back to deterministic rules",
    )
    model = str(health.get("llm_model", ""))
    record(
        PASS if model and model != "openrouter/free" else WARN,
        "model is pinned",
        model or "unset",
    )

    # --- 6. Scheduler honesty -------------------------------------------
    print("\nScheduler")
    scheduler = health.get("scheduler_enabled")
    record(
        PASS if scheduler is False else WARN,
        "scheduler off on free tier",
        "manual scans only" if scheduler is False else "enabled - the instance will sleep",
    )

    # --- 7. CORS ---------------------------------------------------------
    if args.origin:
        print("\nCORS")
        _status, headers, _body = request(f"{base}/api/stats", origin=args.origin)
        allowed = headers.get("access-control-allow-origin") or headers.get(
            "Access-Control-Allow-Origin"
        )
        record(
            PASS if allowed == args.origin else FAIL,
            f"origin {args.origin} allowed",
            allowed or "no Access-Control-Allow-Origin header",
        )
        record(
            PASS if allowed != "*" else FAIL,
            "not a wildcard origin",
            allowed or "-",
        )

    # --- 8. Optional real scan ------------------------------------------
    if args.scan:
        print("\nLive scan")
        if not is_list or not competitors:
            record(WARN, "scan skipped", "no competitors tracked yet")
        else:
            target = competitors[0]
            record(PASS, "scanning", str(target.get("name")))
            status, _h, scan = request(
                f"{base}/api/competitors/{target['id']}/scan", method="POST"
            )
            if status == 200:
                s = scan.get("stats", {})
                record(
                    PASS,
                    "scan completed",
                    f"{s.get('raw_changes', 0)} raw, "
                    f"{s.get('meaningful_changes', 0)} meaningful, "
                    f"{s.get('noise_reduction', 0)}% noise removed",
                )
            else:
                record(FAIL, "scan failed", f"HTTP {status}: {scan.get('detail', '')[:120]}")

    # --- Summary ---------------------------------------------------------
    failed = [r for r in results if r[0] == FAIL]
    warned = [r for r in results if r[0] == WARN]
    print(
        f"\n{len(results) - len(failed) - len(warned)} passed, "
        f"{len(warned)} warnings, {len(failed)} failed\n"
    )
    if failed:
        print("Failures:")
        for _s, name, detail in failed:
            print(f"  - {name}: {detail}")
        print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
