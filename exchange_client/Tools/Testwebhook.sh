
curl -H 'Content-Type: application/json' \
     -d '{"symbol": "SOL_USDC", "action": "buy", "notprice": "23.00", "quantity": "0.1","secret":"h&ppyfestivu$", "profile":"15m_MB"}' \
     -X POST http://127.0.0.1:8000/webhook/tradingview
    

