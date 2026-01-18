curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "ETH_USDC",
      "timeframe": "60",
      "ema20": 3125.43,
      "ema50": 3114.91,
      "rsi": 45.6,
      "vwap": 3132.68,
      "price": 3114.39,
      "volume":  1122,
      "volume_sma": 1122,
      "volume_ratio": 1.0
    }]
  }'
