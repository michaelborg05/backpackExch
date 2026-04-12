from decimal import Decimal
from typing import Dict, List, Optional, Set
import json

class AssetBalance:
    """Represents the balance of a single asset"""
    
    def __init__(self, symbol: str, available: str, locked: str, staked: str = "0"):
        self.symbol = symbol
        self.available = round(Decimal(available),3) if symbol not in ['BTC', 'ETH'] else Decimal(available)
        self.locked = round(Decimal(locked),3) if symbol not in ['BTC', 'ETH'] else Decimal(locked)
        self.staked = round(Decimal(staked or "0"),3) if symbol not in ['BTC', 'ETH'] else Decimal(staked or "0")
        self.DUST_THRESHOLD = Decimal("0.0001")
    
    @property
    def total(self) -> Decimal:
        """Total balance across all states"""
        return self.available + self.locked + self.staked
    
    @property
    def is_empty(self) -> bool:
        """Check if all balances are zero"""
        return abs(self.total) < self.DUST_THRESHOLD
    
    def __str__(self) -> str:
        return f"{self.symbol:>12}: Available={self.available}, Locked={self.locked}, Staked={self.staked}, Total={self.total}"
    
    def __repr__(self) -> str:
        return f"AssetBalance(symbol='{self.symbol}', available={self.available}, locked={self.locked}, staked={self.staked})"

class BalanceReader:
    """Class for reading and managing Backpack Exchange balance data"""
    
    # Define tokens to exclude from balance display (class-level constant)
    EXCLUDED_TOKENS: Set[str] = {
        "ZEX", "HONEY","MOBILE", "MOTHER", "POINTS"
        # Add delisted or unwanted tokens here
        # Example: "OLDTOKEN", "SCAM", "DEPRECATED"
    }
    
    def __init__(self, balance_data: Dict = None, exclude_tokens: Optional[Set[str]] = None):
        """
        Initialize with balance data dictionary
        
        Args:
            balance_data: Dictionary in Backpack format or None to create empty
            exclude_tokens: Additional tokens to exclude (beyond EXCLUDED_TOKENS)
        """
        self._balances: Dict[str, AssetBalance] = {}
        self._raw_balances: Dict = {}
        
        # Combine default exclusions with any custom ones
        self._excluded = self.EXCLUDED_TOKENS.copy()
        if exclude_tokens:
            self._excluded.update(exclude_tokens)
        
        if balance_data:
            self.load_balances(balance_data)
    
    def load_balances(self, balance_data: Dict) -> None:
        """
        Load balance data from dictionary with filtering
        
        Args:
            balance_data: Dictionary in Backpack balance format
        """
        self._balances.clear()
        self._raw_balances = balance_data.copy()
        
        for symbol, data in balance_data.items():
            # Skip excluded tokens
            if symbol in self._excluded:
                continue
            
            asset_balance = AssetBalance(
                symbol=symbol,
                available=data['available'],
                locked=data['locked'],
                staked=data.get('staked', '0')
            )
            
            # Optionally skip zero balances (uncomment if desired)
            if asset_balance.is_empty:
                continue
            
            self._balances[symbol] = asset_balance
    
    def load_from_json(self, json_string: str) -> None:
        """Load balance data from JSON string"""
        balance_data = json.loads(json_string)
        self.load_balances(balance_data)
    
    def get_balance(self, symbol: str) -> Optional[AssetBalance]:
        """
        Get balance for a specific asset
        
        Args:
            symbol: Asset symbol (e.g., 'BTC', 'ETH')
            
        Returns:
            AssetBalance object or None if not found
        """
        return self._balances.get(symbol.upper())
    
    def get_available_balance(self, symbol: str) -> Decimal:
        """Get available balance for an asset"""
        balance = self.get_balance(symbol)
        return balance.available if balance else Decimal('0')
    
    def get_total_balance(self, symbol: str) -> Decimal:
        """Get total balance for an asset"""
        balance = self.get_balance(symbol)
        return balance.total if balance else Decimal('0')
    
    def get_locked_balance(self, symbol: str) -> Decimal:
        """Get locked balance for an asset"""
        balance = self.get_balance(symbol)
        return balance.locked if balance else Decimal('0')
    
    def get_staked_balance(self, symbol: str) -> Decimal:
        """Get staked balance for an asset"""
        balance = self.get_balance(symbol)
        return balance.staked if balance else Decimal('0')
    
    def has_balance(self, symbol: str, minimum: str = "0") -> bool:
        """
        Check if asset has balance above minimum
        
        Args:
            symbol: Asset symbol
            minimum: Minimum balance threshold (default "0")
            
        Returns:
            True if total balance is above minimum
        """
        balance = self.get_balance(symbol)
        if not balance:
            return False
        return balance.total > Decimal(minimum)
    
    def has_available_balance(self, symbol: str, minimum: str = "0") -> bool:
        """Check if asset has available balance above minimum"""
        balance = self.get_balance(symbol)
        if not balance:
            return False
        return balance.available > Decimal(minimum)
    
    def get_all_symbols(self) -> List[str]:
        """Get list of all asset symbols (filtered)"""
        return list(self._balances.keys())
    
    def get_all_symbols_including_excluded(self) -> List[str]:
        """Get list of ALL asset symbols including excluded ones"""
        return list(self._raw_balances.keys())
    
    def get_non_zero_balances(self) -> Dict[str, AssetBalance]:
        """Get all assets with non-zero balances"""
        return {symbol: balance for symbol, balance in self._balances.items() 
                if not balance.is_empty}
    
    def get_available_assets(self) -> Dict[str, AssetBalance]:
        """Get all assets with available balance > 0"""
        return {symbol: balance for symbol, balance in self._balances.items() 
                if balance.available > 0}
    
    def summary(self) -> str:
        """Get a summary of all non-zero balances"""
        non_zero = self.get_non_zero_balances()
        if not non_zero:
            return "No balances found"
        
        lines = ["Balance Summary:"]
        for symbol, balance in sorted(non_zero.items()):
            lines.append(f"  {balance}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict:
        """Convert back to dictionary format (filtered balances only)"""
        result = {}
        for symbol, balance in self._balances.items():
            result[symbol] = {
                'available': str(balance.available),
                'locked': str(balance.locked),
                'staked': str(balance.staked)
            }
        return result
    
    def to_dict_raw(self) -> Dict:
        """Convert back to dictionary format (including excluded tokens)"""
        return self._raw_balances.copy()
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string (filtered balances only)"""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def add_excluded_token(cls, token: str):
        """Add a token to the global exclusion list"""
        cls.EXCLUDED_TOKENS.add(token.upper())
    
    @classmethod
    def remove_excluded_token(cls, token: str):
        """Remove a token from the global exclusion list"""
        cls.EXCLUDED_TOKENS.discard(token.upper())
    
    @classmethod
    def get_excluded_tokens(cls) -> Set[str]:
        """Get current list of excluded tokens"""
        return cls.EXCLUDED_TOKENS.copy()
    
    def get_excluded_count(self) -> int:
        """Get count of excluded tokens in current data"""
        return sum(1 for symbol in self._raw_balances.keys() if symbol in self._excluded)
    
    def __len__(self) -> int:
        """Number of assets (filtered)"""
        return len(self._balances)
    
    def __contains__(self, symbol: str) -> bool:
        """Check if symbol exists in balances (filtered)"""
        return symbol.upper() in self._balances
    
    def __getitem__(self, symbol: str) -> AssetBalance:
        """Get balance by symbol (raises KeyError if not found)"""
        return self._balances[symbol.upper()]
    
    def __iter__(self):
        """Iterate over asset symbols (filtered)"""
        return iter(self._balances)
    
    def __str__(self) -> str:
        return self.summary()


# Example usage and testing
def example_usage():
    """Example of how to use the BalanceReader class with filtering"""
    
    # Sample balance data
    sample_data = {
        "BONK": {
            "available": "1000000",
            "locked": "0",
            "staked": "500000"
        },
        "BTC": {
            "available": "0.5",
            "locked": "0.1",
            "staked": "0"
        },
        "CLOUD": {
            "available": "0",
            "locked": "0",
            "staked": "0"
        },
        "USDC": {
            "available": "1250.50",
            "locked": "100.00",
            "staked": "0"
        },
        "SCAMTOKEN": {
            "available": "1000",
            "locked": "0",
            "staked": "0"
        }
    }
    
    # Add token to global exclusion list
    BalanceReader.add_excluded_token("SCAMTOKEN")
    
    # Create balance reader (SCAMTOKEN will be filtered out)
    balances = BalanceReader(sample_data)
    
    print("=== Balance Reader Example ===\n")
    
    # Print summary (won't include SCAMTOKEN)
    print(balances.summary())
    print()
    
    # Check specific balances
    print("BTC available balance:", balances.get_available_balance("BTC"))
    print("BTC total balance:", balances.get_total_balance("BTC"))
    print("USDC locked balance:", balances.get_locked_balance("USDC"))
    print()
    
    # Check if has balance
    print("Has BTC balance:", balances.has_balance("BTC"))
    print("Has ETH balance:", balances.has_balance("ETH"))
    print("Has available USDC > 1000:", balances.has_available_balance("USDC", "1000"))
    print()
    
    # Get non-zero balances
    print("Assets with balance:")
    for symbol in balances.get_non_zero_balances():
        print(f"  {symbol}: {balances[symbol]}")
    print()
    
    # Available assets only
    print("Assets with available balance:")
    for symbol, balance in balances.get_available_assets().items():
        print(f"  {symbol}: Available = {balance.available}")
    print()
    
    # Convert back to dict/JSON (filtered)
    print("=== Convert back to JSON (filtered) ===")
    print(balances.to_json())

if __name__ == "__main__":
    example_usage()