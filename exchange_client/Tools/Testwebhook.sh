
curl -H 'Content-Type: application/json' \
     -d '{"symbol": "HYPE_USDC", "action": "buy", "notprice": "23.00", "quantitay": "0.01","secret":"h&ppyfestivu$", "profile":"default"}' \
     -X POST http://127.0.0.1:8000/webhook/tradingview
    

