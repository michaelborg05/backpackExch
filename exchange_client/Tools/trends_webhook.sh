curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{
      "symbol": "SOL_USDC",
      "timeframe": "15",
      "ema20": 103.380927,
      "ema50": 102.587824,
      "rsi": 53.82,
      "vwap": 103.551973,
      "price": 105.46,
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
      "ema20": 102.380927,
      "ema50": 101.587824,
      "rsi": 55.82,
      "vwap": 101.551973,
      "price": 105.46,
      "volume":  424.513,
      "volume_sma": 5446.4477,
      "volume_ratio": 0.078,
      "indicators_changed":"true",
      "ema20_changed":"false",
      "ema50_changed":"false",
      "rsi_changed":"false"
    },{
      "symbol": "SOL_USDC",
      "timeframe": "240",
      "ema20": 103.380927,
      "ema50": 102.587824,
      "rsi": 56.82,
      "vwap": 103.551973,
      "price": 105.46,
      "volume":  424.513,
      "volume_sma": 5446.4477,
      "volume_ratio": 0.078,
      "indicators_changed":"true",
      "ema20_changed":"false",
      "ema50_changed":"false",
      "rsi_changed":"false"}
]
  }'
