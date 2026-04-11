"""Dust conversion functionality for Backpack Exchange"""
from typing import Dict, List, Optional
from decimal import Decimal
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters
from services.client import api_request
from utils.constants import HttpMethod
from utils.exceptions import ExchangeAPIError
from models.trading_profile import TradingProfile
from services.profile_manager import get_profile_manager
from cache.balance_cache import get_balance_cache

class DustConverter:
    """Handles dust conversion for Backpack Exchange accounts"""
    
    # Minimum value thresholds for dust conversion
    DEFAULT_DUST_THRESHOLD = Decimal("1.0")  # $1 USD equivalent
    
    def __init__(self):
        self.logger = log_manager.get_logger("DustConversion")
        
    def convert_dust(
        self,
        profile: TradingProfile,
        dust_threshold: Optional[Decimal] = None
    ) -> Optional[Dict]:
        """
        Convert dust to USDC for a specific profile
        
        Args:
            profile: Trading profile to convert dust for
            dust_threshold: Optional custom threshold (default: $1 USD)
            
        Returns:
            API response with conversion details or None if failed
        """
        if dust_threshold is None:
            dust_threshold = self.DEFAULT_DUST_THRESHOLD

        # Dust conversion is only supported on Backpack
        exchange_type = getattr(profile, "exchange_type", "backpack") or "backpack"
        if exchange_type != "backpack":
            self.logger.debug(
                f"Skipping dust conversion for [{profile.name}] — "
                f"not supported on {exchange_type}"
            )
            return {}

        self.logger.info(
            f"Converting dust for profile [{profile.name}] "
            f"(threshold: ${dust_threshold})"
        )

        url = APIEndpoints.backpack_convert_dust()
        
        # Empty body required - Backpack expects {} not null
        body = {}
        
        # Build authorization headers
        headers = data_converters.build_authorisation_header(
            api_key=profile.api_key,
            secret=profile.secret,
            query_params={},
            body=body,
            instruction="convertDust",
            window=60000
        )
        
        try:
            # Make POST request to convert dust with empty body
            response = api_request(
                url=url,
                headers=headers,
                body=body,  # Empty dict required by Backpack
                requestType=HttpMethod.POST
            )
            
            # Successful conversion - response may be empty {} or None
            # Both indicate success (empty means no dust converted, which is fine)
            if response is not None:
                self.logger.info(
                    f"Dust conversion successful for [{profile.name}]"
                )
                
                # Log converted assets if available
                if isinstance(response, dict) and response:
                    converted = response.get('converted', [])
                    if converted:
                        self.logger.info(
                            f"Converted {len(converted)} assets to USDC"
                        )
                        for asset in converted:
                            self.logger.debug(
                                f"  {asset.get('symbol')}: "
                                f"{asset.get('amount')} @ "
                                f"{asset.get('price')}"
                            )
                    else:
                        self.logger.debug("No dust to convert (empty response)")
                else:
                    self.logger.debug("No dust to convert (empty response)")
                
                # Return empty dict to indicate success even if no dust converted
                return response if response else {}
            else:
                self.logger.error(
                    f"Dust conversion failed for [{profile.name}]"
                )
                return None
                
        except ExchangeAPIError as e:
            # Check if it's the "no funds to convert" error
            if "insufficient_funds" in str(e).lower() or e.status_code == 400:
                self.logger.debug(
                    f"No dust to convert for [{profile.name}] (insufficient funds)"
                )
                # Return empty dict - this is a success case (no dust = nothing to convert)
                return {}
            else:
                # Some other API error
                self.logger.error(
                    f"API error converting dust for [{profile.name}]: {e}",
                    exc_info=True
                )
                return None
                
        except Exception as e:
            self.logger.error(
                f"Error converting dust for [{profile.name}]: {e}",
                exc_info=True
            )
            return None
    
    def convert_dust_all_profiles(
        self,
        dust_threshold: Optional[Decimal] = None
    ) -> Dict[str, Optional[Dict]]:
        """
        Convert dust for all active profiles
        
        Args:
            dust_threshold: Optional custom threshold (default: $1 USD)
            
        Returns:
            Dictionary mapping profile names to conversion results
        """
        profile_manager = get_profile_manager()
        if not profile_manager:
            self.logger.error("Profile manager not initialized")
            return {}
        
        results = {}
        profiles = profile_manager.get_all_profiles()
        
        self.logger.info(
            f"Converting dust for {len(profiles)} profiles..."
        )
        
        for profile in profiles:
            result = self.convert_dust(profile, dust_threshold)
            results[profile.name] = result
        
        # Log summary
        successful = sum(1 for r in results.values() if r is not None)
        self.logger.info(
            f"Dust conversion complete: {successful}/{len(profiles)} successful"
        )
        
        return results
    
    def get_dustable_assets(
        self,
        profile: TradingProfile
    ) -> Optional[List[Dict]]:
        """
        Get list of assets that can be converted to dust
        
        Args:
            profile: Trading profile to check
            
        Returns:
            List of dustable assets or None if failed
        """
        # Use balance cache to identify small balances
        balance_cache = get_balance_cache()
        cached_balances = balance_cache.get_profile_balances(profile.name)
        
        if not cached_balances:
            self.logger.warning(
                f"No cached balances for [{profile.name}], "
                f"cannot identify dustable assets"
            )
            return None
        
        dustable = []
        for symbol, balance_info in cached_balances.items():
            # Skip stablecoins and major assets
            if symbol in ['USDC', 'USDT', 'BTC', 'ETH', 'SOL']:
                continue
            
            available = Decimal(balance_info.get('available', '0'))
            
            # Consider it dust if available balance is very small
            if available > 0 and available < Decimal("0.01"):  # Arbitrary small threshold
                dustable.append({
                    'symbol': symbol,
                    'available': str(available),
                    'total': str(
                        available + 
                        Decimal(balance_info.get('locked', '0')) + 
                        Decimal(balance_info.get('staked', '0'))
                    )
                })
        
        if dustable:
            self.logger.debug(
                f"Found {len(dustable)} dustable assets for [{profile.name}]"
            )
        
        return dustable if dustable else None


# Global instance
_dust_converter = None


def get_dust_converter() -> DustConverter:
    """Get or create the global dust converter instance"""
    global _dust_converter
    if _dust_converter is None:
        _dust_converter = DustConverter()
    return _dust_converter


def set_dust_converter(converter: DustConverter):
    """Set the global dust converter instance"""
    global _dust_converter
    _dust_converter = converter