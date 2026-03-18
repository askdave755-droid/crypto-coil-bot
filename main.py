from fastapi import FastAPI, BackgroundTasks
from alpaca.trading.client import TradingClient
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
import os
from datetime import datetime

app = FastAPI()

# Environment (same pattern as InsureFlowAI Memory ID 10)
ALPACA_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_SECRET = os.getenv('ALPACA_SECRET_KEY')
PAPER = os.getenv('PAPER_TRADING', 'true').lower() == 'true'

# Clients
trade_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=PAPER)
data_client = CryptoHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)

@app.get("/health")
def health():
    return {
        "status": "coil_bot_active",
        "paper": PAPER,
        "assets": ["BTC/USD", "ETH/USD"],
        "daily_pnl": get_today_pnl()  # From your database
    }

@app.post("/scan")
def scan_coils():
    """Detect coil patterns across BTC and ETH"""
    symbols = ["BTC/USD", "ETH/USD"]
    signals = []
    
    for symbol in symbols:
        if detect_coil(symbol):  # Your Bollinger + ATR logic
            signals.append({
                "symbol": symbol,
                "action": "coil_detected",
                "timestamp": datetime.utcnow()
            })
            # Queue for potential entry
            background_tasks.add_task(monitor_breakout, symbol)
    
    return {"signals": signals, "count": len(signals)}

@app.post("/execute")
def execute_trade(symbol: str, direction: str, notional: float = 250.0):
    """Execute with 1.5% risk guard"""
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    
    # Risk guard (like InsureFlowAI state configs)
    if get_today_pnl() <= -0.015:
        return {"blocked": "Daily loss limit hit (1.5%)"}
    
    order = MarketOrderRequest(
        symbol=symbol,
        notional=notional,  # USD amount, not qty (crypto-friendly)
        side=OrderSide.BUY if direction == "long" else OrderSide.SELL,
        time_in_force=TimeInForce.GTC  # Crypto: GTC or IOC only [^45^]
    )
    
    result = trade_client.submit_order(order)
    log_trade_to_db(result)  # Your PostgreSQL logging
    
    return {"order_id": result.id, "status": result.status}
