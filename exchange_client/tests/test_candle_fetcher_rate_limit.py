"""Unit tests for the fetcher's 418/429 handling.

Binance escalates a rate-limit ban — 2 minutes to 3 days — for every request
that arrives while the ban is in force. The old retry loop treated a 418 as a
transient error and answered it with four more requests per series, across 23
symbols x 2 timeframes, which is how a two-minute ban turns into a day. These
tests pin the opposite behaviour: a ban is never retried, it parks the whole
process until it lifts, and nothing else is transmitted in the meantime.

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


def _clear_ban():
    cf._ban_until = 0.0
    cf._last_used_weight = 0


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


def test_418_is_not_retried():
    """One request, not four — every extra one lengthens the ban."""
    _clear_ban()
    calls = []
    with mock.patch.object(cf.urllib.request, "urlopen",
                           _raising_urlopen(418, calls=calls)):
        try:
            cf._http_get("https://x/api", {"symbol": "BTCUSDT"})
            assert False, "expected BinanceRateLimited"
        except cf.BinanceRateLimited:
            pass
    assert len(calls) == 1, f"sent {len(calls)} requests into an active ban"


def test_ban_timestamp_is_read_from_the_body():
    """The -1003 payload carries the unban instant in epoch milliseconds."""
    _clear_ban()
    until_ms = int((time.time() + 3600) * 1000)
    msg = f"Way too much request weight used; IP banned until {until_ms}."
    with mock.patch.object(cf.urllib.request, "urlopen",
                           _raising_urlopen(418, msg=msg)):
        try:
            cf._http_get("https://x/api", {})
            assert False, "expected BinanceRateLimited"
        except cf.BinanceRateLimited as e:
            assert abs(e.until - until_ms / 1000.0) < 1

    assert abs(cf.banned_until() - until_ms / 1000.0) < 1


def test_retry_after_header_is_honoured():
    _clear_ban()
    with mock.patch.object(cf.urllib.request, "urlopen",
                           _raising_urlopen(429, headers={"Retry-After": "30"})):
        try:
            cf._http_get("https://x/api", {})
            assert False, "expected BinanceRateLimited"
        except cf.BinanceRateLimited as e:
            assert 25 <= e.until - time.time() <= 31


def test_an_active_ban_suppresses_every_later_request():
    """The gate is process-wide: the next series must not open a socket."""
    _clear_ban()
    cf._ban_until = time.time() + 300
    calls = []

    def _urlopen(req, timeout=None):
        calls.append(req.full_url)
        return _Resp()

    with mock.patch.object(cf.urllib.request, "urlopen", _urlopen):
        try:
            cf._http_get("https://x/api", {"symbol": "ETHUSDT"})
            assert False, "expected BinanceRateLimited"
        except cf.BinanceRateLimited:
            pass
    assert calls == []
    _clear_ban()


def test_expired_ban_lets_requests_through():
    _clear_ban()
    cf._ban_until = time.time() - 1
    with mock.patch.object(cf.urllib.request, "urlopen", lambda req, timeout=None: _Resp()):
        assert cf._http_get("https://x/api", {}) == []
    assert cf.banned_until() == 0.0


def test_permanent_status_is_not_retried():
    """451 (restricted location) will not become a 200 by asking again."""
    _clear_ban()
    calls = []
    with mock.patch.object(cf.urllib.request, "urlopen",
                           _raising_urlopen(451, calls=calls)):
        try:
            cf._http_get("https://x/api", {})
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
            cf._http_get("https://x/api", {}, retries=3)
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass
    assert len(calls) == 3


def test_used_weight_near_the_cap_pauses_before_the_429():
    """Backing off at 80% avoids the 429 that starts the escalation."""
    _clear_ban()
    slept = []
    resp = _Resp({"X-MBX-USED-WEIGHT-1M": str(cf._WEIGHT_SOFT_LIMIT + 1)})
    with mock.patch.object(cf.urllib.request, "urlopen", lambda req, timeout=None: resp), \
            mock.patch.object(cf.time, "sleep", side_effect=lambda s: slept.append(s)):
        assert cf._http_get("https://x/api", {}) == []
    assert slept and 0 < slept[0] <= 60
    assert cf.last_used_weight() == cf._WEIGHT_SOFT_LIMIT + 1
    _clear_ban()


def test_normal_weight_does_not_pause():
    _clear_ban()
    slept = []
    resp = _Resp({"X-MBX-USED-WEIGHT-1M": "22"})
    with mock.patch.object(cf.urllib.request, "urlopen", lambda req, timeout=None: resp), \
            mock.patch.object(cf.time, "sleep", side_effect=lambda s: slept.append(s)):
        assert cf._http_get("https://x/api", {}) == []
    assert slept == []
    assert cf.last_used_weight() == 22


if __name__ == "__main__":
    for fn in [test_418_is_not_retried,
               test_ban_timestamp_is_read_from_the_body,
               test_retry_after_header_is_honoured,
               test_an_active_ban_suppresses_every_later_request,
               test_expired_ban_lets_requests_through,
               test_permanent_status_is_not_retried,
               test_server_error_still_retries,
               test_used_weight_near_the_cap_pauses_before_the_429,
               test_normal_weight_does_not_pause]:
        fn()
        print(f"  ok {fn.__name__}")
    print("\nALL CANDLE FETCHER RATE-LIMIT TESTS PASSED")
