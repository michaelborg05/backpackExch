#!/usr/bin/env python3
# tools/settings_manager.py
"""
CLI tool for managing settings in the database.

Usage:
    python -m tools.settings_manager list [--profile PROFILE]
    python -m tools.settings_manager get SETTING_NAME [--profile PROFILE]
    python -m tools.settings_manager set SETTING_NAME VALUE [--profile PROFILE]
    python -m tools.settings_manager delete SETTING_NAME [--profile PROFILE]
    python -m tools.settings_manager init
    python -m tools.settings_manager refresh-cache
"""
import argparse
import sys
from typing import Optional
from db.utils import get_db_session
from db.crud_settings import (
    get_setting,
    get_all_settings,
    get_settings_for_profile,
    update_setting,
    delete_setting,
    initialize_default_settings
)
from cache.settings_cache import get_settings_cache


def list_settings(profile_name: Optional[str] = None):
    """List all settings or settings for a specific profile"""
    with get_db_session() as db:
        if profile_name:
            settings_dict = get_settings_for_profile(db, profile_name)
            print(f"\nSettings for profile '{profile_name}':")
            print("=" * 80)
            
            table_data = []
            for name, value in sorted(settings_dict.items()):
                table_data.append([name, value])
            
            print ("Setting Name, Value")
            for row in table_data:
                print(" | ".join(map(str, row)))
            print(f"\nTotal: {len(settings_dict)} settings")
        else:
            settings = get_all_settings(db)
            print(f"\nAll Settings:")
            print("=" * 80)
            
            table_data = []
            for s in settings:
                profile = "GLOBAL" if s.profile_name == '0' else s.profile_name
                table_data.append([
                    profile,
                    s.setting_name,
                    s.value,
                    s.updated_at.strftime('%Y-%m-%d %H:%M:%S') if s.updated_at else 'N/A'
                ])
            print ("Profile | Setting Name | Value | Updated At")
            for row in table_data:
                print(" | ".join(map(str, row)))

            print(f"\nTotal: {len(settings)} settings")


def get_setting_value(setting_name: str, profile_name: str = '0'):
    """Get a specific setting"""
    with get_db_session() as db:
        setting = get_setting(db, setting_name, profile_name)
        
        if setting:
            profile = "GLOBAL" if setting.profile_name == '0' else setting.profile_name
            print(f"\n✓ Setting found:")
            print(f"  Profile: {profile}")
            print(f"  Name: {setting.setting_name}")
            print(f"  Value: {setting.value}")
            print(f"  Updated: {setting.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
            return 0
        else:
            profile = "GLOBAL" if profile_name == '0' else profile_name
            print(f"\n✗ Setting '{setting_name}' not found for profile '{profile}'")
            return 1


def set_setting_value(setting_name: str, value: str, profile_name: str = '0'):
    """Set a setting value"""
    with get_db_session() as db:
        setting = update_setting(db, setting_name, value, profile_name)
        
        profile = "GLOBAL" if profile_name == '0' else profile_name
        print(f"\n✓ Setting updated:")
        print(f"  Profile: {profile}")
        print(f"  Name: {setting.setting_name}")
        print(f"  Value: {setting.value}")
        print(f"  Updated: {setting.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print("\nNote: Cache will refresh automatically within the configured interval.")
        print("      Or use 'refresh-cache' command for immediate update.")
        return 0


def delete_setting_value(setting_name: str, profile_name: str = '0'):
    """Delete a setting"""
    with get_db_session() as db:
        success = delete_setting(db, setting_name, profile_name)
        
        profile = "GLOBAL" if profile_name == '0' else profile_name
        if success:
            print(f"\n✓ Setting '{setting_name}' deleted for profile '{profile}'")
            return 0
        else:
            print(f"\n✗ Setting '{setting_name}' not found for profile '{profile}'")
            return 1


def initialize_settings():
    """Initialize default settings"""
    with get_db_session() as db:
        created = initialize_default_settings(db)
        
        if created:
            print(f"\n✓ Initialized {len(created)} default settings:")
            for setting in created:
                profile = "GLOBAL" if setting.profile_name == '0' else setting.profile_name
                print(f"  - [{profile}] {setting.setting_name} = {setting.value}")
            return 0
        else:
            print("\n✓ All default settings already exist")
            return 0


def refresh_cache():
    """Force refresh the settings cache"""
    cache = get_settings_cache()
    
    if cache is None:
        print("\n✗ Settings cache not initialized")
        print("   Make sure your application is running and cache is initialized")
        return 1
    
    print("\n⟳ Refreshing settings cache...")
    cache.refresh()
    
    info = cache.get_cache_info()
    print("\n✓ Cache refreshed successfully:")
    print(f"  Last refresh: {info['last_refresh']}")
    print(f"  Profiles cached: {info['profiles_cached']}")
    print(f"  Global settings: {info['global_settings_count']}")
    print(f"  Total settings: {info['total_settings']}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Manage application settings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all settings
  python -m tools.settings_manager list
  
  # List settings for specific profile
  python -m tools.settings_manager list --profile trader_1
  
  # Get a setting value
  python -m tools.settings_manager get circuit_breaker_interval

  # Set a global setting
  python -m tools.settings_manager set circuit_breaker_interval 2
  
  # Set a profile-specific setting
  python -m tools.settings_manager set signal_cooldown_seconds 180 --profile trader_1
  
  # Delete a setting
  python -m tools.settings_manager delete custom_setting --profile trader_1
  
  # Initialize default settings
  python -m tools.settings_manager init
  
  # Force cache refresh
  python -m tools.settings_manager refresh-cache
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List settings')
    list_parser.add_argument('--profile', help='Profile name (omit for all settings)')
    
    # Get command
    get_parser = subparsers.add_parser('get', help='Get a setting value')
    get_parser.add_argument('setting_name', help='Name of the setting')
    get_parser.add_argument('--profile', default='0', help='Profile name (default: 0 for global)')
    
    # Set command
    set_parser = subparsers.add_parser('set', help='Set a setting value')
    set_parser.add_argument('setting_name', help='Name of the setting')
    set_parser.add_argument('value', help='Value to set')
    set_parser.add_argument('--profile', default='0', help='Profile name (default: 0 for global)')
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a setting')
    delete_parser.add_argument('setting_name', help='Name of the setting')
    delete_parser.add_argument('--profile', default='0', help='Profile name (default: 0 for global)')
    
    # Init command
    init_parser = subparsers.add_parser('init', help='Initialize default settings')
    
    # Refresh cache command
    refresh_parser = subparsers.add_parser('refresh-cache', help='Force refresh settings cache')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        if args.command == 'list':
            return list_settings(args.profile)
        elif args.command == 'get':
            return get_setting_value(args.setting_name, args.profile)
        elif args.command == 'set':
            return set_setting_value(args.setting_name, args.value, args.profile)
        elif args.command == 'delete':
            return delete_setting_value(args.setting_name, args.profile)
        elif args.command == 'init':
            return initialize_settings()
        elif args.command == 'refresh-cache':
            return refresh_cache()
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())