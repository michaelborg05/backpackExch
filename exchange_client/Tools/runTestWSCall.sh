
curl -H 'Content-Type: application/json' \
          -d '{"symbol": "SOL_USDC","quantity":"0.1", "side":"BUY"}' \
          -X POST http://127.0.0.1:8000/order/market

