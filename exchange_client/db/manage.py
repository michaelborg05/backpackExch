from pathlib import Path
from decimal import Decimal
import os
import sys
# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from db.models import Trade, Position
from db.session import engine,SessionLocal
from db.models import Base
from utils.logging import log_manager
import yaml
from db.crud import create_profile, create_daily_snapshot
from models.trading_profile import TradingProfile
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

def migrate_yaml_profiles():
    """One-time migration: Load profiles from YAML into database"""
    yaml_path = Path(__file__).parent / "config/trading_profiles.yaml"
    
    if not yaml_path.exists():
        print("✗ trading_profiles.yaml not found")
        return
    
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    
    db = SessionLocal()
    try:
        for name, config in data.get("profiles", {}).items():
            # Get credentials from environment
            api_key = os.getenv(config["api_key_env"])
            secret = os.getenv(config["secret_env"])
            
            if not api_key or not secret:
                print(f"✗ Skipping {name}: missing environment variables")
                continue
            
            profile = TradingProfile(
                name=name,
                api_key=api_key,
                secret=secret,
                max_risk_pct=Decimal(str(config.get("max_risk_pct", 0.25))),
                default_order_size_pct=Decimal(str(config.get("default_order_size_pct", 5)))
            )
            
            try:
                create_profile(db, profile)
                print(f"✓ Migrated profile: {name}")
            except Exception as e:
                print(f"✗ Failed to migrate {name}: {e}")
        
    finally:
        db.close()

# Add to manage.py

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
            }
            new_settings = {
                'mean_rever_rsi_inval_threshold': '36',  # default cooldown after take profit
                'mean_rever_rsi_lookback_candles': '2',    # default cooldown after stop loss

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
    "migrate-profiles": migrate_yaml_profiles,
    "load-dummy": load_dummy_data,
    "migrate_circuit_breaker": migrate_circuit_breaker,
    "setup-symbols": setup_symbol_configs,
    "add-profile": add_new_profile,
    "populate-settings": populate_default_settings,
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
         print("  load-dummy - Load dummy data into database")
         print("  migrate-circuit-breaker - Migrate circuit breaker configurations")
         print("  setup-symbols - Set up symbol-specific configurations")
         print("  add-profile - Add a new trading profile")
         print("  populate-settings - Populate default settings in settings table")
         sys.exit(1)
    
    command = sys.argv[1]
    commands[command]()