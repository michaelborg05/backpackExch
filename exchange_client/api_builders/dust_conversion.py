"""Dust conversion functionality for Backpack Exchange"""
from typing import Dict, List, Optional
from decimal import Decimal
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters
from services.client import api_request
from utils.constants import HttpMethod
from utils.exceptions import ExchangeAPIError

class DustConverter:
    """Handles dust conversion for Backpack Exchange accounts"""

    # Minimum value thresholds for dust conversion
    DEFAULT_DUST_THRESHOLD = Decimal("1.0")  # $1 USD equivalent

    def __init__(self):
        self.logger = log_manager.get_logger("DustConversion")

    def convert_dust(
        self,
        account_name: str,
        api_key: str,
        secret: str,
        dust_threshold: Optional[Decimal] = None
    ) -> Optional[Dict]:
        """
        Convert dust to USDC for a specific exchange account

        Args:
            account_name: Exchange account name (for logging)
            api_key: Decrypted API key
            secret: Decrypted secret
            dust_threshold: Optional custom threshold (default: $1 USD)

        Returns:
            API response with conversion details or None if failed
        """
        if dust_threshold is None:
            dust_threshold = self.DEFAULT_DUST_THRESHOLD

        self.logger.info(
            f"Converting dust for account [{account_name}] "
            f"(threshold: ${dust_threshold})"
        )

        url = APIEndpoints.backpack_convert_dust()

        # Empty body required - Backpack expects {} not null
        body = {}

        # Build authorization headers
        headers = data_converters.build_authorisation_header(
            api_key=api_key,
            secret=secret,
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
                    f"Dust conversion successful for [{account_name}]"
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
                    f"Dust conversion failed for [{account_name}]"
                )
                return None

        except ExchangeAPIError as e:
            # Check if it's the "no funds to convert" error
            if "insufficient_funds" in str(e).lower() or e.status_code == 400:
                self.logger.debug(
                    f"No dust to convert for [{account_name}] (insufficient funds)"
                )
                # Return empty dict - this is a success case (no dust = nothing to convert)
                return {}
            else:
                # Some other API error
                self.logger.error(
                    f"API error converting dust for [{account_name}]: {e}",
                    exc_info=True
                )
                return None

        except Exception as e:
            self.logger.error(
                f"Error converting dust for [{account_name}]: {e}",
                exc_info=True
            )
            return None

    def convert_dust_all_accounts(
        self,
        dust_threshold: Optional[Decimal] = None
    ) -> Dict[str, Optional[Dict]]:
        """
        Convert dust for all active Backpack exchange accounts

        Args:
            dust_threshold: Optional custom threshold (default: $1 USD)

        Returns:
            Dictionary mapping account names to conversion results
        """
        from db.utils import get_db_session
        from db.models import ExchangeAccount, TradingProfileDB
        from utils.db_secrets import resolve_secret

        with get_db_session() as db:
            # Only convert dust for accounts that have at least one enabled profile
            enabled_account_ids = (
                db.query(TradingProfileDB.account_id)
                .filter(
                    TradingProfileDB.is_active == True,
                    TradingProfileDB.enable_signal_generation == True,
                    TradingProfileDB.account_id.isnot(None),
                )
                .distinct()
                .subquery()
            )
            accounts = (
                db.query(ExchangeAccount)
                .filter(
                    ExchangeAccount.is_active == True,
                    ExchangeAccount.exchange_type == "backpack",
                    ExchangeAccount.id.in_(enabled_account_ids),
                )
                .order_by(ExchangeAccount.name)
                .all()
            )
            # Pull out what we need before the session closes
            account_creds = []
            for acct in accounts:
                api_key = resolve_secret(acct.api_key)
                secret = resolve_secret(acct.secret)
                if not api_key or not secret:
                    self.logger.warning(
                        f"Skipping account [{acct.name}] — missing credentials"
                    )
                    continue
                account_creds.append((acct.name, api_key, secret))

        self.logger.info(
            f"Converting dust for {len(account_creds)} exchange accounts..."
        )

        results = {}
        for account_name, api_key, secret in account_creds:
            result = self.convert_dust(account_name, api_key, secret, dust_threshold)
            results[account_name] = result

        # Log summary
        successful = sum(1 for r in results.values() if r is not None)
        self.logger.info(
            f"Dust conversion complete: {successful}/{len(account_creds)} successful"
        )

        return results


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
