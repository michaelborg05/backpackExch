
curl -H 'Content-Type: application/json' \
     -d '{"symbol": "ETH_USDC", "action": "buy", "notprice": "23.00", "quantity": "0.01","secret":"h&ppyfestivu$", "profile":"15m_MB"}' \
     -X POST http://127.0.0.1:8000/webhook/tradingview
    

