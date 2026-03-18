import pandas as pd
import pandas_ta as ta

def detect_coil(symbol: str, data_client) -> bool:
    """Crypto-specific coil detection (tighter than forex)"""
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame
    
    # Get 50 recent 15-min bars (crypto scalping timeframe)
    req = CryptoBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),  # 15-min for crypto
        limit=50
    )
    
    bars = data_client.get_crypto_bars(req).df
    df = bars.reset_index(level='symbol', drop=True)
    
    # Bollinger Bands (tighter period for crypto)
    df.ta.bbands(length=20, std=2.0, append=True)
    
    # ATR (volatility compression)
    df.ta.atr(length=14, append=True)
    
    # EMAs (faster for crypto momentum)
    df["ema_12"] = df["close"].ewm(span=12, adjust=False).mean()
    df["ema_26"] = df["close"].ewm(span=26, adjust=False).mean()
    
    # Volume analysis (key for crypto fakeout prevention)
    df["volume_sma"] = df["volume"].rolling(20).mean()
    
    # Latest values
    latest = df.iloc[-1]
    bandwidth = (latest['BBU_20_2.0'] - latest['BBL_20_2.0']) / latest['BBM_20_2.0']
    atr = latest['ATRr_14']
    atr_mean = df['ATRr_14'].rolling(20).mean().iloc[-1]
    volume_dry = latest['volume'] < (latest['volume_sma'] * 0.5)  # 50% below average
    
    # Coil conditions (stricter than forex)
    coil_forming = (bandwidth < 0.08) and (atr < atr_mean) and volume_dry
    
    # Trend bias
    bullish = latest['ema_12'] > latest['ema_26']
    
    return coil_forming, bullish
