"""Privacy-preserving, fail-closed rate-limit contracts and adapters."""

from __future__ import annotations

import hashlib
import hmac
import math
import threading
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol


class RateLimitScope(StrEnum):
    """Stable protection scopes for internet-facing application actions."""

    LOGIN_IP = "login_ip"
    LOGIN_ACCOUNT_FAILURE = "login_account_failure"
    OIDC_CALLBACK_IP = "oidc_callback_ip"
    UPLOAD_RESERVATION_ACTOR = "upload_reservation_actor"
    ASSISTANT_QUERY_ACTOR = "assistant_query_actor"
    REPORT_GENERATE_ACTOR = "report_generate_actor"
    EXPORT_ACTOR = "export_actor"


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """One bounded sliding-window policy."""

    limit: int
    window: timedelta

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("Rate-limit count must be positive.")
        if not timedelta(seconds=1) <= self.window <= timedelta(days=1):
            raise ValueError("Rate-limit window must be between 1 second and 1 day.")


DEFAULT_RATE_LIMIT_POLICIES: Mapping[RateLimitScope, RateLimitPolicy] = {
    RateLimitScope.LOGIN_IP: RateLimitPolicy(10, timedelta(minutes=1)),
    RateLimitScope.LOGIN_ACCOUNT_FAILURE: RateLimitPolicy(5, timedelta(minutes=15)),
    RateLimitScope.OIDC_CALLBACK_IP: RateLimitPolicy(20, timedelta(minutes=5)),
    RateLimitScope.UPLOAD_RESERVATION_ACTOR: RateLimitPolicy(10, timedelta(minutes=10)),
    RateLimitScope.ASSISTANT_QUERY_ACTOR: RateLimitPolicy(30, timedelta(minutes=1)),
    RateLimitScope.REPORT_GENERATE_ACTOR: RateLimitPolicy(6, timedelta(minutes=10)),
    RateLimitScope.EXPORT_ACTOR: RateLimitPolicy(20, timedelta(minutes=10)),
}


@dataclass(frozen=True, slots=True)
class RateLimitStoreResult:
    """Atomic storage result using only non-sensitive timing/count data."""

    allowed: bool
    remaining: int
    retry_after_seconds: int

    def __post_init__(self) -> None:
        if self.remaining < 0 or self.retry_after_seconds < 0:
            raise ValueError("Rate-limit counters cannot be negative.")


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Caller-facing decision without the raw subject or storage key."""

    allowed: bool
    remaining: int
    retry_after_seconds: int
    scope: RateLimitScope


class RateLimitUnavailable(RuntimeError):
    """Fail-closed storage failure with no backend details."""

    def __init__(self) -> None:
        super().__init__("Rate-limit protection is temporarily unavailable.")
        self.code = "rate_limit_unavailable"


class RateLimitStore(Protocol):
    """Atomic store contract suitable for Redis or another shared backend."""

    def consume(
        self,
        *,
        bucket_key: str,
        member: str,
        policy: RateLimitPolicy,
        now: datetime,
    ) -> RateLimitStoreResult: ...

    def reset(self, *, bucket_key: str) -> None: ...


class RateLimitService:
    """Apply named policies while HMAC-binding raw IP/account/actor subjects."""

    def __init__(
        self,
        store: RateLimitStore,
        *,
        subject_pepper: bytes,
        clock: Callable[[], datetime],
        policies: Mapping[RateLimitScope, RateLimitPolicy] = DEFAULT_RATE_LIMIT_POLICIES,
    ) -> None:
        if len(subject_pepper) < 32:
            raise ValueError("Rate-limit subject pepper must contain at least 256 bits.")
        if frozenset(policies) != frozenset(RateLimitScope):
            raise ValueError("Rate-limit policies must cover every protection scope exactly.")
        self._store = store
        self._pepper = subject_pepper
        self._clock = clock
        self._policies = dict(policies)

    def check(self, scope: RateLimitScope, *, subject: str, request_id: str) -> RateLimitDecision:
        """Atomically consume one allowance, denying safely if storage fails."""

        _require_bounded(subject, "Rate-limit subject", maximum=512)
        _require_bounded(request_id, "Request ID", maximum=256)
        now = self._clock()
        _require_aware(now)
        bucket_key = self._bucket_key(scope, subject)
        member = _digest(self._pepper, f"request\n{request_id}")
        try:
            result = self._store.consume(
                bucket_key=bucket_key,
                member=member,
                policy=self._policies[scope],
                now=now,
            )
        except Exception as exc:
            raise RateLimitUnavailable() from exc
        return RateLimitDecision(
            allowed=result.allowed,
            remaining=result.remaining,
            retry_after_seconds=result.retry_after_seconds,
            scope=scope,
        )

    def reset(self, scope: RateLimitScope, *, subject: str) -> None:
        """Clear a failure bucket after a successful authenticated event."""

        _require_bounded(subject, "Rate-limit subject", maximum=512)
        try:
            self._store.reset(bucket_key=self._bucket_key(scope, subject))
        except Exception as exc:
            raise RateLimitUnavailable() from exc

    def _bucket_key(self, scope: RateLimitScope, subject: str) -> str:
        subject_digest = _digest(self._pepper, f"subject\n{scope.value}\n{subject}")
        return f"pulseiq:rate:v1:{scope.value}:{subject_digest}"


class InMemoryRateLimitStore:
    """Thread-safe deterministic adapter for unit tests and isolated local use."""

    def __init__(self) -> None:
        self._events: defaultdict[str, deque[tuple[datetime, str]]] = defaultdict(deque)
        self._lock = threading.Lock()

    def consume(
        self,
        *,
        bucket_key: str,
        member: str,
        policy: RateLimitPolicy,
        now: datetime,
    ) -> RateLimitStoreResult:
        with self._lock:
            events = self._events[bucket_key]
            cutoff = now - policy.window
            while events and events[0][0] <= cutoff:
                events.popleft()
            if any(existing_member == member for _, existing_member in events):
                remaining = max(0, policy.limit - len(events))
                return RateLimitStoreResult(True, remaining, 0)
            if len(events) >= policy.limit:
                retry_after = max(1, math.ceil((events[0][0] + policy.window - now).total_seconds()))
                return RateLimitStoreResult(False, 0, retry_after)
            events.append((now, member))
            return RateLimitStoreResult(True, policy.limit - len(events), 0)

    def reset(self, *, bucket_key: str) -> None:
        with self._lock:
            self._events.pop(bucket_key, None)

    def storage_keys(self) -> tuple[str, ...]:
        """Expose only HMAC-derived keys for deterministic privacy tests."""

        with self._lock:
            return tuple(self._events)


_REDIS_SLIDING_WINDOW = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now_ms - window_ms)
local existing = redis.call('ZSCORE', key, member)
local count = redis.call('ZCARD', key)
if existing then
  redis.call('PEXPIRE', key, window_ms)
  return {1, math.max(0, limit - count), 0}
end
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  redis.call('PEXPIRE', key, window_ms)
  local retry_ms = math.max(1, tonumber(oldest[2]) + window_ms - now_ms)
  return {0, 0, retry_ms}
end
redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms)
return {1, limit - count - 1, 0}
"""


class RedisRateLimitStore:
    """Atomic Redis sorted-set adapter; keys and members are already HMAC-derived."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def consume(
        self,
        *,
        bucket_key: str,
        member: str,
        policy: RateLimitPolicy,
        now: datetime,
    ) -> RateLimitStoreResult:
        now_ms = int(now.timestamp() * 1000)
        window_ms = int(policy.window.total_seconds() * 1000)
        raw = self._client.eval(
            _REDIS_SLIDING_WINDOW,
            1,
            bucket_key,
            now_ms,
            window_ms,
            policy.limit,
            member,
        )
        if not isinstance(raw, (list, tuple)) or len(raw) != 3:
            raise RuntimeError("Redis rate-limit response has an invalid shape.")
        allowed, remaining, retry_ms = (int(item) for item in raw)
        if allowed not in {0, 1} or remaining < 0 or retry_ms < 0:
            raise RuntimeError("Redis rate-limit response has invalid values.")
        return RateLimitStoreResult(
            allowed=bool(allowed),
            remaining=remaining,
            retry_after_seconds=math.ceil(retry_ms / 1000),
        )

    def reset(self, *, bucket_key: str) -> None:
        self._client.delete(bucket_key)


def _digest(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def _require_bounded(value: str, label: str, *, maximum: int) -> None:
    if not value or value.isspace() or len(value) > maximum:
        raise ValueError(f"{label} must be a non-empty bounded value.")


def _require_aware(moment: datetime) -> None:
    if moment.tzinfo is None:
        raise ValueError("Rate-limit time must be timezone-aware.")
