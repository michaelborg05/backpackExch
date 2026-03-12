"""
db/crud_ai.py
=============
CRUD helpers for AI signal outcome resolution.

Called from monitoring_service._execute_close() after a position closes
(TP hit, SL hit, trailing stop, trend invalidation, etc.).

Responsibilities:
  - resolve_ai_signal_outcome()  : update ai_signal_log with trade result
  - _classify_outcome()          : WIN / LOSS / BREAKEVEN helper
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("crud_ai")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def resolve_ai_signal_outcome(
    db: Session,
    ai_log_id: int,
    exit_price: float,
    entry_price: float,
    close_reason: str,
    closed_at: Optional[datetime] = None,
    candles_held: Optional[int] = None,
) -> bool:
    """
    Mark an ai_signal_log row as resolved with the actual trade outcome.

    Args:
        db           : active SQLAlchemy session
        ai_log_id    : id of the ai_signal_log row (stored on Position)
        exit_price   : actual exit price
        entry_price  : position entry price (for pnl calculation)
        close_reason : TAKE_PROFIT | STOP_LOSS | TRAILING_STOP | TREND_INVALIDATION | ...
        closed_at    : datetime the position closed (defaults to now)
        candles_held : optional number of 15m candles held (for analytics)

    Returns:
        True if row was found and updated, False otherwise.
    """
    try:
        from db.models import AISignalLog  # local import — avoids circular refs at module load

        row: Optional[AISignalLog] = db.query(AISignalLog).filter(
            AISignalLog.id == ai_log_id
        ).first()

        if row is None:
            logger.warning(f"resolve_ai_signal_outcome: ai_log_id={ai_log_id} not found — skipping")
            return False

        if row.outcome_resolved:
            logger.debug(f"ai_signal_log id={ai_log_id} already resolved — skipping")
            return True

        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        outcome = _classify_outcome(pnl_pct, close_reason)

        row.outcome_resolved     = True
        row.outcome_result       = outcome
        row.outcome_pnl_pct      = round(pnl_pct, 4)
        row.outcome_exit_price   = exit_price
        row.outcome_exit_time    = closed_at or datetime.now(timezone.utc)
        row.outcome_candles_held = candles_held

        db.commit()

        logger.info(
            f"✅ AI signal resolved: id={ai_log_id} | "
            f"outcome={outcome} | pnl={pnl_pct:+.2f}% | reason={close_reason}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to resolve AI signal outcome (id={ai_log_id}): {e}", exc_info=True)
        # Don't re-raise — a logging failure should never block position close
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _classify_outcome(pnl_pct: float, close_reason: str) -> str:
    """
    Map P&L percentage and close reason to one of the four outcome values
    that the ai_signal_log CHECK constraint allows:
        WIN | LOSS | BREAKEVEN | MISSED

    MISSED is reserved for shadow-mode rows where the rules system did NOT
    enter (rules_decision=SKIP) but the AI said ENTER — in that case there's
    no real trade to resolve, so we never call this function for those rows.
    """
    if abs(pnl_pct) < 0.05:   # within 5 bps — call it breakeven
        return "BREAKEVEN"
    return "WIN" if pnl_pct > 0 else "LOSS"
