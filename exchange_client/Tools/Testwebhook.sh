
curl -H 'Content-Type: application/json' \
     -d '{"symbol": "MON_USDC", "action": "sell", "notprice": "23.00", "quantity": "1300","secret":"h&ppyfestivu$"}' \
     -X POST http://127.0.0.1:8000/webhook/tradingview
    

