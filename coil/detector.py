import pandas as pd
import numpy as np
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
import os

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

def detect_coil(symbol: str, data_client=None):
    """
    Detect Bollinger Squeeze (coil pattern) on crypto
    Returns: (is_coil: bool, data: dict)
    """
    try:
        # Use provided client or create new one
        if data_client is None:
            data_client = CryptoHistoricalDataClient(
                os.getenv('ALPACA_API_KEY'),
                os.getenv('ALPACA_SECRET_KEY')
            )
        
        # Get recent bars (15-min timeframe)
        req = CryptoBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame(15, TimeFrameUnit.Minute),
            limit=50
        )
        
        bars = data_client.get_crypto_bars(req).df
        
        if bars.empty or len(bars) < 30:
            return False, {
                'symbol': symbol,
                'error': 'Insufficient data',
                'bars_received': len(bars)
            }
        
        # Reset index if multi-index
        if isinstance(bars.index, pd.MultiIndex):
            df = bars.reset_index(level='symbol', drop=True)
        else:
            df = bars.copy()
        
        # Calculate indicators
        df = calculate_bollinger_bands(df)
        df = calculate_atr(df)
        
        # EMAs for trend
        df['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema_26'] = df['close'].ewm(span=26, adjust=False).mean()
        
        # Volume analysis
        df['volume_sma'] = df['volume'].rolling(20).mean()
        
        # Get latest values
        latest = df.iloc[-1]
        
        # Coil detection metrics
        bandwidth = (latest['bb_upper'] - latest['bb_lower']) / latest['bb_middle']
        atr_current = latest['atr']
        atr_mean = df['atr'].rolling(20).mean().iloc[-1]
        volume_current = latest['volume']
        volume_mean = latest['volume_sma']
        
        # Logic checks
        coil_squeeze = bandwidth < 0.08  # Bollinger squeeze < 8%
        atr_low = atr_current < atr_mean  # ATR below average
        volume_dry = volume_current < (volume_mean * 0.5)  # Volume < 50% avg
        bullish = latest['ema_12'] > latest['ema_26']
        
        is_coil = coil_squeeze and atr_low and volume_dry
        
        # Build response data (ALWAYS returned, even if no coil)
        data = {
            'symbol': symbol,
            'coil_detected': bool(is_coil),
            'current_price': float(latest['close']),
            'bandwidth': float(bandwidth),
            'bandwidth_threshold': 0.08,
            'atr': float(atr_current),
            'atr_average': float(atr_mean),
            'atr_low': bool(atr_low),
            'volume': float(volume_current),
            'volume_average': float(volume_mean),
            'volume_dry': bool(volume_dry),
            'trend': 'bullish' if bullish else 'bearish',
            'bb_upper': float(latest['bb_upper']),
            'bb_lower': float(latest['bb_lower']),
            'timestamp': str(df.index[-1])
        }
        
        # Debug print (shows in Railway logs)
        print(f"{symbol}: Bandwidth={bandwidth:.4f}, "
              f"ATR_low={atr_low}, Vol_dry={volume_dry}, "
              f"Trend={'Bull' if bullish else 'Bear'}, "
              f"COIL={is_coil}")
        
        return is_coil, data
        
    except Exception as e:
        error_msg = str(e)
        print(f"Error detecting coil for {symbol}: {error_msg}")
        
        # Return partial data with error info
        return False, {
            'symbol': symbol,
            'coil_detected': False,
            'error': error_msg,
            'current_price': None,
            'bandwidth': None
        }
