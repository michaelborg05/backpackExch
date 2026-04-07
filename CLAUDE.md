# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Python-based automated trading bot for the Backpack Exchange. It manages multiple trading profiles simultaneously, each with independent indicator configurations, risk parameters, and signal logic. The system runs as a multi-threaded service with a FastAPI REST API and dashboard UI.

## Commands

All commands run from `exchange_client/`:

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application (monitoring + API server on port 8000)
python main.py

# Run just the API server
uvicorn services/api_server:app --host 0.0.0.0 --port 8000

# Database migrations
alembic upgrade head                    # Apply all pending migrations
alembic revision --autogenerate -m ""   # Generate new migration

# Backtesting
python backtesting/run_backtest.py
python backtesting/run_profile_variants_backtest.py

# Utility scripts
python Tools/backfill_adx.py           # Populate ATR/ADX historical data
python Tools/resolve_ai_outcomes.py    # Process AI trading outcome logs
python Tools/settings_manager.py       # Manage DB settings
```

There is no linting or automated test suite. Testing is done via backtesting scripts and the `/signals/scan/{profile_name}` API endpoint.

## Architecture

The app starts from `main.py` which initializes the following in parallel threads:

1. **MonitoringService** (`services/monitoring_service.py`) — Main trading loop. Every N seconds: fetches prices, evaluates signals per profile, checks open positions for TP/SL/trailing stop, executes reentry logic, updates caches.
2. **SignalGenerator** (`services/signal_generator.py`) — One instance per profile. Evaluates trend + entry filters across timeframes using a scoring system. Delegates indicator evaluation to `TrendCache`.
3. **HealthAlertingService** (`services/alerting.py`) — Independent health monitor. Runs separately from the trading loop to send Telegram alerts if the main loop fails.
4. **FastAPI Server** (`services/api_server.py`) — 50+ REST endpoints for profile/indicator CRUD, position management, signal testing, TradingView webhook ingestion, and the dashboard UI.
5. **AISignalHandler** (`services/ai_signal_handler.py`) — Optional shadow mode. Runs Claude API evaluation in parallel with rule-based signals for research/comparison; never executes live trades directly.

### Cache Layer

All hot data is held in in-memory singletons under `cache/`:
- `TrendCache` — indicator history and computed signals
- `PriceCache` — latest quotes
- `BalanceCache` — account balances
- `PortfolioCache` — open positions summary
- `ATRCache` — volatility metrics
- `RegimeFilter` — market regime classification (trending/ranging/volatile)
- `SettingsCache` — configurable DB settings (cooldown timers, check intervals)

On startup, `trend_cache_warmup.py` pre-populates caches from the `trend_analysis_log` table so the system can resume without waiting for fresh candles.

### Data Flow

```
TradingView Webhook → FastAPI → MonitoringService
                                      ↓
                              SignalGenerators (per profile)
                                      ↓
                              TrendCache (indicator eval)
                                      ↓
                              Backpack Exchange API
                                      ↓
                              PostgreSQL (Neon) — all state persisted
```

### Database

PostgreSQL via Neon (serverless). All state is persisted so restarts are stateless. Key tables:
- `trading_profiles` — profile configs (TP%, SL%, timeframes, filter toggles)
- `indicators` — per-profile indicators with JSON `params`
- `positions` / `trades` — execution history
- `circuit_breaker_config` / `circuit_breaker_events` — daily risk limits
- `trend_analysis_log` — full OHLCV history used for cache warmup and backtesting
- `ai_signal_log` — AI vs rules-based decision log with outcomes
- `settings` — global configurable settings
- `exchange_accounts` — API credentials per account

ORM is SQLAlchemy 2.0 with Alembic migrations (`alembic/versions/`).

## Key Design Patterns

**Config-driven trading logic**: All indicator parameters and profile settings live in the database (not hardcoded). `profile_manager.py` loads profiles from `trading_profiles` + `indicators` tables on startup and on-demand.

**API key authentication**: Three tiers — master (all access), readonly (queries only), trading (order execution only). Managed in `utils/security.py` and `services/dashboard_auth.py`.

**Circuit breaker**: Singleton (`services/circuit_breaker.py`) that blocks new trades when daily profit/loss limits are hit. Config stored in DB per profile.

**Multi-account support**: `exchange_accounts` table stores multiple Backpack API key pairs. Different timeframe profiles can use different API keys (env vars `BP_API_KEY_1H`, `BP_SECRET_1H`, etc.).

## Environment Variables

Loaded from `.env` (see `.env.example`). Key variables:
```
DATABASE_URL                     # Neon PostgreSQL connection string
BACKPACK_API_KEY, SECRET         # Primary exchange credentials
BP_API_KEY_1H, BP_SECRET_1H     # Per-timeframe API keys
TELEGRAM_BOT_TOKEN, CHAT_GROUP_ID, TELEGRAM_WEBHOOK_URL
API_MASTER_KEY, API_READONLY_KEY, API_TRADING_KEY
PORT                             # Default 8000
DEBUG_MODE, LOG_LEVEL, LOG_LOCATION
WEBHOOK_SECRET                   # TradingView webhook signing
JWT_SECRET                       # Dashboard auth
```

## Deployment

Deployed on Render (see `render.yaml`). The build command installs requirements; the start command runs uvicorn. Database is Neon PostgreSQL. Auto-deploys from GitHub main branch.
