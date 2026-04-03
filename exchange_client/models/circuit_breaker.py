"""
Cache models for the circuit breaker service.
These dataclasses hold in-memory state so the service avoids hitting the DB
on every check cycle. The DB is only used on startup (state recovery) and on
write operations (trigger, expire, reset, snapshot persist).
"""
from dataclasses import dataclass
from typing import Optional
from decimal import Decimal
from datetime import datetime


@dataclass
class CachedCircuitBreakerConfig:
    max_daily_profit_pct: Decimal
    max_daily_loss_pct: Decimal
    profit_lock_hours: int
    loss_lock_hours: int


@dataclass
class CachedCircuitBreakerEvent:
    id: int
    profile_name: str
    account_id: Optional[int]
    reason: str
    triggered_at: datetime
    reset_at: datetime
    balance_at_trigger: Optional[Decimal]
    trigger_value_pct: Optional[Decimal]


@dataclass
class CachedDailySnapshot:
    id: int
    snapshot_date: datetime
    starting_balance: Decimal
    highest_balance: Decimal
    circuit_breaker_baseline: Optional[Decimal]
