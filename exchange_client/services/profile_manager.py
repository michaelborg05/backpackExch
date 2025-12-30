from pathlib import Path
import os
import yaml
from typing import Dict
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


def load_profiles(path: Path | None = None) -> ProfileManager:
    path = path or DEFAULT_PROFILE_PATH
    if not path.exists():
        raise FileNotFoundError(f"Profile config not found: {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    profiles = {}

    for name, cfg in raw.get("profiles", {}).items():
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
        )

    return ProfileManager(profiles)

_profile_manager = None

def set_profile_manager(pm):
    global _profile_manager
    _profile_manager = pm

def get_profile_manager():
    return _profile_manager