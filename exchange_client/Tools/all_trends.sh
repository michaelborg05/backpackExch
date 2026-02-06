curl -X POST http://localhost:8000/webhook/tradingview/trend \
  -H "Content-Type: application/json" \
  -d '{
    "action": "trend_update",
    "secret": "h&ppyfestivu$",
    "trends": [{"symbol":"SUI_USDC","timeframe":"240","price":1.0617,"rsi":33.47,"ema20":1.124838,"ema50":1.209966,"vwap":1.070633,"volume_ratio":1.399,"indicators_changed":true,"timestamp":1770264182.9188743},
{"symbol":"SUI_USDC","timeframe":"240","price":1.0429,"rsi":30.93,"ema20":1.116901,"ema50":1.203359,"vwap":1.061284,"volume_ratio":1.032,"indicators_changed":true,"timestamp":1770278583.71135},
{"symbol":"SUI_USDC","timeframe":"240","price":1.0096,"rsi":27.19,"ema20":1.106472,"ema50":1.195675,"vwap":1.047239,"volume_ratio":1.13,"indicators_changed":true,"timestamp":1770292982.5261505},
{"symbol":"SUI_USDC","timeframe":"240","price":0.9567,"rsi":22.9,"ema20":1.092351,"ema50":1.186362,"vwap":1.011518,"volume_ratio":2.782,"indicators_changed":true,"timestamp":1770307385.719345},
{"symbol":"SUI_USDC","timeframe":"60","price":0.9418,"rsi":16.42,"ema20":1.017745,"ema50":1.062511,"vwap":1.002928,"volume_ratio":2.072,"indicators_changed":true,"timestamp":1770314583.6647506},
{"symbol":"SUI_USDC","timeframe":"60","price":0.9402,"rsi":21.56,"ema20":1.011093,"ema50":1.058016,"vwap":0.997084,"volume_ratio":1.793,"indicators_changed":true,"timestamp":1770318182.0216565},
{"symbol":"SUI_USDC","timeframe":"60","price":0.9244,"rsi":18.19,"ema20":1.002646,"ema50":1.052698,"vwap":0.992484,"volume_ratio":1.245,"indicators_changed":true,"timestamp":1770321782.1874156},
{"symbol":"SUI_USDC","timeframe":"240","price":0.9244,"rsi":20.37,"ema20":1.076165,"ema50":1.17601,"vwap":0.985048,"volume_ratio":2.982,"indicators_changed":true,"timestamp":1770321783.133332},
{"symbol":"SUI_USDC","timeframe":"60","price":0.9061,"rsi":15.12,"ema20":0.99208,"ema50":1.046384,"vwap":0.980553,"volume_ratio":2.388,"indicators_changed":true,"timestamp":1770325381.523515},
{"symbol":"SUI_USDC","timeframe":"15","price":0.8998,"rsi":36.73,"ema20":0.924911,"ema50":0.962231,"vwap":0.977129,"volume_ratio":0.705,"indicators_changed":true,"timestamp":1770328082.7150958},
{"symbol":"SUI_USDC","timeframe":"15","price":0.893,"rsi":35.82,"ema20":0.921929,"ema50":0.95954,"vwap":0.975841,"volume_ratio":0.805,"indicators_changed":true,"timestamp":1770328981.5605106},
{"symbol":"SUI_USDC","timeframe":"60","price":0.893,"rsi":16.06,"ema20":0.982701,"ema50":1.040393,"vwap":0.975639,"volume_ratio":1.607,"indicators_changed":true,"timestamp":1770328982.5089808},
{"symbol":"SUI_USDC","timeframe":"15","price":0.8807,"rsi":37.17,"ema20":0.919507,"ema50":0.957067,"vwap":0.974701,"volume_ratio":0.815,"indicators_changed":true,"timestamp":1770329880.5736504},
{"symbol":"SUI_USDC","timeframe":"15","price":0.8991,"rsi":41.34,"ema20":0.918183,"ema50":0.955049,"vwap":0.972949,"volume_ratio":1.195,"indicators_changed":true,"timestamp":1770330781.5622232},
{"symbol":"SUI_USDC","timeframe":"15","price":0.8966,"rsi":39.01,"ema20":0.916261,"ema50":0.952812,"vwap":0.972276,"volume_ratio":0.63,"indicators_changed":true,"timestamp":1770331682.8303964}
]
  }'
