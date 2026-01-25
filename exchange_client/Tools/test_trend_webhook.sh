curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "SOL_USDC",
      "timeframe": "15",
      "ema20": 125.43,
      "ema50": 124.91,
      "rsi": 45.6,
      "vwap": 122.68,
      "price": 125.39,
      "volume":  1122,
      "volume_sma": 1122,
      "volume_ratio": 1.0
    }]
  }'
