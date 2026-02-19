curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [
{  "symbol": "SOL_USDC",  "timeframe": "15",  "price": 81.49,  "rsi": 42.7,  "ema20": 81.659266,  "ema50": 81.877174,  "vwap": 81.68228,  "volume_ratio": 1.105,  "indicators_changed": true,  "timestamp": 1771479189.6638288},
{  "symbol": "SOL_USDC",  "timeframe": "15",  "price": 82.44,  "rsi": 44.7,  "ema20": 81.802479,  "ema50": 81.906406,  "vwap": 81.728545,  "volume_ratio": 0.307,  "indicators_changed": true,  "timestamp": 1771482789.656391},
{  "symbol": "SOL_USDC",  "timeframe": "15",  "price": 81.73,  "rsi": 46.07,  "ema20": 83.665051,  "ema50": 81.87101,  "vwap": 83.683199,  "volume_ratio": 0.796,  "indicators_changed": true,  "timestamp": 1771480094.995481},
{  "symbol": "SOL_USDC",  "timeframe": "60",  "price": 81.69,  "rsi": 37.41,  "ema20": 82.419219,  "ema50": 83.638718,  "vwap": 81.702219,  "volume_ratio": 0.58,  "indicators_changed": true,  "timestamp": 1771470196.867685},
{  "symbol": "SOL_USDC",  "timeframe": "60",  "price": 81.9,  "rsi": 41.63,  "ema20": 82.235459,  "ema50": 83.420388,  "vwap": 81.701206,  "volume_ratio": 1.153,  "indicators_changed": true,  "timestamp": 1771480998.7546718},
{  "symbol": "SOL_USDC",  "timeframe": "60",  "price": 81.89,  "rsi": 40.4,  "ema20": 82.357389,  "ema50": 83.565435,  "vwap": 81.711132,  "volume_ratio": 0.429,  "indicators_changed": true,  "timestamp": 1771473810.6922314}
] }'
