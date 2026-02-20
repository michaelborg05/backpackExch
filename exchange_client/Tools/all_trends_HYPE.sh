curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{    "action": "trend_update",    "secret": "h&ppyfestivu$",    "trends": [
{  "symbol": "HYPE_USDC",  "timeframe": "15",  "ema20": 29.351902,  "ema50": 29.157673,  "rsi": 48.13,  "vwap": 29.379959,  "price": 29.3,  "timestamp": 1771569204.1980639,  "volume": 4113.079,  "volume_sma": 8122.2373,  "volume_ratio": 0.506,  "indicators_changed": true,  "change_details": {    "ema20_changed": true,    "ema50_changed": true,    "rsi_changed": true  },  "prev_candle": {    "prev_open": 29.36,    "prev_high": 29.4,    "prev_low": 29.27,    "prev_close": 29.27  },  "bb": {    "bb_lower": 29.26219, "bb_upper": 29.4075,"bb_basis": 29.55281}},
{  "symbol": "HYPE_USDC",  "timeframe": "15",  "ema20": 29.360524,  "ema50": 29.153088,  "rsi": 52.31,  "vwap": 29.381735,  "price": 29.36,  "timestamp": 1771568323.0096455,  "volume": 17260.248,  "volume_sma": 8317.4854,  "volume_ratio": 2.075,  "indicators_changed": true,  "change_details": {    "ema20_changed": false,    "ema50_changed": true,    "rsi_changed": true  },  "prev_candle": {    "prev_open": 29.48,    "prev_high": 29.51,    "prev_low": 29.25,    "prev_close": 29.36  },  "bb": {    "bb_lower": 29.28408,    "bb_upper": 29.415,    "bb_basis": 29.54592  }}
]
  }'
