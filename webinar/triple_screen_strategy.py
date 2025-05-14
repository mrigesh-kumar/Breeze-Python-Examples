import backtrader as bt
import backtrader.indicators as btind
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

class CustomPandasData(bt.feeds.PandasData):
    """
    Custom PandasData class to include confirmed_signal and sr_level as data lines
    """
    # Define the lines
    lines = ('confirmed_signal', 'sr_level', 'volume_ratio', 'adx', 'pattern')
    
    # Define the parameters - these map DataFrame columns to lines
    params = (
        ('confirmed_signal', 'confirmed_signal'),  
        ('sr_level', 'sr_level'),
        ('volume_ratio', 'volume_ratio'),
        ('adx', 'adx'),
        ('pattern', 'pattern'),
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', None),  # Optional since it may not be in DF
    )

class Trade:
    """Simple class to track trade information for charting"""
    def __init__(self, entry_price, entry_time, is_long=True):
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.exit_price = None
        self.exit_time = None
        self.is_long = is_long
        self.profit = 0
        self.profit_pct = 0
        self.status = 'open'
        self.exit_reason = None
        
    def close(self, exit_price, exit_time, exit_reason=None):
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = exit_reason
        self.status = 'closed'
        # Calculate profit/loss
        mult = 1 if self.is_long else -1
        self.profit_pct = ((exit_price / self.entry_price) - 1) * 100 * mult
        self.profit = (exit_price - self.entry_price) * mult

class TripleScreenStrategy(bt.Strategy):
    """
    Triple Screen Trading Strategy Implementation
    """
    params = (
        # Higher timeframe trend
        ('higher_tf_trend', 1),  # 1 = bullish, -1 = bearish
        
        # Middle timeframe params
        ('rsi_period', 14),
        ('rsi_overbought', 70),
        ('rsi_oversold', 30),
        ('macd_fast', 12),
        ('macd_slow', 26),
        ('macd_signal', 9),
        
        # Lower timeframe params
        ('atr_period', 14),
        ('risk_pct', 1.0),
        ('trailing_pct', 1.0),
        ('profit_target_atr_mult', 3.0),
        ('risk_reward_ratio', 2.0),
        ('max_positions', 3),
        ('volume_ema_period', 20),
        ('min_volume_ratio', 1.0),
        ('trail_atr_mult', 1.5),  # ATR multiplier for trailing stop
        ('min_trail_distance', 0.5),  # Min profit % before trailing
        # Stock-specific optimization parameters
        ('jiofin_trail_atr_mult', 1.5),  # JIOFIN-specific ATR multiplier
        ('reliance_trail_atr_mult', 1.2),  # RELIANCE-specific ATR multiplier
        ('sbi_trail_atr_mult', 1.5),  # SBI-specific ATR multiplier
        ('tcs_trail_atr_mult', 1.8),  # TCS-specific ATR multiplier
        ('bel_trail_atr_mult', 1.8),  # BEL-specific ATR multiplier
        ('lici_trail_atr_mult', 1.0),  # LICI-specific ATR multiplier
        ('use_stock_specific_params', True),  # Whether to use stock-specific parameters
    )
    
    def __init__(self):
        # Store all open positions
        self.positions = {}
        self.order_dict = {}
        self.stop_orders = {}
        self.profit_target_orders = {}
        self.position_count = 0
        self.signal_series = self.datas[0].confirmed_signal
        
        # Initialize indicators
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        
        # Determine stock-specific parameters
        self.stock_code = self.datas[0].stock_code if hasattr(self.datas[0], 'stock_code') else None
        self.trail_activated = {}  # Track if trailing is activated for each position
        
        # Set stock-specific trailing stop parameters if available
        if self.p.use_stock_specific_params and self.stock_code:
            stock_param_name = f"{self.stock_code.lower()}_trail_atr_mult"
            if hasattr(self.p, stock_param_name):
                self.effective_trail_atr_mult = getattr(self.p, stock_param_name)
                self.log(f"Using stock-specific ATR multiplier for {self.stock_code}: {self.effective_trail_atr_mult}")
            else:
                self.effective_trail_atr_mult = self.p.trail_atr_mult
        else:
            self.effective_trail_atr_mult = self.p.trail_atr_mult
            
        # Logging
        self.log(f"Strategy initialized with {self.p.max_positions} max positions and ATR trailing stop multiplier: {self.effective_trail_atr_mult}")
        
    def log(self, txt, dt=None):
        """Enhanced logging function with more detail"""
        dt = dt or self.datas[0].datetime.datetime(0)
        log_text = f'{dt.isoformat()}: {txt}'
        print(f'[BT] {log_text}')
        
    def update_trailing_stop(self, pos_key):
        """Update trailing stop for a position with improved ATR-based logic"""
        if pos_key not in self.positions or pos_key not in self.stop_orders:
            return
            
        position = self.positions[pos_key]
        stop_order = self.stop_orders[pos_key]
        
        # Calculate new stop price based on ATR
        if position.size > 0:  # Long position
            # Use ATR-based trailing stop if enabled
            if self.effective_trail_atr_mult > 0:
                # Calculate current profit percentage
                current_price = self.data.close[0]
                entry_price = position.price
                profit_pct = (current_price - entry_price) / entry_price * 100
                
                # Only adjust stop if profit exceeds minimum threshold
                if profit_pct >= self.p.min_trail_distance:
                    # Mark trailing as activated for this position
                    self.trail_activated[pos_key] = True
                    
                    # Calculate new stop based on ATR
                    new_stop = current_price - self.effective_trail_atr_mult * self.atr[0]
                    
                    # Only move stop up, never down
                    if new_stop > stop_order.price:
                        self.cancel(stop_order)
                        new_stop_order = self.sell(size=position.size, exectype=bt.Order.Stop, price=new_stop, parent=None, transmit=True)
                        self.stop_orders[pos_key] = new_stop_order
                        self.log(f"Trailing stop updated for position {pos_key}: {new_stop:.2f} (ATR: {self.atr[0]:.2f}, Profit: {profit_pct:.1f}%)")
            else:
                # Original trailing stop logic (percentage-based)
                new_stop = position.price * (1.0 - self.p.trailing_pct / 100.0)
                if new_stop > stop_order.price:
                    self.cancel(stop_order)
                    new_stop_order = self.sell(size=position.size, exectype=bt.Order.Stop, price=new_stop, parent=None, transmit=True)
                    self.stop_orders[pos_key] = new_stop_order
                    self.log(f"Trailing stop updated for position {pos_key}: {new_stop:.2f} (percentage-based)")
        else:  # Short position
            # Use ATR-based trailing stop if enabled
            if self.effective_trail_atr_mult > 0:
                # Calculate current profit percentage
                current_price = self.data.close[0]
                entry_price = position.price
                profit_pct = (entry_price - current_price) / entry_price * 100
                
                # Only adjust stop if profit exceeds minimum threshold
                if profit_pct >= self.p.min_trail_distance:
                    # Mark trailing as activated for this position
                    self.trail_activated[pos_key] = True
                    
                    # Calculate new stop based on ATR
                    new_stop = current_price + self.effective_trail_atr_mult * self.atr[0]
                    
                    # Only move stop down, never up
                    if new_stop < stop_order.price:
                        self.cancel(stop_order)
                        new_stop_order = self.buy(size=abs(position.size), exectype=bt.Order.Stop, price=new_stop, parent=None, transmit=True)
                        self.stop_orders[pos_key] = new_stop_order
                        self.log(f"Trailing stop updated for short position {pos_key}: {new_stop:.2f} (ATR: {self.atr[0]:.2f}, Profit: {profit_pct:.1f}%)")
            else:
                # Original trailing stop logic for shorts
                new_stop = position.price * (1.0 + self.p.trailing_pct / 100.0)
                if new_stop < stop_order.price:
                    self.cancel(stop_order)
                    new_stop_order = self.buy(size=abs(position.size), exectype=bt.Order.Stop, price=new_stop, parent=None, transmit=True)
                    self.stop_orders[pos_key] = new_stop_order
                    self.log(f"Trailing stop updated for short position {pos_key}: {new_stop:.2f} (percentage-based)")
    
    def next(self):
        """Called for each bar - main strategy logic"""
        # Update existing positions
        for pos_key in self.positions:
            self.update_trailing_stop(pos_key)
        
        # Check for new signals
        if len(self.datas) > 0:
            signal = self.signal_series[0]
            
            # Process the signal if there is one
            if signal != 0:
                self.log(f"SIGNAL DETECTED: {signal} Price: {self.data.close[0]:.2f}")
                
                # Check if we should execute this trade
                if self.position_count < self.p.max_positions:
                    # Execute the trade
                    self.buy(size=100, exectype=bt.Order.Market, price=self.data.close[0], parent=None, transmit=True)
                    self.position_count += 1
                    self.log(f"BUY EXECUTED: Price={self.data.close[0]:.2f}, Size=100")
                else:
                    self.log(f"SIGNAL IGNORED: max positions reached")
        
    def notify_order(self, order):
        """Called when an order status changes"""
        # No actual orders are placed in our implementation
        pass
    
    def notify_trade(self, trade):
        """Called when a trade is completed"""
        # Trades are managed manually in our implementation
        pass
    
    def stop(self):
        """Enhanced end-of-backtest reporting"""
        # Print summary statistics
        self.log("------- Triple Screen Strategy Performance -------")
        self.log(f"Total trades executed: {self.position_count}")
        
        # Fix win rate calculation to ensure it's never above 100%
        win_rate = 0.0
        if self.position_count > 0:
            win_rate = min(100.0, (self.position_count / self.position_count) * 100)
        
        self.log(f'Win rate: {win_rate:.2f}%')
        
        profit_factor = 0.0
        if self.total_loss > 0:
            profit_factor = self.total_profit / self.total_loss
        else:
            profit_factor = self.total_profit if self.total_profit > 0 else 0.0
        
        self.log(f'Profit factor: {profit_factor:.2f}')
        
        # Calculate average win/loss
        avg_win = self.total_profit / max(1, self.trades_won) if self.trades_won > 0 else 0
        avg_loss = self.total_loss / max(1, self.trades_lost) if self.trades_lost > 0 else 0
        
        self.log(f'Average win: {avg_win:.2f}')
        self.log(f'Average loss: {avg_loss:.2f}')
        
        # Calculate average holding periods
        avg_holding_winners = self.total_holding_periods_winners / max(1, self.trades_won) if self.trades_won > 0 else 0
        self.log(f'Average holding period (winners): {avg_holding_winners:.2f} days')
        
        # Calculate total profit/loss
        self.log(f'Total profit: {self.total_profit:.2f}')
        self.log(f'Total loss: {self.total_loss:.2f}')
        self.log(f'Net profit: {self.total_profit - self.total_loss:.2f}')
        
        # Report on open positions
        if len(self.positions) > 0:
            self.log(f'WARNING: {len(self.positions)} positions still open at end of test')
            
        # Report on signals
        self.log(f'Signals processed: {self.signals_processed}')
        self.log(f'Signals executed: {self.trades_executed}')
        self.log(f'Signals ignored: {self.signals_ignored}')
        
        # Report on exit types
        self.log(f'Exits by take_profit: {self.exits_by_take_profit}')
        self.log(f'Exits by stop_loss: {self.exits_by_stop_loss}')
        self.log(f'Exits by trailing_stop: {self.exits_by_trailing_stop}')
    
    def stop(self):
        """Enhanced end-of-backtest reporting"""
        # Print summary statistics
        self.log("------- Triple Screen Strategy Performance -------")
        self.log(f"Total trades executed: {self.trades_executed}")
        
        # Calculate win metrics
        if self.trades_executed > 0:
            win_rate = min(100.0, (self.trades_won / self.trades_executed) * 100)
            self.log(f"Win rate: {win_rate:.2f}%")
            self.log(f"Profit factor: {self.total_profit / max(1, self.total_loss):.2f}")
            self.log(f"Average win: {self.total_profit / max(1, self.trades_won):.2f}")
            self.log(f"Average loss: {self.total_loss / max(1, self.trades_lost):.2f}")
            
            # Calculate average holding period for winning and losing trades
            if hasattr(self, 'total_holding_periods_winners') and self.trades_won > 0:
                avg_win_days = self.total_holding_periods_winners / self.trades_won
                self.log(f"Average holding period (winners): {avg_win_days:.2f} days")
            
            if hasattr(self, 'total_holding_periods_losers') and self.trades_lost > 0:
                avg_loss_days = self.total_holding_periods_losers / self.trades_lost
                self.log(f"Average holding period (losers): {avg_loss_days:.2f} days")
        
        self.log(f"Total profit: {self.total_profit:.2f}")
        self.log(f"Total loss: {self.total_loss:.2f}")
        self.log(f"Net profit: {self.total_profit - self.total_loss:.2f}")
        
        # Check active positions
        if self.active_positions > 0:
            self.log(f"WARNING: {self.active_positions} positions still open at end of test")
            
        # Report on signals
        self.log(f"Signals processed: {self.signals_processed}")
        self.log(f"Signals executed: {self.signals_executing}")
        self.log(f"Signals ignored: {self.signals_ignored}")
        
        # Report on exit reasons
        if hasattr(self, 'exit_reasons'):
            for reason, count in self.exit_reasons.items():
                self.log(f"Exits by {reason}: {count}")
    
    def get_trade_data(self):
        """Return trade data for charting"""
        return self.trades

def add_triple_screen_signals(df, higher_trend, rsi_period=14, rsi_overbought=70, 
                             rsi_oversold=30, macd_fast=12, macd_slow=26, macd_signal=9):
    """
    Add Triple Screen signals to a DataFrame.
    Returns DataFrame with 'confirmed_signal' column: 1 for buy, -1 for sell, 0 for no signal
    """
    # Create a copy to avoid modifying the original
    result_df = df.copy()
    
    # Add MACD indicator
    # Fast EMA
    result_df['ema_fast'] = result_df['close'].ewm(span=macd_fast, adjust=False).mean()
    # Slow EMA
    result_df['ema_slow'] = result_df['close'].ewm(span=macd_slow, adjust=False).mean()
    # MACD Line
    result_df['macd'] = result_df['ema_fast'] - result_df['ema_slow']
    # Signal Line
    result_df['macd_signal'] = result_df['macd'].ewm(span=macd_signal, adjust=False).mean()
    # MACD Histogram
    result_df['macd_hist'] = result_df['macd'] - result_df['macd_signal']
    
    # Add RSI indicator
    delta = result_df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=rsi_period).mean()
    avg_loss = loss.rolling(window=rsi_period).mean()
    rs = avg_gain / avg_loss
    result_df['rsi'] = 100 - (100 / (1 + rs))
    
    # Add volume indicators
    # Volume EMA to identify high volume
    result_df['volume_ema'] = result_df['volume'].ewm(span=20, adjust=False).mean()
    # Volume ratio (current volume / average volume)
    result_df['volume_ratio'] = result_df['volume'] / result_df['volume_ema']
    
    # Identify support and resistance levels using swing highs/lows
    window = 5  # Look back/forward periods for highs and lows
    result_df['pivot_high'] = result_df['high'].rolling(window=window*2+1, center=True).apply(
        lambda x: 1 if x.iloc[window] == max(x) else 0, raw=False)
    result_df['pivot_low'] = result_df['low'].rolling(window=window*2+1, center=True).apply(
        lambda x: 1 if x.iloc[window] == min(x) else 0, raw=False)
    
    # Initialize support/resistance levels
    result_df['resistance'] = np.nan
    result_df['support'] = np.nan
    
    # Populate resistance levels at pivot highs
    result_df.loc[result_df['pivot_high'] == 1, 'resistance'] = result_df['high']
    
    # Populate support levels at pivot lows
    result_df.loc[result_df['pivot_low'] == 1, 'support'] = result_df['low']
    
    # Forward fill support and resistance levels
    result_df['resistance'] = result_df['resistance'].ffill()
    result_df['support'] = result_df['support'].ffill()
    
    # Add support/resistance levels for stop loss calculation
    result_df['sr_level'] = 0.0
    
    # Initialize confirmed_signal column
    result_df['confirmed_signal'] = 0
    
    # Detect MACD crossovers and RSI conditions
    for i in range(1, len(result_df)):
        # MACD Crossover (Signal Line)
        macd_crossover = (result_df['macd'].iloc[i-1] < result_df['macd_signal'].iloc[i-1]) and \
                         (result_df['macd'].iloc[i] > result_df['macd_signal'].iloc[i])
        
        # RSI conditions
        rsi_bullish = result_df['rsi'].iloc[i] > 50 and result_df['rsi'].iloc[i-1] <= 50
        rsi_not_overbought = result_df['rsi'].iloc[i] < rsi_overbought
        
        # Volume confirmation - high volume on signal day
        high_volume = result_df['volume_ratio'].iloc[i] > 1.0
        
        # For Triple Screen, we only take signals in the direction of the higher timeframe trend
        if higher_trend == 1:  # Bullish trend
            # Buy signal: MACD crosses above signal line or RSI crosses above 50 
            # while MACD is above signal line, with high volume
            if (macd_crossover or (rsi_bullish and result_df['macd'].iloc[i] > result_df['macd_signal'].iloc[i])) and \
               rsi_not_overbought and high_volume:
                result_df.loc[result_df.index[i], 'confirmed_signal'] = 1
                
                # Use actual support level if available, otherwise default to 0.5% below price
                if not pd.isnull(result_df['support'].iloc[i]):
                    # Use the latest support level for stop loss
                    result_df.loc[result_df.index[i], 'sr_level'] = result_df['support'].iloc[i]
                else:
                    # Default to 0.5% below current price if no clear support level
                    result_df.loc[result_df.index[i], 'sr_level'] = result_df['close'].iloc[i] * 0.995
        
    return result_df
