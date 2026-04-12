from typing import Dict, Optional
from decimal import Decimal
from cache.balance_cache import get_balance_cache
from cache.price_cache import get_price_cache
from utils.logging import log_manager


class PortfolioCache:
    """
    Combines balance and price data to provide portfolio information
    Does not store data itself - reads from BalanceCache and PriceCache
    """
    
    def __init__(self):
        self.logger = log_manager.get_logger("PortfolioCache")
        self.balance_cache = get_balance_cache()
        self.price_cache = get_price_cache()
        self.DUST_THRESHOLD = Decimal("0.0001")  # Minimum balance to consider
    def get_asset_value(
        self,
        profile_name: str,
        asset: str,
        quote_asset: str = "USDC",
        summary: bool = True
    ) -> Optional[Dict]:
        """
        Get asset balance and its USD value
        
        Args:
            asset: Asset symbol (e.g., "SOL")
            quote_asset: Quote asset for pricing (default "USDC")
            
        Returns:
            Dict with balance, price, and value information
        """
        balances = self.balance_cache.get_profile_balances(profile_name)
        if not balances or asset not in balances:
            return None

        asset_balance = balances[asset]

        available_qty = Decimal(asset_balance.get("available", "0"))
        locked_qty = Decimal(asset_balance.get("locked", "0"))
        staked_qty = Decimal(asset_balance.get("staked", "0"))
        total_qty = available_qty + locked_qty + staked_qty

        if total_qty < self.DUST_THRESHOLD:
            return None

        # If asset IS the quote asset (e.g., USDC), price is 1
        if asset == quote_asset:
            price = Decimal("1.0")
        else:
            # Get price
            symbol = f"{asset}_{quote_asset}"
            price = self.price_cache.get_price(symbol)
        
        if summary:
            result = {
                "asset": asset,
                "total": str(total_qty),
            }

            if price is not None:
                result["price"] = str(price)
                result["total_value"] = str(round(total_qty * price, 2))
            else:
                result["price"] = None
                result["note"] = "Price not available"

            return result
        
        # detailed version
        result = {
            "asset": asset,
            "available": str(available_qty),
            "locked": str(locked_qty),
            "staked": str(staked_qty),
            "total": str(total_qty),
            "quote_asset": quote_asset,
        }

        if price is not None:
            result.update({
                "price": str(price),
                "available_value": str(round(available_qty * price, 2)),
                "locked_value": str(round(locked_qty * price, 2)),
                "staked_value": str(round(staked_qty * price, 2)),
                "total_value": str(round(total_qty * price, 2)),
            })
        else:
            result["price"] = None
            result["note"] = "Price not available"

        return result
    
    def get_portfolio_summary(
        self,
        profile_name: str,
        quote_asset: str = "USDC",
        summary: bool = True
    ) -> Dict:

        balances = self.balance_cache.get_profile_balances(profile_name)

        if not balances:
            return {
                "profile": profile_name,
                "error": "No balance data available",
                "total_value": "0",
                "assets": []
            }

        assets = []
        total_value = Decimal("0")

        for asset in balances.keys():
            asset_info = self.get_asset_value(
                profile_name,
                asset,
                quote_asset,
                summary
            )

            if asset_info and not self._is_zero_balance(asset_info):
                assets.append(asset_info)

                if "total_value" in asset_info:
                    try:
                        total_value += Decimal(asset_info["total_value"])
                    except:
                        pass

        return {
            "profile": profile_name,
            "total_value": str(round(total_value, 2)),
            "asset_count": len(assets),
            "assets": assets,
            "balance_cache_info": self.balance_cache.get_cache_info(),
            "price_cache_info": self.price_cache.get_cache_info()
        }

    def print_portfolio_summary(self, profile_name: str, quote_asset: str = "USDC", display_name: str = "") -> str:
        from services.circuit_breaker import get_circuit_breaker
        portfolio = self.get_portfolio_summary(profile_name, quote_asset)
        circuit_breaker = get_circuit_breaker()
        limit_summary = circuit_breaker.get_daily_summary(profile_name)

        if limit_summary:
            status = f"⛔ - {limit_summary['hours_remaining']}hrs left" if limit_summary.get('circuit_breaker_active') else "✅"
            result = f"({display_name if display_name else profile_name}) Total: ${portfolio.get('total_value')} ({limit_summary['daily_pnl_pct']}) {status}"
        else:
            result = f"({display_name if display_name else profile_name}) Total: ${portfolio.get('total_value')} "


        return result
    def _is_zero_balance(self, asset_data: dict) -> bool:
        """Check if all balance fields are zero"""
        try:
            total = sum(
                Decimal(asset_data.get(field, "0"))
                for field in ["total_value", "total"]
            )
            return total <= 0.1
        except:
            return False

    def get_total_value(self, profile_name: str, quote_asset: str = "USDC") -> Decimal:
        summary = self.get_portfolio_summary(profile_name, quote_asset)
        return Decimal(summary.get("total_value", "0"))

# Global instance
_portfolio_cache = PortfolioCache()


def get_portfolio_cache() -> PortfolioCache:
    """Get the global portfolio cache instance"""
    return _portfolio_cache
