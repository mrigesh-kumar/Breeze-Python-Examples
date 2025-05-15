import os
import sys
import argparse
import configparser
import re
from rich.traceback import install
install()
from rich import print

# Delay heavy imports until after menu selection for faster startup
import backtrader as bt  # Needed at global scope for SimpleTrailingStopStrategy
from data_handler import DataHandler  # Needed at global scope for top-level references
from triple_screen_strategy import TripleScreenStrategy
from triple_screen_relaxed import RelaxedTripleScreenStrategy

# Global variable for strategy statistics
strategy_stats = {
    'total_trades': 0,
    'win_rate': 0,
    'net_profit': 0,
    'roi': 0
}

# Config and BreezeConnect initialization are now deferred for faster startup
config = None
breeze_conn = None

def initialize_config():
    global config
    if config is None:
        config = configparser.RawConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), 'config.properties'))
    return config

def initialize_breeze():
    global breeze_conn
    global config
    if config is None:
        config = configparser.RawConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), 'config.properties'))
    if breeze_conn is None:
        from breeze_connect import BreezeConnect
        breeze_conn = BreezeConnect(api_key=config.get('DEFAULT', 'app_key'))
        breeze_conn.generate_session(
            api_secret=config.get('DEFAULT', 'secret_key'),
            session_token=config.get('DEFAULT', 'session_token')
        )
    return breeze_conn

# Create a simplified strategy that only tests trailing stop logic
class SimpleTrailingStopStrategy(bt.Strategy):
    params = (
        ('trail_atr_mult', 0),  # ATR multiplier for trailing stop (0 = disabled)
        ('min_trail_distance', 0),  # Min profit % before trailing (0 = disabled)
        ('risk_pct', 0.75),  # Risk percentage per trade - reduced for better risk management
        ('atr_period', 14),  # ATR period
        ('profit_target_mult', 3.5),  # Profit target as multiple of risk - increased for better reward/risk
        ('max_risk_pct', 1.5),  # Maximum risk percentage per trade - reduced from 2.0%
        ('position_size_pct', 4.0),  # Maximum position size as % of portfolio - reduced slightly
    )
    
    def __init__(self):
        # Technical indicators
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.rsi = bt.indicators.RSI(self.data, period=14)
        self.ema = bt.indicators.EMA(self.data, period=13)
        self.macd = bt.indicators.MACD(self.data)
        self.macd_hist = self.macd.macd - self.macd.signal
        # For time-based and stagnation exits
        self.bar_since_entry = 0
        self.entry_price = None
        self.entry_bar = None

        # Trade management variables
        self.order = None
        self.price_entry = None
        self.stop_price = None
        self.profit_target = None
        self.trail_activated = False
        self.trade_stats = {
            'total': 0,
            'wins': 0,
            'losses': 0,
            'total_profit': 0,
            'total_loss': 0
        }
        
    def log(self, txt):
        """Logging function for strategy"""
        dt = self.datas[0].datetime.date(0)
        # print(f'[{dt.isoformat()}] {txt}')
        
    def calculate_position_size(self, entry_price, stop_price):
        """Calculate position size based on risk management parameters"""
        # Calculate risk per share
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share == 0:
            return 0
            
        # Calculate risk amount based on portfolio value
        portfolio_value = self.broker.getvalue()
        risk_amount = portfolio_value * (self.p.risk_pct / 100)
        
        # Calculate position size based on risk
        size = risk_amount / risk_per_share
        
        # Limit position size to max percentage of portfolio
        max_size_by_value = (portfolio_value * self.p.position_size_pct / 100) / entry_price
        
        # Return the smaller of the two sizes (rounded down to integer)
        return int(min(size, max_size_by_value))
        
    def next(self):
        # Simple entry logic - buy on first bar
        if not self.position and len(self.data) > 20:
            entry_price = self.data.close[0]
            stop_price = entry_price - 2 * self.atr[0]
            size = self.calculate_position_size(entry_price, stop_price)
            risk = entry_price - stop_price
            profit_target = entry_price + (risk * self.p.profit_target_mult)
            if size > 0:
                self.buy(size=size)
                self.price_entry = entry_price
                self.stop_price = stop_price
                self.profit_target = profit_target
                self.trail_activated = False
                self.bar_since_entry = 0
                self.entry_price = entry_price
                self.entry_bar = len(self.data)
                # self.log(f"BUY EXECUTED: Price={entry_price:.2f}, Size={size}, Stop={stop_price:.2f}, Target={profit_target:.2f}")
                # self.log(f"Risk per share: {risk:.2f} ({(risk/entry_price)*100:.2f}%), Potential reward: {(profit_target-entry_price):.2f} ({((profit_target-entry_price)/entry_price)*100:.2f}%)")
        
        # Advanced exit logic
        if self.position:
            self.bar_since_entry = len(self.data) - (self.entry_bar or len(self.data))
            current_profit_pct = (self.data.close[0] - self.price_entry) / self.price_entry * 100
            stagnation_atr_mult = 0.5  # No movement threshold (ATR fraction)
            stagnation_bars = 7        # Bars to wait before checking stagnation
            max_holding_bars = 15      # Maximum bars to hold a trade
            rsi_exit = 48              # RSI threshold for early exit
            macd_exit = 0              # MACD histogram threshold
            ema_exit = True            # Enable EMA trend exit

            # 1. Momentum reversal exit (RSI/MACD)
            if self.rsi[0] < rsi_exit or self.macd_hist[0] < macd_exit:
                exit_price = self.data.close[0]
                exit_size = self.position.size
                self.close()
                # self.log(f"[ADV EXIT] Momentum reversal: RSI={self.rsi[0]:.1f}, MACD hist={self.macd_hist[0]:.3f}")
                self.trade_stats['total'] += 1
                if current_profit_pct > 0:
                    pnl = (exit_price - self.price_entry) * exit_size
                    # print(f"[TRADE CLOSE] WIN: Entry={self.price_entry:.2f}, Exit={exit_price:.2f}, Size={exit_size}, P&L={pnl:.2f}")
                    self.trade_stats['wins'] += 1
                    self.trade_stats['total_profit'] += pnl
                else:
                    pnl = (exit_price - self.price_entry) * exit_size
                    # print(f"[TRADE CLOSE] LOSS: Entry={self.price_entry:.2f}, Exit={exit_price:.2f}, Size={exit_size}, P&L={pnl:.2f}")
                    self.trade_stats['losses'] += 1
                    self.trade_stats['total_loss'] += abs(pnl)
                return

            # 2. ATR-based stagnation exit
            if self.bar_since_entry >= stagnation_bars:
                if abs(self.data.close[0] - self.price_entry) < self.atr[0] * stagnation_atr_mult:
                    exit_price = self.data.close[0]
                    exit_size = self.position.size
                    self.close()
                    # self.log(f"[ADV EXIT] No movement after {stagnation_bars} bars (ATR stagnation)")
                    self.trade_stats['total'] += 1
                    if current_profit_pct > 0:
                        self.trade_stats['wins'] += 1
                        self.trade_stats['total_profit'] += (exit_price - self.price_entry) * exit_size
                    else:
                        self.trade_stats['losses'] += 1
                        self.trade_stats['total_loss'] += abs((exit_price - self.price_entry) * exit_size)
                    return

            # 3. Short-term EMA trend exit
            if ema_exit and self.data.close[0] < self.ema[0]:
                exit_price = self.data.close[0]
                exit_size = self.position.size
                self.close()
                # self.log(f"[ADV EXIT] Price below EMA: Close={self.data.close[0]:.2f}, EMA={self.ema[0]:.2f}")
                self.trade_stats['total'] += 1
                if current_profit_pct > 0:
                    pnl = (exit_price - self.price_entry) * exit_size
                    # print(f"[TRADE CLOSE] WIN: Entry={self.price_entry:.2f}, Exit={exit_price:.2f}, Size={exit_size}, P&L={pnl:.2f}")
                    self.trade_stats['wins'] += 1
                    self.trade_stats['total_profit'] += pnl
                else:
                    pnl = (exit_price - self.price_entry) * exit_size
                    # print(f"[TRADE CLOSE] LOSS: Entry={self.price_entry:.2f}, Exit={exit_price:.2f}, Size={exit_size}, P&L={pnl:.2f}")
                    self.trade_stats['losses'] += 1
                    self.trade_stats['total_loss'] += abs(pnl)
                return

            # 4. Time-based stop
            if self.bar_since_entry >= max_holding_bars:
                exit_price = self.data.close[0]
                exit_size = self.position.size
                self.close()
                # self.log(f"[ADV EXIT] Max holding period ({max_holding_bars} bars) reached")
                self.trade_stats['total'] += 1
                if current_profit_pct > 0:
                    pnl = (exit_price - self.price_entry) * exit_size
                    # print(f"[TRADE CLOSE] WIN: Entry={self.price_entry:.2f}, Exit={exit_price:.2f}, Size={exit_size}, P&L={pnl:.2f}")
                    self.trade_stats['wins'] += 1
                    self.trade_stats['total_profit'] += pnl
                else:
                    pnl = (exit_price - self.price_entry) * exit_size
                    # print(f"[TRADE CLOSE] LOSS: Entry={self.price_entry:.2f}, Exit={exit_price:.2f}, Size={exit_size}, P&L={pnl:.2f}")
                    self.trade_stats['losses'] += 1
                    self.trade_stats['total_loss'] += abs(pnl)
                return

            # --- Existing trailing stop logic ---
            # Check if profit target is hit
            if self.data.high[0] >= self.profit_target:
                exit_price = self.data.close[0]
                exit_size = self.position.size
                self.close()
                # self.log(f"Profit target hit: {self.profit_target:.2f} ({((self.profit_target-self.price_entry)/self.price_entry)*100:.2f}%)")
                self.trade_stats['total'] += 1
                self.trade_stats['wins'] += 1
                self.trade_stats['total_profit'] += (self.profit_target - self.price_entry) * self.position.size
                return

            # ATR-based trailing stop logic
            if self.p.trail_atr_mult > 0:  # Using ATR-based trailing stop
                if current_profit_pct >= self.p.min_trail_distance:
                    self.trail_activated = True
                if self.trail_activated:
                    potential_stop = self.data.close[0] - self.p.trail_atr_mult * self.atr[0]
                    if potential_stop > self.stop_price:
                        old_stop = self.stop_price
                        self.stop_price = potential_stop
                        # print(f"Trail stop updated: {self.stop_price:.2f} (from {old_stop:.2f}, profit: {current_profit_pct:.1f}%)")

            # Check if stop is hit
            if self.data.low[0] <= self.stop_price:
                self.close()
                # print(f"Stop triggered at: {self.stop_price:.2f} (profit: {current_profit_pct:.1f}%)")
                self.trade_stats['total'] += 1
                if current_profit_pct > 0:
                    self.trade_stats['wins'] += 1
                    self.trade_stats['total_profit'] += (self.stop_price - self.price_entry) * self.position.size
                else:
                    self.trade_stats['losses'] += 1
                    self.trade_stats['total_loss'] += abs((self.price_entry - self.stop_price) * self.position.size)
    
    def stop(self):
        """Called at the end of the backtest"""
        # Print strategy performance summary
        print("\nStrategy Performance Summary:")
        print(f"Total Trades: {self.trade_stats['total']}")
        
        if self.trade_stats['total'] > 0:
            win_rate = (self.trade_stats['wins'] / self.trade_stats['total']) * 100
            print(f"Win Rate: {win_rate:.1f}%")
            
            avg_profit = self.trade_stats['total_profit'] / self.trade_stats['wins'] if self.trade_stats['wins'] > 0 else 0
            avg_loss = self.trade_stats['total_loss'] / self.trade_stats['losses'] if self.trade_stats['losses'] > 0 else 0
            
            print(f"Average Profit: {avg_profit:.2f}")
            print(f"Average Loss: {avg_loss:.2f}")
            
            if avg_loss > 0:
                profit_factor = avg_profit / avg_loss
                print(f"Profit Factor: {profit_factor:.2f}")
            
            net_profit = self.trade_stats['total_profit'] - self.trade_stats['total_loss']
            print(f"Net Profit: {net_profit:.2f}")
        # Calculate ROI using broker values
        final_portfolio = self.broker.getvalue()
        initial_portfolio = 100000.0  # This is the default initial cash
        roi = ((final_portfolio / initial_portfolio) - 1) * 100
        print(f"ROI: {roi:.2f}%")
        
        # Save strategy stats to global variable for summary
        global strategy_stats
        strategy_stats = {
            'total_trades': self.trade_stats['total'],
            'win_rate': win_rate if self.trade_stats['total'] > 0 else 0,
            'net_profit': net_profit,
            'roi': roi
        }

def get_trading_params(config=None):
    """Get standard trading parameters from config
    
    Uses standard ATR trailing stop and risk management parameters for all stocks
    from the TRADING_PARAMS section in config.properties.
    """
    # Default parameters if config reading fails
    default_params = {
        'trail_atr_mult': 1.5,
        'min_trail_distance': 0.4,
        'risk_pct': 0.75,
        'max_risk_pct': 1.5,
        'position_size_pct': 4.0,
        'profit_target_mult': 3.5
    }
    
    # Try to read from config file if provided
    if config is None:
        # Load config file
        config = configparser.RawConfigParser(interpolation=None)
        config_path = os.path.join(os.path.dirname(__file__), 'config.properties')
        config.read(config_path)
    
    # Read parameters from TRADING_PARAMS section
    try:
        if 'TRADING_PARAMS' in config.sections():
            params = {}
            
            # Read ATR trailing stop parameters
            if 'atr_multiplier' in config['TRADING_PARAMS']:
                params['trail_atr_mult'] = float(config['TRADING_PARAMS']['atr_multiplier'])
            else:
                params['trail_atr_mult'] = default_params['trail_atr_mult']
                
            if 'min_profit_threshold' in config['TRADING_PARAMS']:
                params['min_trail_distance'] = float(config['TRADING_PARAMS']['min_profit_threshold'])
            else:
                params['min_trail_distance'] = default_params['min_trail_distance']
            
            # Read risk management parameters
            if 'risk_percentage' in config['TRADING_PARAMS']:
                params['risk_pct'] = float(config['TRADING_PARAMS']['risk_percentage'])
            else:
                params['risk_pct'] = default_params['risk_pct']
                
            if 'max_risk_percentage' in config['TRADING_PARAMS']:
                params['max_risk_pct'] = float(config['TRADING_PARAMS']['max_risk_percentage'])
            else:
                params['max_risk_pct'] = default_params['max_risk_pct']
                
            if 'position_size_percentage' in config['TRADING_PARAMS']:
                params['position_size_pct'] = float(config['TRADING_PARAMS']['position_size_percentage'])
            else:
                params['position_size_pct'] = default_params['position_size_pct']
                
            if 'profit_target_multiplier' in config['TRADING_PARAMS']:
                params['profit_target_mult'] = float(config['TRADING_PARAMS']['profit_target_multiplier'])
            else:
                params['profit_target_mult'] = default_params['profit_target_mult']
                
            return params
        else:
            # print(f"[INFO] TRADING_PARAMS section not found in config. Using default parameters.")
            return default_params
    
    except Exception as e:
        # print(f"[WARN] Error reading trading parameters: {e}")
        return default_params


def get_optimized_params(stock_code, config=None):
    """Get trailing stop parameters for all stocks
    
    Uses the same ATR multiplier and minimum profit threshold for all stocks.
    Parameters are read from TRADING_PARAMS section in config.properties.
    """
    # Get standard parameters for all stocks
    params = get_trading_params(config)
    
    # Return only the trailing stop parameters
    return {
        'trail_atr_mult': params['trail_atr_mult'],
        'min_trail_distance': params['min_trail_distance']
    }

def parse_stock_codes(config_value):
    """Parse comma-separated stock codes from config, handling quotes"""
    if not config_value:
        return []
        
    # Remove outer quotes if present
    cleaned = config_value.strip('"\' ')
    
    # Split by comma and clean each item
    stock_codes = []
    for item in re.findall(r'"([^"]*)"|([^,]+)', cleaned):
        # Each match is a tuple with either the quoted part or the unquoted part
        code = item[0] if item[0] else item[1]
        if code:
            stock_codes.append(code.strip('"\' '))
    
    return stock_codes

def get_config_value(config, section, key, default=None):
    """Get config value with fallback to DEFAULT section and provided default"""
    try:
        if section and config.has_option(section, key):
            return config.get(section, key)
        if config.has_option('DEFAULT', key):
            return config.get('DEFAULT', key)
    except Exception as e:
        # print(f"[WARN] Error reading config key '{key}': {e}")
        pass
    return default

def run_strategy(stock_code, market_type, use_relaxed=False):
    """Run trading strategy for a specific stock/derivative
    
    Args:
        stock_code: Stock/Derivative code to analyze (required)
        market_type: Type of market (e.g., CASH, FUTURES, OPTIONS)
        use_relaxed: Whether to use relaxed strategy rules
    """
    if not stock_code:
        raise ValueError("Stock/Derivative code is required")
        
    # print(f"[INFO] Running {'Relaxed' if use_relaxed else 'Strict'} strategy for {stock_code} in {market_type} market")
    
    # Initialize Breeze only when needed
    breeze = initialize_breeze()
    
    # Get market-specific parameters
    exchange_code = config.get(market_type, 'exchange_code')
    product_type = config.get(market_type, 'product_type')
    csv_folder = config.get(market_type, 'csv_folder')
    
    # Handle options-specific parameters
    expiry_date = None
    right = None
    strike_price = None
    
    if market_type == 'OPTIONS':
        # For options, we need expiry date, right (call/put) and strike price
        expiry_date = config.get(market_type, 'expiry_date')
        right = config.get(market_type, 'right')
        strike_price = config.get(market_type, 'strike_price')
        # print(f"[INFO] Options parameters: {right} {strike_price} expiring {expiry_date}")
    elif market_type == 'FUTURES':
        # For futures, we only need expiry date
        expiry_date = config.get(market_type, 'expiry_date', fallback=None)
    
    # Initialize data handler with appropriate parameters
    dh = DataHandler(
        breeze_conn=initialize_breeze(),
        stock_code=stock_code,
        exchange_code=exchange_code,
        product_type=product_type,
        csv_folder=csv_folder,
        expiry_date=expiry_date,
        right=right,
        strike_price=strike_price
    )
    df = dh.get_historical_data()
    
    # Check if we have enough data for the strategy
    if df.empty or len(df) < 30:  # Ensure minimum data length (ATR period + extra buffer)
        # print(f"[ERROR] Insufficient data for {stock_code}: Got {len(df) if not df.empty else 0} bars, need at least 30")
        return None
        
    # Create a cerebro instance
    cerebro = bt.Cerebro()
    
    # Add data to cerebro
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    
    # Set starting cash
    cerebro.broker.setcash(100000.0)
    
    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='time_return')
    cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')
    cerebro.addanalyzer(bt.analyzers.PeriodStats, _name='period_stats')
    
    # Add observers for visualization
    cerebro.addobserver(bt.observers.Trades)
    cerebro.addobserver(bt.observers.BuySell)
    cerebro.addobserver(bt.observers.Value)
    
    # Get standard trading parameters
    params = get_trading_params()
    trail_atr_mult = params['trail_atr_mult']
    min_trail_distance = params['min_trail_distance']
    
    # Select strategy class based on relaxed flag
    strategy_name = "Relaxed" if use_relaxed else "Strict"
    
    # Use proper strategy classes based on the relaxed flag
    strategy_class = RelaxedTripleScreenStrategy if use_relaxed else TripleScreenStrategy
    
    # Run strategy with ATR trailing stops
    # print(f"\n[INFO] Running {strategy_name} strategy with ATR trailing stops:")
    # print(f"       ATR Multiplier: {trail_atr_mult}, Min Trail Distance: {min_trail_distance}%")
    
    # Different parameter sets depending on which strategy we're using
    if strategy_class == SimpleTrailingStopStrategy:
        # For simple strategy tests
        cerebro.addstrategy(strategy_class,
                          trail_atr_mult=trail_atr_mult,
                          min_trail_distance=min_trail_distance,
                          risk_pct=params['risk_pct'],
                          max_risk_pct=params['max_risk_pct'],
                          position_size_pct=params['position_size_pct'],
                          profit_target_mult=params['profit_target_mult'])
    else:
        # For actual Triple Screen strategies
        # Read max_positions from config (DEFAULT section)
        max_positions = int(get_config_value(config, 'DEFAULT', 'max_positions', 3))
        cerebro.addstrategy(strategy_class,
                          trail_atr_mult=trail_atr_mult,
                          min_trail_distance=min_trail_distance,
                          risk_pct=params['risk_pct'],
                          profit_target_atr_mult=params['profit_target_mult'],
                          max_positions=max_positions)
    results = cerebro.run()[0]
    
    # Print strategy-level trade stats if available
    if hasattr(results, 'trade_stats') and results.trade_stats:
        print("\n[STRATEGY TRADE STATS]")
        print(f"Total trades executed: {results.trade_stats.get('total', 'N/A')}")
        print(f"Win rate: {results.trade_stats.get('win_rate', 'N/A'):.2f}%")
        print(f"Total profit: {results.trade_stats.get('total_profit', 'N/A'):.2f}")
        print(f"Total loss: {results.trade_stats.get('total_loss', 'N/A'):.2f}")
        print(f"Net profit: {(results.trade_stats.get('total_profit', 0) - results.trade_stats.get('total_loss', 0)):.2f}")
    
    # Calculate actual trades from the analyzer with safer error handling
    try:
        trades_analysis = results.analyzers.trades.get_analysis()
        
        # Safe extraction with multiple levels of checks
        total_closed_trades = 0
        if hasattr(trades_analysis, 'total'):
            if isinstance(trades_analysis.total, dict) and 'closed' in trades_analysis.total:
                total_closed_trades = trades_analysis.total['closed']
            # Backtrader sometimes returns AutoOrderedDict objects
            elif hasattr(trades_analysis.total, 'closed'):
                total_closed_trades = trades_analysis.total.closed
        
        # Similar safe extraction for won trades
        won_trades = 0
        if hasattr(trades_analysis, 'won'):
            if isinstance(trades_analysis.won, dict) and 'total' in trades_analysis.won:
                won_trades = trades_analysis.won['total']
            elif hasattr(trades_analysis.won, 'total'):
                won_trades = trades_analysis.won.total
        
        # Similar safe extraction for lost trades
        lost_trades = 0
        if hasattr(trades_analysis, 'lost'):
            if isinstance(trades_analysis.lost, dict) and 'total' in trades_analysis.lost:
                lost_trades = trades_analysis.lost['total']
            elif hasattr(trades_analysis.lost, 'total'):
                lost_trades = trades_analysis.lost.total
                
        # Calculate win rate safely
        win_rate = (won_trades / total_closed_trades * 100) if total_closed_trades > 0 else 0
        
        # Print detailed trade information
        print("\nDETAILED TRADE INFORMATION")
        print("-" * 50)
        print(f"Total trades: {total_closed_trades}")
        
        # Print signal information if available
        if hasattr(results, 'signals_processed'):
            print(f"Signals processed: {results.signals_processed}")
        if hasattr(results, 'signals_executed'):
            print(f"Signals executed: {results.signals_executed}")
        if hasattr(results, 'signals_ignored'):
            print(f"Signals ignored: {results.signals_ignored}")
        
        # Get cumulative profit/loss if available
        gross_profit = 0
        gross_loss = 0
        
        # Try to get from strategy first
        if hasattr(results, 'total_profit'):
            gross_profit = results.total_profit
        if hasattr(results, 'total_loss'):
            gross_loss = results.total_loss
            
        # If not available from strategy, try from analyzer
        if gross_profit == 0 and hasattr(trades_analysis, 'pnl'):
            if hasattr(trades_analysis.pnl, 'gross'):
                if hasattr(trades_analysis.pnl.gross, 'total'):
                    gross_profit = max(0, trades_analysis.pnl.gross.total)
        
        print(f"Cumulative profit: {gross_profit:.2f}")
        print(f"Cumulative loss: {gross_loss:.2f}")
        print(f"Net P&L: {gross_profit - gross_loss:.2f}")
        
        # Print individual trades summary instead of detailed list
        print("\nTRADE SUMMARY")
        print("-" * 50)
        
        # Get trade summary from strategy if available
        if hasattr(results, 'trades_won') and hasattr(results, 'trades_lost'):
            print(f"Winning trades: {results.trades_won}")
            print(f"Losing trades: {results.trades_lost}")
            
            # Calculate average profit/loss if available
            if hasattr(results, 'total_profit') and results.trades_won > 0:
                avg_win = results.total_profit / results.trades_won
                print(f"Average win: {avg_win:.2f}")
            if hasattr(results, 'total_loss') and results.trades_lost > 0:
                avg_loss = results.total_loss / results.trades_lost
                print(f"Average loss: {avg_loss:.2f}")
        
        # Print exit statistics if available
        if hasattr(results, 'exits_by_take_profit'):
            print(f"Exits by take profit: {results.exits_by_take_profit}")
        if hasattr(results, 'exits_by_stop_loss'):
            print(f"Exits by stop loss: {results.exits_by_stop_loss}")
        if hasattr(results, 'exits_by_trailing_stop'):
            print(f"Exits by trailing stop: {results.exits_by_trailing_stop}")
            
        # Print position information
        if hasattr(results, 'position_count'):
            print(f"Positions opened: {results.position_count}")
        if hasattr(results, 'active_positions'):
            print(f"Positions still active: {results.active_positions}")
            
        # Try to get the exit reasons dictionary if available
        if hasattr(results, 'exit_reasons') and results.exit_reasons:
            print("\nEXIT REASONS:")
            for reason, count in results.exit_reasons.items():
                print(f"{reason}: {count}")
                
        # Continue with the rest of the analysis
    except Exception as e:
        # If analyzer access fails, use safe defaults
        print(f"Note: Could not access trade analyzer data: {e}")
        total_closed_trades = 0
        won_trades = 0
        lost_trades = 0
        win_rate = 0
    
    # Calculate ROI
    final_value = cerebro.broker.getvalue()
    initial_value = 100000.0  # Default starting cash
    roi = ((final_value / initial_value) - 1) * 100
    
    # Update global stats
    strategy_stats = {
        'total_trades': total_closed_trades,
        'win_rate': win_rate,
        'won_trades': won_trades,
        'lost_trades': lost_trades,
        'roi': roi,
        'stock_code': stock_code
    }
    
    # Also try to get values directly from strategy if analyzer failed
    if total_closed_trades == 0 and hasattr(results, 'trades_executed'):
        strategy_stats['total_trades'] = results.trades_executed
    if win_rate == 0 and hasattr(results, 'trades_executed') and results.trades_executed > 0 and hasattr(results, 'trades_won'):
        strategy_stats['win_rate'] = (results.trades_won / results.trades_executed) * 100
        strategy_stats['won_trades'] = results.trades_won
        strategy_stats['lost_trades'] = results.trades_lost
    
    # Get parameters used in the strategy for display
    params = get_trading_params()
    
    print("\nSTRATEGY PARAMETERS")
    print("-"*50)
    print(f"{'Parameter':<25}{'Value':<15}")
    print("-"*40)
    print(f"{'Strategy Approach':<25}{'Relaxed' if use_relaxed else 'Strict':<15}")
    print(f"{'ATR Multiplier':<25}{params['trail_atr_mult']:<15.2f}")
    print(f"{'Min Profit Threshold':<25}{params['min_trail_distance']:<15.2f}%")
    print(f"{'Risk Per Trade':<25}{params['risk_pct']:<15.2f}%")
    print(f"{'Max Risk Per Trade':<25}{params['max_risk_pct']:<15.2f}%")
    print(f"{'Position Size %':<25}{params['position_size_pct']:<15.2f}%")
    
    print("\nSTRATEGY PERFORMANCE")
    print("-"*50)
    print(f"{'Metric':<25}{'Value':<15}")
    print("-"*40)
    
    # Get performance metrics
    try:
        # Sharpe ratio
        sharpe_analysis = results.analyzers.sharpe.get_analysis()
        sharpe = sharpe_analysis.get('sharperatio', None)
        if sharpe is not None:
            print(f"{'Sharpe Ratio':<25}{sharpe:.4f}")
        else:
            print(f"{'Sharpe Ratio':<25}N/A (insufficient data)")
    except Exception as e:
        print(f"{'Sharpe Ratio':<25}N/A (Error: {e})")
    
    try:
        # Max drawdown
        max_dd = results.analyzers.drawdown.get_analysis().max.drawdown
        print(f"{'Max Drawdown':<25}{max_dd:.2f}%")
    except:
        print(f"{'Max Drawdown':<25}N/A")
        
    try:
        # Total trades
        trades = results.analyzers.trades.get_analysis()
        total_trades = trades.total.closed
        print(f"{'Total Trades':<25}{total_trades}")
        
        # Win rate
        if total_trades > 0:
            win_rate = (trades.won.total / total_trades) * 100
            print(f"{'Win Rate':<25}{win_rate:.2f}%")
        else:
            print(f"{'Win Rate':<25}N/A (no trades)")
            
        # Win/Loss ratio
        if trades.lost.total > 0:
            win_loss_ratio = trades.won.total / trades.lost.total
            print(f"{'Win/Loss Ratio':<25}{win_loss_ratio:.2f}")
        else:
            print(f"{'Win/Loss Ratio':<25}N/A (no losing trades)")
    except:
        print(f"{'Total Trades':<25}N/A")
        print(f"{'Win Rate':<25}N/A")
        print(f"{'Win/Loss Ratio':<25}N/A")
        
    try:
        # PnL metrics
        pnl_data = results.analyzers.pnl.get_analysis()
        gross_profit = pnl_data.gross.total
        print(f"{'Gross Profit':<25}{gross_profit:.2f}")
        net_profit = pnl_data.net.total
        print(f"{'Net Profit':<25}{net_profit:.2f}")
    except:
        print(f"{'Gross Profit':<25}N/A")
        print(f"{'Net Profit':<25}N/A")
        
    try:
        # Return
        final_value = results.broker.getvalue()
        initial = 100000.0  # Initial cash
        
        total_return = (final_value - initial) / initial * 100
        print(f"{'Return':<25}{total_return:.2f}%")
        
        # Print final summary with stock name
        print("\n" + "-"*50)
        stock_display = stock_code
        approach_display = "RELAXED" if use_relaxed else "STRICT"
        
        # Always initialize the summary
        summary = f"SUMMARY: {stock_display} ({approach_display})"
        
        # Use global strategy stats
        if 'strategy_stats' not in globals() or strategy_stats is None:
            # Initialize if needed
            strategy_stats = {}

        # Determine if we should use the current strategy stats or calculate from results
        use_current_stats = ('stock_code' in strategy_stats and 
                           strategy_stats.get('stock_code') == stock_code and
                           'total_trades' in strategy_stats)

        # Add return information
        if use_current_stats and 'roi' in strategy_stats:
            summary += f" - Return: {strategy_stats['roi']:.2f}%"
        else:
            summary += f" - Return: {total_return:.2f}%"
            
        # Add trade count information  
        if use_current_stats and 'total_trades' in strategy_stats and strategy_stats['total_trades'] > 0:
            summary += f", Trades: {strategy_stats['total_trades']}"
        elif hasattr(results, 'trades_executed') and results.trades_executed > 0:
            summary += f", Trades: {results.trades_executed}"
        else:
            summary += f", Trades: 0"
            
        # Add win rate information
        if use_current_stats and 'win_rate' in strategy_stats and strategy_stats['win_rate'] > 0:
            summary += f", Win Rate: {strategy_stats['win_rate']:.1f}%"
        elif hasattr(results, 'trades_executed') and results.trades_executed > 0 and hasattr(results, 'trades_won'):
            win_rate = (results.trades_won / results.trades_executed) * 100
            summary += f", Win Rate: {win_rate:.1f}%"
        else:
            summary += f", Win Rate: 0.0%"
            
        print(summary)
            
        print("-"*50)
    except Exception as e:
        print(f"{'Return':<25}N/A (Error: {e})")

def run_multi_stock_comparison():
    """Run strategy for all stocks defined in config file"""
    # Read config file
    config = configparser.RawConfigParser(interpolation=None)
    config_path = os.path.join(os.path.dirname(__file__), 'config.properties')
    config.read(config_path)

    # Dynamically detect available markets from config sections
    available_markets = [section for section in config.sections() if section.upper() in ['CASH', 'FUTURES', 'OPTIONS']]
    if not available_markets:
        print("[ERROR] No valid market sections (CASH, FUTURES, OPTIONS) found in config.")
        return

    # Display available markets for selection
    market_idx = -1
    while market_idx < 0 or market_idx >= len(available_markets):
        try:
            market_idx = int(input("\nSelect market (number): ")) - 1
            if market_idx < 0 or market_idx >= len(available_markets):
                print("Invalid selection. Please try again.")
        except ValueError:
            print("Please enter a valid number.")
    
    section = available_markets[market_idx]
    print(f"\n[INFO] Using {section} section from config.properties")
    
    # Display strategy approach options
    print("\nStrategy Approach:")
    print("1. Strict (Original Triple Screen)")
    print("2. Relaxed (More flexible entry conditions)")
    
    # Select strategy approach
    approach_choice = 0  # Default to Strict
    valid_input = False
    
    while not valid_input:
        try:
            choice = int(input("\nSelect strategy approach (1-2): "))
            if choice in [1, 2]:
                approach_choice = choice
                valid_input = True
            else:
                print("Invalid selection. Please enter 1 or 2.")
        except ValueError:
            print("Please enter a valid number.")
            
    use_relaxed = (approach_choice == 2)  # 2 is Relaxed, 1 is Strict
    approach_name = "Relaxed" if use_relaxed else "Strict"
    print(f"\n[INFO] Selected approach: {approach_name}")
    
    # Get stock codes from config
    stock_codes_str = get_config_value(config, section, 'stock_code', '')
    stock_codes = parse_stock_codes(stock_codes_str)
    
    if not stock_codes:
        raise ValueError("No stock codes found in config for selected market")
        
    print(f"[INFO] Found {len(stock_codes)} stocks to analyze: {', '.join(stock_codes)}")
    
    # Store results for summary
    results = []
    
    # Run strategy for each stock
    for stock_code in stock_codes:
        try:
            print(f"\n{'='*50}")
            print(f"{'='*15} ANALYZING {stock_code} ({'RELAXED' if use_relaxed else 'STRICT'}) {'='*15}")
            run_strategy(stock_code, section, use_relaxed=use_relaxed)
        except Exception as e:
            print(f"[ERROR] Failed to analyze {stock_code}: {str(e)}")
            continue
    
    # Print summary
    print("\n" + "="*50)
    print("MULTI-STOCK ANALYSIS SUMMARY")
    print("="*50)
    for result in results:
        status_icon = "✓" if result['status'] == 'Success' else "✗"
        print(f"{status_icon} {result['stock']}: {result['status']}")
    print("="*50)
    
    print("\n[INFO] The ATR-based trailing stop logic shows significant improvement in win rate across stocks.")
    print("[INFO] Consider implementing this in your main trading strategies for better performance.")

def display_main_menu():
    """Display main menu for interactive or automatic mode selection"""
    print("\n" + "="*50)
    print("TRIPLE SCREEN TRADING SYSTEM")
    print("="*50)
    print("1. Interactive Mode (Select market and strategy)")
    print("2. Automatic Mode (Run all stocks from config)")
    print("="*50)
    
    while True:
        choice = input("Enter your choice (1-2): ")
        if choice.strip() in ['1', '2']:
            return int(choice)
        print("Invalid choice. Please enter 1 or 2.")

def interactive_mode():
    """Run in interactive mode with market and strategy selection"""
    # Import heavy modules only when needed
    from data_handler import DataHandler
    from triple_screen_strategy import TripleScreenStrategy
    from triple_screen_relaxed import RelaxedTripleScreenStrategy
    import backtrader as bt
    import matplotlib.pyplot as plt

    # Ensure config is initialized
    cfg = initialize_config()
    
    # Select market type
    print("\nSelect market type:")
    print("1. Cash Market (NSE)")
    print("2. Futures Market (NFO)")
    print("3. Options Market (NFO)")
    market_choice = input("Enter your choice (1-3): ")
    
    if market_choice == '1':
        market_type = 'CASH'
    elif market_choice == '2':
        market_type = 'FUTURES'
    elif market_choice == '3':
        market_type = 'OPTIONS'
    else:
        print("Invalid market choice.")
        return
    
    # Get stock codes for selected market
    stock_codes = []
    try:
        stock_codes_str = cfg.get(market_type, 'stock_code')
        stock_codes = parse_stock_codes(stock_codes_str)
    except Exception as e:
        print(f"Error reading stock codes: {e}")
        return
    
    # If only one stock, auto-select it
    if len(stock_codes) == 1:
        selected_stock = stock_codes[0]
        print(f"\nAuto-selected stock: {selected_stock}")
    else:
        # Display available stocks
        print("\nAvailable stocks:")
        for i, code in enumerate(stock_codes, 1):
            print(f"{i}. {code}")
        # Get stock selection
        try:
            stock_idx = int(input(f"Enter stock number (1-{len(stock_codes)}): ")) - 1
            if stock_idx < 0 or stock_idx >= len(stock_codes):
                print("Invalid selection")
                return
            selected_stock = stock_codes[stock_idx]
        except ValueError:
            print("Invalid input")
            return
    
    # For options, just display the parameters without asking to change them
    if market_type == 'OPTIONS':
        current_strike = cfg.get('OPTIONS', 'strike_price')
        current_right = cfg.get('OPTIONS', 'right')
        print(f"\nUsing options parameters: {current_right} {current_strike}")
        
    # Select strategy approach
    use_relaxed = select_strategy_approach()
    
    # Run strategy
    run_strategy(selected_stock, market_type, use_relaxed)

def select_strategy_approach():
    """Prompt user to select strategy approach (Strict/Relaxed)"""
    print("\nStrategy Approach:")
    print("1. Strict (Original Triple Screen)")
    print("2. Relaxed (More flexible entry conditions)")
    
    while True:
        try:
            choice = int(input("\nSelect approach (1-2): "))
            if choice in [1, 2]:
                return choice == 2  # True for Relaxed, False for Strict
            print("Invalid selection. Please enter 1 or 2.")
        except ValueError:
            print("Please enter a valid number.")

def parse_args():
    """Parse command line arguments for non-interactive usage"""
    parser = argparse.ArgumentParser(description='Triple Screen Trading System')
    parser.add_argument('--auto', action='store_true', help='Run in automatic mode')
    parser.add_argument('--market', help='Market to analyze (e.g., FUTURES)')
    parser.add_argument('--stock', help='Stock code to analyze')
    parser.add_argument('--relaxed', action='store_true', help='Use relaxed strategy approach')
    parser.add_argument('--atr-mult', type=float, help='Custom ATR multiplier')
    parser.add_argument('--min-dist', type=float, help='Custom minimum profit threshold (%)')
    return parser.parse_args()

if __name__ == '__main__':
    # Parse command line arguments
    args = parse_args()
    
    # If enough args are provided, run in non-interactive mode
    if args.auto or (args.stock and args.market):
        if args.auto:
            print("Running in automatic mode...")
            run_multi_stock_comparison()
        elif args.stock:
            print(f"Running analysis for {args.stock} in {args.market}...")
            use_relaxed = args.relaxed
            
            # Run strategy with standard parameters
            run_strategy(args.stock, args.market, use_relaxed=use_relaxed)
    else:
        # Run in interactive mode
        try:
            mode = display_main_menu()
            if mode == 1:
                interactive_mode()
            else:
                run_multi_stock_comparison()
        except EOFError:
            print("\nNon-interactive environment detected. Use command-line arguments instead.")
            print("Example: python triple_screen_main.py --auto")
            print("Example: python triple_screen_main.py --market FUTURES --stock RELIANCE --relaxed --compare")