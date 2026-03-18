import pandas as pd
import numpy as np
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

def calculate_bollinger_bands(df, length=20, std_dev=2.0):
    """Calculate Bollinger Bands using pure pandas"""
    df['sma'] = df['close'].rolling(window=length).mean()
    df['std'] = df['close'].rolling(window=length).std()
    df['bb_upper'] = df['sma'] + (df['std'] * std_dev)
    df['bb_lower'] = df['sma'] - (df['std'] * std_dev)
    df['bb_middle'] = df['sma']
    return df

def calculate_atr(df, length=14):
    """Calculate Average True Range using pure pandas"""
    df['high_low'] = df['high'] - df['low']
    df['high_close'] = abs(df['high'] - df['close'].shift())
    df['low_close'] = abs(df['low'] - df['close'].shift())
    df['tr'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=length).mean()
    return df

def detect_coil(symbol: str, data_client=None) -> bool:
    """
    Detect Bollinger Squeeze (coil pattern) on crypto
    Returns True if coil detected, False otherwise
    """
    try:
        # Use provided client or create new one
        if data_client is None:
            from alpaca.data.historical.crypto import CryptoHistoricalDataClient
            import os
            data_client = CryptoHistoricalDataClient(
                os.getenv('ALPACA_API_KEY'),
                os.getenv('ALPACA_SECRET_KEY')
            )
        
        # Get recent bars
        req = CryptoBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame(15, TimeFrameUnit.Minute),  # 15-min bars
            limit=50
        )
        
        bars = data_client.get_crypto_bars(req).df
        
        if bars.empty or len(bars) < 30:
            print(f"Insufficient data for {symbol}")
            return False, None
        
        df = bars.reset_index(level='symbol', drop=True) if 'symbol' in bars.index.names else bars
        
        # Calculate indicators
        df = calculate_bollinger_bands(df)
        df = calculate_atr(df)
        
        # EMAs for trend bias
        df['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema_26'] = df['close'].ewm(span=26, adjust=False).mean()
        
        # Volume analysis
        df['volume_sma'] = df['volume'].rolling(20).mean()
        
        # Latest values
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Coil detection (tighter than forex: 8% bandwidth)
        bandwidth = (latest['bb_upper'] - latest['bb_lower']) / latest['bb_middle']
        coil_squeeze = bandwidth < 0.08
        
        # ATR compression
        atr_low = latest['atr'] < df['atr'].rolling(20).mean().iloc[-1]
        
        # Volume drying up (institutions waiting)
        volume_dry = latest['volume'] < (latest['volume_sma'] * 0.5)
        
        # Trend bias
        bullish = latest['ema_12'] > latest['ema_26']
        
        is_coil = coil_squeeze and atr_low and volume_dry
        
        print(f"{symbol}: Bandwidth={bandwidth:.4f}, ATR low={atr_low}, Volume dry={volume_dry}, Bullish={bullish}")
        
        return is_coil, {
            'symbol': symbol,
            'coil_detected': is_coil,
            'bandwidth': float(bandwidth),
            'trend': 'bullish' if bullish else 'bearish',
            'current_price': float(latest['close']),
            'bb_upper': float(latest['bb_upper']),
            'bb_lower': float(latest['bb_lower']),
            'atr': float(latest['atr'])
        }
        
    except Exception as e:
        print(f"Error detecting coil for {symbol}: {str(e)}")
        return False, None
