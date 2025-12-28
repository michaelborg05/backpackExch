from typing import Dict, Optional
from decimal import Decimal
from services.balance_cache import get_balance_cache
from services.price_cache import get_price_cache
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
    
    def get_asset_value(self, asset: str, quote_asset: str = "USDC", summary: bool = True) -> Optional[Dict]:
        """
        Get asset balance and its USD value
        
        Args:
            asset: Asset symbol (e.g., "SOL")
            quote_asset: Quote asset for pricing (default "USDC")
            
        Returns:
            Dict with balance, price, and value information
        """
        # Get balance
        available = self.balance_cache.get_available_balance(asset)
        if available is None:
            return None
        
        # Get all balances for this asset
        balances = self.balance_cache.get_all_balances()
        if not balances or asset not in balances:
            return None
        
        asset_balance = balances[asset]
        
        # If asset IS the quote asset (e.g., USDC), price is 1
        if asset == quote_asset:
            price = Decimal("1.0")
        else:
            # Get price
            symbol = f"{asset}_{quote_asset}"
            price = self.price_cache.get_price(symbol)
        
        # Calculate values
        available_qty = Decimal(asset_balance.get("available", "0"))
        locked_qty = Decimal(asset_balance.get("locked", "0"))
        staked_qty = Decimal(asset_balance.get("staked", "0"))
        total_qty = available_qty + locked_qty + staked_qty
        
        match summary:
            case True:
                result = {
                    "asset": asset,
                    "total": str(total_qty),
                }
                
                if price is not None:
                    result.update({
                        "price": str(price),
                        "total_value": str(round(total_qty * price, 2)),
                    })
                else:
                    result["price"] = None
                    result["note"] = "Price not available"
            case False:
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
    
    def get_portfolio_summary(self, quote_asset: str = "USDC", summary: bool = True) -> Dict:
        """
        Get complete portfolio summary with total values
        
        Args:
            quote_asset: Quote asset for valuation (default "USDC")
            
        Returns:
            Portfolio summary with all assets and total value
        """
        balances = self.balance_cache.get_all_balances()
        
        if not balances:
            return {
                "error": "No balance data available",
                "total_value": "0",
                "assets": []
            }
        
        assets = []
        total_value = Decimal("0")
        
        for asset in balances.keys():
            asset_info = self.get_asset_value(asset, quote_asset, summary=summary)
            
            if asset_info:
                assets.append(asset_info)
                
                # Add to total if value is available
                if "total_value" in asset_info:
                    try:
                        total_value += Decimal(asset_info["total_value"])
                    except:
                        pass
        
        return {
            "total_value": str(round(total_value, 2)),
            "asset_count": len(assets),
            "assets": assets,
            "balance_cache_info": self.balance_cache.get_cache_info(),
            "price_cache_info": self.price_cache.get_cache_info()
        }

    def print_portfolio_summary(self, quote_asset: str = "USDC") -> str:
        portfolio_summary = self.get_portfolio_summary(quote_asset, summary=True)
        result = f"Portfolio Total: ${portfolio_summary.get('total_value', '0')} {quote_asset}\n"
        for asset_info in portfolio_summary.get("assets", []):
            result += (
                f" - {asset_info.get('asset')}: "
                f"{asset_info.get('total', '0')} - "
                f" ${asset_info.get('total_value', '0')} \n"
            )
        return result


    def get_total_value(self, quote_asset: str = "USDC") -> Decimal:
        """
        Get total portfolio value
        
        Args:
            quote_asset: Quote asset for valuation
            
        Returns:
            Total value as Decimal
        """
        summary = self.get_portfolio_summary(quote_asset)
        return Decimal(summary.get("total_value", "0"))

# Global instance
_portfolio_cache = PortfolioCache()


def get_portfolio_cache() -> PortfolioCache:
    """Get the global portfolio cache instance"""
    return _portfolio_cache
