curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "SOL_USDC",
      "timeframe": "1h",
      "ema20": 139.26,
      "ema50": 137.97,
      "rsi": 73.3,
      "vwap": 141.57,
      "price": 142.62
    }]
  }'
