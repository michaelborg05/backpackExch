curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "HYPE_USDC",
      "timeframe": "15",
      "ema20": 30.891593,
      "ema50": 30.547287,
      "rsi": 46.32,
      "vwap": 29.91522,
      "price": 30.63,
      "volume":  19200.513,
      "volume_sma": 42436.4477,
      "volume_ratio": 0.452,
      "indicators_changed":"true",
      "ema20_changed":"false",
      "ema50_changed":"false",
      "rsi_changed":"false"
    }]
  }'
