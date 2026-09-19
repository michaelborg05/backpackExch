"""Unit tests for the fetcher's 418/429 handling.

Binance escalates a rate-limit ban for every request that arrives while it is
in force. The old retry loop treated a 418 as transient and answered it with
four more requests per series: in the 2026-09-19 prod logs, an 18-request
boundary cycle met a 2-minute ban with 72 requests and a 279-second outage.

These tests pin the replacement. A rate-limited host is dropped, not retried;
the request fails over to the mirror; the feed only gives up when every host is
banned; and the retry ladder still covers the 5xx case it was written for.

No DB, no network — urlopen is stubbed.
"""
import json
import sys
import time
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import candle_fetcher as cf


PRIMARY = cf.BINANCE_BASE
MIRROR = cf.BINANCE_FALLBACK_BASE
URL = f"{PRIMARY}/api/v3/klines"


def _clear_ban():
    cf._ban_until.clear()
    cf._used_weight.clear()


def _http_error(code: int, msg: str = "", headers: dict = None):
    body = json.dumps({"code": -1003, "msg": msg}).encode() if msg else b""
    return urllib.error.HTTPError(
        url="https://x/api", code=code, msg="err",
        hdrs=headers or {}, fp=None,
    ), body


class _Resp:
    """Minimal urlopen context manager returning an empty JSON array."""

    def __init__(self, headers=None):
        self.headers = headers or {}

    def read(self):
        return b"[]"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _raising_urlopen(code, msg="", headers=None, calls=None):
    def _urlopen(req, timeout=None):
        if calls is not None:
            calls.append(req.full_url)
        err, body = _http_error(code, msg, headers)
        # HTTPError.read() needs a file object; fake it.
        err.read = lambda: body
        raise err
    return _urlopen


def test_418_costs_one_request_per_host():
    """Never four to the same host — every extra one lengthens the ban."""
    _clear_ban()
    calls = []
    with mock.patch.object(cf.urllib.request, "urlopen",
                           _raising_urlopen(418, calls=calls)):
        try:
            cf._http_get(URL, {"symbol": "BTCUSDT"})
            assert False, "expected BinanceRateLimited"
        except cf.BinanceRateLimited:
            pass
    # One to the primary, one to the mirror — and no retry on either.
    assert len(calls) == 2, f"sent {len(calls)} requests into an active ban"
    assert sorted({cf._host_of(c) for c in calls}) == sorted(
        {cf._host_of(PRIMARY), cf._host_of(MIRROR)})


def test_a_banned_host_fails_over_to_the_mirror():
    """A ban on one edge must not stop the feed — the other still answers."""
    _clear_ban()
    calls = []

    def _urlopen(req, timeout=None):
        calls.append(req.full_url)
        if cf._host_of(req.full_url) == cf._host_of(PRIMARY):
            err, body = _http_error(418, "")
            err.read = lambda: body
            raise err
        return _Resp()

    with mock.patch.object(cf.urllib.request, "urlopen", _urlopen):
        assert cf._http_get(URL, {"symbol": "BTCUSDT"}) == []

    assert len(calls) == 2
    assert cf._host_of(calls[1]) == cf._host_of(MIRROR)
    # The primary stays out of rotation; the mirror is untouched.
    assert cf.banned_until(cf._host_of(PRIMARY)) > time.time()
    assert cf.banned_until(cf._host_of(MIRROR)) == 0.0
    # The feed as a whole is still healthy — a usable host remains.
    assert cf.banned_until() == 0.0
    _clear_ban()


def test_ban_timestamp_is_read_from_the_body():
    """The -1003 payload carries the unban instant in epoch milliseconds."""
    _clear_ban()
    until_ms = int((time.time() + 3600) * 1000)
    msg = f"Way too much request weight used; IP banned until {until_ms}."
    with mock.patch.object(cf.urllib.request, "urlopen",
                           _raising_urlopen(418, msg=msg)):
        try:
            cf._http_get(URL, {})
            assert False, "expected BinanceRateLimited"
        except cf.BinanceRateLimited as e:
            assert abs(e.until - until_ms / 1000.0) < 1

    assert abs(cf.banned_until(cf._host_of(PRIMARY)) - until_ms / 1000.0) < 1


def test_retry_after_header_is_honoured():
    _clear_ban()
    with mock.patch.object(cf.urllib.request, "urlopen",
                           _raising_urlopen(429, headers={"Retry-After": "30"})):
        try:
            cf._http_get(URL, {})
            assert False, "expected BinanceRateLimited"
        except cf.BinanceRateLimited as e:
            assert 25 <= e.until - time.time() <= 31


def test_every_host_banned_opens_no_socket_at_all():
    """With nowhere to ask, the next series must not touch the network."""
    _clear_ban()
    for base in (PRIMARY, MIRROR):
        cf._ban_until[cf._host_of(base)] = time.time() + 300
    calls = []

    def _urlopen(req, timeout=None):
        calls.append(req.full_url)
        return _Resp()

    with mock.patch.object(cf.urllib.request, "urlopen", _urlopen):
        try:
            cf._http_get(URL, {"symbol": "ETHUSDT"})
            assert False, "expected BinanceRateLimited"
        except cf.BinanceRateLimited:
            pass
    assert calls == []
    assert cf.banned_until() > time.time()
    _clear_ban()


def test_expired_ban_lets_requests_through():
    _clear_ban()
    cf._ban_until[cf._host_of(PRIMARY)] = time.time() - 1
    with mock.patch.object(cf.urllib.request, "urlopen", lambda req, timeout=None: _Resp()):
        assert cf._http_get(URL, {}) == []
    assert cf.banned_until() == 0.0


def test_permanent_status_is_not_retried():
    """451 (restricted location) will not become a 200 by asking again."""
    _clear_ban()
    calls = []
    with mock.patch.object(cf.urllib.request, "urlopen",
                           _raising_urlopen(451, calls=calls)):
        try:
            cf._http_get(URL, {})
            assert False, "expected RuntimeError"
        except cf.BinanceRateLimited:
            assert False, "451 must not be treated as a ban"
        except RuntimeError:
            pass
    assert len(calls) == 1


def test_server_error_still_retries():
    """5xx is the transient case the retry ladder exists for."""
    _clear_ban()
    calls = []
    with mock.patch.object(cf.urllib.request, "urlopen",
                           _raising_urlopen(502, calls=calls)), \
            mock.patch.object(cf.time, "sleep"):
        try:
            cf._http_get(URL, {}, retries=3)
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass
    # Three attempts against each of the two hosts.
    assert len(calls) == 6


def test_used_weight_near_the_cap_pauses_before_the_429():
    """Backing off at 80% avoids the 429 that starts the escalation."""
    _clear_ban()
    slept = []
    resp = _Resp({"X-MBX-USED-WEIGHT-1M": str(cf._WEIGHT_SOFT_LIMIT + 1)})
    with mock.patch.object(cf.urllib.request, "urlopen", lambda req, timeout=None: resp), \
            mock.patch.object(cf.time, "sleep", side_effect=lambda s: slept.append(s)):
        assert cf._http_get(URL, {}) == []
    assert slept and 0 < slept[0] <= 60
    assert cf.last_used_weight(cf._host_of(PRIMARY)) == cf._WEIGHT_SOFT_LIMIT + 1
    _clear_ban()


def test_normal_weight_does_not_pause():
    _clear_ban()
    slept = []
    resp = _Resp({"X-MBX-USED-WEIGHT-1M": "22"})
    with mock.patch.object(cf.urllib.request, "urlopen", lambda req, timeout=None: resp), \
            mock.patch.object(cf.time, "sleep", side_effect=lambda s: slept.append(s)):
        assert cf._http_get(URL, {}) == []
    assert slept == []
    assert cf.last_used_weight(cf._host_of(PRIMARY)) == 22


if __name__ == "__main__":
    for fn in [test_418_costs_one_request_per_host,
               test_a_banned_host_fails_over_to_the_mirror,
               test_ban_timestamp_is_read_from_the_body,
               test_retry_after_header_is_honoured,
               test_every_host_banned_opens_no_socket_at_all,
               test_expired_ban_lets_requests_through,
               test_permanent_status_is_not_retried,
               test_server_error_still_retries,
               test_used_weight_near_the_cap_pauses_before_the_429,
               test_normal_weight_does_not_pause]:
        fn()
        print(f"  ok {fn.__name__}")
    print("\nALL CANDLE FETCHER RATE-LIMIT TESTS PASSED")
