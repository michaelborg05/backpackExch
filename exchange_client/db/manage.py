from pathlib import Path
from decimal import Decimal
import os
import sys
# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from db.models import Trade, Position
from db.session import engine,SessionLocal
from db.models import Base,TradingProfileDB, IndicatorDB
from utils.logging import log_manager
import yaml
from db.crud import create_profile, create_daily_snapshot
from db.utils import get_db_session
from db.crud_settings import initialize_default_settings, bulk_upsert_settings
from utils.logging import log_manager



logger = log_manager.get_logger("DatabaseManager")

def create_tables():
    """Create all database tables"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Database tables created successfully")
        print("✓ Database tables created successfully")
    except Exception as e:
        logger.error(f"✗ Failed to create tables: {e}")
        print(f"✗ Failed to create tables: {e}")
        sys.exit(1)

def drop_tables():
    """Drop all database tables (DESTRUCTIVE!)"""
    confirm = input("Are you sure you want to drop all tables? (yes/no): ")
    if confirm.lower() == "yes":
        try:
            Base.metadata.drop_all(bind=engine)
            logger.info("✓ Database tables dropped")
            print("✓ Database tables dropped")
        except Exception as e:
            logger.error(f"✗ Failed to drop tables: {e}")
            print(f"✗ Failed to drop tables: {e}")
            sys.exit(1)
    else:
        print("Operation cancelled")

def reset_tables():
    """Drop and recreate all tables (DESTRUCTIVE!)"""
    confirm = input("Are you sure you want to reset all tables? All data will be lost! (yes/no): ")
    if confirm.lower() == "yes":
        drop_tables()
        create_tables()

def load_dummy_data():
    """Load dummy data into the database for testing"""
    db = SessionLocal()
    confirm = input("Are you sure you want to load dummy data? (yes/no): ")
    if confirm.lower() == "yes":
        try:
            # Add dummy data loading logic here

            trade = Trade(
                profile_name="1hr_MB",
                order_id=str(1234567),
                symbol="HYPE_USDC",
                side="BID",
                quantity=Decimal("1"),
                price=Decimal("24.52"),
                exchange="backpack"
            )
            db.add(trade)
            db.commit()
            db.refresh(trade)
            position = Position(
                    profile_name="1hr_MB", 
                    symbol="HYPE_USDC",
                    buy_trade_id=trade.id,  # Use database Trade ID
                    tp_price=26.02,
                    sl_price=23.02,
                    trailing_sl_price=23.60,
                    highest_price=24.52 or trade.price,  # Initialize with entry price
                    status="OPEN"
            )
            db.add(position)
            db.commit()
            db.refresh(position)

            logger.info("✓ Dummy data loaded successfully")
            print("✓ Dummy data loaded successfully")
        except Exception as e:
            logger.error(f"✗ Failed to load dummy data: {e}")
            print(f"✗ Failed to load dummy data: {e}")
        finally:
            db.close()

def setup_appusers():
    from db.session import SessionLocal
    from db.auth_crud import create_user, assign_profile
    db = SessionLocal()
    user = create_user(db, "michael", "password", role="admin")
    assign_profile(db, user.id, "default")
    assign_profile(db, user.id, "profile3")
    assign_profile(db, user.id, "15m_MB_ATR")
    assign_profile(db, user.id, "15m_no_trend")
    assign_profile(db, user.id, "15m_MB")



def update_keys():
    from db.session import SessionLocal
    from db.models import TradingProfileDB, IndicatorDB
    from utils.db_secrets import encrypt_secret, is_encrypted

    yaml_path = Path(__file__).parent.parent / "config/trading_profilesa.yaml"
    if not yaml_path.exists():
        print(f"✗ trading_profiles.yaml not found: {yaml_path}")
        return

    if not os.environ.get("DB_ENCRYPTION_KEY"):
        print(
            "ERROR: DB_ENCRYPTION_KEY is not set.\n"
            "Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    profiles_cfg: dict = data.get("profiles", {})

    db = SessionLocal()
    try:
        for name, cfg in profiles_cfg.items():

            # ── Resolve credentials ───────────────────────────────────────
            raw_key    = os.getenv(cfg.get("api_key_env", ""))
            raw_secret = os.getenv(cfg.get("secret_env", ""))

            if not raw_key or not raw_secret:
                print(f"  SKIP  {name!r} — missing env var "
                      f"({cfg.get('api_key_env')} / {cfg.get('secret_env')})")
                skipped += 1
                continue
            
            enc_key    = raw_key    if is_encrypted(raw_key)    else encrypt_secret(raw_key)
            enc_secret = raw_secret if is_encrypted(raw_secret) else encrypt_secret(raw_secret)

            print (f"raw: {raw_key} - encrypted: {enc_key}")

            # ── Check for existing profile (idempotency) ──────────────────
            existing: TradingProfileDB | None = (
                db.query(TradingProfileDB).filter_by(name=name).first()
            )

            if existing:
                print(f"    {name!r} — profile already exists in DB (id={existing.id}) - Updating")
                existing.api_key=enc_key
                existing.secret=enc_secret
                db.commit()
                db.refresh(existing)
            else:
                print(f"  Profile {name!r}  not found")

    except Exception as e:
        db.rollback()
        logger.error(f"✗ Migration failed, rolled back: {e}", exc_info=True)
        print(f"✗ Migration failed, rolled back: {e}")
    finally:
        db.close()


def migrate_yaml_profiles(dry_run: bool = False) -> None:
    """
    One-time migration: load profiles + indicators from YAML into the database.

    Safe to re-run — profiles and indicators that already exist are skipped,
    not duplicated.  Disabled profiles in YAML are skipped entirely.

    Args:
        dry_run: When True, prints what *would* happen without writing to DB.
                 Trigger with:  python manage.py migrate-profiles --dry-run
    """
    from db.session import SessionLocal
    from db.models import TradingProfileDB, IndicatorDB
    from utils.db_secrets import encrypt_secret, is_encrypted

    tag = "[DRY-RUN] " if dry_run else ""

    yaml_path = Path(__file__).parent.parent / "config/trading_profilesa.yaml"
    if not yaml_path.exists():
        print(f"✗ trading_profiles.yaml not found: {yaml_path}")
        return

    if not os.environ.get("DB_ENCRYPTION_KEY"):
        print(
            "ERROR: DB_ENCRYPTION_KEY is not set.\n"
            "Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    profiles_cfg: dict = data.get("profiles", {})

    migrated = skipped = failed = 0
    indicator_counts: dict[str, int] = {}  # profile_name → indicators inserted

    db = SessionLocal()
    try:
        for name, cfg in profiles_cfg.items():

            # ── Skip disabled profiles ────────────────────────────────────
            if not cfg.get("enabled", False):
                print(f"  SKIP  {name!r} — disabled in YAML")
                skipped += 1
                continue

            # ── Resolve credentials ───────────────────────────────────────
            raw_key    = os.getenv(cfg.get("api_key_env", ""))
            raw_secret = os.getenv(cfg.get("secret_env", ""))

            if not raw_key or not raw_secret:
                print(f"  SKIP  {name!r} — missing env var "
                      f"({cfg.get('api_key_env')} / {cfg.get('secret_env')})")
                skipped += 1
                continue

            enc_key    = raw_key    if is_encrypted(raw_key)    else encrypt_secret(raw_key)
            enc_secret = raw_secret if is_encrypted(raw_secret) else encrypt_secret(raw_secret)

            # ── Check for existing profile (idempotency) ──────────────────
            existing: TradingProfileDB | None = (
                db.query(TradingProfileDB).filter_by(name=name).first()
            )

            if existing:
                print(f"    {name!r} — profile already exists in DB (id={existing.id}) - Updating")
                skipped += 1
                # Still attempt to migrate indicators in case they're missing
                existing.strategy_type = str(cfg.get("strategy_type","trend_following"))
                existing.signal_timeframe = str(cfg.get("signal_timeframe",15))
                existing.signal_cooldown_seconds = int(cfg.get("signal_cooldown_seconds",900))
                existing.min_signal_confidence = Decimal(cfg.get("min_signal_confidence",70))
                existing.min_volume_ratio = Decimal(cfg.get("min_volume_ratio",1))
                existing.use_market_regime_filter = bool(cfg.get("use_market_regime_filter", False))
                existing.use_trend_filter = bool(cfg.get("use_trend_filter", False))
                existing.use_entry_filter = bool(cfg.get("use_entry_filter", False))
                existing.use_atr_filter = bool(cfg.get("use_atr_filter", False))
                existing.trend_timeframe = str(cfg.get("trend_timeframe","60"))
                existing.entry_timeframe = str(cfg.get("entry_timeframe","15"))
                existing.min_indicators_required = int(cfg.get("min_indicators_required",0))
                existing.min_entry_indicators_required = int(cfg.get("min_entry_indicators_required",0))
                
                profile_row = existing
                if not dry_run:
                    db.commit()
                    db.refresh(existing)
            else:
                # ── Build TradingProfileDB row ────────────────────────────
                profile_row = TradingProfileDB(
                    name=name,
                    display_name=str(cfg.get("display_name", name)),
                    api_key=enc_key,
                    secret=enc_secret,

                    # Position management
                    take_profit_pct=Decimal(str(cfg.get("take_profit_pct", 0))),
                    stop_loss_pct=Decimal(str(cfg.get("stop_loss_pct", 0))),
                    trailing_stop_pct=Decimal(str(cfg.get("trailing_stop_pct", 0))),
                    arm_trailing_stop_pct=Decimal(str(cfg.get("arm_trailing_stop_pct", 0))),
                    use_trailing_stop=bool(cfg.get("use_trailing_stop", False)),  # direct bool, not bool(str())

                    # Risk / sizing
                    max_risk_pct=Decimal(str(cfg.get("max_risk_pct", 0.25))),
                    default_order_size_usdc=Decimal(str(cfg.get("default_order_size_usdc", 100))),
                    max_position_size_pct=Decimal(str(cfg.get("max_position_size_pct", 40))),
                    max_open_positions=int(cfg.get("max_open_positions", 1)),
                    max_portfolio_exposure_pct=Decimal(str(cfg.get("max_portfolio_exposure_pct", 80))),

                    # Strategy
                    strategy_type=cfg.get("strategy_type", "trend_following"),

                    # Signal generation
                    signal_timeframe=str(cfg.get("signal_timeframe", "15")),
                    signal_cooldown_seconds=int(cfg.get("signal_cooldown_seconds", 900)),
                    min_signal_confidence=float(cfg.get("min_signal_confidence", 72.0)),
                    min_volume_ratio=float(cfg.get("min_volume_ratio", 1.0)),

                    # Filter toggles
                    use_market_regime_filter=bool(cfg.get("use_market_regime_filter", False)),
                    use_trend_filter=bool(cfg.get("use_trend_filter", False)),
                    use_entry_filter=bool(cfg.get("use_entry_filter", False)),
                    use_atr_filter=bool(cfg.get("use_atr_filter", False)),

                    # Timeframes & thresholds
                    trend_timeframe=str(cfg.get("trend_timeframe", "60")),
                    entry_timeframe=str(cfg.get("entry_timeframe", "15")),
                    min_indicators_required=int(cfg.get("min_indicators_required", 2)),
                    min_entry_indicators_required=int(cfg.get("min_entry_indicators_required", 2)),

                    is_active=bool(cfg.get("enabled", True)),
                )

                if not dry_run:
                    db.add(profile_row)
                    db.flush()  # gives us profile_row.id before commit

                migrated += 1
                hint = enc_key[-6:]
                print(f"  {tag}✓ Profile {name!r}  key=...{hint}")

            #── Migrate indicators ────────────────────────────────────────
            ind_count = _migrate_indicators(
                db=db,
                profile_row=profile_row,
                cfg=cfg,
                dry_run=dry_run,
                tag=tag,
            )
            indicator_counts[name] = ind_count

        # ── Commit everything in one transaction ──────────────────────────
        if not dry_run:
            db.commit()
            print(f"\n✓ Committed to database")
        else:
            print(f"\n[DRY-RUN] No changes written.")

        # ── Summary ───────────────────────────────────────────────────────
        total_indicators = sum(indicator_counts.values())
        print(f"\n{'='*55}")
        print(f"  Migration summary")
        print(f"{'='*55}")
        print(f"  Profiles migrated : {migrated}")
        print(f"  Profiles skipped  : {skipped}")
        print(f"  Profiles failed   : {failed}")
        print(f"  Indicators written: {total_indicators}")
        for pname, cnt in indicator_counts.items():
            if cnt:
                print(f"    └─ {pname}: {cnt} indicator(s)")
        print(f"{'='*55}")

    except Exception as e:
        db.rollback()
        logger.error(f"✗ Migration failed, rolled back: {e}", exc_info=True)
        print(f"✗ Migration failed, rolled back: {e}")
    finally:
        db.close()



def _migrate_indicators(
    db,
    profile_row: "TradingProfileDB",
    cfg: dict,
    dry_run: bool,
    tag: str,
) -> int:
    """
    Insert IndicatorDB rows for all trend + entry indicators in `cfg`.
    Skips any indicator whose (profile_id, category, indicator_type, params)
    combination already exists, so it's safe to re-run.

    Returns the number of new indicators inserted (or that would be inserted).
    """
    inserted = 0

    indicator_groups = [
        ("trend", cfg.get("trend_indicators") or []),
        ("entry", cfg.get("entry_indicators") or []),
    ]

    for category, indicators in indicator_groups:
        if not indicators:
            continue

        for ind_cfg in indicators:
            if not isinstance(ind_cfg, dict) or "type" not in ind_cfg:
                print(f"    WARNING: skipping malformed indicator in {profile_row.name!r}: {ind_cfg}")
                continue

            indicator_type = ind_cfg["type"]

            # Params = everything except 'type'; hard_stop lives as its own column
            params = {k: v for k, v in ind_cfg.get("params", {}).items()}

            # Some YAML configs put hard_stop at the top level of the indicator
            # dict rather than nested inside params — handle both shapes.
            is_hard_stop = bool(
                ind_cfg.get("hard_stop", params.pop("hard_stop", False))
            )

            # ── Idempotency check ─────────────────────────────────────────
            # Skip if this exact indicator already exists for this profile
            if profile_row.id is not None:
                already_exists = (
                    db.query(IndicatorDB)
                    .filter_by(
                        profile_id=profile_row.id,
                        category=category,
                        indicator_type=indicator_type,
                    )
                    .first()
                )
                if already_exists:
                    print(f"    SKIP  [{category}] {indicator_type!r} — already in DB")
                    continue

            print(f"    {tag}+ [{category}] {indicator_type!r}  hard_stop={is_hard_stop}  params={params}")

            if not dry_run:
                ind_row = IndicatorDB(
                    profile_id=profile_row.id,
                    category=category,
                    indicator_type=indicator_type,
                    params=params,
                    is_hard_stop=is_hard_stop,
                    enabled=True,
                )
                db.add(ind_row)

            inserted += 1

    return inserted

def _migrate_yaml_profiles_cli():
    """Wrapper that checks for --dry-run flag before calling the real function."""
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("*** DRY-RUN MODE — no changes will be written ***\n")
    migrate_yaml_profiles(dry_run=dry_run)


def migrate_circuit_breaker():
    """Initialize circuit breaker configs for existing profiles"""
    db = SessionLocal()
    
    try:
        from db.crud import get_all_profiles, create_circuit_breaker_config
        from cache.portfolio_cache import get_portfolio_cache
        from services.profile_manager import get_profile_manager, load_profiles,set_profile_manager

        profile_manager = load_profiles()
        set_profile_manager(profile_manager)          
        profiles = profile_manager._profiles.values()
        
        for profile in profiles:
            # Create default config
            try:
                create_circuit_breaker_config(
                    db,
                    profile_name=profile.name,
                    max_daily_profit_pct=Decimal("5.0"),
                    max_daily_loss_pct=Decimal("2.0"),
                    profit_lock_hours=6,
                    loss_lock_hours=12
                )
                print(f"✓ Created circuit breaker config for {profile.name}")
                
                # Create initial balance snapshot
                #current_value = portfolio.get_total_value(profile.name, "USDC")
                match profile.name:
                    case "default":
                        current_value = 420.16
                    case "15m_MB":
                        current_value = 424.31
                    case "1m_MB":
                        current_value = 145.55
                    case "1m_MB_ATR":
                        current_value = 143.14
                    
                create_daily_snapshot(db, profile.name, current_value)
                print(f"✓ Created initial snapshot for {profile.name}: ${current_value:.2f}")
                
            except Exception as e:
                print(f"✗ Failed to migrate {profile.name}: {e}")
        
        print("\n✓ Circuit breaker migration complete!")
        
    finally:
        db.close()

def setup_symbol_configs():
    """
    Initialize symbol_configs table and optionally create default configs
    Run this after creating tables to set up initial symbol configurations
    """
    db = SessionLocal()

    try:
        from db.crud import upsert_symbol_config
        from services.profile_manager import load_profiles, set_profile_manager

        # Load profiles
        profile_manager = load_profiles()
        set_profile_manager(profile_manager)

        print("\n🔧 Setting up symbol configurations...")
        print("=" * 60)

        # Example default configurations
        # Adjust these based on your needs
        default_configs = {
            "SOL_USDC": {
                "order_size_usdc": 150.0,
                "max_position_size_pct": 40.0  # 15% of portfolio
            },
            "ETH_USDC": {
                "order_size_usdc": 150.0,
                "max_position_size_pct": 40.0  # 20% of portfolio
            },
            "HYPE_USDC": {
                "order_size_usdc": 100.0,
                "max_position_size_pct": 25.0  # 10% of portfolio
            },
            "SUI_USDC": {
                "order_size_usdc": 100.0,
                "max_position_size_pct": 25.0  # 15% of portfolio
            }
        }

        # Ask if user wants to create default configs
        create_defaults = input("\nCreate default symbol configurations? (yes/no): ").lower() == "yes"

        if create_defaults:
            for profile in profile_manager._profiles.values():
                print(f"\n📋 Setting up configs for profile: {profile.name}")

                for symbol, config in default_configs.items():
                    try:
                        upsert_symbol_config(
                            db,
                            profile_name=profile.name,
                            symbol=symbol,
                            order_size_usdc=config["order_size_usdc"],
                            max_position_size_pct=config.get("max_position_size_pct")
                        )

                        print(f"  ✓ {symbol}: ${config['order_size_usdc']}, max {config.get('max_position_size_pct', 'N/A')}% of portfolio")

                    except Exception as e:
                        print(f"  ✗ Failed to create config for {symbol}: {e}")

        # Interactive config creation
        create_custom = input("\nCreate custom symbol configurations? (yes/no): ").lower() == "yes"

        if create_custom:
            while True:
                print("\n" + "=" * 60)
                profile_name = input("Profile name (or 'done' to finish): ").strip()

                if profile_name.lower() == 'done':
                    break

                if not profile_manager.has_profile(profile_name):
                    print(f"❌ Profile '{profile_name}' not found")
                    continue

                symbol = input("Symbol (e.g., SOL_USDC): ").strip().upper()

                order_size_usdc = float(input("Order size in USDC: "))
                max_position_pct = float(input("Max position size as % of portfolio (e.g., 15.0 for 15%): "))

                try:
                    upsert_symbol_config(
                        db,
                        profile_name=profile_name,
                        symbol=symbol,
                        order_size_usdc=order_size_usdc,
                        max_position_size_pct=max_position_pct
                    )

                    print(f"✅ Created config: {symbol} - ${order_size_usdc}, max {max_position_pct}% of portfolio")

                except Exception as e:
                    print(f"❌ Failed to create config: {e}")

        print("\n" + "=" * 60)
        print("✅ Symbol config setup complete!")

        # Show summary
        from db.crud import get_all_symbol_configs

        print("\n📊 Configuration Summary:")
        for profile in profile_manager._profiles.values():
            configs = get_all_symbol_configs(db, profile.name)
            if configs:
                print(f"\n{profile.name}:")
                for config in configs:
                    print(f"  • {config.symbol}: ${config.order_size_usdc}, max {config.max_position_size_pct if config.max_position_size_pct else 'N/A'}% of portfolio")

    except Exception as e:
        print(f"❌ Error setting up symbol configs: {e}")
        import traceback
        traceback.print_exc()

    finally:
        db.close()

def add_new_profile():
    # Function to add a new trading profile
    profile_name = input("\nEnter new profile name: ")
    print(f"Adding new profile: {profile_name}")
    confirm = input("\nConfirm? (yes/no): ").lower() == "yes"
    if confirm == False: 
        return
    
    from db.crud import create_circuit_breaker_config
    try:
        db = SessionLocal()
        create_circuit_breaker_config(
            db,
            profile_name=profile_name,
            max_daily_profit_pct=Decimal("5.0"),
            max_daily_loss_pct=Decimal("3.0"),
            profit_lock_hours=6,
            loss_lock_hours=12
        )
        default_configs = {
            "SOL_USDC": {
                "order_size_usdc": 150.0,
                "max_position_size_pct": 50.0  # 15% of portfolio
            },
            "ETH_USDC": {
                "order_size_usdc": 150.0,
                "max_position_size_pct": 50.0  # 20% of portfolio
            },
            "HYPE_USDC": {
                "order_size_usdc": 100.0,
                "max_position_size_pct": 40.0  # 10% of portfolio
            },
            "SUI_USDC": {
                "order_size_usdc": 100.0,
                "max_position_size_pct": 40.0  # 15% of portfolio
            }
        } 
        
        from db.crud import upsert_symbol_config
        for symbol, config in default_configs.items():
            try:
                upsert_symbol_config(
                    db,
                    profile_name=profile_name,
                    symbol=symbol,
                    order_size_usdc=config["order_size_usdc"],
                    max_position_size_pct=config.get("max_position_size_pct")
                )

                print(f"  ✓ {symbol}: ${config['order_size_usdc']}, max {config.get('max_position_size_pct', 'N/A')}% of portfolio")

            except Exception as e:
                print(f"  ✗ Failed to create config for {symbol}: {e}")
       
    except Exception as e:
        print(f"✗ Failed to migrate {profile_name}: {e}")
        
    finally:
        db.close()
    print("\n✓ Profile setup complete")

def populate_default_settings():
    """Populate the settings table with initial default values"""
    
    try:
        with get_db_session() as db:
            # Initialize default settings
            default_settings = {
                # Monitoring intervals (in cycles)
                'atr_update_interval': '5',  # Update ATR every 5 cycles
                'circuit_breaker_interval': '2',  # Check circuit breakers every 2 cycles
                'dust_conversion_interval': '2880',  # Convert dust every 2880 cycles (24h if cycle is 30s)
                'signal_check_interval': '10',  # Check signals every 10 cycles (5 min if cycle is 30s)
                'trend_invalidation_interval': '10',  # Update trend invalidation every 10 cycles
                'position_validation_interval': '10',  # Run position validation every 10 cycles
                'cooldown_take_profit_mins': '35',  # default cooldown after take profit
                'cooldown_stop_loss_mins': '35',    # default cooldown after stop loss
                'cooldown_default_mins': '15',      # default cooldown
                'mean_rever_rsi_inval_threshold': '36',  # default cooldown after take profit
                'mean_rever_rsi_lookback_candles': '35',    # default cooldown after stop loss
                'alert_trend_max_age': '1200',      # max age for trend cache before i raise an alert - in seconds
                'alert_price_max_age': '300',       #  max age for price cache before i raise an alert - in seconds
                'alert_re_alert_cooldown': '900',   # time between raising the same alert
                'alert_startup_grace_period': '120',# grace period before enabling the alerting logic
                'profile_refresh_interval': '30',      # how many cycles to refresh profile from db - 30 x 30 seconds = 10 mins
            }
            new_settings = {
                'profile_refresh_interval': '30',

            }
            created = initialize_default_settings(db, default_settings=new_settings)
            
            print(f"✅ Successfully initialized {len(created)} default settings")
            
            # Print created settings
            for setting in created:
                print(
                    f"  - {setting.profile_name}/{setting.setting_name} = {setting.value}"
                )
            
            # Example: Add profile-specific settings
            # Uncomment and modify as needed
            """
            profile_settings = {
                'signal_check_interval': '5',  # Override for specific profile
                'signal_cooldown_seconds': '180',  # 3 minutes for this profile
            }
            bulk_upsert_settings(db, profile_settings, profile_name='your_profile_name')
            logger.info("✅ Successfully added profile-specific settings")
            """
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Failed to populate settings: {e}", exc_info=True)
        return False


# Update the commands dict:
commands = {
    "create": create_tables,
    "drop": drop_tables,
    "reset": reset_tables,
    "migrate-profiles": _migrate_yaml_profiles_cli,
    "load-dummy": load_dummy_data,
    "migrate_circuit_breaker": migrate_circuit_breaker,
    "setup-symbols": setup_symbol_configs,
    "add-profile": add_new_profile,
    "populate-settings": populate_default_settings,
    "create-appuser" : setup_appusers,
    "update-keys": update_keys,
}

if __name__ == "__main__":
    #command = "migrate_circuit_breaker"
    #command= "setup_circuit"
    command = None
    if (len(sys.argv) < 2 or sys.argv[1] not in commands) and command is None:
         print("Usage: python manage.py [create|drop|reset]")
         print("  create - Create database tables")
         print("  drop   - Drop all tables (destructive)")
         print("  reset  - Drop and recreate tables (destructive)")
         print("  migrate-profiles - Load profiles from YAML into database")
         print("  migrate-profiles --dry-run  Preview migration without writing")
         print("  load-dummy - Load dummy data into database")
         print("  migrate-circuit-breaker - Migrate circuit breaker configurations")
         print("  setup-symbols - Set up symbol-specific configurations")
         print("  add-profile - Add a new trading profile")
         print("  populate-settings - Populate default settings in settings table")
         print("  create-appuser - Create new user for UI")
         print("  update-keys - Update API keys in db")
         
         sys.exit(1)
    
    command = sys.argv[1]
    commands[command]()