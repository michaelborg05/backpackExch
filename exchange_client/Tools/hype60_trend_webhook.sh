curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "HYPE_USDC",
      "timeframe": "60",
      "ema20": 30.4978,
      "ema50": 30.740756,
      "rsi": 54.95,
      "vwap": 29.93409,
      "price": 30.64,
      "volume":  61790.027,
      "volume_sma": 154940.0334,
      "volume_ratio": 0.399,
      "indicators_changed":"true",
      "ema20_changed":"false",
      "ema50_changed":"false",
      "rsi_changed":"false"
    }]
  }'
