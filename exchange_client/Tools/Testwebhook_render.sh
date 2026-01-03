
curl -H 'Content-Type: application/json' \
     -d '{"symbol": "MON_USDC", "action": "buy", "notprice": "23.00", "quantity": "200","secret":"h&ppyfestivu$", "profile":"default", "take_profit":"2"}' \
     -X POST https://borgy-trading.onrender.com/webhook/tradingview
    

