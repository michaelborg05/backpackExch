"""
resolve_ai_outcomes.py
======================
Backfills outcome columns in ai_signal_log for rows that:
  1. Are NOT yet outcome_resolved
  2. Do NOT have a matching id in positions.ai_log_id
     (live positions write their own outcome on close)

For every qualifying row, walks forward through trend_analysis_log candles
(same pair/timeframe, after the signal's candle_time) and determines
whether SL or TP was hit first using candle high/low.

Handles all ai_decision types (ENTER / SKIP / WAIT):
  - ENTER: uses ai_entry_price, ai_stop_loss, ai_take_profit
  - SKIP / WAIT: simulates "what would have happened" at ai_entry_price
    so AI vs rules comparison is apples-to-apples

Outcome values written:
  WIN    — TP hit first
  LOSS   — SL hit first
  MISSED — no candle data available after signal (still recent / no data)

Usage:
  python resolve_ai_outcomes.py [--dry-run]
"""
import sys
import argparse
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("OutcomeResolver")

MAX_CANDLES_FORWARD = 200  # Safety cap per signal


# ---------------------------------------------------------------------------
# Simulation logic
# ---------------------------------------------------------------------------

def simulate_outcome(entry: float, sl: float, tp: float, candles: list) -> dict:
    """
    Walk candles forward. Check if high hit TP or low hit SL on each candle.
    If both within the same candle, whichever level is closer to the open fires first.
    """
    if not candles:
        return {"result": "MISSED", "exit_price": None, "exit_time": None, "candles_held": 0, "pnl_pct": None}

    is_long = tp > entry

    for i, candle in enumerate(candles):
        high  = float(candle.high)
        low   = float(candle.low)
        open_ = float(candle.open)

        tp_hit = (high >= tp) if is_long else (low  <= tp)
        sl_hit = (low  <= sl) if is_long else (high >= sl)

        if tp_hit and sl_hit:
            # Same candle — closer to open fires first
            if abs(open_ - tp) <= abs(open_ - sl):
                sl_hit = False
            else:
                tp_hit = False

        if tp_hit:
            pnl = abs(tp - entry) / entry * 100 * (1 if is_long else -1)
            return {"result": "WIN",  "exit_price": tp, "exit_time": candle.timestamp, "candles_held": i + 1, "pnl_pct": round(pnl, 4)}

        if sl_hit:
            pnl = -abs(sl - entry) / entry * 100
            return {"result": "LOSS", "exit_price": sl, "exit_time": candle.timestamp, "candles_held": i + 1, "pnl_pct": round(pnl, 4)}

    return {"result": "MISSED", "exit_price": None, "exit_time": None, "candles_held": len(candles), "pnl_pct": None}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def resolve(dry_run: bool = False):
    from db.utils import get_db_session
    from db.models import AISignalLog, TrendAnalysisLog, Position
    from sqlalchemy import exists

    with get_db_session() as db:
        # Fetch unresolved signals with no linked position
        signals = (
            db.query(AISignalLog)
            .filter(
                AISignalLog.outcome_resolved == False,
                ~exists().where(Position.ai_log_id == AISignalLog.id),
            )
            .order_by(AISignalLog.candle_time.asc())
            .all()
        )

        log.info(f"Found {len(signals)} unresolved signals not linked to live positions  (dry_run={dry_run})")

        stats = {"WIN": 0, "LOSS": 0, "MISSED": 0, "skipped": 0}

        for sig in signals:
            entry = float(sig.ai_entry_price) if sig.ai_entry_price is not None else None
            sl    = float(sig.ai_stop_loss)   if sig.ai_stop_loss   is not None else None
            tp    = float(sig.ai_take_profit) if sig.ai_take_profit is not None else None

            if entry is None or sl is None or tp is None:
                log.warning(f"  id={sig.id} missing price levels — skipping")
                stats["skipped"] += 1
                continue

            candles = (
                db.query(TrendAnalysisLog)
                .filter(
                    TrendAnalysisLog.symbol    == sig.pair,
                    TrendAnalysisLog.timeframe == sig.timeframe,
                    TrendAnalysisLog.timestamp >  sig.candle_time,
                )
                .order_by(TrendAnalysisLog.timestamp.asc())
                .limit(MAX_CANDLES_FORWARD)
                .all()
            )

            outcome = simulate_outcome(entry, sl, tp, candles)
            stats[outcome["result"]] += 1

            label = f"[{sig.ai_decision}→sim]" if sig.ai_decision in ("SKIP", "WAIT") else "[ENTER]"
            log.info(
                f"  id={sig.id:>4}  {sig.pair:<12}  {label:<14}  "
                f"entry={entry:.4f}  sl={sl:.4f}  tp={tp:.4f}  "
                f"-> {outcome['result']:<6}  pnl={outcome['pnl_pct']}%  candles={outcome['candles_held']}"
            )

            if not dry_run:
                sig.outcome_resolved     = True
                sig.outcome_result       = outcome["result"]
                sig.outcome_pnl_pct      = outcome["pnl_pct"]
                sig.outcome_exit_price   = outcome["exit_price"]
                sig.outcome_exit_time    = outcome["exit_time"]
                sig.outcome_candles_held = outcome["candles_held"]

        if not dry_run:
            db.commit()
            log.info("Changes committed.")
        else:
            log.info("Dry run — no changes written.")

        log.info(
            f"\nSummary: WIN={stats['WIN']}  LOSS={stats['LOSS']}  "
            f"MISSED={stats['MISSED']}  skipped(no prices)={stats['skipped']}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill ai_signal_log outcome columns")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to DB")
    args = parser.parse_args()

    resolve(dry_run=args.dry_run)
