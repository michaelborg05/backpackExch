
curl -H 'Content-Type: application/json' \
     -d '{"action":"buy","symbol":"SOL_USDC","quoteQuantity":"100","secret":"supersecret"}'\
     -X POST http://127.0.0.1:8000/webhook/tradingview


