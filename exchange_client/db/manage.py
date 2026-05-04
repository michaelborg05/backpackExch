from pathlib import Path
from decimal import Decimal
import os
import sys
# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from db.models import Trade, Position
from db.session import engine,SessionLocal
from db.models import (
    Base,
    TradingProfileDB, 
    IndicatorDB,
    ExchangeAccount,
    CircuitBreakerConfig,
    CircuitBreakerEvent,
    DailyBalanceSnapshot,
)
from utils.logging import log_manager
import yaml
from db.crud import create_profile, create_daily_snapshot
from db.utils import get_db_session
from db.crud_settings import initialize_default_settings, bulk_upsert_settings
from utils.logging import log_manager

import argparse
from collections import defaultdict
from utils.db_secrets import resolve_secret, encrypt_secret


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
                    entry_trade_id=trade.id,  # Use database Trade ID
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

    if not os.environ.get("DB_ENCRYPTION_KEY"):
        print(
            "ERROR: DB_ENCRYPTION_KEY is not set.\n"
            "Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"",
            file=sys.stderr,
        )
        sys.exit(1)

    db = SessionLocal()
    try:
            # ── Resolve credentials ───────────────────────────────────────
        raw_key    = os.getenv("BULLET_DELEGATE_KEY")
        raw_secret = os.getenv("BULLET_PRIVATE_KEY")

        profile = input("Enter Profile name: ")

        enc_key    = raw_key    if is_encrypted(raw_key)    else encrypt_secret(raw_key)
        enc_secret = raw_secret if is_encrypted(raw_secret) else encrypt_secret(raw_secret)

        print (f"raw: {raw_key} - encrypted: {enc_key}")

        # ── Check for existing profile (idempotency) ──────────────────
        existing: ExchangeAccount | None = (
            db.query(ExchangeAccount).filter_by(name=profile).first()
        )
        existing.api_key = enc_key
        existing.secret = enc_secret
        db.commit()
        db.refresh(existing)

    except Exception as e:
        db.rollback()
        logger.error(f"✗ Migration failed, rolled back: {e}", exc_info=True)
        print(f"✗ Migration failed, rolled back: {e}")
    finally:
        db.close()

def add_new_exchacct():
    db = SessionLocal()
    try:
        # Create a new ExchangeAccount
        from utils.db_secrets import encrypt_secret, is_encrypted

        name = input("\nEnter account name: ")
        print("choose exchange:\n"
              "1. backpack\n"
              "2. bullet")
        exchange = "backpack" if input("\nEnter exchange (1 or 2): ") == "1" else "bullet"
        raw_key = input("\nEnter api key: ")
        raw_secret = input("\nEnter secret: ")
        raw_wallet = input("\nEnter wallet address: ")

        if not os.environ.get("DB_ENCRYPTION_KEY"):
            print(
                "ERROR: DB_ENCRYPTION_KEY is not set.\n"
                "Generate one with:\n"
                "  python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"",
                file=sys.stderr,
            )
            sys.exit(1)


        if not raw_key or not raw_secret:
            print(f"  ERROR - Must include apikey and secret")
            exit(1)

        enc_key = raw_key if is_encrypted(raw_key) else encrypt_secret(raw_key)
        enc_secret = raw_secret if is_encrypted(raw_secret) else encrypt_secret(raw_secret)
        enc_wallet = raw_wallet if is_encrypted(raw_wallet) else encrypt_secret(raw_wallet) 

        new_account = ExchangeAccount(
            name=name,
            api_key=enc_key,
            secret=enc_secret,
            exchange_type=exchange,
            wallet_address=enc_wallet,
            is_active=True,
        )

        db.add(new_account)
        db.commit()
        db.refresh(new_account)
        print(f"✓ Added new exchange account: {new_account.name} (id={new_account.id})")
    except Exception as e:
        db.rollback()
        logger.error(f"✗ Failed to add new exchange account: {e}", exc_info=True)
        print(f"✗ Failed to add new exchange account: {e}")
    finally:
        db.close()

def migrate_to_accounts(dry_run: bool = False):
    tag = "[DRY-RUN] " if dry_run else ""
    db = SessionLocal()

    try:
        profiles = (
            db.query(TradingProfileDB)
            .filter(TradingProfileDB.is_active == True)
            .all()
        )

        if not profiles:
            print("No active profiles found — nothing to migrate.")
            return

        # ── Step 1: Group profiles by decrypted api_key ───────────────────────
        # Profiles sharing the same api_key belong to the same exchange account.
        # We decrypt here only to group — the account row stores the encrypted value.
        print("\nGrouping profiles by API key...")
        key_to_profiles = defaultdict(list)

        for p in profiles:
            try:
                raw_key = resolve_secret(p.api_key)
            except Exception as e:
                print(f"  WARNING: Could not decrypt api_key for '{p.name}': {e}")
                raw_key = p.api_key  # fall back to stored value for grouping

            key_to_profiles[raw_key].append(p)

        print(f"Found {len(key_to_profiles)} unique exchange account(s) "
              f"across {len(profiles)} profile(s).\n")

        # ── Step 2: Create ExchangeAccount rows ───────────────────────────────
        key_to_account_id = {}  # raw_key → account.id

        for raw_key, grouped_profiles in key_to_profiles.items():
            # Build a sensible account name from the profile names
            if len(grouped_profiles) == 1:
                account_name = grouped_profiles[0].name
                if grouped_profiles[0].name == "default":
                    account_name = "ai_trading_acct"
                elif grouped_profiles[0].name == "15m_MB_ATR":
                    account_name = "mean_reversion"
                elif grouped_profiles[0].name == "profile3":
                    account_name = "4hr_trend_trading"
                elif grouped_profiles[0].name == "15m_no_trend":
                    account_name = "15m_entry_trading"
                elif grouped_profiles[0].name == "15m_MB":
                    account_name = "range_trading"
            else:
                account_name = "_".join(p.name for p in grouped_profiles[:3])
                display_name = " / ".join(
                    p.display_name for p in grouped_profiles[:3]
                )
                if len(grouped_profiles) > 3:
                    display_name += f" (+{len(grouped_profiles) - 3} more)"

            # Check if account already exists (idempotency)
            existing = (
                db.query(ExchangeAccount)
                .filter(ExchangeAccount.name == account_name)
                .first()
            )

            if existing:
                print(f"  SKIP  Account '{account_name}' already exists "
                      f"(id={existing.id})")
                key_to_account_id[raw_key] = existing.id
                continue

            # Resolve encrypted credentials from first profile
            canonical = grouped_profiles[0]
            try:
                enc_key    = canonical.api_key    # already encrypted
                enc_secret = canonical.secret     # already encrypted
            except Exception as e:
                print(f"  ERROR: Could not get credentials for '{account_name}': {e}")
                continue

            account = ExchangeAccount(
                name=account_name,
                api_key=enc_key,
                secret=enc_secret,
                is_active=True,
            )

            profile_names = [p.name for p in grouped_profiles]
            print(f"  {tag}✓ Creating account '{account_name}' "
                  f"for profile(s): {profile_names}")

            if not dry_run:
                db.add(account)
                db.flush()  # get account.id before commit
                key_to_account_id[raw_key] = account.id

        if not dry_run:
            db.commit()

        # ── Step 3: Back-fill account_id on trading_profiles ─────────────────
        print("\nBack-filling trading_profiles.account_id...")

        for raw_key, grouped_profiles in key_to_profiles.items():
            account_id = key_to_account_id.get(raw_key)
            if account_id is None:
                print(f"  WARNING: No account_id resolved for key group "
                      f"({[p.name for p in grouped_profiles]}) — skipping")
                continue

            for p in grouped_profiles:
                if p.account_id == account_id:
                    print(f"  SKIP  {p.name} already has account_id={account_id}")
                    continue
                print(f"  {tag}✓ {p.name} → account_id={account_id}")
                if not dry_run:
                    p.account_id = account_id

        if not dry_run:
            db.commit()

        # ── Step 4: Back-fill circuit_breaker_config ──────────────────────────
        print("\nBack-filling circuit_breaker_config.account_id...")

        configs = db.query(CircuitBreakerConfig).all()
        for config in configs:
            profile = (
                db.query(TradingProfileDB)
                .filter(TradingProfileDB.name == config.profile_name)
                .first()
            )
            if not profile or not profile.account_id:
                print(f"  SKIP  config for '{config.profile_name}' "
                      f"(no matching profile or account_id)")
                continue
            if config.account_id == profile.account_id:
                print(f"  SKIP  config for '{config.profile_name}' "
                      f"already has account_id={config.account_id}")
                continue
            print(f"  {tag}✓ CB config '{config.profile_name}' "
                  f"→ account_id={profile.account_id}")
            if not dry_run:
                config.account_id = profile.account_id

        if not dry_run:
            db.commit()

        # ── Step 5: Back-fill circuit_breaker_events ──────────────────────────
        print("\nBack-filling circuit_breaker_events.account_id...")

        events = db.query(CircuitBreakerEvent).all()
        updated_events = 0
        skipped_events = 0

        for event in events:
            profile = (
                db.query(TradingProfileDB)
                .filter(TradingProfileDB.name == event.profile_name)
                .first()
            )
            if not profile or not profile.account_id:
                skipped_events += 1
                continue
            if event.account_id == profile.account_id:
                skipped_events += 1
                continue
            if not dry_run:
                event.account_id = profile.account_id
            updated_events += 1

        print(f"  {tag}✓ Updated {updated_events} events, "
              f"skipped {skipped_events}")

        if not dry_run:
            db.commit()

        # ── Step 6: Back-fill daily_balance_snapshots ─────────────────────────
        print("\nBack-filling daily_balance_snapshots.account_id...")

        snapshots = db.query(DailyBalanceSnapshot).all()
        updated_snaps = 0
        skipped_snaps = 0

        for snap in snapshots:
            profile = (
                db.query(TradingProfileDB)
                .filter(TradingProfileDB.name == snap.profile_name)
                .first()
            )
            if not profile or not profile.account_id:
                skipped_snaps += 1
                continue
            if snap.account_id == profile.account_id:
                skipped_snaps += 1
                continue
            if not dry_run:
                snap.account_id = profile.account_id
            updated_snaps += 1

        print(f"  {tag}✓ Updated {updated_snaps} snapshots, "
              f"skipped {skipped_snaps}")

        if not dry_run:
            db.commit()

        # ── Summary ───────────────────────────────────────────────────────────
        print(f"\n{'=' * 55}")
        print(f"  Migration {'preview' if dry_run else 'complete'}")
        print(f"{'=' * 55}")
        print(f"  Accounts created : {len(key_to_account_id)}")
        print(f"  Profiles updated : {len(profiles)}")
        print(f"  CB configs updated: {len(configs)}")
        print(f"  CB events updated : {updated_events}")
        print(f"  Snapshots updated : {updated_snaps}")
        if dry_run:
            print("\n  *** DRY RUN — no changes written ***")
        print(f"{'=' * 55}\n")

    except Exception as e:
        db.rollback()
        logger.error(f"Migration failed, rolled back: {e}", exc_info=True)
        print(f"\n✗ Migration failed: {e}")
        sys.exit(1)
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

                    # Position management
                    take_profit_pct=Decimal(str(cfg.get("take_profit_pct", 0))),
                    stop_loss_pct=Decimal(str(cfg.get("stop_loss_pct", 0))),
                    trailing_stop_pct=Decimal(str(cfg.get("trailing_stop_pct", 0))),
                    arm_trailing_stop_pct=Decimal(str(cfg.get("arm_trailing_stop_pct", 0))),
                    use_trailing_stop=bool(cfg.get("use_trailing_stop", False)),  # direct bool, not bool(str())

                    # Risk / sizing
                    default_order_size_usdc=Decimal(str(cfg.get("default_order_size_usdc", 100))),
                    max_position_size_pct=Decimal(str(cfg.get("max_position_size_pct", 40))),
                    max_open_positions=int(cfg.get("max_open_positions", 1)),
                    max_portfolio_exposure_pct=Decimal(str(cfg.get("max_portfolio_exposure_pct", 80))),

                    # Strategy
                    strategy_type=cfg.get("strategy_type", "trend_following"),

                    # Signal generation
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
                    
                account_id = getattr(profile, 'account_id', None)
                create_daily_snapshot(
                    db,
                    account_id=account_id,
                    starting_balance=current_value,
                    profile_name=profile.name,
                )
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
    with SessionLocal() as db:
        accts = (
            db.query(ExchangeAccount)
            .filter(ExchangeAccount.is_active == True)
            .all()
        )
    for acct in accts:
        print(f"Acct {acct.id} {acct.name}")

    acct_id = input("\nEnter acct_id to link to: ")
    profile_name = input("\nEnter new profile name: ")
    acct_details = None
    for acct in accts:
        if acct.id == int(acct_id):
            acct_details = acct

    if acct_details is None: 
        print (f"couldnt find acct_id {acct_id}. Exiting")        
        return
    
    print(f"Adding new profile: {profile_name} to account {acct_id}")
    confirm = input("\nConfirm? (yes/no): ").lower() == "yes"
    if confirm == False: 
        return
    
    with SessionLocal() as db:
        profile_row = TradingProfileDB(
            name=profile_name,
            display_name=profile_name,
            account_id=acct_details.id,
            # Position management
            take_profit_pct=2,
            stop_loss_pct=2,
            trailing_stop_pct=1.5,
            arm_trailing_stop_pct=1,
            use_trailing_stop=True,

            # Risk / sizing
            default_order_size_usdc=100,
            max_position_size_pct=40,
            max_open_positions=1,
            max_portfolio_exposure_pct=100,

            # Strategy
            strategy_type= "trend_following",

            # Signal generation
            signal_cooldown_seconds=900,
            min_signal_confidence=72,
            min_volume_ratio=1.0,

            # Filter toggles
            use_market_regime_filter=True,
            use_trend_filter=True,
            use_entry_filter=True,
            use_atr_filter=False,

            # Timeframes & thresholds
            trend_timeframe=60,
            entry_timeframe=15,
            min_indicators_required=3,
            min_entry_indicators_required=3,

            is_active=True,
        )

        db.add(profile_row)
        db.flush()  # gives us profile_row.id before commit
        db.commit()

    from db.crud import create_circuit_breaker_config
    try:
        db = SessionLocal()
        create_circuit_breaker_config(
            db,
            account_id=acct_id,
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
                # Data retention (days)
                'retention_trans_history_days': '90',   # orders, positions, trades, ai_signal_log
                'retention_trenddata_history_days': '90', # trend_analysis_log
                'retention_audit_history_days': '28',          # circuit_breaker_events, config_audit_log, daily_balance_snapshots
            }
            new_settings = {
                'retention_trans_history_days': '90',
                'retention_trenddata_history_days': '90',
                'retention_audit_history_days': '28',
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
    "add-exchangeacct": add_new_exchacct,
    "add-profile": add_new_profile,
    "populate-settings": populate_default_settings,
    "create-appuser" : setup_appusers,
    "update-keys": update_keys,
    "migrate-exchaccts": migrate_to_accounts,
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
         print("  migrate-exchaccts - Migrate profiles to accts table")
         print("  add-exchangeacct - Add a new exchange account")
         sys.exit(1)
    
    command = sys.argv[1]
    commands[command]()