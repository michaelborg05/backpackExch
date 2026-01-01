from pathlib import Path
from decimal import Decimal
import os
import sys
# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from db.session import engine,SessionLocal
from db.models import Base
from utils.logging import log_manager
import yaml
from db.crud import create_profile
from models.trading_profile import TradingProfile


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

if __name__ == "__main__":
    commands = {
        "create": create_tables,
        "drop": drop_tables,
        "reset": reset_tables,
        "migrate-profiles": migrate_yaml_profiles,
    }
    
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("Usage: python manage.py [create|drop|reset]")
        print("  create - Create database tables")
        print("  drop   - Drop all tables (destructive)")
        print("  reset  - Drop and recreate tables (destructive)")
        print("  migrate-profiles - Load profiles from YAML into database")
        sys.exit(1)
    
    command = sys.argv[1]
    commands[command]()