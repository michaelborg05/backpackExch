
curl -H 'Content-Type: application/json' \
     -d '{"symbol": "MON_USDC", "action": "buy", "notprice": "23.00", "quantity": "2300","secret":"h&ppyfestivu$", "profile":"1hr_MB"}' \
     -X POST http://127.0.0.1:8000/webhook/tradingview
    

