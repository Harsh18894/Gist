"""Smoke-test a running Gist public demo. Never makes a paid call: it only checks that AI requests without a
valid access code are refused.

  python deploy/smoke_test.py --api https://gist-api.onrender.com [--web https://gist.vercel.app] [--expect-ai off|on]
"""
from __future__ import annotations

import argparse
import sys
import time

import httpx

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    RESULTS.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", required=True)
    parser.add_argument("--web")
    parser.add_argument("--expect-ai", choices=["off", "on"], default="off")
    args = parser.parse_args()
    api = args.api.rstrip("/")
    client = httpx.Client(timeout=90)        # a sleeping free instance can take ~60 s to wake

    for attempt in range(3):
        try:
            health = client.get(f"{api}/api/health")
            break
        except httpx.HTTPError:
            time.sleep(10)
    else:
        print(f"FAIL  API not reachable at {api}")
        return 1
    check(health.status_code == 200, "API health")

    rag = client.get(f"{api}/api/rag/status").json()
    check(rag.get("dataset_version") == "v2" and rag.get("sources") == 534, "Pulse v2 dataset served (534 sources)")
    check(rag.get("openai_vectors") == 536, "stored learned vectors present (536)")

    pub = client.get(f"{api}/api/public/status").json()
    check(pub.get("public_mode") is True and pub.get("read_only") is True, "public mode on (read-only shared state)")
    check(pub.get("public_ai") is (args.expect_ai == "on"), f"visitor AI is {args.expect_ai}")
    check(set(pub) == {"public_mode", "public_ai", "ai_needs_access_code", "limits", "spent_today_usd", "read_only"},
          "status exposes only the expected fields (never the code)")

    blocked = client.put(f"{api}/api/priorities/weights", json={"weights": {"reach": 1, "recent": 1, "negative": 1, "support": 1, "evidence": 1}})
    check(blocked.status_code == 403, "owner-only writes blocked (priority weights)")
    billing = client.put(f"{api}/api/observability/billing", json={"day": "2026-11-26", "amount_usd": 1})
    check(billing.status_code == 403, "owner-only writes blocked (billing)")

    rules = client.post(f"{api}/api/investigations", json={"question": "Why did onboarding activation drop in October?"})
    check(rules.status_code == 200 and rules.json().get("status") == "completed", "rules investigation runs ($0)")
    history = client.get(f"{api}/api/investigations").json()
    check(history.get("audit", {}).get("ok") is True, "audit chain verifies")
    check(sum(1 for i in history.get("investigations", []) if i.get("has_report")) >= 10, "stored AI investigation runs visible")
    experiments = client.get(f"{api}/api/experiments").json()
    check(experiments.get("counts", {}).get("draft") == 58, "stored AI experiment drafts visible (58)")

    no_code = client.post(f"{api}/api/investigations", json={"question": "Why did activation drop in February?", "planner": "model"})
    check(no_code.status_code == 403, "AI investigation refused without a valid access code (no spend)")
    wrong = client.post(f"{api}/api/investigations", json={"question": "Why did activation drop in February?", "planner": "model"},
                        headers={"X-Gist-Access-Code": "definitely-not-the-code"})
    check(wrong.status_code == 403, "AI investigation refused with a wrong access code (no spend)")

    if args.web:
        web = args.web.rstrip("/")
        pre = client.options(f"{api}/api/priorities/weights", headers={"Origin": web, "Access-Control-Request-Method": "GET"})
        check(pre.headers.get("access-control-allow-origin") == web, "CORS allows the web origin")
        evil = client.options(f"{api}/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
        check("access-control-allow-origin" not in evil.headers, "CORS rejects other origins")
        page = client.get(f"{web}/")
        csp = page.headers.get("content-security-policy", "")
        check(page.status_code == 200, "web app loads")
        check(api in csp and "frame-ancestors 'none'" in csp, "CSP allows only the API and blocks framing")
        check(page.headers.get("x-frame-options") == "DENY" and page.headers.get("x-content-type-options") == "nosniff", "security headers")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
