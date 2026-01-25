#not implemented yet. Need to find  a way to trigger via telegram service to test functions

def test_reentry_check(symbol: str, profile_name: str, timeframe: str):
    """Test if re-entry would be allowed right now"""
    from services.reentry_manager import get_reentry_manager
    from cache.trend_cache import get_trend_cache
    
    reentry_mgr = get_reentry_manager()
    trend_cache = get_trend_cache()
    
    trend = trend_cache.get(symbol, timeframe)
    
    if not trend:
        print(f"No trend data for {symbol} ({timeframe})")
        return
    
    can_enter, reason = reentry_mgr.can_reenter(
        symbol=symbol,
        profile_name=profile_name,
        timeframe=timeframe,
        current_trend=trend
    )
    
    status = "✅ ALLOWED" if can_enter else "❌ BLOCKED"
    print(f"{status}: {reason}")
    print(f"Current RSI: {trend.rsi:.1f}")
    print(f"Price vs EMA20: {((trend.price - trend.ema20) / trend.ema20 * 100):+.2f}%")