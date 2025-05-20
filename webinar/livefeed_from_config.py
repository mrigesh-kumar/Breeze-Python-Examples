"""
LIVEFEED FROM CONFIGURATION
--------------------------
This script reads all configuration values (API credentials, instrument details, etc.) from config.properties and connects to the Breeze WebSocket for live market data feed. No user prompts are required—everything is loaded from the config file.
"""

from breeze_connect import BreezeConnect
from datetime import datetime
import os
import sys
import time
import threading
import pandas as pd
import numpy as np
from app_config import load_config

# Import Triple Screen strategy components
try:
    from triple_screen_strategy import TripleScreenStrategy
    from triple_screen_relaxed import TripleScreenRelaxedStrategy
    # If there's a data handler class, import it too
    try:
        from data_handler import DataHandler
    except ImportError:
        print("DataHandler module not found, will use direct data processing")
except ImportError:
    print("WARNING: Triple Screen strategy modules not found.")
    print("Will only collect data in DataFrame format.")

# NEW: Prompt user for market type (Cash/Futures/Options) and strategy approach
section_map = {'1': 'CASH', '2': 'FUTURES', '3': 'OPTIONS'}
print("Select Market Type:\n1. Cash\n2. Futures\n3. Options")
market_choice = input("Enter choice (1/2/3) [default 3]: ").strip()
market_section = section_map.get(market_choice, 'OPTIONS')

print("Select Strategy Approach:\n1. Strict\n2. Relaxed")
strategy_choice = input("Enter choice (1/2) [default 1]: ").strip()
selected_approach = 'relaxed' if strategy_choice == '2' else 'strict'

# Load configuration for the chosen section
config = load_config(config_file='config.properties', section=market_section)

# Fallback to DEFAULT if not present
if not config:
    print("[ERROR] Could not load configuration. Exiting.")
    sys.exit(1)

# Inject/override strategy approach selected by user
config['strategy_approach'] = selected_approach

# Credentials
api_key = config.get('app_key')
api_secret = config.get('secret_key')
api_session = config.get('session_token')

# Prompt for credentials if placeholders or empty
if not api_key or 'INSERT' in str(api_key):
    api_key = input('Enter your Breeze API Key: ').strip()
if not api_secret or 'INSERT' in str(api_secret):
    api_secret = input('Enter your Breeze API Secret: ').strip()
if not api_session or 'INSERT' in str(api_session):
    api_session = input('Enter your Breeze Session Token: ').strip()

# Connect to Breeze API
breeze = BreezeConnect(api_key=api_key)

# Attempt to generate session, retry on failure once interactively
while True:
    try:
        breeze.generate_session(api_secret=api_secret, session_token=api_session)
        break
    except Exception as ex:
        print(f"[ERROR] Breeze session error -> {ex}")
        retry = input('Retry with a different session token? (y/N): ').strip().lower()
        if retry == 'y':
            api_session = input('Enter new Breeze Session Token: ').strip()
            continue
        else:
            print('Exiting due to session initialization failure.')
            sys.exit(1)

# Set interval before any token operations
breeze.interval = config.get('interval', '1minute')

# Enable debug mode
breeze.debug = True

# Connect to WebSocket
print("Connecting to WebSocket...")
breeze.ws_connect()
print("WebSocket connection established")

# Global DataFrame to store live feed data
live_data = pd.DataFrame(columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
strategy_instance = None

# Import necessary libraries for our simplified strategy
try:
    import pandas_ta as ta
except ImportError:
    ta = None
    print("pandas_ta is not installed. Some features may be disabled.")

# Detect TA-Lib availability
try:
    import talib
    HAS_TALIB = True
except ImportError:
    HAS_TALIB = False

# Simplified Triple Screen strategy for live data
class LiveTripleScreenStrategy:
    def __init__(self, stock_code, atr_multiplier=1.5, min_profit_threshold=0.005, approach='strict'):
        self.stock_code = stock_code
        self.atr_multiplier = atr_multiplier
        self.min_profit_threshold = min_profit_threshold
        self.approach = approach.lower()
        self.last_signal = None
        self.last_signal_time = None
        self.last_signal_price = None
        print(f"Initialized Live Triple Screen Strategy ({approach}) for {stock_code}")
        print(f"ATR Multiplier: {atr_multiplier}, Min Profit Threshold: {min_profit_threshold*100}%")
    
    def _calculate_indicators(self, data):
        """Calculate technical indicators for the strategy"""
        df = data.copy()
        
        # Calculate basic indicators
        if HAS_TALIB:
            # Calculate MACD
            macd, macd_signal, macd_hist = talib.MACD(
                df['close'].values, fastperiod=12, slowperiod=26, signalperiod=9
            )
            df['macd'] = macd
            df['macd_signal'] = macd_signal
            df['macd_hist'] = macd_hist
            
            # Calculate RSI
            df['rsi'] = talib.RSI(df['close'].values, timeperiod=14)
            
            # Calculate Stochastic
            df['slowk'], df['slowd'] = talib.STOCH(
                df['high'].values, df['low'].values, df['close'].values,
                fastk_period=14, slowk_period=3, slowk_matype=0, slowd_period=3, slowd_matype=0
            )
            
            # Calculate ATR for trailing stops
            df['atr'] = talib.ATR(
                df['high'].values, df['low'].values, df['close'].values, timeperiod=14
            )
            
            # Calculate EMA for trend direction
            df['ema20'] = talib.EMA(df['close'].values, timeperiod=20)
            df['ema50'] = talib.EMA(df['close'].values, timeperiod=50)
        else:
            # Use pandas-ta as fallback
            macd = df.ta.macd(close='close', fast=12, slow=26, signal=9)
            df = df.join(macd)
            df.rename(columns={"MACD_12_26_9": "macd", "MACDs_12_26_9": "macd_signal", "MACDh_12_26_9": "macd_hist"}, inplace=True)
            
            df['rsi'] = df.ta.rsi(close='close', length=14)
            
            stoch = df.ta.stoch(high='high', low='low', close='close', k=14, d=3, smooth_k=3)
            df = df.join(stoch)
            df.rename(columns={"STOCHk_14_3_3": "slowk", "STOCHd_14_3_3": "slowd"}, inplace=True)
            
            df['atr'] = df.ta.atr(high='high', low='low', close='close', length=14)
            
            df['ema20'] = df.ta.ema(close='close', length=20)
            df['ema50'] = df.ta.ema(close='close', length=50)
        
        return df
    
    def generate_signals(self, data):
        """Generate trading signals based on the Triple Screen approach"""
        if len(data) < 50:  # Need enough data for reliable signals
            return None
            
        # Calculate all indicators
        df = self._calculate_indicators(data)
        
        # Get the current and previous data points
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Initialize signal components
        signal = None
        confidence = 0
        reasons = []
        
        # Basic trend analysis
        price_above_ema20 = current['close'] > current['ema20']
        price_above_ema50 = current['close'] > current['ema50']
        ema20_above_ema50 = current['ema20'] > current['ema50']
        
        # MACD analysis
        macd_rising = current['macd'] > prev['macd']
        macd_above_signal = current['macd'] > current['macd_signal']
        macd_crossover = (prev['macd'] < prev['macd_signal']) and (current['macd'] > current['macd_signal'])
        
        # RSI analysis
        rsi_above_50 = current['rsi'] > 50
        rsi_rising = current['rsi'] > prev['rsi']
        
        # Stochastic analysis
        stoch_rising = current['slowk'] > prev['slowk']
        stoch_above_20 = current['slowk'] > 20
        stoch_below_80 = current['slowk'] < 80
        stoch_crossover = (prev['slowk'] < prev['slowd']) and (current['slowk'] > current['slowd'])
        
        # Different signal generation based on strategy approach
        if self.approach == 'strict':
            # Strict Triple Screen approach (Elder's original method)
            # BUY signals
            if (price_above_ema50 and  # Weekly trend is up
                macd_above_signal and   # Daily momentum is positive
                rsi_above_50 and        # RSI confirms momentum
                stoch_crossover and     # Stochastics timing entry
                stoch_below_80):        # Not overbought
                
                signal = "BUY"
                confidence = 0.8
                reasons.append("Strict Triple Screen buy conditions met")
                if macd_crossover:
                    confidence += 0.1
                    reasons.append("MACD bullish crossover")
                if ema20_above_ema50:
                    confidence += 0.1
                    reasons.append("EMA20 above EMA50 (golden cross)")
            
            # SELL signals for existing positions (simplified)
            elif (not price_above_ema50 or
                  (not macd_above_signal and not rsi_above_50) or
                  stoch_above_80):
                signal = "SELL"
                confidence = 0.7
                reasons.append("Strict Triple Screen sell conditions met")
                if current['close'] < current['ema50']:
                    confidence += 0.2
                    reasons.append("Price below EMA50 (trend reversal)")
        
        else:  # Relaxed approach
            # More generous entry conditions
            conditions_met = 0
            if price_above_ema20: conditions_met += 1
            if macd_rising: conditions_met += 1
            if macd_above_signal: conditions_met += 1
            if rsi_rising: conditions_met += 1
            if rsi_above_50: conditions_met += 1
            if stoch_rising and stoch_above_20: conditions_met += 1
            
            # BUY if majority of conditions are met
            if conditions_met >= 4:  # At least 4 of 6 conditions
                signal = "BUY"
                confidence = 0.5 + (conditions_met - 4) * 0.1  # 0.5 to 0.7 based on conditions
                reasons.append(f"Relaxed approach: {conditions_met}/6 conditions met")
                
                if macd_crossover:
                    confidence += 0.1
                    reasons.append("MACD bullish crossover")
                if stoch_crossover:
                    confidence += 0.1
                    reasons.append("Stochastic bullish crossover")
            
            # SELL signals (relaxed approach)
            elif conditions_met <= 2:  # 2 or fewer conditions met
                signal = "SELL"
                confidence = 0.5 + (2 - conditions_met) * 0.1
                reasons.append(f"Relaxed approach: only {conditions_met}/6 conditions met")
        
        # If we have a signal and a valid price
        if signal and not pd.isna(current['close']):
            # Don't repeat signals within short periods
            current_time = datetime.now()
            if (self.last_signal == signal and 
                self.last_signal_time and 
                (current_time - self.last_signal_time).total_seconds() < 300):  # 5 minutes
                return None
                
            # Update last signal info
            self.last_signal = signal
            self.last_signal_time = current_time
            self.last_signal_price = current['close']
            
            return {
                'action': signal,
                'price': current['close'],
                'confidence': round(min(confidence, 0.99), 2),
                'reason': "; ".join(reasons),
                'atr': current['atr'],
                'timestamp': current_time
            }
        
        return None

# Global strategy instance
strategy_instance = None

# ----------------------
# Trading helper methods
# ----------------------

def execute_trade(signal):
    """Execute trade via Breeze if sufficient funds are available"""
    action = signal['action'].lower()
    price = signal['price']

    # Default quantity (can be configured in properties)
    quantity = int(config.get('default_quantity', 1))
    trade_value = price * quantity

    # Fetch available funds
    try:
        funds_resp = breeze.get_funds()
        available_funds = None
        if isinstance(funds_resp, dict) and 'Success' in funds_resp:
            success_data = funds_resp['Success']
            # Success can be dict or list depending on Breeze version
            if isinstance(success_data, dict):
                available_funds = float(success_data.get('net_margin_available', success_data.get('available_cash', 0)))
            elif isinstance(success_data, list) and success_data:
                available_funds = float(success_data[0].get('net_margin_available', success_data[0].get('available_cash', 0)))
        if available_funds is None:
            print("[WARN] Could not determine available funds from response, proceeding with caution.")
            available_funds = 0.0
    except Exception as ex:
        print(f"[ERROR] Unable to fetch funds: {ex}. Proceeding without funds check.")
        available_funds = 0.0

    # Check funds
    if available_funds and trade_value > available_funds:
        print(f"[WARN] Insufficient funds (Required: {trade_value:.2f}, Available: {available_funds:.2f}). Trade skipped.")
        return

    # Prepare order params
    order_params = {
        'stock_code': config.get('stock_code', 'stock_code'),
        'exchange_code': config.get('exchange_code', 'NSE'),
        'product': config.get('product_type', 'cash').lower(),
        'action': action,
        'order_type': 'market',
        'stoploss': '',
        'quantity': str(quantity),
        'price': '',
        'validity': 'day'
    }
    if config.get('product_type', 'cash').lower() == 'options':
        order_params.update({
            'expiry_date': config.get('expiry_date', 'expiry_date'),
            'right': config.get('right', 'right'),
            'strike_price': config.get('strike_price', 'strike_price')
        })
    try:
        resp = breeze.place_order(**order_params)
        print(f"[ORDER] Response: {resp}")
    except Exception as ex:
        print(f"[ERROR] Failed to place order: {ex}")

def process_strategy(data):
    """Process the latest data with the simplified Triple Screen Strategy"""
    global strategy_instance
    
    # Initialize strategy if needed
    if strategy_instance is None:
        # Get configuration parameters
        approach = config.get('strategy_approach', 'strict').lower()
        atr_multiplier = float(config.get('atr_multiplier', 1.5))
        min_profit_threshold = float(config.get('min_profit_threshold', 0.5))/100
        
        # Create our simplified strategy instance that doesn't require Backtrader
        strategy_instance = LiveTripleScreenStrategy(
            stock_code=config.get('stock_code', 'stock_code'),
            atr_multiplier=atr_multiplier,
            min_profit_threshold=min_profit_threshold,
            approach=approach
        )
    
    # Process data and generate signals
    try:
        signal = strategy_instance.generate_signals(data)
        if signal:
            print(f"\n🚨 SIGNAL ALERT - {signal['timestamp']}")
            print(f"Strategy: Triple Screen {strategy_instance.approach.capitalize()}")
            print(f"Signal: {signal['action']} {config.get('stock_code', 'stock_code')} at ₹{signal['price']:.2f}")
            print(f"Confidence: {signal['confidence']}")
            print(f"ATR: {signal['atr']:.2f}")
            print(f"Reason: {signal['reason']}")
            print("---------------------------------------")
            
            # AUTO TRADE EXECUTION
            execute_trade(signal)
    except Exception as e:
        print(f"Error processing strategy: {e}")
        import traceback
        traceback.print_exc()

def on_event_data(ticks):
    """Process incoming tick data"""
    global live_data
    
    try:
        # We now know the Breeze API sends OHLC data in dictionary format
        if isinstance(ticks, dict):
            # Extract timestamp from the data or use current time
            timestamp = datetime.strptime(ticks.get('datetime', datetime.now().strftime('%Y-%m-%d %H:%M:%S')), 
                                         '%Y-%m-%d %H:%M:%S') if 'datetime' in ticks else datetime.now()
            
            # Extract OHLC data - the Breeze API already provides this format
            if all(key in ticks for key in ['open', 'high', 'low', 'close']):
                # We have complete OHLC data
                open_price = float(ticks.get('open', 0))
                high_price = float(ticks.get('high', 0))
                low_price = float(ticks.get('low', 0))
                close_price = float(ticks.get('close', 0))
                
                # Extract volume and open interest if available
                volume = int(ticks.get('volume', 0))
                oi = int(ticks.get('oi', 0)) if 'oi' in ticks else None
                
                # Create a new row with a complete dictionary (avoids pandas warning)
                row_dict = {
                    'datetime': timestamp,
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'close': close_price,
                    'volume': volume
                }
                
                # Add OI if available
                if oi is not None:
                    row_dict['oi'] = oi
                    
                # Create a new DataFrame row with typed data
                new_data = pd.DataFrame([row_dict])
                
                # Concat with existing data, ensuring proper dtypes
                if live_data.empty:
                    live_data = new_data
                else:
                    # Use a dtype-preserving approach
                    live_data = pd.concat([live_data, new_data], ignore_index=True)
                
                # Keep only the last 1000 records to manage memory
                if len(live_data) > 1000:
                    live_data = live_data.tail(1000)
                
                # Print data update in consistent format for monitoring
                print(f"[TICK] {timestamp.strftime('%H:%M:%S')} | {config.get('stock_code', 'stock_code')} | O:{open_price:.2f} H:{high_price:.2f} L:{low_price:.2f} C:{close_price:.2f} | Vol:{volume}" + 
                      (f" | OI:{oi}" if oi is not None else ""))
                
                # Process with strategy if we have enough data
                # This ensures compatibility with your existing backtesting code
                if len(live_data) >= 20:  # Need minimum data for indicators
                    process_strategy(live_data)
            else:
                print(f"[WARNING] Incomplete OHLC data received: {ticks}")
        else:
            print(f"[WARNING] Unexpected data format: {type(ticks)} - {ticks}")
    except Exception as e:
        print(f"Error in on_event_data: {e}")
        import traceback
        traceback.print_exc()

# Heartbeat function to confirm script is still running
def heartbeat():
    while True:
        print(f"[HEARTBEAT] Still connected and waiting for data... {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(30)

breeze.on_ticks = on_event_data

# Verify stock exists
print(f"Verifying stock: {config.get('stock_code', 'stock_code')} on {config.get('exchange_code', 'NSE')}")
print("Subscribing with params:")
print("exchange_code:", config.get('exchange_code', 'NSE'))
print("stock_code:", config.get('stock_code', 'stock_code'))
print("product_type:", config.get('product_type', 'cash').lower())
print("expiry_date:", config.get('expiry_date', 'expiry_date'))
print("strike_price:", config.get('strike_price', 'strike_price'))
print("right:", config.get('right', 'right'))
print("interval:", config.get('interval', '1minute'))
# Subscribe to live market data
if config.get('product_type', 'cash').lower() == "options":
    breeze.subscribe_feeds(
        exchange_code=config.get('exchange_code', 'NSE'),
        stock_code=config.get('stock_code', 'stock_code'),
        product_type=config.get('product_type', 'cash').lower(),
        expiry_date=config.get('expiry_date', 'expiry_date'),
        strike_price=config.get('strike_price', 'strike_price'),
        right=config.get('right', 'right'),
        interval=config.get('interval', '1minute'),
        get_market_depth=False,
        get_exchange_quotes=True
    )
else:
    breeze.subscribe_feeds(
        exchange_code=config.get('exchange_code', 'NSE'),
        stock_code=config.get('stock_code', 'stock_code'),
        product_type=config.get('product_type', 'cash').lower(),
        expiry_date=config.get('expiry_date', 'expiry_date')
    )

print("\nSubscription completed successfully. Waiting for data...")
print("Triple Screen Strategy integration is ready.")
print("If no data appears, it might be because:")
print("1. The market is closed or the instrument isn't actively trading")
print("2. There's an issue with the WebSocket connection")
print("3. The subscription parameters aren't matching any active instrument")
print("\nStarting heartbeat to monitor connection...")

# Add strategy configuration information
print("\nStrategy Configuration:")
print(f"Stock: {config.get('stock_code', 'stock_code')} on {config.get('exchange_code', 'NSE')}")
print(f"Product Type: {config.get('product_type', 'cash').lower()}")
if config.get('product_type', 'cash').lower() == 'options':
    print(f"Expiry: {config.get('expiry_date', 'expiry_date')}")
    print(f"Strike: {config.get('strike_price', 'strike_price')} {config.get('right', 'right')}")
print(f"Strategy Approach: {config.get('strategy_approach', 'strict')}")
print(f"ATR Multiplier: {config.get('atr_multiplier', '1.5')}")
print(f"Min Profit Threshold: {config.get('min_profit_threshold', '0.5')}%")

# Start the heartbeat thread
heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
heartbeat_thread.start()

input("\nPress Enter to exit...\n")
