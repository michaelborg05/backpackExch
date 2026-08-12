# services/signal_diagnostics.py
"""Keeps the reason each profile/symbol did NOT signal on its most recent scan.

The scan already computes a precise rejection reason for every symbol — it just
logs it and throws it away, which is why answering "why is nothing firing?"
currently means reading thousands of log lines. This module holds the latest
outcome per (profile, symbol) in memory so a Telegram lookup can answer that
from the last real cycle: no re-evaluation, no exchange calls, no DB reads.

Records are overwritten each scan, so the store never grows beyond
profiles × symbols.
"""
import re
import time
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Stage labels, in pipeline order. Used for ordering/grouping in summaries.
STAGE_ORDER = [
    "signal",
    "confidence",
    "entry",
    "trend",
    "reentry",
    "regime",
    "cooldown",
    "capacity",
    "breaker",
    "hours",
    "balance",
    "price",
    "error",
]

STAGE_EMOJI = {
    "signal": "🎯",
    "confidence": "📉",
    "entry": "✗",
    "trend": "✗",
    "reentry": "⏳",
    "regime": "⛔",
    "cooldown": "⏳",
    "capacity": "📦",
    "breaker": "🚨",
    "hours": "🕑",
    "balance": "💰",
    "price": "❓",
    "error": "⚠️",
}

# Indicator messages are always "<Label>: ✓/✗ (detail)". Labels never contain
# ':', ';' or brackets, so anchoring on ": ✗" pulls the failing ones out of a
# reason string without tripping over commas inside the detail parentheses.
_FAIL_RE = re.compile(r"([^;:(),\[\]]+?):\s*✗")


def failing_labels(text: str) -> List[str]:
    """Indicator names that failed inside a reason string, in order, deduped."""
    seen: Dict[str, None] = {}
    for match in _FAIL_RE.finditer(text or ""):
        label = match.group(1).strip()
        if label:
            seen.setdefault(label, None)
    return list(seen)


def strip_trailing_details(text: str) -> str:
    """Drop the trailing "(every indicator, passing or not)" dump.

    Every reason string ends with that full dump in parentheses, which repeats
    the failures and buries the ones that actually mattered. Parens nest inside
    it, so match from the end rather than splitting on " (".
    """
    text = (text or "").rstrip()
    if not text.endswith(")"):
        return text

    depth = 0
    for i in range(len(text) - 1, -1, -1):
        if text[i] == ")":
            depth += 1
        elif text[i] == "(":
            depth -= 1
            if depth == 0:
                return text[:i].rstrip()
    return text


def blocking_labels(reason: str) -> List[str]:
    """The indicators actually responsible for the rejection.

    For a hard stop that's just the hard-stop list (the trailing dump also
    shows ✗ for indicators that weren't hard stops). For a score-based failure
    every failing indicator contributed.
    """
    if "HARD STOP:" in reason:
        return failing_labels(strip_trailing_details(reason.split("HARD STOP:", 1)[1]))
    return failing_labels(reason)


@dataclass
class SignalOutcome:
    profile_name: str
    display_name: str
    symbol: str
    stage: str            # see STAGE_ORDER
    reason: str           # full reason string as logged
    timeframe: str = ""   # timeframe the failing gate ran on, when relevant
    confidence: Optional[float] = None
    timestamp: float = 0.0

    @property
    def passed(self) -> bool:
        return self.stage == "signal"

    def cause(self) -> str:
        """Short, groupable description of what blocked this symbol."""
        if self.stage == "signal":
            return "SIGNAL"

        if self.stage in ("trend", "entry"):
            labels = blocking_labels(self.reason)
            tf = f" ({self.timeframe})" if self.timeframe else ""
            if not labels:
                # Score-based failure with no ✗ parsed — fall back to the count.
                head = self.reason.split("(")[0].strip()
                return f"{head}{tf}" if head else f"{self.stage} filter{tf}"
            return " + ".join(labels[:2]) + ("…" if len(labels) > 2 else "") + tf

        if self.stage == "regime":
            # "⚠️ Choppy conditions (2 issues): Price stagnant…" → "regime: Choppy conditions"
            head = self.reason.split("(")[0].split(":")[0].strip()
            head = head.lstrip("⚠️🚫✅ ").strip()
            return f"regime: {head}" if head else "regime blocked"

        if self.stage == "confidence":
            return self.reason

        if self.stage == "reentry":
            return f"re-entry: {self.reason.split('(')[0].strip()}"

        return self.reason.split("(")[0].strip() or self.stage


class SignalDiagnostics:
    """Thread-safe store of the last outcome per (profile, symbol)."""

    def __init__(self):
        self._outcomes: Dict[Tuple[str, str], SignalOutcome] = {}
        self._lock = threading.Lock()

    def record(
        self,
        profile_name: str,
        display_name: str,
        symbol: str,
        stage: str,
        reason: str,
        timeframe: str = "",
        confidence: Optional[float] = None,
    ) -> None:
        outcome = SignalOutcome(
            profile_name=profile_name,
            display_name=display_name,
            symbol=symbol,
            stage=stage,
            reason=reason,
            timeframe=timeframe,
            confidence=confidence,
            timestamp=time.time(),
        )
        with self._lock:
            self._outcomes[(profile_name, symbol)] = outcome

    def all_outcomes(self) -> List[SignalOutcome]:
        with self._lock:
            return list(self._outcomes.values())

    def by_profile(self) -> Dict[str, List[SignalOutcome]]:
        grouped: Dict[str, List[SignalOutcome]] = {}
        for outcome in self.all_outcomes():
            grouped.setdefault(outcome.display_name or outcome.profile_name, []).append(outcome)
        for outcomes in grouped.values():
            outcomes.sort(key=lambda o: o.symbol)
        return grouped

    def for_symbol(self, symbol: str) -> List[SignalOutcome]:
        symbol = symbol.upper()
        return sorted(
            (o for o in self.all_outcomes() if o.symbol.upper() == symbol),
            key=lambda o: o.display_name,
        )

    def last_update(self) -> Optional[float]:
        stamps = [o.timestamp for o in self.all_outcomes()]
        return max(stamps) if stamps else None

    def clear_profile(self, profile_name: str) -> None:
        """Drop a profile's records — e.g. when its config is edited."""
        with self._lock:
            for key in [k for k in self._outcomes if k[0] == profile_name]:
                del self._outcomes[key]


_diagnostics = SignalDiagnostics()


def get_signal_diagnostics() -> SignalDiagnostics:
    return _diagnostics
