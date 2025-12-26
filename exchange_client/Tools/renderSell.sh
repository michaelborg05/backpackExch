
curl -H 'Content-Type: application/json' \
          -d '{"symbol": "SOL_USDC","quantity":"0.1", "side":"SELL"}' \
          -X POST http://127.0.0.1:8000/order \
          -H "X-API-Key: z_SSnfo9ZlQwptr4oIAlW-a72IVP7fRLVQcG2mEHoLU"
