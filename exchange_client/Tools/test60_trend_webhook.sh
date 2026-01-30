curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "SOL_USDC",
      "timeframe": "60",
      "ema20": 117.969778,
      "ema50": 114.010756,
      "rsi": 52.58,
      "vwap": 114.8109,
      "price": 115.49,
      "volume":  4347.027,
      "volume_sma": 13942.0334,
      "volume_ratio": 0.312,
      "indicators_changed":"true",
      "ema20_changed":"false",
      "ema50_changed":"false",
      "rsi_changed":"false"
    }]
  }'
