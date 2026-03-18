from fastapi import FastAPI, BackgroundTasks
from alpaca.trading.client import TradingClient
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
import os
from datetime import datetime

app = FastAPI()

# Environment variables
ALPACA_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_SECRET = os.getenv('ALPACA_SECRET_KEY')
PAPER = os.getenv('PAPER_TRADING', 'true').lower() == 'true'

# Initialize clients
trade_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=PAPER)

@app.get("/health")
def health():
    return {
        "status": "coil_bot_active",
        "paper": PAPER,
        "assets": ["BTC/USD", "ETH/USD"],
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/")
def root():
    return {"message": "Crypto Coil Bot Running", "version": "1.0"}
