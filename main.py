from fastapi import FastAPI, HTTPException
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from apscheduler.schedulers.background import BackgroundScheduler
import os
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# ========== CONFIGURATION ==========
try:
    ALPACA_KEY = os.getenv('ALPACA_API_KEY', '')
    ALPACA_SECRET = os.getenv('ALPACA_SECRET_KEY', '')
    PAPER = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
    
    if not ALPACA_KEY or not ALPACA_SECRET:
        logger.error("Missing API keys!")
        trade_client = None
        data_client = None
    else:
        trade_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=PAPER)
        data_client = CryptoHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)
        logger.info("Alpaca clients initialized")
except Exception as e:
    logger.error(f"Init error: {e}")
    trade_client = None
    data_client = None

# ========== STATE ==========
class State:
    def __init__(self):
        self.scan_count = 0
        self.last_scan = None
        self.coils = 0

state = State()

# ========== AUTO SCANNER ==========
def run_scan():
    try:
        logger.info(f"Scan #{state.scan_count + 1} at {datetime.utcnow().strftime('%H:%M')}")
        from coil.detector import detect_coil
        
        for symbol in ["BTC/USD", "ETH/USD"]:
            try:
                is_coil, data = detect_coil(symbol, data_client)
                logger.info(f"{symbol}: Coil={is_coil}, Price=${data.get('current_price', 'N/A')}")
                if is_coil:
                    state.coils += 1
            except Exception as e:
                logger.error(f"Scan error {symbol}: {e}")
        
        state.scan_count += 1
        state.last_scan = datetime.utcnow()
    except Exception as e:
        logger.error(f"Scanner crash: {e}")

# Start scheduler
try:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scan, 'interval', minutes=15)
    scheduler.start()
    logger.info("Scheduler started")
except Exception as e:
    logger.error(f"Scheduler failed: {e}")
    scheduler = None

# ========== ENDPOINTS ==========
@app.get("/")
def root():
    return {
        "bot": "Crypto Coil Bot",
        "status": "running",
        "paper": PAPER,
        "endpoints": ["/health", "/debug", "/trade", "/scan"]
    }

@app.get("/health")
def health():
    return {
        "status": "running",
        "scans": state.scan_count,
        "api_connected": trade_client is not None,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/debug")
def debug():
    """Check account balance and ID"""
    if not trade_client:
        return {"error": "Not connected"}
    try:
        acc = trade_client.get_account()
        return {
            "account_id": acc.id,
            "cash": float(acc.cash),
            "buying_power": float(acc.buying_power),
            "portfolio_value": float(acc.portfolio_value),
            "status": acc.status
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/trade")
def trade_get(symbol: str, direction: str, notional: float = 10):
    """GET method for easy browser testing"""
    return execute_trade(symbol, direction, notional)

@app.post("/trade")
def trade_post(symbol: str, direction: str, notional: float = 10):
    """POST method for proper API calls"""
    return execute_trade(symbol, direction, notional)

def execute_trade(symbol, direction, notional):
    """Execute trade with error handling"""
    if not trade_client:
        return {"error": "Trading not initialized"}
    
    try:
        side = OrderSide.BUY if direction == "long" else OrderSide.SELL
        
        order = MarketOrderRequest(
            symbol=symbol,
            notional=float(notional),
            side=side,
            time_in_force=TimeInForce.GTC
        )
        
        result = trade_client.submit_order(order)
        
        return {
            "success": True,
            "order_id": str(result.id),
            "symbol": symbol,
            "side": direction,
            "notional": notional,
            "status": str(result.status)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/scan")
def manual_scan():
    """Force a scan now"""
    run_scan()
    return {
        "scans_total": state.scan_count,
        "coils_total": state.coils,
        "timestamp": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
