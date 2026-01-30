curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "SOL_USDC",
      "timeframe": "15",
      "ema20": 115.380927,
      "ema50": 1116.587824,
      "rsi": 49.82,
      "vwap": 114.551973,
      "price": 115.46,
      "volume":  424.513,
      "volume_sma": 5446.4477,
      "volume_ratio": 0.078,
      "indicators_changed":"true",
      "ema20_changed":"false",
      "ema50_changed":"false",
      "rsi_changed":"false"
    }]
  }'
