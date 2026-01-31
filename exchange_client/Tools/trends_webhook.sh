curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "SOL_USDC",
      "timeframe": "15",
      "ema20": 115.380927,
      "ema50": 114.587824,
      "rsi": 51.82,
      "vwap": 114.551973,
      "price": 115.46,
      "volume":  424.513,
      "volume_sma": 5446.4477,
      "volume_ratio": 0.078,
      "indicators_changed":"true",
      "ema20_changed":"false",
      "ema50_changed":"false",
      "rsi_changed":"false"
    },{
      "symbol": "SOL_USDC",
      "timeframe": "60",
      "ema20": 114.380927,
      "ema50": 113.587824,
      "rsi": 55.82,
      "vwap": 114.551973,
      "price": 112.46,
      "volume":  424.513,
      "volume_sma": 5446.4477,
      "volume_ratio": 0.078,
      "indicators_changed":"true",
      "ema20_changed":"false",
      "ema50_changed":"false",
      "rsi_changed":"false"
    }]
  }'
