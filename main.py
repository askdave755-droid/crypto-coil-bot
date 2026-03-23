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

# ========== POSITION TRACKER ==========
class PositionTracker:
    def __init__(self):
        self.positions = {}
        self.max_hold_hours = 4
        self.stop_loss_pct = 0.02
        self.take_profit_pct = 0.04
    
    def add_position(self, symbol, side, notional, entry_price):
        self.positions[symbol] = {
            'entry_price': float(entry_price),
            'entry_time': datetime.utcnow(),
            'side': side,
            'notional': float(notional),
            'stop_loss': float(entry_price) * (0.98 if side == 'long' else 1.02),
            'take_profit': float(entry_price) * (1.04 if side == 'long' else 0.96)
        }
        logger.info(f"Tracking {symbol}: SL ${self.positions[symbol]['stop_loss']:.2f} | TP ${self.positions[symbol]['take_profit']:.2f}")
    
    def should_exit(self, symbol, current_price):
        if symbol not in self.positions:
            return False, None
        
        pos = self.positions[symbol]
        side = pos['side']
        entry = pos['entry_price']
        
        if side == 'long':
            pnl_pct = (current_price - entry) / entry
            hit_stop = current_price <= pos['stop_loss']
            hit_target = current_price >= pos['take_profit']
        else:
            pnl_pct = (entry - current_price) / entry
            hit_stop = current_price >= pos['stop_loss']
            hit_target = current_price <= pos['take_profit']
        
        time_held = datetime.utcnow() - pos['entry_time']
        hit_time = time_held > timedelta(hours=self.max_hold_hours)
        
        if hit_stop:
            return True, f"STOP LOSS ({pnl_pct*100:.2f}%)"
        elif hit_target:
            return True, f"TAKE PROFIT ({pnl_pct*100:.2f}%)"
        elif hit_time:
            return True, f"TIME EXIT ({time_held.total_seconds()/3600:.1f}h)"
        
        return False, None
    
    def remove_position(self, symbol):
        if symbol in self.positions:
            del self.positions[symbol]

tracker = PositionTracker()

# ========== SYNC EXISTING POSITIONS ==========
try:
    if trade_client:
        logger.info("Syncing existing positions...")
        for position in trade_client.get_all_positions():
            symbol = position.symbol
            tracker.positions[symbol] = {
                'entry_price': float(position.avg_entry_price),
                'entry_time': datetime.utcnow() - timedelta(hours=1),
                'side': 'long' if float(position.qty) > 0 else 'short',
                'notional': float(position.market_value),
                'stop_loss': float(position.avg_entry_price) * 0.98,
                'take_profit': float(position.avg_entry_price) * 1.04
            }
            logger.info(f"Synced {symbol}: {position.qty} @ ${position.avg_entry_price}")
except Exception as e:
    logger.info(f"No positions to sync: {e}")

# ========== SCANNER STATE ==========
class ScanState:
    def __init__(self):
        self.scan_count = 0
        self.last_scan = None
        self.coils = 0
        self.trades_today = 0

scan_state = ScanState()

# ========== AUTO SCANNER (ENTRY) ==========
def run_scan():
    try:
        logger.info(f"\n🔍 ENTRY SCAN #{scan_state.scan_count + 1}")
        from coil.detector import detect_coil
        
        for symbol in ["BTC/USD", "ETH/USD"]:
            if symbol in tracker.positions:
                logger.info(f"{symbol}: Already holding")
                continue
            
            try:
                is_coil, data = detect_coil(symbol, data_client)
                price = data.get('current_price', 0)
                
                logger.info(f"{symbol}: Coil={is_coil}, Price=${price:.2f}")
                
                if is_coil and price > 0:
                    scan_state.coils += 1
                    direction = 'long' if data.get('trend') == 'bullish' else 'short'
                    
                    # Execute
                    side = OrderSide.BUY if direction == "long" else OrderSide.SELL
                    order = MarketOrderRequest(
                        symbol=symbol,
                        notional=250.0,
                        side=side,
                        time_in_force=TimeInForce.GTC
                    )
                    result = trade_client.submit_order(order)
                    
                    if result:
                        tracker.add_position(symbol, direction, 250.0, price)
                        scan_state.trades_today += 1
                        logger.info(f"🎯 ENTRY: {symbol} {direction} @ ${price:.2f}")
                        
            except Exception as e:
                logger.error(f"Scan error {symbol}: {e}")
        
        scan_state.scan_count += 1
        scan_state.last_scan = datetime.utcnow()
        logger.info(f"Scan complete. Trades today: {scan_state.trades_today}")
        
    except Exception as e:
        logger.error(f"Scanner crash: {e}")

# ========== EXIT MONITOR ==========
def monitor_exits():
    if not trade_client:
        return
    
    try:
        for symbol in list(tracker.positions.keys()):
            try:
                position = trade_client.get_open_position(symbol)
                current_price = float(position.current_price)
                
                should_exit, reason = tracker.should_exit(symbol, current_price)
                
                if should_exit:
                    trade_client.close_position(symbol)
                    tracker.remove_position(symbol)
                    logger.info(f"💰 EXIT: {symbol} | {reason} | Price: ${current_price:.2f}")
                else:
                    entry = tracker.positions[symbol]['entry_price']
                    pnl = ((current_price - entry) / entry) * 100
                    logger.info(f"📈 HOLDING: {symbol} | P&L: {pnl:+.2f}%")
                    
            except Exception as e:
                logger.warning(f"Exit check failed {symbol}: {e}")
                tracker.remove_position(symbol)
    except Exception as e:
        logger.error(f"Exit monitor error: {e}")

# Start schedulers
try:
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scan, 'interval', minutes=15, id='entry')
    scheduler.add_job(monitor_exits, 'interval', minutes=5, id='exit')
    scheduler.start()
    logger.info("🤖 BOT STARTED: Entry (15m) + Exit (5m)")
except Exception as e:
    logger.error(f"Scheduler failed: {e}")
    scheduler = None

# ========== ENDPOINTS ==========
@app.get("/")
def root():
    return {
        "bot": "Crypto Coil Bot v2.0",
        "features": ["Auto-Entry", "Auto-Exit (SL/TP/Time)", "Position Sync"],
        "open_positions": len(tracker.positions),
        "status": "running"
    }

@app.get("/health")
def health():
    return {
        "status": "running",
        "scans": scan_state.scan_count,
        "open_positions": len(tracker.positions),
        "trades_today": scan_state.trades_today,
        "api_connected": trade_client is not None
    }

@app.get("/positions")
def get_positions():
    return {
        "positions": tracker.positions,
        "rules": {
            "stop_loss": f"{tracker.stop_loss_pct*100}%",
            "take_profit": f"{tracker.take_profit_pct*100}%",
            "max_hold": f"{tracker.max_hold_hours}h"
        }
    }

@app.get("/close")
def close_position(symbol: str):
    try:
        trade_client.close_position(symbol)
        tracker.remove_position(symbol)
        return {"success": True, "closed": symbol}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
