"""
Triple Screen Trading Strategy - Relaxed Version
This is a modified version of the original Triple Screen strategy with more flexible entry conditions.
"""

import backtrader as bt
import numpy as np
import pandas as pd
from triple_screen_strategy import TripleScreenStrategy, add_triple_screen_signals

class DonchianChannels(bt.Indicator):
    lines = ('upper', 'lower', 'middle',)
    params = (('period', 20),)

    def __init__(self):
        self.lines.upper = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.lines.lower = bt.indicators.Lowest(self.data.low, period=self.p.period)
        self.lines.middle = (self.lines.upper + self.lines.lower) / 2

class RelaxedTripleScreenStrategy(TripleScreenStrategy):
    """
    Relaxed version of the Triple Screen Trading Strategy with more flexible entry conditions:
    1. Relaxed pattern requirement - doesn't strictly require candlestick patterns
    2. Additional patterns supported
    3. More lenient pattern detection
    4. Alternative confirmation methods
    """
    
    params = (
        ('use_price_action_patterns', True),  # Can be turned off for maximum flexibility
        ('use_volume_confirmation', True),    # Use volume as an additional confirmation
        ('use_momentum_confirmation', True),  # Use momentum indicators for confirmation
        ('use_breakout_confirmation', True),  # Use breakout levels for confirmation
        ('pattern_sensitivity', 0.7),         # Lower values = more lenient pattern detection (0.0-1.0)
        ('min_volume_ratio', 0.8),            # Minimum volume ratio for volume confirmation
        ('momentum_threshold', 0.0),          # Momentum threshold for entry
        ('trail_atr_mult', 1.5),  # Trail at 1.5x ATR
        ('min_trail_distance', 0.5),  # Minimum 0.5% profit before trailing
    )
    
    def __init__(self):
        # Initialize the parent class
        super(RelaxedTripleScreenStrategy, self).__init__()
        
        # Additional indicators for relaxed strategy
        # Momentum indicator (Rate of Change)
        self.roc = bt.indicators.RateOfChange(self.data.close, period=14)
        
        # Breakout indicator (Donchian Channel)
        self.dc = DonchianChannels(self.data, period=20)
        
        # Volume indicators
        self.volume_sma = bt.indicators.SMA(self.data.volume, period=20)
        
        # Additional price patterns
        # These are already handled in the base class or in our custom pattern detection
        
    def next(self):
        super().next()
        
        # ... rest of relaxed strategy logic ...
        
    def should_buy(self):
        """Enhanced buy condition with relaxed requirements"""
        # Get the base class buy signal
        base_signal = super(RelaxedTripleScreenStrategy, self).should_buy()
        
        # If base strategy already gives a buy signal, use it
        if base_signal and not self.p.use_relaxed_rules:
            return True
        
        # Otherwise, check our relaxed conditions
        # 1. Trend must still be bullish (from higher timeframe)
        trend_bullish = self.p.higher_tf_trend > 0
        
        # 2. Check for entry signals with relaxed conditions
        relaxed_entry = False
        
        # Check if we have a confirmed signal from the dataframe
        if hasattr(self.data, 'confirmed_signal') and self.data.confirmed_signal[0] > 0:
            # We have a basic signal, now apply relaxed confirmations
            
            # Condition 1: Price action patterns (if enabled)
            pattern_confirmed = True  # Default to True for maximum relaxation
            if self.p.use_price_action_patterns:
                # Check if any pattern is detected with reduced sensitivity
                pattern_confirmed = self._check_relaxed_patterns()
            
            # Condition 2: Volume confirmation (if enabled)
            volume_confirmed = True  # Default to True
            if self.p.use_volume_confirmation:
                # Check if volume is above average
                volume_confirmed = self.data.volume[0] > self.volume_sma[0] * self.p.min_volume_ratio
            
            # Condition 3: Momentum confirmation (if enabled)
            momentum_confirmed = True  # Default to True
            if self.p.use_momentum_confirmation:
                # Check if momentum is positive
                momentum_confirmed = self.roc[0] > self.p.momentum_threshold
            
            # Condition 4: Breakout confirmation (if enabled)
            breakout_confirmed = True  # Default to True
            if self.p.use_breakout_confirmation:
                # Check if price is breaking out of the upper Donchian channel
                breakout_confirmed = self.data.close[0] > self.dc.lines.middle[0]
            
            # Combine all confirmations - need at least 2 out of 4 to be true for maximum flexibility
            confirmation_count = sum([
                pattern_confirmed,
                volume_confirmed,
                momentum_confirmed,
                breakout_confirmed
            ])
            
            relaxed_entry = confirmation_count >= 2 and trend_bullish
        
        return base_signal or relaxed_entry
    
    def should_sell(self):
        """Enhanced sell condition with relaxed requirements"""
        # For selling, we'll mostly rely on the base strategy's rules
        # as they're primarily based on stop loss, take profit, and trailing stops
        return super(RelaxedTripleScreenStrategy, self).should_sell()
    
    def _check_relaxed_patterns(self):
        """Check for price action patterns with reduced sensitivity"""
        # Get the current and previous candles
        o0, h0, l0, c0 = self.data.open[0], self.data.high[0], self.data.low[0], self.data.close[0]
        o1, h1, l1, c1 = self.data.open[-1], self.data.high[-1], self.data.low[-1], self.data.close[-1]
        o2, h2, l2, c2 = self.data.open[-2], self.data.high[-2], self.data.low[-2], self.data.close[-2]
        
        # Bullish candle
        bullish_candle = c0 > o0
        
        # Relaxed engulfing pattern
        body_size0 = abs(c0 - o0)
        body_size1 = abs(c1 - o1)
        engulfing = bullish_candle and o0 <= c1 and c0 >= o1 and body_size0 > body_size1 * self.p.pattern_sensitivity
        
        # Relaxed hammer pattern
        body_size = abs(c0 - o0)
        lower_wick = min(o0, c0) - l0
        upper_wick = h0 - max(o0, c0)
        hammer = bullish_candle and lower_wick > body_size * 1.5 * self.p.pattern_sensitivity and upper_wick < body_size * 0.5
        
        # Relaxed piercing line
        piercing = bullish_candle and o0 < c1 and c0 > o1 + (c1 - o1) * 0.5 * self.p.pattern_sensitivity and c1 < o1
        
        # Relaxed morning star
        morning_star = (c2 < o2) and (abs(c1 - o1) < abs(c2 - o2) * self.p.pattern_sensitivity) and bullish_candle and c0 > (o2 + c2) / 2
        
        # Relaxed bullish harami
        harami = bullish_candle and o0 > c1 and c0 < o1 and abs(c0 - o0) < abs(c1 - o1) * self.p.pattern_sensitivity
        
        # Additional patterns for the relaxed strategy
        
        # Relaxed three white soldiers
        three_white_soldiers = (
            bullish_candle and 
            self.data.close[-1] > self.data.open[-1] and 
            self.data.close[-2] > self.data.open[-2] and
            self.data.open[0] > self.data.open[-1] * 0.99 and
            self.data.open[-1] > self.data.open[-2] * 0.99 and
            self.data.close[0] > self.data.close[-1] and
            self.data.close[-1] > self.data.close[-2]
        )
        
        # Relaxed bullish kicker
        bullish_kicker = (
            self.data.close[-1] < self.data.open[-1] and  # Previous candle bearish
            bullish_candle and  # Current candle bullish
            self.data.open[0] > self.data.close[-1] and  # Gap up
            self.data.close[0] > self.data.open[-1]  # Strong move up
        )
        
        # Relaxed inside bar breakout
        inside_bar = (
            self.data.high[-1] <= self.data.high[-2] and
            self.data.low[-1] >= self.data.low[-2] and
            self.data.high[0] > self.data.high[-1] and
            bullish_candle
        )
        
        # Return True if any pattern is detected
        return any([engulfing, hammer, piercing, morning_star, harami, three_white_soldiers, bullish_kicker, inside_bar])


def add_relaxed_triple_screen_signals(df, middle_frame=None, higher_trend=None, 
                                     rsi_period=14, rsi_overbought=70, rsi_oversold=30,
                                     macd_fast=12, macd_slow=26, macd_signal=9,
                                     min_volume_ratio=0.8):
    """
    Add Triple Screen trading signals to a dataframe with relaxed conditions
    This is an enhanced version of the original add_triple_screen_signals function
    """
    # Make a copy of the dataframe to avoid modifying the original
    df = df.copy()
    
    # Generate basic signals first (similar to the original function but with relaxed conditions)
    # 1. Calculate RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=rsi_period).mean()
    avg_loss = loss.rolling(window=rsi_period).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 2. Calculate MACD
    ema_fast = df['close'].ewm(span=macd_fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=macd_slow, adjust=False).mean()
    df['macd'] = ema_fast - ema_slow
    df['macd_signal'] = df['macd'].ewm(span=macd_signal, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    # 3. Add Rate of Change (ROC) for momentum confirmation
    df['roc'] = df['close'].pct_change(14) * 100
    
    # 4. Add volume ratio for volume confirmation
    df['volume_sma'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_sma']
    
    # 5. Add Donchian Channels for breakout confirmation
    period = 20
    df['dc_high'] = df['high'].rolling(period).max()
    df['dc_low'] = df['low'].rolling(period).min()
    df['dc_mid'] = (df['dc_high'] + df['dc_low']) / 2
    
    # 6. Calculate support/resistance levels
    # Use recent swing lows/highs as support/resistance
    window = 10
    df['rolling_min'] = df['low'].rolling(window=window, center=True).min()
    df['rolling_max'] = df['high'].rolling(window=window, center=True).max()
    
    # 7. Generate basic signals based on RSI and MACD
    df['signal'] = 0
    
    # For bullish trend
    if higher_trend is None or higher_trend > 0:
        # RSI coming from oversold
        rsi_buy = (df['rsi'] > rsi_oversold) & (df['rsi'] < 60) & (df['rsi'].shift(1) <= rsi_oversold)
        # MACD crossing above signal line
        macd_buy = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
        # Combined signal
        df.loc[rsi_buy | macd_buy, 'signal'] = 1
    
    # For bearish trend
    if higher_trend is None or higher_trend < 0:
        # RSI coming from overbought
        rsi_sell = (df['rsi'] < rsi_overbought) & (df['rsi'] > 40) & (df['rsi'].shift(1) >= rsi_overbought)
        # MACD crossing below signal line
        macd_sell = (df['macd'] < df['macd_signal']) & (df['macd'].shift(1) >= df['macd_signal'].shift(1))
        # Combined signal
        df.loc[rsi_sell | macd_sell, 'signal'] = -1
    
    # 8. Add relaxed signal based on combined factors
    df['relaxed_signal'] = df['signal'].copy()
    
    # For rows where we have no signal but have favorable conditions, add a relaxed signal
    # This is where we'll catch signals that the strict version missed
    for i in range(1, len(df)):
        # Skip if we already have a signal
        if df.iloc[i]['signal'] != 0:
            continue
        
        # Check if trend is favorable
        trend_bullish = higher_trend > 0 if higher_trend is not None else True
        
        # Check RSI conditions (middle frame)
        rsi_favorable = False
        if middle_frame is not None and 'rsi' in middle_frame.columns:
            try:
                # Get current timestamp
                current_time = df.index[i]
                # Find the closest timestamp in middle_frame
                if hasattr(middle_frame.index, 'get_indexer'):
                    # For DatetimeIndex
                    closest_idx = middle_frame.index.get_indexer([current_time], method='nearest')[0]
                else:
                    # Fallback for other index types
                    middle_frame_times = middle_frame.index.tolist()
                    closest_idx = min(range(len(middle_frame_times)), 
                                     key=lambda j: abs((middle_frame_times[j] - current_time).total_seconds()) 
                                     if hasattr(middle_frame_times[j], 'total_seconds') else 0)
                
                if closest_idx >= 0 and closest_idx < len(middle_frame):
                    middle_rsi = middle_frame.iloc[closest_idx]['rsi']
                    # For bullish trend, RSI should be coming up from oversold
                    if trend_bullish and middle_rsi > rsi_oversold and middle_rsi < 60:
                        rsi_favorable = True
            except (TypeError, AttributeError, IndexError) as e:
                # If there's any issue with index comparison, fall back to using the current frame's RSI
                print(f"[WARN] Error comparing timeframes: {e}. Using current frame RSI.")
                rsi_favorable = False
        else:
            # Use the RSI from the lower timeframe if middle timeframe is not available
            rsi_favorable = (trend_bullish and df.iloc[i]['rsi'] > rsi_oversold and df.iloc[i]['rsi'] < 60) or \
                           (not trend_bullish and df.iloc[i]['rsi'] < rsi_overbought and df.iloc[i]['rsi'] > 40)
        
        # Check volume condition
        volume_favorable = df.iloc[i]['volume_ratio'] > min_volume_ratio
        
        # Check momentum condition
        momentum_favorable = (df.iloc[i]['roc'] > 0 if trend_bullish else df.iloc[i]['roc'] < 0)
        
        # Check breakout condition
        breakout_favorable = (df.iloc[i]['close'] > df.iloc[i]['dc_mid'] if trend_bullish else 
                             df.iloc[i]['close'] < df.iloc[i]['dc_mid'])
        
        # Combined relaxed signal - need at least 2 favorable conditions
        favorable_count = sum([trend_bullish, rsi_favorable, volume_favorable, momentum_favorable, breakout_favorable])
        
        if favorable_count >= 2:
            # This is a relaxed buy/sell signal
            df.at[df.index[i], 'relaxed_signal'] = 1 if trend_bullish else -1
    
    # Calculate support/resistance levels for confirmed signals
    df['sr_level'] = None
    
    for i in range(1, len(df)):
        if df.iloc[i]['signal'] != 0 or df.iloc[i]['relaxed_signal'] != 0:
            # For buy signals, use support level
            if df.iloc[i]['relaxed_signal'] > 0 or df.iloc[i]['signal'] > 0:
                # Look back for recent lows
                lookback = 10
                if i >= lookback:
                    df.at[df.index[i], 'sr_level'] = df.iloc[i-lookback:i]['low'].min()
                else:
                    df.at[df.index[i], 'sr_level'] = df.iloc[:i]['low'].min()
            # For sell signals, use resistance level
            else:
                # Look back for recent highs
                lookback = 10
                if i >= lookback:
                    df.at[df.index[i], 'sr_level'] = df.iloc[i-lookback:i]['high'].max()
                else:
                    df.at[df.index[i], 'sr_level'] = df.iloc[:i]['high'].max()
    
    # Add confirmed signal based on original criteria
    df['confirmed_signal'] = 0
    for i in range(1, len(df)):
        if df.iloc[i]['signal'] != 0 and not pd.isna(df.iloc[i]['sr_level']):
            # Check for candlestick patterns (strict criteria)
            pattern_confirmed = False
            o0, h0, l0, c0 = df.iloc[i]['open'], df.iloc[i]['high'], df.iloc[i]['low'], df.iloc[i]['close']
            o1, h1, l1, c1 = df.iloc[i-1]['open'], df.iloc[i-1]['high'], df.iloc[i-1]['low'], df.iloc[i-1]['close']
            
            # Simple bullish/bearish candle check
            bullish_candle = c0 > o0
            bearish_candle = c0 < o0
            
            # Bullish engulfing
            if df.iloc[i]['signal'] > 0 and bullish_candle and o0 <= c1 and c0 >= o1 and c1 < o1:
                pattern_confirmed = True
            # Bearish engulfing    
            elif df.iloc[i]['signal'] < 0 and bearish_candle and o0 >= c1 and c0 <= o1 and c1 > o1:
                pattern_confirmed = True
            
            if pattern_confirmed:
                df.at[df.index[i], 'confirmed_signal'] = df.iloc[i]['signal']
    
    # Add confirmed relaxed signal with more lenient criteria
    df['confirmed_relaxed_signal'] = 0
    
    for i in range(1, len(df)):
        if df.iloc[i]['relaxed_signal'] != 0 and not pd.isna(df.iloc[i]['sr_level']):
            # For relaxed signals, we don't require specific candlestick patterns
            # Just check that the signal aligns with the trend and has good volume
            if ((df.iloc[i]['relaxed_signal'] > 0 and higher_trend > 0) or 
                (df.iloc[i]['relaxed_signal'] < 0 and higher_trend < 0)) and \
               df.iloc[i]['volume_ratio'] > min_volume_ratio:
                df.at[df.index[i], 'confirmed_relaxed_signal'] = df.iloc[i]['relaxed_signal']
    
    return df
