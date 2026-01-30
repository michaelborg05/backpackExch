curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "SOL_USDC",
      "timeframe": "15",
      "ema20": 123.43,
      "ema50": 122.91,
      "rsi": 51.6,
      "vwap": 122.68,
      "price": 123.39,
      "volume":  1122,
      "volume_sma": 1122,
      "volume_ratio": 1.0,
      "indicators_changed":"true",
      "ema20_changed":"false",
      "ema50_changed":"false",
      "rsi_changed":"false"
    }]
  }'
