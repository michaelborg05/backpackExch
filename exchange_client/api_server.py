# api_server.py
from http.client import HTTPException
from fastapi import FastAPI
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price
from models.trade import MarketOrderRequest
from api_builders.trading_builder import TradingService

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/price/{symbol}")
def price_endpoint(symbol: str):
    try:
        price = get_price(symbol)
        return {"symbol": symbol, "price": price}
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/balances")
def balance_endpoint():
    """Get account balances"""
    try:
        balances = get_balances()
        return {
            asset: {
                "available": balance.available,
                "locked": balance.locked,
                "staked": balance.staked
            }
            for asset, balance in balances.items()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
@app.post("/order/market")
def place_market_order(
    request: MarketOrderRequest
):
    trading: TradingService = TradingService()  

    """Place a market order"""
    try:
        if request.side.lower() == "buy":
            result = trading.market_buy(request.symbol, request.quantity)
        elif request.side.lower() == "sell":
            
            result = trading.market_sell(request.symbol, request.quantity)
        else:
            raise HTTPException(status_code=400, detail="Side must be 'buy' or 'sell'")
        
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
