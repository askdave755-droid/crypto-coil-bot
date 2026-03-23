from fastapi import FastAPI, HTTPException
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
import os
from datetime import datetime, timedelta
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# ========== SAFE INITIALIZATION ==========
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

# ========== STATE TRACKING ==========
class SafeState:
    def __init__(self):
        self.scan_count = 0
        self.last_scan = None
        self.coils_found = 0
        self.errors = 0
        
    def reset(self):
        self.scan_count = 0
        self.coils_found = 0

state = SafeState()

# ========== SAFE DETECTOR WRAPPER ==========
def safe_detect_coil(symbol):
    """Wrapper that never crashes"""
    try:
        if data_client is None:
            return False, {"error": "API not initialized"}
        
        from coil.detector import detect_coil
        return detect_coil(symbol, data_client)
    except Exception as e:
        logger.error(f"Detector error for {symbol}: {e}")
        state.errors += 1
        return False, {"error": str(e)}

# ========== AUTO-SCANNER ==========
def run_auto_scan():
    """Safe auto-scan that catches all errors"""
    try:
        logger.info(f"Starting auto-scan #{state.scan_count + 1}")
        state.last_scan = datetime.utcnow()
        
        for symbol in ["BTC/USD", "ETH/USD"]:
            try:
                is_coil, data = safe_detect_coil(symbol)
                
                if is_coil:
                    state.coils_found += 1
                    logger.info(f"🚨 COIL: {symbol} at ${data.get('current_price')}")
                else:
                    logger.info(f"{symbol}: No coil (bandwidth: {data.get('bandwidth', 'N/A')})")
                    
            except Exception as e:
                logger.error(f"Scan error {symbol}: {e}")
        
        state.scan_count += 1
        logger.info(f"Scan complete. Total: {state.scan_count}")
        
    except Exception as e:
        logger.error(f"Auto-scan crash: {e}")
        state.errors += 1

# ========== START SCHEDULER SAFELY ==========
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    import atexit
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_auto_scan, 
        'interval', 
        minutes=15,
        id='crypto_scanner',
        replace_existing=True
    )
    scheduler.start()
    logger.info("Scheduler started - scanning every 15 min")
    
    # Cleanup on exit
    atexit.register(lambda: scheduler.shutdown())
    
except Exception as e:
    logger.error(f"Scheduler failed: {e}")
    scheduler = None

# ========== API ENDPOINTS ==========
@app.get("/debug")
def debug():
    """See which account we're connected to"""
    try:
        acc = trade_client.get_account()
        return {
            "account_id": acc.id,
            "cash": float(acc.cash),
            "buying_power": float(acc.buying_power),
            "target_account": "PA3D1GO63T5L"
        }
    except Exception as e:
        return {"error": str(e)}
    }

@app.get("/health")
def health():
    next_scan = None
    if state.last_scan:
        next_scan = (state.last_scan + timedelta(minutes=15)).isoformat()
    
    return {
        "status": "running",
        "scheduler_active": scheduler is not None,
        "api_connected": data_client is not None,
        "paper_trading": PAPER if 'PAPER' in locals() else 'unknown',
        "scans_completed": state.scan_count,
        "coils_detected": state.coils_found,
        "errors": state.errors,
        "next_scan": next_scan,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/status")
def status():
    return {
        "scans": state.scan_count,
        "coils_found": state.coils_found,
        "total_errors": state.errors,
        "last_scan": state.last_scan.isoformat() if state.last_scan else None,
        "api_working": data_client is not None,
        "scheduler_working": scheduler is not None
    }

@app.get("/test")
def test():
    """Quick test without full scan"""
    if data_client is None:
        return {"error": "API not connected", "fix": "Check Railway variables"}
    
    try:
        is_coil, data = safe_detect_coil("BTC/USD")
        return {
            "working": True,
            "coil_detected": is_coil,
            "price": data.get('current_price'),
            "bandwidth": data.get('bandwidth'),
            "error": data.get('error')
        }
    except Exception as e:
        return {"working": False, "error": str(e)}

@app.post("/scan")
def manual_scan():
    """Force a scan now"""
    try:
        run_auto_scan()
        return {
            "success": True,
            "scans_total": state.scan_count,
            "coils_total": state.coils_found,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/trade")
def manual_trade(symbol: str, direction: str, notional: float = 100):
    """Manual trade with safety checks"""
    if trade_client is None:
        raise HTTPException(400, "Trading client not initialized")
    
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
            "order_id": result.id,
            "status": result.status
        }
    except Exception as e:
        raise HTTPException(400, str(e))

# Force first scan on startup
if data_client:
    logger.info("Running initial scan...")
    run_auto_scan()
