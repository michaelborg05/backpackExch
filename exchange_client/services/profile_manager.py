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

        # Load trend filter configuration
        use_trend_filter = cfg.get("use_trend_filter", False)
        trend_timeframe = cfg.get("trend_timeframe", "1h")
        trend_indicators = cfg.get("trend_indicators", None)
        min_indicators_required = cfg.get("min_indicators_required", 2)
        
        # Validate trend indicators if trend filter is enabled
        if use_trend_filter and trend_indicators:
            # Ensure trend_indicators is a list
            if not isinstance(trend_indicators, list):
                print(f"WARNING: Profile '{name}' has invalid trend_indicators format, disabling trend filter")
                use_trend_filter = False
                trend_indicators = None
            else:
                # Validate each indicator config
                valid_indicators = []
                for indicator in trend_indicators:
                    if isinstance(indicator, dict) and "type" in indicator:
                        valid_indicators.append(indicator)
                    else:
                        print(f"WARNING: Profile '{name}' has invalid indicator config: {indicator}")
                
                if len(valid_indicators) == 0:
                    print(f"WARNING: Profile '{name}' has no valid indicators, disabling trend filter")
                    use_trend_filter = False
                    trend_indicators = None
                else:
                    trend_indicators = valid_indicators
                    
                    # Adjust min_indicators_required if it exceeds available indicators
                    if min_indicators_required > len(trend_indicators):
                        print(
                            f"WARNING: Profile '{name}' min_indicators_required ({min_indicators_required}) "
                            f"exceeds available indicators ({len(trend_indicators)}), adjusting to {len(trend_indicators)}"
                        )
                        min_indicators_required = len(trend_indicators)


        enable_signal_generation    = cfg.get("enable_signal_generation",False)
        signal_timeframe            = cfg.get("signal_timeframe", "15m")
        signal_cooldown_seconds     = cfg.get("signal_cooldown_seconds", 300)
        min_signal_confidence       = cfg.get("min_signal_confidence", 75)
        min_volume_ratio            = cfg.get("min_volume_ratio", 1.5)

        # Market Regime filter
        use_market_regime_filter    = cfg.get("use_market_regime_filter", False)

        # Load ATR filter configuration
        use_atr_filter = cfg.get("use_atr_filter", False)
        atr_timeframe = cfg.get("atr_timeframe", "1m")
        atr_threshold = cfg.get("atr_threshold", 1.05)
        atr_filter_mode = cfg.get("atr_filter_mode", "require_high")
        atr_max_threshold = cfg.get("atr_max_threshold", None)

        #Position exit logic
        use_trend_invalidation_exit = cfg.get("use_trend_invalidation_exit",False)
        min_position_age_for_trend_check = cfg.get("min_position_age_for_trend_check",2)
        max_position_hours = cfg.get("max_position_hours",None)


        profiles[name] = TradingProfile(
            name=name,
            api_key=api_key,
            secret=secret,
        
            # Position sizing
            default_order_size_usdc=float(cfg.get("default_order_size_usdc", 100)), # Default order size in USDC (fixed amount)
            max_position_size_pct=float(cfg.get("max_position_size_pct", 10)),      # Max position as % of portfolio (e.g., 10% = 10.0)

            # Risk management
            max_open_positions=int(cfg.get("max_open_positions", 5)),               # Max concurrent positions
            max_portfolio_exposure_pct=float(cfg.get("max_portfolio_exposure_pct", 80)),    # Max % of portfolio in positions
            take_profit_pct=float(cfg.get("take_profit_pct", 0)),
            stop_loss_pct=float(cfg.get("stop_loss_pct", 0)),
            trailing_stop_pct=float(cfg.get("trailing_stop_pct", 0)),
            arm_trailing_stop_pct=float(cfg.get("arm_trailing_stop_pct", 0)),
            use_trailing_stop=cfg.get("use_trailing_stop", False),
            max_position_size=float(cfg.get("max_position_size", 0)),
            # NEW: Trend filter fields
            use_trend_filter=use_trend_filter,
            trend_timeframe=trend_timeframe,
            trend_indicators=trend_indicators,
            min_indicators_required=min_indicators_required,
            # ATR filter fields (NEW)
            use_atr_filter=use_atr_filter,
            atr_timeframe=atr_timeframe,
            atr_threshold=atr_threshold,
            atr_filter_mode=atr_filter_mode,
            atr_max_threshold=atr_max_threshold,
            #New signal fields
            enable_signal_generation    = enable_signal_generation,
            signal_timeframe            = signal_timeframe,
            signal_cooldown_seconds     = signal_cooldown_seconds,
            min_signal_confidence       = min_signal_confidence,
            min_volume_ratio            = min_volume_ratio,
            #position logic
            use_trend_invalidation_exit = use_trend_invalidation_exit,
            min_position_age_for_trend_check = min_position_age_for_trend_check,
            max_position_hours          = max_position_hours,
            use_market_regime_filter=use_market_regime_filter,

        )


        # Log trend filter status for this profile
        filter_info = []
        
        if use_trend_filter:
            indicator_types = [ind.get("type") for ind in (trend_indicators or [])]
            filter_info.append(
                f"Trend: {trend_timeframe} "
                f"({min_indicators_required}/{len(trend_indicators)} required: {', '.join(indicator_types)})"
            )

        if use_atr_filter:
            atr_desc = f"ATR: {atr_timeframe} (threshold: {atr_threshold}, mode: {atr_filter_mode}"
            if atr_max_threshold:
                atr_desc += f", max: {atr_max_threshold}"
            atr_desc += ")"
            filter_info.append(atr_desc)

        if filter_info:
            print(f"  └─ {name}: {' | '.join(filter_info)}")
        else:
            print(f"  └─ {name}: No filters enabled")
                
    print(f"\nLoaded {len(profiles)} enabled profiles from YAML")
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