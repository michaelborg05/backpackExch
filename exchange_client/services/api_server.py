# api_server.py
from fastapi import FastAPI,HTTPException
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price
from models.trade import OrderRequest
from api_builders.trading_builder import TradingService
from services.monitoring_service import MonitoringService
from pydantic import BaseModel
from typing import Optional
from services.balance_cache import get_balance_cache

app = FastAPI(title="Trading API")

# Global reference to monitoring service (injected from main.py)
_monitoring_service: Optional[MonitoringService] = None

def set_monitoring_service(service: MonitoringService):
    """Set the monitoring service instance (called from main.py)"""
    global _monitoring_service
    _monitoring_service = service

def get_monitoring_service() -> MonitoringService:
    """Get the monitoring service instance"""
    if _monitoring_service is None:
        raise HTTPException(
            status_code=503, 
            detail="Monitoring service not initialized"
        )
    return _monitoring_service

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/monitoring/status")
def get_monitoring_status():
    """Get monitoring service status"""
    service = get_monitoring_service()
    return service.get_status()

class TickerRequest(BaseModel):
    ticker: str

@app.post("/monitoring/add-ticker")
def add_ticker(request: TickerRequest):
    """Add a ticker to monitor"""
    service = get_monitoring_service()
    service.add_ticker(request.ticker)
    return {
        "message": f"Added ticker {request.ticker}",
        "tickers": service.tickers
    }


@app.post("/monitoring/remove-ticker")
def remove_ticker(request: TickerRequest):
    """Remove a ticker from monitoring"""
    service = get_monitoring_service()
    service.remove_ticker(request.ticker)
    return {
        "message": f"Removed ticker {request.ticker}",
        "tickers": service.tickers
    }


@app.post("/monitoring/stop")
def stop_monitoring():
    """Stop the monitoring service"""
    service = get_monitoring_service()
    service.stop()
    return {"message": "Monitoring stopped", "status": service.get_status()}


@app.post("/monitoring/start")
def start_monitoring():
    """Start the monitoring service"""
    service = get_monitoring_service()
    service.start()
    return {"message": "Monitoring started", "status": service.get_status()}

@app.get("/monitoring/tickers")
def get_tickers():
    """Get list of monitored tickers"""
    service = get_monitoring_service()
    return {"tickers": service.tickers}


class UpdateTickersRequest(BaseModel):
    tickers: list[str]


@app.put("/monitoring/tickers")
def update_tickers(request: UpdateTickersRequest):
    """Replace the entire list of monitored tickers"""
    service = get_monitoring_service()
    service.tickers = request.tickers
    return {
        "message": "Tickers updated",
        "tickers": service.tickers
    }

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
    
@app.post("/order")
def place_order(
    request: OrderRequest
):
    trading: TradingService = TradingService()  

    """Place a market order"""
    try:
        if request.side.lower() == "buy":
            result = trading.order_buy(request.symbol, request.quantity)
        elif request.side.lower() == "sell":
            result = trading.order_sell(request.symbol, request.quantity)
        else:
            raise HTTPException(status_code=400, detail="Side must be 'buy' or 'sell'")
        
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/balances/cached")
def get_cached_balances():
    """Get balances from cache (fast, no API call)"""
    cache = get_balance_cache()
    balances = cache.get_all_balances()
    
    if balances is None:
        return {
            "error": "Balance cache is empty or stale",
            "cache_info": cache.get_cache_info()
        }
    
    return {
        "balances": balances,
        "cache_info": cache.get_cache_info()
    }


@app.get("/balances/cached/{asset}")
def get_cached_asset_balance(asset: str):
    """Get balance for specific asset from cache"""
    cache = get_balance_cache()
    balance = cache.get_available_balance(asset)
    
    if balance is None:
        return {
            "error": f"Balance for {asset} not found or cache is stale",
            "cache_info": cache.get_cache_info()
        }
    
    return {
        "asset": asset,
        "available": str(balance),
        "cache_info": cache.get_cache_info()
    }