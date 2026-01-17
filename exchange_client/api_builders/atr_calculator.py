from typing import List, Optional
from decimal import Decimal
from collections import deque
import time
from services.client import api_request
from utils.endpoints import APIEndpoints
from utils.logging import log_manager
from services.atr_cache import ATRData, get_atr_cache
from utils.exceptions import ExchangeAPIError
"""         
        
        # Convert model to dict, excluding None values
        order_data = order.model_dump(by_alias=True, exclude_none=True)
            
        headers=data_converters.build_authorisation_header(
            api_key=self.profile.api_key,
            secret=self.profile.secret,
            query_params={},
            body=order_data,
            instruction="orderExecute",
            window=60000
        )

        try:
            self.trader_logger.info(f"Debug Trade Request: \r\n{order_data}")
            trade = api_request(url, headers,requestType=HttpMethod.POST, body=order_data)
 """
#close': '143.58', 'end': '2026-01-16 12:23:00', 'high': '143.59', 'low': '143.36', 'open': '143.36', 'quoteVolume': '6129.5838', 'start': '2026-01-16 12:22:00', 'trades': '40', 'volume': '42.73'
class Candle:
    """OHLCV candle data"""
    def __init__(self, data: dict):
        self.open = Decimal(str(data['open']))
        self.high = Decimal(str(data['high']))
        self.low = Decimal(str(data['low']))
        self.close = Decimal(str(data['close']))
        self.volume = Decimal(str(data['volume']))
        #self.timestamp = int(data['start'])

    def get_true_range(self, prev_close: Optional[Decimal] = None) -> Decimal:
        """
        Calculate True Range for this candle
        TR = max(high - low, |high - prev_close|, |low - prev_close|)
        """
        if prev_close is None:
            # First candle - just use high - low
            return self.high - self.low
        
        hl = self.high - self.low
        hc = abs(self.high - prev_close)
        lc = abs(self.low - prev_close)
        
        return max(hl, hc, lc)


class ATRCalculator:
    """
    Fetches candle data from Backpack and calculates ATR
    """
    
    def __init__(
        self,
        atr_period: int = 14,
        sma_period: int = 20
    ):
        self.logger = log_manager.get_logger("ATRCalculator")
        self.atr_period = atr_period
        self.sma_period = sma_period
        self.atr_cache = get_atr_cache()
        
        # Keep a rolling window of ATR values for SMA calculation
        # key: "SYMBOL_TIMEFRAME"
        self._atr_history: dict[str, deque] = {}

    def _timeframe_to_seconds(self, timeframe: str) -> int:
        """
        Convert timeframe string to seconds
        
        Args:
            timeframe: e.g., "1m", "5m", "15m", "1h", "4h", "1d"
            
        Returns:
            Number of seconds per candle
        """
        unit = timeframe[-1].lower()
        value = int(timeframe[:-1])
        
        multipliers = {
            'm': 60,           # minutes
            'h': 3600,         # hours
            'd': 86400,        # days
            'w': 604800        # weeks
        }
        
        if unit not in multipliers:
            self.logger.warning(f"Unknown timeframe unit: {unit}, defaulting to 1m")
            return 60
        
        return value * multipliers[unit]
    
    def fetch_candles(
        self, 
        symbol: str, 
        timeframe: str = "1m",
        limit: int = 100
    ) -> List[Candle]:
        """
        Fetch candle data from Backpack
        
        Args:
            symbol: Trading pair (e.g., "SOL_USDC")
            timeframe: Candle interval (1m, 5m, 15m, 1h, etc.)
            limit: Number of candles to fetch
            
        Returns:
            List of Candle objects, oldest first
        """
        try:
            # Calculate start time based on limit and timeframe
            seconds_per_candle = self._timeframe_to_seconds(timeframe)
            current_time = int(time.time())

            # Go back enough time to get 'limit' candles
            # Add a buffer to ensure we get enough data
            lookback = (limit + 5) * seconds_per_candle
            start_time = current_time - lookback
            


            self.logger.debug(
                f"Fetching candles for {symbol} ({timeframe}): "
                f"startTime={start_time}, lookback={lookback:.0f}s"
            )

            url = APIEndpoints.backpack_klines(ticker=symbol, interval=timeframe, startTime=start_time)

            data = api_request(url, timeout=10)

            if data is None:
                self.logger.error(f"No candle data returned for {symbol}")
                return []
            
            # Convert to Candle objects
            candles = [Candle(k) for k in data]
            
            # Backpack might return more than we need, trim to limit
            if len(candles) > limit:
                candles = candles[-limit:]
            
            self.logger.debug(
                f"Fetched {len(candles)} candles for {symbol} ({timeframe})"
            )

            return candles
            
        except ExchangeAPIError as e:
            self.logger.error(f"Exchange API error fetching candles for {symbol}: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching candles: {e}", exc_info=True)
            return []
    
    def calculate_atr(self, candles: List[Candle]) -> Optional[Decimal]:
        """
        Calculate ATR from candles using Wilder's smoothing
        
        Args:
            candles: List of at least atr_period+1 candles
            
        Returns:
            ATR value or None if insufficient data
        """
        if len(candles) < self.atr_period + 1:
            self.logger.warning(
                f"Insufficient candles for ATR: need {self.atr_period + 1}, "
                f"got {len(candles)}"
            )
            return None
        
        # Calculate True Range for each candle
        true_ranges = []
        for i in range(len(candles)):
            prev_close = candles[i-1].close if i > 0 else None
            tr = candles[i].get_true_range(prev_close)
            true_ranges.append(tr)
        
        # Calculate initial ATR (simple average of first N TRs)
        atr = sum(true_ranges[:self.atr_period]) / self.atr_period
        
        # Apply Wilder's smoothing for remaining candles
        # ATR = ((previous ATR * (n-1)) + current TR) / n
        for i in range(self.atr_period, len(true_ranges)):
            atr = ((atr * (self.atr_period - 1)) + true_ranges[i]) / self.atr_period
        
        return atr
    
    def calculate_atr_sma(self, symbol: str, timeframe: str, current_atr: Decimal) -> Decimal:
        """
        Calculate SMA of ATR values
        Maintains a rolling window of ATR values
        
        On first call, uses the current ATR as the SMA (bootstrap)
        Subsequent calls build up history until we have full SMA period
        """
        key = f"{symbol}_{timeframe}"
        
        # Initialize deque if needed
        if key not in self._atr_history:
            self._atr_history[key] = deque(maxlen=self.sma_period)
        
        # Add current ATR to history
        self._atr_history[key].append(current_atr)
        
        # Calculate SMA from available data
        atr_values = list(self._atr_history[key])
        return sum(atr_values) / len(atr_values)
    
    def update_atr(self, symbol: str, timeframe: str = "1m", bootstrap: bool = True) -> Optional[ATRData]:
        """
        Fetch candles, calculate ATR and ATR_SMA, update cache
        
        Args:
            symbol: Trading pair
            timeframe: Candle interval
            bootstrap: If True and no history exists, bootstrap SMA from historical ATRs
            
        Returns:
            ATRData object or None if calculation failed
        """
        try:
            key = f"{symbol}_{timeframe}"
            
            # Check if we need to bootstrap
            needs_bootstrap = (
                bootstrap and 
                (key not in self._atr_history or len(self._atr_history[key]) < self.sma_period)
            )
            
            if needs_bootstrap:
                # Fetch extra candles to bootstrap the SMA
                # Need enough candles to calculate multiple ATRs
                limit = self.atr_period + self.sma_period + 10
                self.logger.info(
                    f"Bootstrapping ATR history for {symbol} ({timeframe}) "
                    f"with {limit} candles"
                )
            else:
                # Normal update - just need enough for one ATR
                limit = self.atr_period + 10
            
            candles = self.fetch_candles(symbol, timeframe, limit)
            
            if not candles:
                return None
            
            # Bootstrap mode: Calculate multiple historical ATRs
            if needs_bootstrap and len(candles) >= self.atr_period + self.sma_period:
                self.logger.debug(f"Calculating {self.sma_period} historical ATRs for bootstrap")
                
                # Calculate ATR for each window
                for i in range(self.sma_period):
                    # Get a window of candles for this ATR calculation
                    window_start = i
                    window_end = i + self.atr_period + 1
                    
                    if window_end > len(candles):
                        break
                    
                    window = candles[window_start:window_end]
                    atr = self.calculate_atr(window)
                    
                    if atr:
                        # Add to history (but don't update cache yet)
                        if key not in self._atr_history:
                            self._atr_history[key] = deque(maxlen=self.sma_period)
                        self._atr_history[key].append(atr)
                
                self.logger.info(
                    f"Bootstrapped {len(self._atr_history.get(key, []))} ATR values for {symbol}"
                )
            
            # Calculate current ATR (using most recent candles)
            atr = self.calculate_atr(candles)
            if atr is None:
                return None
            
            # Calculate ATR SMA (will use bootstrapped history if available)
            atr_sma = self.calculate_atr_sma(symbol, timeframe, atr)
            
            # Create ATR data object
            atr_data = ATRData(
                symbol=symbol,
                timeframe=timeframe,
                atr=atr,
                atr_sma=atr_sma,
                atr_period=self.atr_period,
                sma_period=self.sma_period
            )
            
            # Update cache
            history_count = len(self._atr_history.get(key, []))
            self.atr_cache.update(atr_data, history_count=history_count)
            
            return atr_data
            
        except Exception as e:
            self.logger.error(
                f"Error updating ATR for {symbol} ({timeframe}): {e}",
                exc_info=True
            )
            return None
    
    def update_multiple(
        self, 
        symbols: List[str], 
        timeframe: str = "1m"
    ) -> dict[str, Optional[ATRData]]:
        """
        Update ATR for multiple symbols
        
        Returns:
            Dict of {symbol: ATRData or None}
        """
        results = {}
        for symbol in symbols:
            results[symbol] = self.update_atr(symbol, timeframe)
        return results


# Global instance
_atr_calculator = None


def get_atr_calculator() -> ATRCalculator:
    """Get or create global ATR calculator"""
    global _atr_calculator
    if _atr_calculator is None:
        _atr_calculator = ATRCalculator()
    return _atr_calculator