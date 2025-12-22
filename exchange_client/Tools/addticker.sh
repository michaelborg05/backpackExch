curl -H 'Content-Type: application/json' \
          -d '{"ticker": "BTC_USDC"}' \
          -X POST http://127.0.0.1:8000/monitoring/add-ticker
