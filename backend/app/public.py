"""Phase 5.1 public-mode hardening. Everything here is off unless GIST_PUBLIC_MODE=true.

Public mode:
- blocks owner-only writes (priority edits, billing entries) and free-text feedback;
- rate-limits every API route per client IP;
- gates paid AI behind GIST_PUBLIC_AI=true plus an access code, per-IP AI limits, one AI request
  at a time and a per-UTC-day dollar cap checked against the worst-case cost of each request.

The in-process limits reset on restart. The durable backstop is a dedicated OpenAI project and key
with its own budget limit, set by the owner in OpenAI's dashboard.
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import Request

from .errors import GistError


class PublicRejected(GistError):
    code = "public_mode"
    status = 403

    def __init__(self, message: str, *, public_message: str, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message, public_message=public_message, code=code)
        if status is not None:
            self.status = status


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() == "true"


def _number(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def public_mode() -> bool:
    return _flag("GIST_PUBLIC_MODE")


def access_code() -> str:
    return os.getenv("GIST_PUBLIC_AI_ACCESS_CODE", "")


def public_ai_enabled() -> bool:
    """Paid AI for visitors needs the flag AND an access code of at least 12 characters."""
    return public_mode() and _flag("GIST_PUBLIC_AI") and len(access_code()) >= 12


def limits() -> dict:
    return {"ai_per_hour": int(_number("GIST_PUBLIC_AI_PER_HOUR", 3)), "ai_per_day": int(_number("GIST_PUBLIC_AI_PER_DAY", 10)),
            "daily_usd": _number("GIST_PUBLIC_AI_DAILY_USD", 0.10), "api_per_minute": int(_number("GIST_PUBLIC_API_PER_MINUTE", 120)),
            "max_body_bytes": int(_number("GIST_MAX_BODY_BYTES", 65_536))}


def client_ip(request: Request) -> str:
    """Behind a trusted proxy (Render), the first X-Forwarded-For hop; otherwise the socket address."""
    if _flag("GIST_TRUST_PROXY"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded[:64]
    return request.client.host if request.client else "unknown"


def require_owner_write(action: str) -> None:
    if public_mode():
        raise PublicRejected(f"public mode blocked {action}", code="read_only_demo",
                             public_message=f"{action} is turned off in the public demo, so visitors cannot change what others see.")


class _Window:
    """Sliding-window counters per key, pruned as they age."""
    def __init__(self) -> None:
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str, limit: int, seconds: float, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self.lock:
            q = self.hits[key]
            while q and q[0] <= now - seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self.hits) > 50_000:            # bound memory under a flood of distinct IPs
                for k in [k for k, v in self.hits.items() if not v][:25_000]:
                    del self.hits[k]
            return True


class AiGate:
    """Access code, per-IP limits, one request at a time, and a per-UTC-day dollar cap."""
    def __init__(self) -> None:
        self.hour, self.day = _Window(), _Window()
        self.busy = threading.Lock()
        self.spend_lock = threading.Lock()
        self.spent: dict[str, float] = {}

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def spent_today(self) -> float:
        return round(self.spent.get(self._today(), 0.0), 6)

    @contextmanager
    def admit(self, ip: str, code: str | None, worst_case_usd: float):
        if not public_ai_enabled():
            raise PublicRejected("public AI off", code="ai_disabled",
                                 public_message="AI features are turned off in this public demo. Rule-based investigations and stored AI runs still work.")
        if not code or not hmac.compare_digest(code.encode(), access_code().encode()):
            raise PublicRejected("bad access code", code="access_code",
                                 public_message="AI features in this demo need an access code. Ask the project owner for one.")
        lim = limits()
        with self.spend_lock:
            if self.spent_today() + worst_case_usd > lim["daily_usd"]:
                raise PublicRejected("daily cap", code="daily_cap", status=429,
                                     public_message="Today's AI budget for this demo is used up. Try again tomorrow (UTC), or use the rule-based mode.")
        if not self.hour.allow(ip, lim["ai_per_hour"], 3600) or not self.day.allow(ip, lim["ai_per_day"], 86_400):
            raise PublicRejected("ip limit", code="rate_limited", status=429,
                                 public_message="You've reached this demo's AI limit for now. Try again later.")
        if not self.busy.acquire(blocking=False):
            raise PublicRejected("busy", code="busy", status=429, public_message="Another AI request is running. Try again in a moment.")
        try:
            with self.spend_lock:                     # reserve the worst case while running
                self.spent[self._today()] = self.spent_today() + worst_case_usd
            actual = {"usd": worst_case_usd}
            yield actual
        finally:
            with self.spend_lock:                     # replace the reservation with the recorded cost
                self.spent[self._today()] = max(0.0, self.spent_today() - worst_case_usd + actual["usd"])
            self.busy.release()


GATE = AiGate()
API_WINDOW = _Window()


def worst_case_usd(calls: int, output_cap: int) -> float:
    """Upper bound for `calls` model calls at the provider's byte and output caps and configured prices."""
    from .rag import provider
    try:
        _, in_price, out_price = provider._llm_settings()
    except provider.PaidApiDisabled:
        in_price, out_price = provider.DEFAULT_INPUT_USD_PER_M, provider.DEFAULT_OUTPUT_USD_PER_M
    return round(calls * (provider.GENERATION_BYTE_LIMIT * in_price + output_cap * out_price) / 1_000_000, 6)


def status() -> dict:
    lim = limits()
    return {"public_mode": public_mode(), "public_ai": public_ai_enabled(),
            "ai_needs_access_code": public_ai_enabled(),
            "limits": {k: lim[k] for k in ("ai_per_hour", "ai_per_day", "daily_usd")} if public_mode() else None,
            "spent_today_usd": GATE.spent_today() if public_mode() else None,
            "read_only": public_mode()}
