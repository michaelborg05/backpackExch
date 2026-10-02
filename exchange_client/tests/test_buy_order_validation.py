"""Unit tests for TradingService._validate_buy_order. No exchange, no DB.

Driven with an unbound call against a fake `self` (same trick as
test_maker_execution.py) so the balance/price/rounding collaborators can be
faked without constructing a real TradingService.

Regression origin (live, 2026-10-02): a maker→taker fallback read a stale
BalanceCache that still showed the cancelled maker order's USDC locked, silently
downsized a 0.34 ZEC order to 0.0027, and lost the entry when the step size
rounded that to zero.
"""
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api_builders.trading_builder import TradingService
from utils.exceptions import InsufficientBalanceError

_NOOP_LOGGER = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                               error=lambda *a, **k: None, debug=lambda *a, **k: None)


class _FakeBalanceCache:
    """Returns the balances in sequence, one per read, holding the last value —
    so a test can model "stale, then fresh after refresh"."""

    def __init__(self, *availables):
        self._availables = [Decimal(str(a)) for a in availables]
        self.reads = 0

    def get_available_balance(self, profile_name, asset):
        value = self._availables[min(self.reads, len(self._availables) - 1)]
        self.reads += 1
        return value


def _fake_self(balance_cache, price="1388.34"):
    """A `self` carrying the real helper methods under test plus fakes for its
    collaborators. Price/parse/round are the production implementations."""
    fake = SimpleNamespace(
        logger=_NOOP_LOGGER,
        balance_cache=balance_cache,
        profile=SimpleNamespace(name="profile7"),
        MIN_BUY_DOWNSIZE_RATIO=TradingService.MIN_BUY_DOWNSIZE_RATIO,
        refreshes=0,
    )
    fake._get_order_price = lambda order, base, quote: Decimal(price)
    fake._parse_order_quantity = lambda q, avail, asset: (
        None if str(q).upper() == "MAX" else Decimal(str(q))
    )
    fake._apply_buffer_and_round = lambda qty, px: TradingService._apply_buffer_and_round(
        fake, qty, px
    )
    fake._round_down = lambda value, dp: TradingService._round_down(fake, value, dp)

    def _refresh(order_response=None):
        fake.refreshes += 1

    fake._refresh_balance_cache_after_trade = _refresh
    return fake


def _validate(fake, quantity):
    order = SimpleNamespace(symbol="ZEC_USDC", quantity=str(quantity),
                            order_type=None, price=None)
    return TradingService._validate_buy_order(fake, order, "ZEC", "USDC")


def test_sufficient_balance_passes_through_untouched():
    fake = _fake_self(_FakeBalanceCache("1000"))
    order = _validate(fake, "0.34")
    assert Decimal(order.quantity) == Decimal("0.34")
    assert fake.refreshes == 0, "no refresh should be needed when the balance covers it"
    print("  ok sufficient balance: quantity unchanged, no refresh")


def test_stale_cache_is_refreshed_before_downsizing():
    # The live failure: cache says $3.756 (maker order's hold not yet released),
    # the venue has $475.79 once refreshed. The order must survive intact.
    fake = _fake_self(_FakeBalanceCache("3.756", "475.79"))
    order = _validate(fake, "0.34")
    assert fake.refreshes == 1, "stale shortfall did not trigger a refresh"
    assert Decimal(order.quantity) == Decimal("0.34"), (
        f"order was downsized despite the refreshed balance covering it: {order.quantity}"
    )
    print("  ok stale shortfall triggers a refresh and the order survives")


def test_genuine_dust_shortfall_raises_rather_than_placing():
    # Refresh confirms the funds really aren't there: fail loudly instead of
    # opening a dust position (its own TP/SL, fees, and it holds the symbol).
    fake = _fake_self(_FakeBalanceCache("3.756"))
    try:
        _validate(fake, "0.34")
    except InsufficientBalanceError as e:
        assert "dust" in str(e)
        assert fake.refreshes == 1, "should still have tried a refresh first"
        print("  ok genuine dust shortfall raises InsufficientBalanceError")
        return
    raise AssertionError("a 0.7%-of-intended order was placed instead of raising")


def test_small_shortfall_still_shaves():
    # A fee/rounding-sized shortfall is the legitimate downsize case and must
    # keep working — only gutting the order is refused. Bound derived from the
    # constant so retuning MIN_BUY_DOWNSIZE_RATIO doesn't make this vacuous.
    fake = _fake_self(_FakeBalanceCache("450.00"))
    requested = Decimal("0.34")
    order = _validate(fake, requested)
    qty = Decimal(order.quantity)
    assert requested * TradingService.MIN_BUY_DOWNSIZE_RATIO <= qty < requested, (
        f"expected a shave above the dust floor, got {qty}"
    )
    print(f"  ok small shortfall shaves 0.34 -> {qty}")


def test_max_order_unaffected():
    fake = _fake_self(_FakeBalanceCache("475.79"))
    order = _validate(fake, "MAX")
    assert Decimal(order.quantity) > 0
    assert fake.refreshes == 0
    print(f"  ok MAX still sizes to the full balance ({order.quantity})")


if __name__ == "__main__":
    for fn in [test_sufficient_balance_passes_through_untouched,
               test_stale_cache_is_refreshed_before_downsizing,
               test_genuine_dust_shortfall_raises_rather_than_placing,
               test_small_shortfall_still_shaves,
               test_max_order_unaffected]:
        fn()
    print("\nALL BUY-ORDER VALIDATION TESTS PASSED")
