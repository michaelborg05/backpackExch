curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "SOL_USDC",
      "timeframe": "1h",
      "ema20": 142.50,
      "ema50": 141.20,
      "rsi": 58.5,
      "vwap": 140.90,
      "price": 142.80
    }]
  }'
