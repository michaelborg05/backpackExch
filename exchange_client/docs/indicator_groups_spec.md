# Indicator Groups — Design Spec & Implementation Plan

## Context

BorgBot is a Python algorithmic trading bot with a FastAPI backend, PostgreSQL (neon.tech), SQLAlchemy/Alembic, deployed on Render via GitHub.

### Relevant files
- `trend_cache.py` — primary signal/trend evaluation logic; where indicator evaluation happens
- `models.py` — SQLAlchemy ORM models
- `db/crud.py` — DB access layer
- `signal_generator.py` — calls trend_cache, drives entry decisions
- `profiles.html` — web UI for managing profiles and indicators
- `db/utils.py` — session management (`get_db_session`)

### Conventions
- Always use `from db.utils import get_db_session` with `with get_db_session() as db:` pattern
- SQLAlchemy ORM, not raw SQL
- All schema changes via Alembic (two-phase: add columns first, drop old after production validation)
- Indicator params are always nested under a `"params"` key in JSON — never spread flat
- Use `--dry-run` on any data migration scripts before committing

---

## Current Indicator System

Each trading profile has two indicator lists: `trend_indicators` (evaluated against 240m candles) and `entry_indicators` (evaluated against 60m candles).

Each indicator has:
- `indicator_type` — string identifying the evaluator (e.g. `rsi_range`, `price_vs_ema`, `adx_regime`)
- `is_hard_stop` — bool. If True and indicator fails, the entire evaluation fails immediately regardless of other indicators
- `params` — JSON object (always nested under `"params"` key in DB)
- Soft indicators (not hard stop) contribute +1 to a pass counter if they pass

Profile-level fields:
- `min_indicators_required` — minimum number of soft indicator passes needed (hard stops must all pass separately)
- `min_entry_indicators_required` — same concept for entry indicators

**Current evaluation pseudocode (trend_cache.py):**
```python
for indicator in indicators:
    result = evaluate_single(indicator, candle_data)
    if indicator.is_hard_stop and not result.passed:
        return FAIL  # immediate exit
    if result.passed:
        pass_count += 1

if pass_count >= min_indicators_required:
    return PASS
```

---

## Problem Being Solved

The current model cannot express conditional logic **between** indicators. Specifically:

**Real case:** In the `p3_v20_tight_pullback` profile, we want to block entries only when **both** of these are true simultaneously:
- 4h RSI > 55 (market extended/overbought)
- 4h EMA50 gap > 1.5% (price too far above EMA50)

Either condition alone is not reliable enough to hard-block — there are valid entries where RSI is 56 but EMA50 gap is fine, and vice versa. Blocking on either individually causes too many false negatives on good trading days.

With the current flat hard-stop model, you can only express "block if RSI > 55" OR "block if gap > 1.5%" — not "block only if both are elevated together."

---

## Solution: Indicator Groups

Add an optional `group` field to indicators. Indicators sharing a group ID are evaluated together as a unit. The group itself produces a single pass/fail result, which is then treated like a single indicator in the outer evaluation (contributing to pass count, or acting as a hard stop at group level).

### Group config fields

```python
{
    "group_id": "extension_check",   # matches indicator's group field
    "require_all": False,            # False = OR logic (any pass = group pass)
                                     # True  = AND logic (all must pass)
    "hard_stop": True,               # if True, group failure = immediate overall fail
    "min_required": 1                # alternative to require_all for fractional logic
                                     # (optional — use require_all for simple cases)
}
```

`require_all: False` (OR) — group passes if **any** indicator in the group passes.
This means the group **blocks** only when **all** indicators fail — i.e., "block if A AND B both fail."

`require_all: True` (AND) — group passes only if **all** indicators in the group pass.
This means the group **blocks** if **any** indicator fails — i.e., "block if A OR B fails."

### Solving the tight_pullback case

```python
"trend_indicators": [
    # Grouped: block ONLY if BOTH rsi and ema50 gap are elevated
    {
        "type": "rsi_range",
        "group": "extension_check",
        "params": {"min_value": 47, "max_value": 55, "invert": True}
    },
    {
        "type": "price_vs_ema",
        "group": "extension_check",
        "params": {"ema": 50, "min_gap_pct": -2.5, "max_gap_pct": 1.5}
    },
    # Ungrouped: standalone hard stop (existing behaviour)
    {"type": "adx_regime", "hard_stop": True, "params": {"min_adx": 10, "max_adx": 27}},
],
"indicator_groups": {
    "extension_check": {"require_all": False, "hard_stop": True}
    # require_all=False means: group passes if EITHER rsi OR ema50_gap passes
    # hard_stop=True means: if NEITHER passes (both elevated), fail immediately
}
```

### Other use cases this enables

**OR logic (any of these signals is enough):**
```python
# Entry: accept volume spike OR bb lower band — don't require both
{"type": "volume_spike",   "group": "entry_signal", ...},
{"type": "bollinger_bands","group": "entry_signal", ...},
"indicator_groups": {"entry_signal": {"require_all": False, "hard_stop": False}}
```

**AND logic (all of these must be true):**
```python
# Trend: require BOTH ema alignment AND rsi momentum to confirm trend
{"type": "price_vs_ema",          "group": "trend_confirm", ...},
{"type": "rsi_reversal_momentum", "group": "trend_confirm", ...},
"indicator_groups": {"trend_confirm": {"require_all": True, "hard_stop": True}}
```

---

## Data Model Changes

### `trading_indicators` table — add `indicator_group` column

```sql
ALTER TABLE trading_indicators ADD COLUMN indicator_group VARCHAR(64) NULL;
```

Nullable. NULL = ungrouped, existing behaviour applies.

### `trading_profile_db` table — add `indicator_groups` column

```sql
ALTER TABLE trading_profile_db ADD COLUMN indicator_groups JSONB NULL;
```

Stores group config keyed by group ID:
```json
{
  "extension_check": {"require_all": false, "hard_stop": true},
  "trend_confirm":   {"require_all": true,  "hard_stop": true}
}
```

NULL = no groups configured, existing behaviour applies fully.

### SQLAlchemy model changes (`models.py`)

```python
class TradingIndicatorDB(Base):
    # ... existing fields ...
    indicator_group = Column(String(64), nullable=True)

class TradingProfileDB(Base):
    # ... existing fields ...
    indicator_groups = Column(JSONB, nullable=True)
```

---

## Evaluator Changes (`trend_cache.py`)

Replace the flat evaluation loop with a group-aware version. **Ungrouped indicators must follow existing logic exactly — no behaviour change.**

```python
def evaluate_indicators(indicators, groups_config, min_required):
    """
    groups_config: dict of {group_id: {"require_all": bool, "hard_stop": bool}}
                   Pass {} or None if no groups configured.
    """
    groups_config = groups_config or {}
    
    grouped = {}    # group_id -> list of (indicator, result)
    ungrouped = []  # (indicator, result) pairs — existing logic path

    # Step 1: evaluate all indicators individually
    for ind in indicators:
        result = evaluate_single_indicator(ind, candle_data)
        if ind.indicator_group:
            grouped.setdefault(ind.indicator_group, []).append((ind, result))
        else:
            ungrouped.append((ind, result))

    # Step 2: existing hard stop check for ungrouped indicators
    for ind, result in ungrouped:
        if ind.is_hard_stop and not result.passed:
            return EvaluationResult(passed=False, reason=f"Hard stop failed: {ind.indicator_type}")

    # Step 3: evaluate each group
    group_passes = []
    for group_id, members in grouped.items():
        cfg = groups_config.get(group_id, {"require_all": False, "hard_stop": False})
        
        if cfg.get("require_all", False):
            group_passed = all(r.passed for _, r in members)  # AND logic
        else:
            group_passed = any(r.passed for _, r in members)  # OR logic (default)

        if cfg.get("hard_stop", False) and not group_passed:
            return EvaluationResult(passed=False, reason=f"Group hard stop failed: {group_id}")
        
        group_passes.append(group_passed)

    # Step 4: count passes (ungrouped soft + group results)
    soft_pass_count = sum(1 for ind, r in ungrouped if r.passed)
    group_pass_count = sum(1 for p in group_passes if p)
    total_passes = soft_pass_count + group_pass_count

    return EvaluationResult(passed=total_passes >= min_required)
```

**Important:** The backtester must use the same evaluator function — not a separate copy. If `trend_cache.py` exports `evaluate_indicators`, import it in the backtester directly so results stay consistent.

---

## Alembic Migration Plan

Two-phase migration (standard project convention):

**Phase 1 — add columns (deploy first):**
```python
def upgrade():
    op.add_column('trading_indicators', 
        sa.Column('indicator_group', sa.String(64), nullable=True))
    op.add_column('trading_profile_db',
        sa.Column('indicator_groups', postgresql.JSONB, nullable=True))

def downgrade():
    op.drop_column('trading_indicators', 'indicator_group')
    op.drop_column('trading_profile_db', 'indicator_groups')
```

Phase 2 (if any old columns need dropping) — only after production validation.

---

## API / CRUD Changes

### Profile endpoints
- `GET /profiles/{id}` — include `indicator_groups` in response
- `PUT /profiles/{id}` — accept and persist `indicator_groups`
- `POST /profiles` — accept `indicator_groups` on creation

### Indicator endpoints
- `PUT /indicators/{id}` — accept and persist `indicator_group`
- `POST /indicators` — accept `indicator_group` on creation

### `config_audit_log`
Existing audit logging should capture `indicator_group` changes automatically if the before/after JSON snapshot includes all indicator fields. Verify `indicator_group` is included in the snapshot.

---

## UI Changes (`profiles.html`)

### Simple / Advanced toggle
- Default: **Simple mode** — no group UI visible. Existing behaviour, existing layout.
- **Advanced mode**: unlocks group assignment per indicator and a group config panel.

The toggle state is UI-only (not persisted). Groups are stored in DB regardless of which mode created them — advanced mode just surfaces them visually.

### Advanced mode: indicator row additions
Each indicator row gets a "Group" text input (or dropdown of existing groups) — nullable. Leaving it blank = ungrouped.

### Advanced mode: group config panel
Below the indicator list, a "Groups" section appears showing one config row per unique group ID found in the indicator list:

| Group ID | Logic | Hard Stop |
|---|---|---|
| extension_check | OR (any pass) ▾ | ✓ |
| trend_confirm   | AND (all pass) ▾ | ✓ |

Group rows are auto-created when a group ID is first typed into an indicator row, and auto-removed when no indicators reference that group ID.

### Saving
On save, `indicator_groups` config is assembled from the group panel and sent alongside indicators in the existing profile update payload.

---

## Implementation Order

Work through these steps sequentially. Validate each before moving to the next.

**Step 1 — Alembic migration**
Generate and run Phase 1 migration adding `indicator_group` (String) to `trading_indicators` and `indicator_groups` (JSONB) to `trading_profile_db`. Verify columns exist in neon.tech before proceeding.

**Step 2 — Model + CRUD**
Add fields to `TradingIndicatorDB` and `TradingProfileDB` in `models.py`. Update relevant CRUD functions in `db/crud.py` to read/write both new fields. Update Pydantic schemas if used.

**Step 3 — Evaluator**
Refactor indicator evaluation in `trend_cache.py` into the group-aware `evaluate_indicators` function above. Ungrouped indicators must behave identically to current logic. Add unit tests covering: ungrouped-only (existing behaviour), OR group, AND group, group hard stop, mixed grouped + ungrouped.

**Step 4 — Backtester**
Update backtester to import and use the same `evaluate_indicators` function from `trend_cache.py`. Remove any duplicate evaluation logic.

**Step 5 — API endpoints**
Update profile create/update endpoints to accept and persist `indicator_groups`. Update indicator create/update endpoints to accept and persist `indicator_group`. Ensure `config_audit_log` captures changes.

**Step 6 — UI**
Add Simple/Advanced toggle to `profiles.html`. In advanced mode, add group field to indicator rows and group config panel below indicator list. Wire save to include `indicator_groups` in profile update payload.

---

## First Config to Implement (tight_pullback fix)

Once Step 3 is complete, update `p3_v20_tight_pullback` (or a new `p3_v21`) with:

```python
"trend_indicators": [
    {
        "type": "rsi_range",
        "group": "extension_check",
        "params": {"min_value": 47, "max_value": 55, "invert": True, "hard_stop": False}
    },
    {
        "type": "price_vs_ema",
        "group": "extension_check", 
        "params": {"ema": 50, "min_gap_pct": -2.5, "max_gap_pct": 1.5}
    },
    {
        "type": "adx_regime",
        "hard_stop": True,
        "params": {"min_adx": 10, "max_adx": 27}
    },
    # ... other existing trend indicators
],
"indicator_groups": {
    "extension_check": {
        "require_all": False,  # OR: group passes if EITHER rsi OR ema50_gap is not elevated
        "hard_stop": True      # group failure (both elevated) = immediate block
    }
}
```

Backtest this config against the 28-day window and compare to v19 baseline before deploying live.
