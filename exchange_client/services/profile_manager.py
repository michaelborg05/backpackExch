from pathlib import Path
import os
import yaml
from typing import Dict, List, Optional
from models.trading_profile import TradingProfile
from utils.constants import StrategyType, TradingType

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
        """Get all enabled profiles"""
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

    def replace_profiles(self, new_profiles: Dict[str, TradingProfile]) -> None:
        """
        Hot-swap the internal profiles dict in-place.
        Called by the periodic refresh without replacing the ProfileManager instance,
        so all existing references (e.g. in MonitoringService) remain valid.
        """
        self._profiles = new_profiles

    def get_profiles_for_account(self, account_id: int) -> List[TradingProfile]:
        """Get all active profiles sharing the same exchange account"""
        return [
            p for p in self._profiles.values()
            if getattr(p, 'account_id', None) == account_id
        ]

    def get_canonical_profile_for_account(self, account_id: int) -> Optional[TradingProfile]:
        """
        Return the single 'canonical' profile for balance reporting.
        Uses the profile with the lowest id to ensure consistency.
        """
        profiles = self.get_profiles_for_account(account_id)
        if not profiles:
            return None
        return min(profiles, key=lambda p: p.id)
# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_profile(name: str, cfg: dict, api_key: str, secret: str) -> TradingProfile:
    """
    Shared factory used by both the YAML and DB loaders.
    `cfg` is a plain dict that mirrors the YAML structure.
    """
    display_name = cfg.get("display_name", name)
    try:
        strategy_type = StrategyType(cfg.get("strategy_type", "trend_following"))
    except Exception:
        raise RuntimeError(f"Invalid Strategy Type '{cfg.get('strategy_type')}'")

    try:
        trading_type = TradingType(cfg.get("trading_type", "rules_live"))
    except Exception:
        raise RuntimeError(f"Invalid Trading Type '{cfg.get('trading_type')}'")

    try:
        profile_id = int(cfg.get("id"))
    except Exception:
        raise RuntimeError(f"Profile id not found''")

    # ── Trend filter ────────────────────────────────────────────────────────
    use_trend_filter = cfg.get("use_trend_filter", False)
    trend_timeframe = cfg.get("trend_timeframe", "1h")
    trend_indicators = cfg.get("trend_indicators", None)
    min_indicators_required = cfg.get("min_indicators_required", 2)

    if use_trend_filter and trend_indicators:
        trend_indicators, min_indicators_required = _validate_indicators(
            name, "trend", trend_indicators, min_indicators_required
        )
        if trend_indicators is None:
            use_trend_filter = False

    # ── Entry filter ─────────────────────────────────────────────────────────
    use_entry_filter = cfg.get("use_entry_filter", False)
    entry_timeframe = cfg.get("entry_timeframe", "15m")
    entry_indicators = cfg.get("entry_indicators", None)
    min_entry_indicators_required = cfg.get("min_entry_indicators_required", 2)

    if use_entry_filter and entry_indicators:
        entry_indicators, min_entry_indicators_required = _validate_indicators(
            name, "entry", entry_indicators, min_entry_indicators_required
        )
        if entry_indicators is None:
            use_entry_filter = False

    # ── ATR filter ───────────────────────────────────────────────────────────
    use_atr_filter = cfg.get("use_atr_filter", False)
    atr_timeframe = cfg.get("atr_timeframe", "1m")
    atr_threshold = cfg.get("atr_threshold", 1.05)
    atr_filter_mode = cfg.get("atr_filter_mode", "require_high")

    profile = TradingProfile(
        id=profile_id,
        name=name,
        display_name=display_name,
        account_id=cfg.get("account_id"),
        api_key=api_key,
        secret=secret,
        trading_type=trading_type,
        strategy_type=strategy_type,
        # Position sizing
        default_order_size_usdc=float(cfg.get("default_order_size_usdc", 100)),
        max_position_size_pct=float(cfg.get("max_position_size_pct", 10)),
        # Risk management
        max_open_positions=int(cfg.get("max_open_positions", 5)),
        max_portfolio_exposure_pct=float(cfg.get("max_portfolio_exposure_pct", 80)),
        take_profit_pct=float(cfg.get("take_profit_pct", 0)),
        stop_loss_pct=float(cfg.get("stop_loss_pct", 0)),
        trailing_stop_pct=float(cfg.get("trailing_stop_pct", 0)),
        arm_trailing_stop_pct=float(cfg.get("arm_trailing_stop_pct", 0)),
        use_trailing_stop=cfg.get("use_trailing_stop", False),
        max_position_size=float(cfg.get("max_position_size", 0)),
        # Trend filter
        use_trend_filter=use_trend_filter,
        trend_timeframe=trend_timeframe,
        trend_indicators=trend_indicators,
        min_indicators_required=min_indicators_required,
        # Entry filter
        use_entry_filter=use_entry_filter,
        entry_timeframe=entry_timeframe,
        entry_indicators=entry_indicators,
        min_entry_indicators_required=min_entry_indicators_required,
        # ATR filter
        use_atr_filter=use_atr_filter,
        atr_timeframe=atr_timeframe,
        atr_threshold=atr_threshold,
        atr_filter_mode=atr_filter_mode,
        # Signal generation
        enable_signal_generation=cfg.get("enable_signal_generation", False),
        signal_timeframe=cfg.get("signal_timeframe", "15m"),
        signal_cooldown_seconds=cfg.get("signal_cooldown_seconds", 300),
        min_signal_confidence=cfg.get("min_signal_confidence", 75),
        min_volume_ratio=cfg.get("min_volume_ratio", 1.5),
        # Position exit logic
        use_trend_invalidation_exit=cfg.get("use_trend_invalidation_exit", False),
        trend_invalidation_indicators=cfg.get("trend_invalidation_indicators", "entry"),
        min_position_age_for_trend_check=cfg.get("min_position_age_for_trend_check", 120),
        max_position_hours=cfg.get("max_position_hours", None),
        # Market regime
        use_market_regime_filter=cfg.get("use_market_regime_filter", False),
    )
    return profile


def _validate_indicators(
    profile_name: str,
    label: str,
    indicators,
    min_required: int,
):
    """
    Validate a list of indicator dicts.
    Returns (validated_list, adjusted_min) or (None, min_required) on failure.
    """
    if not isinstance(indicators, list):
        print(f"WARNING: Profile '{profile_name}' has invalid {label}_indicators format, disabling {label} filter")
        return None, min_required

    valid = [ind for ind in indicators if isinstance(ind, dict) and "type" in ind]
    invalid_count = len(indicators) - len(valid)
    if invalid_count:
        print(f"WARNING: Profile '{profile_name}' skipped {invalid_count} invalid {label} indicator(s)")

    if not valid:
        print(f"WARNING: Profile '{profile_name}' has no valid {label} indicators, disabling {label} filter")
        return None, min_required

    if min_required > len(valid):
        print(
            f"WARNING: Profile '{profile_name}' min_{label}_indicators_required ({min_required}) "
            f"exceeds available indicators ({len(valid)}), adjusting to {len(valid)}"
        )
        min_required = len(valid)

    return valid, min_required


def _log_profile_filters(
    name: str,
    use_trend_filter: bool,
    trend_timeframe: str,
    trend_indicators,
    min_indicators_required: int,
    use_entry_filter: bool,
    entry_timeframe: str,
    entry_indicators,
    min_entry_indicators_required: int,
    use_atr_filter: bool,
    atr_timeframe: str,
    atr_threshold: float,
    atr_filter_mode: str,
):
    filter_info = []

    if use_trend_filter and trend_indicators:
        types = [ind.get("type") for ind in trend_indicators]
        filter_info.append(
            f"Trend: {trend_timeframe} ({min_indicators_required}/{len(trend_indicators)} required: {', '.join(types)})"
        )

    if use_entry_filter and entry_indicators:
        types = [ind.get("type") for ind in entry_indicators]
        filter_info.append(
            f"Entry: {entry_timeframe} ({min_entry_indicators_required}/{len(entry_indicators)} required: {', '.join(types)})"
        )

    if use_atr_filter:
        atr_desc = f"ATR: {atr_timeframe} (threshold: {atr_threshold}, mode: {atr_filter_mode}"
        atr_desc += ")"
        filter_info.append(atr_desc)

    if filter_info:
        print(f"  └─ {name}: {' | '.join(filter_info)}")
    else:
        print(f"  └─ {name}: No filters enabled")


# ---------------------------------------------------------------------------
# DB loader  (primary)
# ---------------------------------------------------------------------------

def load_profiles_from_db(db_session) -> ProfileManager:
    """
    Load all active TradingProfileDB rows (with their IndicatorDB children)
    and return a ProfileManager.

    Indicators are stored in `indicators` table with a `category` column
    ('trend' | 'entry' | 'exit') and a `params` JSONB column.
    """
    from db.models import TradingProfileDB  # local import to avoid circular deps

    db_profiles: List[TradingProfileDB] = (
        db_session.query(TradingProfileDB)
        .filter(TradingProfileDB.is_active == True)
        .all()
    )

    profiles: Dict[str, TradingProfile] = {}

    for row in db_profiles:
        # ── Reconstruct indicator lists from IndicatorDB rows ────────────
        trend_indicators = []
        entry_indicators = []

        for ind in row.indicators:
            if not ind.enabled:
                continue

            # Reconstruct the exact same shape that YAML produces:
            # {"type": "ema_slope", "params": {"ema": 20, ...}, "hard_stop": True}
            # Previously params were spread flat (**ind.params) which broke
            # anything downstream that does indicator_config.get("params", {})
            params = dict(ind.params or {})
            params["hard_stop"] = ind.is_hard_stop

            indicator_cfg = {
                "type": ind.indicator_type,
                "params": params,
            }

            if ind.category == "trend":
                trend_indicators.append(indicator_cfg)
            elif ind.category == "entry":
                entry_indicators.append(indicator_cfg)
            # 'exit' category reserved for future use

        # ── Build a normalised cfg dict (same shape _build_profile expects) ─
        cfg = {
            "id" : row.id,
            "display_name": row.display_name,
            "account_id": row.account_id, 
            "trading_type": row.trading_type,
            "strategy_type": row.strategy_type,
            # Position sizing
            "default_order_size_usdc": float(row.default_order_size_usdc or 100),
            "max_position_size_pct": float(row.max_position_size_pct or 10),
            # Risk management
            "max_open_positions": int(row.max_open_positions or 5),
            "max_portfolio_exposure_pct": float(row.max_portfolio_exposure_pct or 80),
            "take_profit_pct": float(row.take_profit_pct or 0),
            "stop_loss_pct": float(row.stop_loss_pct or 0),
            "trailing_stop_pct": float(row.trailing_stop_pct or 0),
            "arm_trailing_stop_pct": float(row.arm_trailing_stop_pct or 0),
            "use_trailing_stop": bool(row.use_trailing_stop),
            "max_position_size": 0,
            # Trend filter
            "use_trend_filter": bool(row.use_trend_filter),
            "trend_timeframe": row.trend_timeframe or "60",
            "trend_indicators": trend_indicators or None,
            "min_indicators_required": row.min_indicators_required or 2,
            # Entry filter
            "use_entry_filter": bool(row.use_entry_filter),
            "entry_timeframe": row.entry_timeframe or "15",
            "entry_indicators": entry_indicators or None,
            "min_entry_indicators_required": row.min_entry_indicators_required or 2,
            # ATR filter
            "use_atr_filter": bool(row.use_atr_filter),
            # Signal generation
            "enable_signal_generation": True,   # all DB profiles are active
            "signal_timeframe": row.signal_timeframe or "15m",
            "signal_cooldown_seconds": row.signal_cooldown_seconds or 300,
            "min_signal_confidence": row.min_signal_confidence or 75,
            "min_volume_ratio": row.min_volume_ratio or 1.5,
            # Market regime
            "use_market_regime_filter": bool(row.use_market_regime_filter),
            "max_position_hours": row.max_position_hours or None,
            "use_trend_invalidation_exit": bool(row.use_trend_invalidation_exit),
            "trend_invalidation_indicators": row.trend_invalidation_indicators or "entry",            
            "min_position_age_for_trend_check": row.min_position_age_for_trend_check or 120,
            
        }
        from utils.db_secrets import resolve_secret
        # Resolve API credentials — stored encrypted in DB, pulled from env as fallback
        # If you store plaintext in DB just use row.api_key / row.secret directly.
        api_key = resolve_secret(row.api_key) or os.getenv(f"{row.name.upper()}_API_KEY")
        secret = resolve_secret(row.secret) or os.getenv(f"{row.name.upper()}_SECRET")

        if not api_key or not secret:
            print(f"WARNING: Skipping profile '{row.name}' — missing API credentials")
            continue

        try:
            profile = _build_profile(row.name, cfg, api_key, secret)
        except Exception as e:
            print(f"WARNING: Skipping profile '{row.name}' — build error: {e}")
            continue

        profiles[row.name] = profile

        _log_profile_filters(
            row.name,
            cfg["use_trend_filter"],
            cfg["trend_timeframe"],
            trend_indicators or [],
            cfg["min_indicators_required"],
            cfg["use_entry_filter"],
            cfg["entry_timeframe"],
            entry_indicators or [],
            cfg["min_entry_indicators_required"],
            cfg["use_atr_filter"],
            getattr(row, "atr_timeframe", "1m"),
            getattr(row, "atr_threshold", 1.05),
            getattr(row, "atr_filter_mode", "require_high"),
        )

    print(f"\nLoaded {len(profiles)} active profiles from DB")
    return ProfileManager(profiles)


# ---------------------------------------------------------------------------
# YAML loader  (fallback / migration helper)
# ---------------------------------------------------------------------------

def load_profiles(path: Path | None = None) -> ProfileManager:
    """Load profiles from YAML. Used as a fallback if DB is unavailable."""
    path = path or DEFAULT_PROFILE_PATH
    if not path.exists():
        raise FileNotFoundError(f"Profile config not found: {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    profiles: Dict[str, TradingProfile] = {}
    skipped_profiles = []

    for name, cfg in raw.get("profiles", {}).items():
        if not cfg.get("enabled", False):
            skipped_profiles.append(name)
            continue

        api_key = os.getenv(cfg["api_key_env"])
        secret = os.getenv(cfg["secret_env"])

        if not api_key or not secret:
            raise RuntimeError(f"Missing env vars for profile '{name}'")

        try:
            profile = _build_profile(name, cfg, api_key, secret)
        except Exception as e:
            print(f"WARNING: Skipping profile '{name}' — build error: {e}")
            continue

        profiles[name] = profile

        p = profile  # shorthand for logging
        _log_profile_filters(
            name,
            p.use_trend_filter,
            p.trend_timeframe,
            p.trend_indicators or [],
            p.min_indicators_required,
            p.use_entry_filter,
            p.entry_timeframe,
            p.entry_indicators or [],
            p.min_entry_indicators_required,
            p.use_atr_filter,
            p.atr_timeframe,
            p.atr_threshold,
            p.atr_filter_mode,
        )

    print(f"\nLoaded {len(profiles)} enabled profiles from YAML")
    if skipped_profiles:
        print(f"Skipped {len(skipped_profiles)} disabled profiles: {', '.join(skipped_profiles)}")

    return ProfileManager(profiles)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_profile_manager: Optional[ProfileManager] = None


def set_profile_manager(pm: ProfileManager) -> None:
    global _profile_manager
    _profile_manager = pm


def get_profile_manager() -> ProfileManager:
    return _profile_manager