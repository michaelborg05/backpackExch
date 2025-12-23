
curl -H 'Content-Type: application/json' \
          -d '{"symbol": "SOL_USDC","quantity":"MAX", "side":"SELL"}' \
          -X POST http://127.0.0.1:8000/order

