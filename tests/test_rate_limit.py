"""Rate-limit policy, privacy, fail-closed, and Redis adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulseiq.rate_limit import (
    DEFAULT_RATE_LIMIT_POLICIES,
    InMemoryRateLimitStore,
    RateLimitPolicy,
    RateLimitScope,
    RateLimitService,
    RateLimitStoreResult,
    RateLimitUnavailable,
    RedisRateLimitStore,
)

NOW = datetime(2026, 8, 27, 9, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _policies(*, limit: int = 2, window: timedelta = timedelta(minutes=1)) -> dict[RateLimitScope, RateLimitPolicy]:
    return {scope: RateLimitPolicy(limit, window) for scope in RateLimitScope}


def test_sliding_window_limits_subject_and_recovers_after_window() -> None:
    clock = _Clock()
    service = RateLimitService(
        InMemoryRateLimitStore(),
        subject_pepper=b"p" * 32,
        clock=clock,
        policies=_policies(),
    )

    first = service.check(RateLimitScope.LOGIN_IP, subject="203.0.113.8", request_id="req-1")
    second = service.check(RateLimitScope.LOGIN_IP, subject="203.0.113.8", request_id="req-2")
    denied = service.check(RateLimitScope.LOGIN_IP, subject="203.0.113.8", request_id="req-3")

    assert first.allowed and first.remaining == 1
    assert second.allowed and second.remaining == 0
    assert not denied.allowed and denied.retry_after_seconds == 60

    clock.now += timedelta(seconds=61)
    recovered = service.check(RateLimitScope.LOGIN_IP, subject="203.0.113.8", request_id="req-4")
    assert recovered.allowed


def test_request_replay_is_idempotent_and_subjects_are_isolated() -> None:
    service = RateLimitService(
        InMemoryRateLimitStore(),
        subject_pepper=b"p" * 32,
        clock=lambda: NOW,
        policies=_policies(limit=1),
    )

    first = service.check(RateLimitScope.ASSISTANT_QUERY_ACTOR, subject="actor-1", request_id="req-1")
    replay = service.check(RateLimitScope.ASSISTANT_QUERY_ACTOR, subject="actor-1", request_id="req-1")
    other = service.check(RateLimitScope.ASSISTANT_QUERY_ACTOR, subject="actor-2", request_id="req-2")

    assert first.allowed and replay.allowed and other.allowed


def test_storage_keys_never_contain_raw_ip_account_or_actor() -> None:
    store = InMemoryRateLimitStore()
    service = RateLimitService(
        store,
        subject_pepper=b"p" * 32,
        clock=lambda: NOW,
        policies=_policies(),
    )
    raw_subject = "person@example.com|203.0.113.8"

    service.check(RateLimitScope.LOGIN_ACCOUNT_FAILURE, subject=raw_subject, request_id="request-raw")

    rendered = " ".join(store.storage_keys())
    assert raw_subject not in rendered
    assert "person@example.com" not in rendered
    assert "203.0.113.8" not in rendered
    assert "request-raw" not in rendered


def test_successful_login_can_reset_the_failure_bucket() -> None:
    service = RateLimitService(
        InMemoryRateLimitStore(),
        subject_pepper=b"p" * 32,
        clock=lambda: NOW,
        policies=_policies(limit=1),
    )
    scope = RateLimitScope.LOGIN_ACCOUNT_FAILURE
    assert service.check(scope, subject="account", request_id="failed-1").allowed
    assert not service.check(scope, subject="account", request_id="failed-2").allowed

    service.reset(scope, subject="account")

    assert service.check(scope, subject="account", request_id="failed-3").allowed


class _FailingStore:
    def consume(self, **_: object) -> object:
        raise ConnectionError("backend details must not escape")

    def reset(self, **_: object) -> None:
        raise ConnectionError("backend details must not escape")


def test_store_failures_deny_with_generic_error() -> None:
    service = RateLimitService(_FailingStore(), subject_pepper=b"p" * 32, clock=lambda: NOW)

    with pytest.raises(RateLimitUnavailable) as error:
        service.check(RateLimitScope.LOGIN_IP, subject="203.0.113.8", request_id="req-1")

    assert error.value.code == "rate_limit_unavailable"
    assert "backend" not in str(error.value).lower()


class _RedisClient:
    def __init__(self, response: object = (1, 4, 0)) -> None:
        self.response = response
        self.eval_args: tuple[object, ...] | None = None
        self.deleted: str | None = None

    def eval(self, *args: object) -> object:
        self.eval_args = args
        return self.response

    def delete(self, key: str) -> None:
        self.deleted = key


def test_redis_adapter_uses_atomic_script_and_converts_retry_to_seconds() -> None:
    client = _RedisClient((0, 0, 1501))
    store = RedisRateLimitStore(client)
    result = store.consume(
        bucket_key="pulseiq:rate:v1:login_ip:digest",
        member="request-digest",
        policy=RateLimitPolicy(5, timedelta(minutes=1)),
        now=NOW,
    )

    assert not result.allowed
    assert result.retry_after_seconds == 2
    assert client.eval_args is not None
    assert client.eval_args[1] == 1
    assert "ZREMRANGEBYSCORE" in str(client.eval_args[0])


def test_invalid_configuration_and_redis_response_fail_closed() -> None:
    with pytest.raises(ValueError, match="256 bits"):
        RateLimitService(InMemoryRateLimitStore(), subject_pepper=b"short", clock=lambda: NOW)
    with pytest.raises(ValueError, match="every protection scope"):
        RateLimitService(
            InMemoryRateLimitStore(),
            subject_pepper=b"p" * 32,
            clock=lambda: NOW,
            policies={RateLimitScope.LOGIN_IP: DEFAULT_RATE_LIMIT_POLICIES[RateLimitScope.LOGIN_IP]},
        )
    with pytest.raises(RuntimeError, match="invalid shape"):
        RedisRateLimitStore(_RedisClient("bad")).consume(
            bucket_key="key",
            member="member",
            policy=RateLimitPolicy(1, timedelta(seconds=1)),
            now=NOW,
        )


@pytest.mark.parametrize(
    "policy",
    [
        (0, timedelta(seconds=1)),
        (1, timedelta(0)),
        (1, timedelta(days=2)),
    ],
)
def test_rate_limit_policy_rejects_unsafe_bounds(policy: tuple[int, timedelta]) -> None:
    with pytest.raises(ValueError):
        RateLimitPolicy(*policy)


def test_store_result_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="negative"):
        RateLimitStoreResult(True, -1, 0)
    with pytest.raises(ValueError, match="negative"):
        RateLimitStoreResult(False, 0, -1)


def test_input_validation_and_naive_clock_fail_before_storage() -> None:
    valid = RateLimitService(
        InMemoryRateLimitStore(),
        subject_pepper=b"p" * 32,
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="subject"):
        valid.check(RateLimitScope.LOGIN_IP, subject="", request_id="request")
    with pytest.raises(ValueError, match="Request ID"):
        valid.check(RateLimitScope.LOGIN_IP, subject="subject", request_id="")

    naive = RateLimitService(
        InMemoryRateLimitStore(),
        subject_pepper=b"p" * 32,
        clock=lambda: datetime(2026, 8, 27),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        naive.check(RateLimitScope.LOGIN_IP, subject="subject", request_id="request")


def test_reset_failure_is_also_fail_closed() -> None:
    service = RateLimitService(_FailingStore(), subject_pepper=b"p" * 32, clock=lambda: NOW)

    with pytest.raises(RateLimitUnavailable):
        service.reset(RateLimitScope.LOGIN_ACCOUNT_FAILURE, subject="account")


@pytest.mark.parametrize("response", [(2, 0, 0), (1, -1, 0), (0, 0, -1)])
def test_redis_adapter_rejects_invalid_response_values(response: tuple[int, int, int]) -> None:
    with pytest.raises(RuntimeError, match="invalid values"):
        RedisRateLimitStore(_RedisClient(response)).consume(
            bucket_key="key",
            member="member",
            policy=RateLimitPolicy(1, timedelta(seconds=1)),
            now=NOW,
        )


def test_redis_reset_deletes_only_the_hmac_bucket_key() -> None:
    client = _RedisClient()
    store = RedisRateLimitStore(client)

    store.reset(bucket_key="pulseiq:rate:v1:scope:digest")

    assert client.deleted == "pulseiq:rate:v1:scope:digest"
