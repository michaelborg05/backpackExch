from pathlib import Path
import os
import yaml
from typing import Dict, List, Optional
from models.trading_profile import TradingProfile


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = BASE_DIR / "config" / "trading_profiles.yaml"

class ProfileManager:
    def __init__(self, profiles: Dict[str, TradingProfile]):
        self._profiles = profiles

    def get(self, name: str) -> TradingProfile:
        if name not in self._profiles:
            raise ValueError(f"Unknown trading profile: {name}")
        return self._profiles[name]

    def get_all_profiles(self) -> List[TradingProfile]:
        """Get all enabled profiles (only enabled profiles are loaded from YAML)"""
        return list(self._profiles.values())
    
    def get_profile(self, name: str) -> Optional[TradingProfile]:
        """Get a specific profile by name (returns None if not found)"""
        return self._profiles.get(name)
    
    def has_profile(self, name: str) -> bool:
        """Check if a profile exists"""
        return name in self._profiles
    
    def get_profile_names(self) -> List[str]:
        """Get list of all profile names"""
        return list(self._profiles.keys())
    
    def get_profiles_dict(self) -> Dict[str, TradingProfile]:
        """Get the profiles dictionary"""
        return self._profiles.copy()    

def load_profiles(path: Path | None = None) -> ProfileManager:
    path = path or DEFAULT_PROFILE_PATH
    if not path.exists():
        raise FileNotFoundError(f"Profile config not found: {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    profiles = {}
    skipped_profiles = []

    for name, cfg in raw.get("profiles", {}).items():
        # Skip disabled profiles
        if not cfg.get("enabled", False):
            skipped_profiles.append(name)
            continue
        api_key = os.getenv(cfg["api_key_env"])
        secret = os.getenv(cfg["secret_env"])

        if not api_key or not secret:
            raise RuntimeError(f"Missing env vars for profile '{name}'")

        profiles[name] = TradingProfile(
            name=name,
            api_key=api_key,
            secret=secret,
            max_risk_pct=float(cfg.get("max_risk_pct", 1.0)),
            default_order_size_pct=float(cfg.get("default_order_size_pct", 10)),
            take_profit_pct=float(cfg.get("take_profit_pct", 0)),
            stop_loss_pct=float(cfg.get("stop_loss_pct", 0)),
            trailing_stop_pct=float(cfg.get("trailing_stop_pct", 0)),
            use_trailing_stop=cfg.get("use_trailing_stop", False),
            max_position_size=float(cfg.get("max_position_size", 0)),
        )
    print(f"Loaded {len(profiles)} enabled profiles from YAML")
    if skipped_profiles:
        print(f"Skipped {len(skipped_profiles)} disabled profiles: {', '.join(skipped_profiles)}")
    
    return ProfileManager(profiles)
# Global instance
_profile_manager = None

def set_profile_manager(pm: ProfileManager):
    """Set the global profile manager instance"""
    global _profile_manager
    _profile_manager = pm

def get_profile_manager() -> ProfileManager:
    """Get the global profile manager instance"""
    return _profile_manager


