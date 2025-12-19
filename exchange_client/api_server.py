# api_server.py
from fastapi import FastAPI
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price

app = FastAPI()

@app.get("/price/{symbol}")
def price_endpoint(symbol: str):
    try:
        price = get_price(symbol)
        return {"symbol": symbol, "price": price}
    except Exception as e:
        return {"error": str(e)}, 500

@app.post("/trade")
def trade_endpoint(symbol: str, amount: float, side: str):
    try:
        #result = execute_trade(symbol, amount, side)
        #return {"status": "success", "result": result}
        return {"Testing":"true"}
    
    except Exception as e:
        return {"error": str(e)}, 500

