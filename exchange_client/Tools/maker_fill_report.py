"""Report maker vs taker fill mix and the realised fee saving.

Run this after enabling entry_order_mode="maker_then_taker" on a profile, to
confirm the live maker fill rate matches the backtest assumption and to quantify
the fee saving that makes the strategy families viable.

    python Tools/maker_fill_report.py
    python Tools/maker_fill_report.py --profile p3_v11_slope_relaxed --days 30

Reads positions.fill_type (populated from live trading). Nothing here places
orders or touches the exchange.
"""
import argparse
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from db.utils import get_db_session

# Rough per-side fee assumptions (bps of notional). Adjust to your tier.
TAKER_FEE_BPS = 13.0   # ~0.13% seen in prod
MAKER_FEE_BPS = 2.0    # maker tier; set to a negative number if you earn a rebate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None)
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    with get_db_session() as db:
        # Guard: the column may not exist yet if the migration is unapplied.
        has_col = db.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name='positions' AND column_name='fill_type'
        """)).fetchone()
        if not has_col:
            print("positions.fill_type does not exist — apply the maker migration first:\n"
                  "  alembic upgrade head")
            return 1

        q = """
            SELECT profile_name, fill_type, close_reason, direction,
                   entry_price, exit_price
            FROM positions
            WHERE status='CLOSED' AND exit_price IS NOT NULL AND entry_price > 0
              AND created_at > now() - (:iv)::interval
        """
        params = {"iv": f"{args.days} days"}
        if args.profile:
            q += " AND profile_name = :p"
            params["p"] = args.profile
        rows = db.execute(text(q), params).fetchall()

    if not rows:
        print("No closed positions with fill_type in the window yet.")
        print("(Enable entry_order_mode='maker_then_taker' on a profile and let it trade.)")
        return 0

    by_type = defaultdict(list)
    labelled = 0
    for prof, ft, cr, direction, ep, xp in rows:
        short = (direction or "LONG") == "SHORT"
        pnl = (float(xp) - float(ep)) / float(ep) * 100 * (-1 if short else 1)
        by_type[ft or "unlabelled"].append(pnl)
        if ft:
            labelled += 1

    print(f"{len(rows)} closed positions ({labelled} with maker/taker attribution)\n")
    print(f"  {'fill_type':<14}{'n':>6}{'fill %':>8}{'gross avg':>11}")
    print("  " + "-" * 40)
    total = sum(len(v) for v in by_type.values())
    for ft, pnls in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        print(f"  {ft:<14}{len(pnls):>6}{len(pnls)/total:>7.0%}{st.mean(pnls):>+10.4f}%")

    maker_n = len(by_type.get("maker", []))
    taker_n = len(by_type.get("taker", []))
    mixed_n = len(by_type.get("mixed", []))
    decided = maker_n + taker_n + mixed_n
    if decided:
        maker_share = (maker_n + 0.5 * mixed_n) / decided
        # Fee per round trip = entry fee + exit fee. Exits are still taker today.
        blended_entry = maker_share * MAKER_FEE_BPS + (1 - maker_share) * TAKER_FEE_BPS
        taker_rt = 2 * TAKER_FEE_BPS
        maker_rt = blended_entry + TAKER_FEE_BPS
        print(f"\n  maker share of entries: {maker_share:.0%}")
        print(f"  round-trip fee  all-taker: {taker_rt:.1f} bps   with maker entries: {maker_rt:.1f} bps")
        print(f"  saving: {taker_rt - maker_rt:.1f} bps/trade "
              f"({(taker_rt - maker_rt)/100:.3f}% — compare to your +avg/trade edge)")
        print("\n  Cross-check: does the live maker fill share match the backtest assumption?")
        print("  If maker share is much below ~90%, the taker-fallback rate is eroding the saving —")
        print("  revisit maker_timeout_sec and confirm PostOnly is resting, not rejecting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
