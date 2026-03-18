from fastapi import FastAPI, BackgroundTasks, HTTPException
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
import os
from datetime import datetime
from coil.detector import detect_coil

app = FastAPI()

# Environment setup
ALPACA_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_SECRET = os.getenv('ALPACA_SECRET_KEY')
PAPER = os.getenv('PAPER_TRADING', 'true').lower() == 'true'

# Initialize clients
trade_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=PAPER)
data_client = CryptoHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)

@app.get("/")
def root():
    return {
        "message": "Crypto Coil Bot Running",
        "version": "1.0",
        "paper_trading": PAPER,
        "endpoints": ["/health", "/scan", "/test-scan", "/execute"]
    }

@app.get("/health")
def health():
    return {
        "status": "coil_bot_active",
        "paper": PAPER,
        "assets": ["BTC/USD", "ETH/USD"],
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/test-scan")
def test_scan():
    """GET endpoint for easy browser testing - checks BTC only"""
    try:
        is_coil, data = detect_coil("BTC/USD", data_client)
        return {
            "symbol": "BTC/USD",
            "coil_detected": is_coil,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "symbol": "BTC/USD"}

@app.post("/scan")
def scan_coils():
    """POST endpoint - full scan of all symbols"""
    symbols = ["BTC/USD", "ETH/USD"]
    signals = []
    
    for symbol in symbols:
        try:
            is_coil, data = detect_coil(symbol, data_client)
            if is_coil:
                signals.append({
                    "symbol": symbol,
                    "action": "coil_detected",
                    "data": data,
                    "timestamp": datetime.utcnow().isoformat()
                })
        except Exception as e:
            print(f"Error scanning {symbol}: {e}")
    
    return {
        "signals": signals,
        "count": len(signals),
        "scanned": symbols,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/execute")
def execute_trade(symbol: str, direction: str, notional: float = 250.0):
    """Execute a trade on Alpaca"""
    try:
        # Risk guard - check daily loss
        # TODO: Implement daily P&L check from database
        
        side = OrderSide.BUY if direction == "long" else OrderSide.SELL
        
        order = MarketOrderRequest(
            symbol=symbol,
            notional=notional,
            side=side,
            time_in_force=TimeInForce.GTC
        )
        
        result = trade_client.submit_order(order)
        
        return {
            "success": True,
            "order_id": result.id,
            "symbol": symbol,
            "side": direction,
            "notional": notional,
            "status": result.status,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
