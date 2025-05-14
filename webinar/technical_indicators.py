import pandas as pd
import numpy as np

class TechnicalIndicators:
    """
    A class for calculating common technical indicators: MACD, MACD divergence, and Stochastic RSI.
    All methods are static and operate on pandas DataFrames.
    """

    @staticmethod
    def calculate_macd(df, close_col='close', fast=12, slow=26, signal=9):
        """
        Calculate MACD line, Signal line, and MACD divergence (histogram).
        Returns a DataFrame with columns: 'MACD', 'Signal', 'Divergence'.
        """
        exp1 = df[close_col].ewm(span=fast, adjust=False).mean()
        exp2 = df[close_col].ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        divergence = macd - signal_line
        result = df.copy()
        result['MACD'] = macd
        result['Signal'] = signal_line
        result['Divergence'] = divergence
        return result[['MACD', 'Signal', 'Divergence']]

    @staticmethod
    def calculate_stochastic_rsi(df, close_col='close', rsi_period=14, stoch_period=14, smooth_k=3, smooth_d=3):
        """
        Calculate Stochastic RSI (StochRSI), %K and %D lines.
        Returns a DataFrame with columns: 'StochRSI', '%K', '%D'.
        """
        delta = df[close_col].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        min_rsi = rsi.rolling(window=stoch_period).min()
        max_rsi = rsi.rolling(window=stoch_period).max()
        stoch_rsi = (rsi - min_rsi) / (max_rsi - min_rsi)
        k = stoch_rsi.rolling(window=smooth_k).mean()
        d = k.rolling(window=smooth_d).mean()
        result = df.copy()
        result['StochRSI'] = stoch_rsi
        result['%K'] = k
        result['%D'] = d
        return result[['StochRSI', '%K', '%D']]

    @staticmethod
    def calculate_pivots(df, high_col='high', low_col='low', close_col='close'):
        """Calculate classic pivot, support, and resistance levels for each row."""
        pivots = pd.DataFrame(index=df.index)
        pivots['pivot'] = (df[high_col] + df[low_col] + df[close_col]) / 3
        pivots['r1'] = 2 * pivots['pivot'] - df[low_col]
        pivots['s1'] = 2 * pivots['pivot'] - df[high_col]
        pivots['r2'] = pivots['pivot'] + (df[high_col] - df[low_col])
        pivots['s2'] = pivots['pivot'] - (df[high_col] - df[low_col])
        pivots['r3'] = pivots['pivot'] + 2 * (df[high_col] - df[low_col])
        pivots['s3'] = pivots['pivot'] - 2 * (df[high_col] - df[low_col])
        return pivots

    @staticmethod
    def calculate_fibonacci_pivots(df, high_col='high', low_col='low', close_col='close'):
        """Calculate Fibonacci pivot, support, and resistance levels for each row."""
        pivots = pd.DataFrame(index=df.index)
        pivots['pivot'] = (df[high_col] + df[low_col] + df[close_col]) / 3
        range_ = df[high_col] - df[low_col]
        pivots['r1'] = pivots['pivot'] + 0.382 * range_
        pivots['r2'] = pivots['pivot'] + 0.618 * range_
        pivots['r3'] = pivots['pivot'] + 1.000 * range_
        pivots['s1'] = pivots['pivot'] - 0.382 * range_
        pivots['s2'] = pivots['pivot'] - 0.618 * range_
        pivots['s3'] = pivots['pivot'] - 1.000 * range_
        return pivots
        
    @staticmethod
    def calculate_ema(df, close_col='close', periods=[50, 200]):
        """
        Calculate Exponential Moving Averages for multiple periods.
        Returns a DataFrame with columns: 'EMA_{period}' for each period.
        """
        result = df.copy()
        for period in periods:
            result[f'EMA_{period}'] = df[close_col].ewm(span=period, adjust=False).mean()
        return result[[f'EMA_{period}' for period in periods]]
    
    @staticmethod
    def detect_ema_crossover(df, fast_ema='EMA_50', slow_ema='EMA_200'):
        """
        Detect EMA crossovers.
        Returns a DataFrame with columns: 'EMA_Trend', 'EMA_Crossover'.
        EMA_Trend: 1 for bullish (fast > slow), -1 for bearish (fast < slow)
        EMA_Crossover: 1 for bullish crossover, -1 for bearish crossover, 0 for no crossover
        """
        result = df.copy()
        # Determine trend
        result['EMA_Trend'] = np.where(df[fast_ema] > df[slow_ema], 1, -1)
        # Detect crossovers
        result['EMA_Crossover'] = result['EMA_Trend'].diff()
        # Convert to 1, -1, 0
        result['EMA_Crossover'] = result['EMA_Crossover'].fillna(0)
        result['EMA_Crossover'] = np.where(result['EMA_Crossover'] > 0, 1, 
                                  np.where(result['EMA_Crossover'] < 0, -1, 0))
        return result[['EMA_Trend', 'EMA_Crossover']]
    
    @staticmethod
    def calculate_atr(df, high_col='high', low_col='low', close_col='close', period=14):
        """
        Calculate Average True Range (ATR).
        Returns a DataFrame with column: 'ATR'.
        """
        result = df.copy()
        high = df[high_col]
        low = df[low_col]
        close = df[close_col]
        
        # Calculate True Range
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Calculate ATR
        result['ATR'] = tr.rolling(window=period).mean()
        return result[['ATR']]
    
    @staticmethod
    def calculate_price_action_signals(df, high_col='high', low_col='low', close_col='close', open_col='open'):
        """
        Generate price action signals based on candlestick patterns.
        Returns a DataFrame with columns: 'Engulfing', 'Hammer', 'Doji'.
        Values: 1 for bullish signal, -1 for bearish signal, 0 for no signal.
        """
        result = df.copy()
        high = df[high_col]
        low = df[low_col]
        close = df[close_col]
        open_ = df[open_col]
        
        # Body size
        body_size = abs(close - open_)
        avg_body = body_size.rolling(window=10).mean()
        
        # Engulfing pattern
        prev_body = body_size.shift()
        prev_close = close.shift()
        prev_open = open_.shift()
        
        bullish_engulfing = (
            (close > open_) &  # Current candle is bullish
            (prev_close < prev_open) &  # Previous candle is bearish
            (close > prev_open) &  # Current close above previous open
            (open_ < prev_close) &  # Current open below previous close
            (body_size > prev_body)  # Current body larger than previous
        )
        
        bearish_engulfing = (
            (close < open_) &  # Current candle is bearish
            (prev_close > prev_open) &  # Previous candle is bullish
            (close < prev_open) &  # Current close below previous open
            (open_ > prev_close) &  # Current open above previous close
            (body_size > prev_body)  # Current body larger than previous
        )
        
        result['Engulfing'] = np.where(bullish_engulfing, 1, np.where(bearish_engulfing, -1, 0))
        
        # Hammer/Shooting Star
        upper_shadow = high - np.maximum(open_, close)
        lower_shadow = np.minimum(open_, close) - low
        
        hammer = (
            (lower_shadow > 2 * body_size) &  # Long lower shadow
            (upper_shadow < 0.5 * body_size) &  # Short upper shadow
            (body_size < avg_body)  # Small body
        )
        
        shooting_star = (
            (upper_shadow > 2 * body_size) &  # Long upper shadow
            (lower_shadow < 0.5 * body_size) &  # Short lower shadow
            (body_size < avg_body)  # Small body
        )
        
        result['Hammer'] = np.where(hammer & (close > open_), 1, 
                          np.where(shooting_star & (close < open_), -1, 0))
        
        # Doji
        doji = body_size < (0.1 * (high - low))
        result['Doji'] = np.where(doji, 1, 0)  # Doji is neutral, just mark its presence
        
        return result[['Engulfing', 'Hammer', 'Doji']]