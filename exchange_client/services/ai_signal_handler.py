"""
services/ai_signal_handler.py
==============================
Bridge between SignalGenerator and the AI entry agent.

Responsibilities:
  - Assembles EntryContext from live trend_cache data
  - Calls AIEntryAgent.evaluate_entry()
  - Logs both AI and rules decisions to ai_signal_log
  - Returns (AIEntryResult, log_id) to SignalGenerator

This keeps SignalGenerator clean — it just calls evaluate_and_log()
and gets back a result. All AI plumbing lives here.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple

logger = logging.getLogger("AISignalHandler")


# ── Re-export EntryDecision so signal_generator can import from here ──────────

class EntryDecision(str, Enum):
    ENTER = "ENTER"
    SKIP  = "SKIP"
    WAIT  = "WAIT"


@dataclass
class AIEntryResult:
    decision: EntryDecision
    confidence: float           # 0.0 – 1.0
    reasoning: str
    risk_flags: list
    suggested_entry: float
    suggested_stop_loss: float
    suggested_take_profit: float
    suggested_position_size_pct: float


# ── Lazy import guard — only pulls in `anthropic` if API key is set ──────────

def _get_anthropic_client():
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set")
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        raise ImportError(
            "anthropic package not installed. Run: pip install anthropic"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main handler
# ─────────────────────────────────────────────────────────────────────────────

class AISignalHandler:
    """
    Singleton service used by SignalGenerator for AI_AGENT profiles.
    One instance shared across all AI_AGENT profile instances.

    System prompt is loaded from the ai_prompts table at startup and cached
    in memory. Call reload_prompt() to refresh without restarting.

    Resolution priority (highest → lowest):
      1. Profile + strategy match  (profile_id AND strategy_type both match)
      2. Profile-only match        (profile_id matches, any strategy_type)
      3. Strategy-type-only match  (strategy_type matches, no profile constraint)
      4. Global default            (is_default=True, no strategy/profile constraint)
      5. Hardcoded _FALLBACK_PROMPT (safety net — logs a warning if reached)
    """

    MODEL = "claude-haiku-4-5-20251001"   # fast + cheap; swap to sonnet for harder reasoning

    # Safety-net prompt — used only if the DB is unreachable or empty.
    # Keep in sync with the seed row in the migration.
    _FALLBACK_PROMPT = """You are an expert crypto trader specialising in multi-timeframe \ntrend-following and mean-reversion entries on 15-minute candles. You are embedded \nin an algorithmic trading system. The 60-minute trend gates have ALREADY passed.\nYour job is purely 15m entry timing discretion.\n\nYour strengths:\n- Reading candle quality (body size, wick positioning, volume confirmation)\n- Identifying optimal RSI entry windows (trajectory, not just threshold)\n- Spotting technically-valid-but-contextually-weak setups (low volume, late entry)\n- Suggesting asymmetric risk/reward levels based on recent structure\n\nRules:\n- Be decisive. WAIT is valid but use sparingly — only when one more candle would \n  meaningfully change your view.\n- SKIP means the setup is genuinely poor, not just uncertain.\n- Position size 1-5% of portfolio. Scale with confidence:\n  <0.60 → 1%, 0.60-0.75 → 2%, 0.75-0.85 → 3%, >0.85 → 4-5%\n- Stop loss: below recent structure low for longs.\n- Take profit: minimum 1.5:1 RR, prefer 2:1+.\n- Volume is a soft signal only. Crypto volume varies significantly by time of day \n  and day of week (Asian/US/EU session gaps, weekend illiquidity). Never hard-block \n  an entry on low volume alone — use it only to shade confidence down by 0.05-0.10 \n  max. A good setup with low volume is still a good setup.\n- The trading system's minimum confidence threshold is 72% (0.72). \n  If you assess confidence >= 0.72, you MUST return ENTER. \n  WAIT is only valid for confidence 0.55-0.71. \n  Below 0.55, return SKIP.\n  Respond ONLY with valid JSON. No markdown. No preamble."""

    def __init__(self):
        self._client = None          # lazy-loaded on first call
        self._prompt_cache: dict = {}  # keyed by (strategy_type, profile_id)

    @property
    def client(self):
        if self._client is None:
            self._client = _get_anthropic_client()
        return self._client

    # ── Prompt resolution ─────────────────────────────────────────────────────

    def _load_prompt(self, strategy_type: Optional[str], profile_id: Optional[int]) -> str:
        """
        Resolve the best matching system prompt from the DB.

        Returns the prompt text. Falls back to _FALLBACK_PROMPT if nothing
        is found or the DB is unreachable.
        """
        try:
            from db.utils import get_db_session
            from db.models import AIPrompt
            from sqlalchemy import and_, or_

            with get_db_session() as db:
                # Fetch all active candidates in one query, then rank in Python.
                # This avoids complex SQL priority ordering across nullable columns.
                candidates = (
                    db.query(AIPrompt)
                    .filter(AIPrompt.is_active == True)
                    .filter(
                        or_(
                            # Exact profile + strategy match
                            and_(
                                AIPrompt.profile_id == profile_id,
                                AIPrompt.strategy_type == strategy_type,
                            ),
                            # Profile-only match
                            and_(
                                AIPrompt.profile_id == profile_id,
                                AIPrompt.strategy_type == None,
                            ),
                            # Strategy-only match
                            and_(
                                AIPrompt.profile_id == None,
                                AIPrompt.strategy_type == strategy_type,
                            ),
                            # Global default
                            and_(
                                AIPrompt.profile_id == None,
                                AIPrompt.strategy_type == None,
                                AIPrompt.is_default == True,
                            ),
                        )
                    )
                    .all()
                )

                if not candidates:
                    logger.warning(
                        f"No active AI prompt found for strategy={strategy_type!r} "
                        f"profile_id={profile_id}. Using hardcoded fallback."
                    )
                    return self._FALLBACK_PROMPT

                # Priority ranking: higher score = better match
                def _rank(p: AIPrompt) -> int:
                    if p.profile_id == profile_id and p.strategy_type == strategy_type:
                        return 4   # exact match
                    if p.profile_id == profile_id:
                        return 3   # profile match, any strategy
                    if p.strategy_type == strategy_type and strategy_type is not None:
                        return 2   # strategy match, no profile constraint
                    return 1       # global default

                best = max(candidates, key=_rank)
                logger.info(
                    f"Resolved prompt '{best.name}' (id={best.id}) "
                    f"for strategy={strategy_type!r} profile_id={profile_id}"
                )
                return best.system_prompt

        except Exception as e:
            logger.error(f"Failed to load prompt from DB: {e}. Using fallback.")
            return self._FALLBACK_PROMPT

    def get_prompt(self, strategy_type: Optional[str], profile_id: Optional[int]) -> str:
        """
        Return the cached prompt for this (strategy_type, profile_id) combination.
        Loads from DB on first call; use reload_prompt() to refresh.
        """
        cache_key = (strategy_type, profile_id)
        if cache_key not in self._prompt_cache:
            self._prompt_cache[cache_key] = self._load_prompt(strategy_type, profile_id)
        return self._prompt_cache[cache_key]

    def reload_prompt(
        self,
        strategy_type: Optional[str] = None,
        profile_id: Optional[int] = None,
    ) -> str:
        """
        Force a fresh DB load for a specific (strategy_type, profile_id) pair,
        or clear the entire cache if both are None.

        Returns the freshly loaded prompt text.
        """
        if strategy_type is None and profile_id is None:
            self._prompt_cache.clear()
            logger.info("AI prompt cache cleared (all entries).")
            return ""
        cache_key = (strategy_type, profile_id)
        self._prompt_cache.pop(cache_key, None)
        prompt = self._load_prompt(strategy_type, profile_id)
        self._prompt_cache[cache_key] = prompt
        logger.info(
            f"AI prompt reloaded for strategy={strategy_type!r} profile_id={profile_id}"
        )
        return prompt

    # ── Public API ────────────────────────────────────────────────────────────

    def evaluate_and_log(
        self,
        symbol: str,
        profile,                    # TradingProfile
        trend_cache,                # TrendCache instance
        current_price: float,
        trend_timeframe: str,
        entry_timeframe: str,
        gate_data: dict,            # Already-computed 60m gate values
        rules_would_enter: bool,    # Parallel rules decision for comparison
    ) -> Tuple[Optional[AIEntryResult], Optional[int]]:
        """
        Main entry point from SignalGenerator.

        Returns:
            (AIEntryResult, log_row_id) — log_row_id is None if DB write failed
        """
        candle_time = datetime.now(timezone.utc)
        current_price = float(current_price)  # guard against Decimal from DB

        # Build context from trend cache
        ctx = self._build_context(
            symbol, profile, trend_cache,
            current_price, trend_timeframe, entry_timeframe,
            gate_data, candle_time
        )

        # Call AI
        ai_result = self._call_agent(ctx, current_price, profile)

        # Log to DB
        log_id = self._log_to_db(
            symbol=symbol,
            profile_name=profile.name,
            candle_time=candle_time,
            gate_data=gate_data,
            ai_result=ai_result,
            rules_would_enter=rules_would_enter,
            current_price=current_price,
            context_snapshot=self._make_snapshot(ctx),
        )

        return ai_result, log_id

    # ── Context assembly ──────────────────────────────────────────────────────

    def _build_context(
        self, symbol, profile, trend_cache,
        current_price, trend_tf, entry_tf,
        gate_data, candle_time
    ) -> dict:
        """
        Assembles all the data the AI needs from trend_cache.
        Returns a plain dict (JSON-serialisable) — no dataclass dependency.
        """
        trend_15m = trend_cache.get(symbol, entry_tf)
        candle_history = trend_cache._candle_history.get(f"{symbol}_{entry_tf}", [])
        rsi_history    = trend_cache._rsi_history.get(f"{symbol}_{entry_tf}", [])

        rsi_15m      = float(trend_15m.rsi)          if trend_15m else None
        volume_ratio = float(trend_15m.volume_ratio)  if trend_15m and trend_15m.volume_ratio else 1.0

        # RSI peak scan from history
        rsi_values = [r[1] for r in rsi_history if r[1] is not None]
        rsi_peak   = max(rsi_values) if rsi_values else None
        candles_since_peak = None
        if rsi_peak and rsi_values:
            peak_idx = rsi_values.index(rsi_peak)
            candles_since_peak = len(rsi_values) - 1 - peak_idx

        # Drop from prior close
        drop_pct = 0.0
        if candle_history:
            prior_close = candle_history[-1].get("close", current_price)
            if prior_close > 0:
                drop_pct = max(0.0, (float(prior_close) - float(current_price)) / float(prior_close) * 100)

        return {
            "pair":               symbol,
            "profile_name":       profile.name,
            "current_price":      current_price,
            "candle_time":        candle_time.isoformat(),
            "gate":               gate_data,
            "rsi_15m":            rsi_15m,
            "volume_vs_avg":      volume_ratio,
            "rsi_peak_recent":    rsi_peak,
            "candles_since_peak": candles_since_peak,
            "drop_from_prior_close_pct": round(drop_pct, 3),
            "candle_pattern":     getattr(trend_15m, 'pattern', None) if trend_15m else None,
            "candles_15m":        candle_history[-8:],
            "profile_params":     self._extract_profile_params(profile),
        }

    def _extract_profile_params(self, profile) -> dict:
        """Pull the key profile config the AI needs to reason within your rules."""
        return {
            "take_profit_pct":    float(profile.take_profit_pct)   if profile.take_profit_pct   else None,
            "stop_loss_pct":      float(profile.stop_loss_pct)     if profile.stop_loss_pct     else None,
            "min_signal_confidence": getattr(profile, 'min_signal_confidence', 72.0),
            "entry_indicators":   [
                {"type": ind.indicator_type, "params": ind.params}
                for ind in getattr(profile, 'indicators', [])
                if ind.category == 'entry' and ind.enabled
            ],
        }

    # ── AI call ───────────────────────────────────────────────────────────────

    def _call_agent(self, ctx: dict, current_price: float, profile) -> AIEntryResult:
        """Calls the Anthropic API and parses the structured response."""
        current_price = float(current_price)  # guard against Decimal from DB
        prompt = self._build_prompt(ctx, current_price)

        # Resolve system prompt from DB (cached after first call)
        strategy_type = getattr(profile, 'strategy_type', None)
        profile_id    = getattr(profile, 'id', None)
        system_prompt = self.get_prompt(strategy_type, profile_id)

        try:
            response = self.client.messages.create(
                model=self.MODEL,
                max_tokens=700,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text
            return self._parse_response(raw, current_price)

        except Exception as e:
            logger.error(f"AI agent API error: {e}")
            # Fail-safe: SKIP on error so no unintended live trades fire
            return AIEntryResult(
                decision=EntryDecision.SKIP,
                confidence=0.0,
                reasoning=f"Agent error: {e}",
                risk_flags=["agent_error"],
                suggested_entry=current_price,
                suggested_stop_loss=current_price * 0.98,
                suggested_take_profit=current_price * 1.04,
                suggested_position_size_pct=0.0,
            )

    def _build_prompt(self, ctx: dict, current_price: float) -> str:
        candles_str = "\n".join([
            f"  O={c.get('open')} H={c.get('high')} L={c.get('low')} C={c.get('close')}"
            for c in ctx.get("candles_15m", [])
        ]) or "  (no candle history)"

        gate = ctx.get("gate", {})

        return f"""15m entry decision needed. 60m gates already passed.

PAIR: {ctx['pair']}  |  PROFILE: {ctx['profile_name']}  |  PRICE: {current_price}

── SESSION CONTEXT ─────────────────────────────────────────
  UTC Time:  {ctx['candle_time']}
  Day:       {datetime.fromisoformat(ctx['candle_time']).strftime('%A')}

── 60m GATE CONTEXT (already confirmed) ───────────────────
  RSI 60m:         {gate.get('rsi_60m')}
  Trend Direction: {gate.get('trend_direction')}
  EMA20/50:        {gate.get('ema20')} / {gate.get('ema50')}

── 15m ENTRY CONDITIONS ────────────────────────────────────
  RSI 15m:             {ctx.get('rsi_15m')}
  Candle Pattern:      {ctx.get('candle_pattern') or 'none'}
  Recent RSI Peak:     {ctx.get('rsi_peak_recent')} ({ctx.get('candles_since_peak')} candles ago)
  Drop from Prior Close: {ctx.get('drop_from_prior_close_pct')}%
  Volume vs Avg:       {ctx.get('volume_vs_avg')}x

── RECENT 15m CANDLES (oldest → newest) ────────────────────
{candles_str}

── PROFILE PARAMETERS ──────────────────────────────────────
{json.dumps(ctx.get('profile_params', {}), indent=2)}

Respond with exactly this JSON:
{{
  "decision": "ENTER" | "SKIP" | "WAIT",
  "confidence": 0.0-1.0,
  "reasoning": "2-4 sentence chain of thought",
  "risk_flags": ["list", "of", "concerns"],
  "suggested_entry": {current_price},
  "suggested_stop_loss": <price>,
  "suggested_take_profit": <price>,
  "suggested_position_size_pct": <1-5>
}}"""

    def _parse_response(self, raw: str, current_price: float) -> AIEntryResult:
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
            data = json.loads(cleaned.strip())
            return AIEntryResult(
                decision=EntryDecision(data["decision"]),
                confidence=float(data["confidence"]),
                reasoning=data.get("reasoning", ""),
                risk_flags=data.get("risk_flags", []),
                suggested_entry=float(data.get("suggested_entry") or current_price),
                suggested_stop_loss=float(data.get("suggested_stop_loss") or current_price * 0.98),
                suggested_take_profit=float(data.get("suggested_take_profit") or current_price * 1.04),
                suggested_position_size_pct=float(data.get("suggested_position_size_pct") or 1.0),
            )
        except Exception as e:
            logger.warning(f"AI response parse error: {e} | raw: {raw[:300]}")
            return AIEntryResult(
                decision=EntryDecision.SKIP,
                confidence=0.0,
                reasoning=f"Parse error: {e}",
                risk_flags=["parse_error"],
                suggested_entry=current_price,
                suggested_stop_loss=current_price * 0.98,
                suggested_take_profit=current_price * 1.04,
                suggested_position_size_pct=0.0,
            )

    # ── DB logging ────────────────────────────────────────────────────────────

    def _log_to_db(
        self,
        symbol, profile_name, candle_time,
        gate_data, ai_result: AIEntryResult,
        rules_would_enter: bool,
        current_price: float,
        context_snapshot: dict,
    ) -> Optional[int]:
        """Insert shadow comparison row into ai_signal_log. Returns row id."""
        try:
            from db.utils import get_db_session
            from db.models import AISignalLog

            with get_db_session() as session:
                row = AISignalLog(
                    pair=symbol,
                    profile_name=profile_name,
                    signal_source="SHADOW",
                    candle_time=candle_time,
                    timeframe="15",
                    gate_60m_passed=True,
                    gate_60m_data=gate_data,
                    ai_decision=ai_result.decision.value,
                    ai_confidence=ai_result.confidence,
                    ai_reasoning=ai_result.reasoning,
                    ai_risk_flags=ai_result.risk_flags,
                    ai_entry_price=ai_result.suggested_entry,
                    ai_stop_loss=ai_result.suggested_stop_loss,
                    ai_take_profit=ai_result.suggested_take_profit,
                    ai_position_size_pct=ai_result.suggested_position_size_pct,
                    rules_decision="ENTER" if rules_would_enter else "SKIP",
                    rules_entry_price=current_price,
                    outcome_resolved=False,
                    context_snapshot=context_snapshot,
                )
                session.add(row)
                session.flush()
                log_id = row.id
                session.commit()
                return log_id

        except Exception as e:
            logger.error(f"Failed to log AI signal to DB: {e}")
            return None

    def _make_snapshot(self, ctx: dict) -> dict:
        """Trim context to a compact JSON snapshot for the DB."""
        return {
            "rsi_15m":            ctx.get("rsi_15m"),
            "rsi_peak_recent":    ctx.get("rsi_peak_recent"),
            "candles_since_peak": ctx.get("candles_since_peak"),
            "drop_pct":           ctx.get("drop_from_prior_close_pct"),
            "volume_vs_avg":      ctx.get("volume_vs_avg"),
            "candle_pattern":     ctx.get("candle_pattern"),
            "candles":            ctx.get("candles_15m", [])[-4:],
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_ai_signal_handler: Optional[AISignalHandler] = None


def get_ai_signal_handler() -> AISignalHandler:
    global _ai_signal_handler
    if _ai_signal_handler is None:
        _ai_signal_handler = AISignalHandler()
    return _ai_signal_handler