"""
LIVEFEED FROM CONFIGURATION
--------------------------
This script reads all configuration values (API credentials, instrument details, etc.) from config.properties and connects to the Breeze WebSocket for live market data feed. No user prompts are required—everything is loaded from the config file.
"""

# --- FAST PROMPT SECTION (move to top for instant user feedback) ---
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
section_map = {'1': 'CASH', '2': 'FUTURES', '3': 'OPTIONS'}
print("Select Market Type:\n1. Cash\n2. Futures\n3. Options")
market_choice = input("Enter choice (1/2/3) [default 3]: ").strip()
market_section = section_map.get(market_choice, 'OPTIONS')

print("Select Strategy Approach:\n1. Strict\n2. Relaxed")
strategy_choice = input("Enter choice (1/2) [default 1]: ").strip()
selected_approach = 'relaxed' if strategy_choice == '2' else 'strict'

from breeze_connect import BreezeConnect
from datetime import datetime, timezone
import time
import threading
import pandas as pd
import numpy as np
from app_config import load_config
from dateutil import parser as dt_parser

# --- Import Breeze API action templates ---
from breeze_templates import (
    set_breeze_instance, cancel_order, modify_order, get_portfolio_positions,
    square_off_futures, preview_order, get_order_detail, get_order_list
)

# Import Triple Screen strategy components
try:
    from triple_screen_strategy import TripleScreenStrategy
    from triple_screen_relaxed import RelaxedTripleScreenStrategy
    # If there's a data handler class, import it too
    try:
        from data_handler import DataHandler
    except ImportError:
        print("DataHandler module not found, will use direct data processing")
except ImportError:
    print("WARNING: Triple Screen strategy modules not found.")
    print("Will only collect data in DataFrame format.")

# Load configuration for the chosen section
config = load_config(config_file='config.properties', section=market_section)

# Fallback to DEFAULT if not present
if not config:
    print("[ERROR] Could not load configuration. Exiting.")
    sys.exit(1)

# Inject/override strategy approach selected by user
config['strategy_approach'] = selected_approach

# --- Fix for CASH and FUTURES market: prompt user to select one stock code ---
if config.get('product_type', '').lower() in ['cash', 'futures']:
    stock_codes = [s.strip().replace('"', '') for s in config.get('stock_code', '').split(',')]
    print("Select Stock:")
    for idx, code in enumerate(stock_codes, 1):
        print(f"{idx}. {code}")
    choice = input(f"Enter stock number (1-{len(stock_codes)}) [default 1]: ").strip()
    try:
        selected_idx = int(choice) - 1 if choice else 0
        selected_stock = stock_codes[selected_idx]
    except Exception:
        selected_stock = stock_codes[0]
    config['stock_code'] = selected_stock


# Credentials
api_key = config.get('app_key')
api_secret = config.get('secret_key')
api_session = config.get('session_token')

# Path to cache Breeze access token to reduce API calls
SESSION_CACHE_FILE = os.path.expanduser('~/.breeze_access_token')
cached_access_token = None
if os.path.exists(SESSION_CACHE_FILE):
    try:
        with open(SESSION_CACHE_FILE, 'r') as f:
            cached_access_token = f.read().strip()
            if cached_access_token == '':
                cached_access_token = None
    except Exception as e:
        print(f"[WARN] Could not read session cache: {e}")

breeze = BreezeConnect(api_key=api_key)
set_breeze_instance(breeze)

# Prompt for credentials if placeholders or empty
if not api_key or 'INSERT' in str(api_key):
    api_key = input('Enter your Breeze API Key: ').strip()
if not api_secret or 'INSERT' in str(api_secret):
    api_secret = input('Enter your Breeze API Secret: ').strip()
if not api_session or 'INSERT' in str(api_session):
    api_session = input('Enter your Breeze Session Token: ').strip()

# Connect to Breeze API
breeze = BreezeConnect(api_key=api_key)

# Use cached access token if available, else generate new session (counts towards API rate-limits)
used_cached_token = False
if cached_access_token:
    try:
        breeze.set_access_token(access_token=cached_access_token)
        used_cached_token = True
        print("[INFO] Re-using cached Breeze access token → no session generation call made.")
    except Exception as e:
        print(f"[WARN] Cached token invalid → {e}. Will fetch a fresh token.")
        cached_access_token = None  # Fallthrough to generation section

# If no valid cached access token, fall back to generate_session (single API hit) and cache the token
if not used_cached_token:
    # Attempt to generate session, retry on failure once interactively
    while True:
        try:
            session_resp = breeze.generate_session(api_secret=api_secret, session_token=api_session)
            new_access_token = session_resp.get('access_token') if isinstance(session_resp, dict) else None
            if new_access_token:
                try:
                    with open(SESSION_CACHE_FILE, 'w') as f:
                        f.write(new_access_token)
                    print(f"[INFO] Cached new Breeze access token to {SESSION_CACHE_FILE}")
                except Exception as e:
                    print(f"[WARN] Could not cache access token: {e}")
                breeze.set_access_token(access_token=new_access_token)
            break
        except Exception as ex:
            print(f"[ERROR] Breeze session error → {ex}")
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

# Global DataFrame to store live feed data
live_data = pd.DataFrame(columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])

# --------------------------------------------------------
# 1. Pre-populate live_data with historical candles (optional)
# --------------------------------------------------------
#   We fetch candles from `from_date` (config) up to "now" (script start)
#   so that indicators (EMA, MACD, ATR, etc.) have warm-up data and
#   signals are immediately valid once the live stream begins.
# --------------------------------------------------------

def preload_historical_data():
    """Fetch historical candles using Breeze REST API and append to live_data."""

    from_date_str = config.get('from_date', '').strip()
    to_date_str = config.get('to_date', '').strip()

    if not from_date_str:
        print("[INFO] No from_date provided – skipping historical preload.")
        return

    try:
        from_dt = dt_parser.isoparse(from_date_str)
    except Exception as ex:
        print(f"[WARN] Could not parse from_date '{from_date_str}': {ex}. Skipping preload.")
        return

    # If to_date is missing or set in the future, use current time
    to_dt = None
    if to_date_str:
        try:
            to_dt = dt_parser.isoparse(to_date_str)
        except Exception as ex:
            print(f"[WARN] Could not parse to_date '{to_date_str}': {ex}. Using now().")
            to_dt = None
    if to_dt is None:
        to_dt = datetime.now(timezone.utc)
    else:
        # If parsed to_dt is naive, attach UTC tz
        if to_dt.tzinfo is None or to_dt.tzinfo.utcoffset(to_dt) is None:
            to_dt = to_dt.replace(tzinfo=timezone.utc)
    now_utc = datetime.now(timezone.utc)
    if to_dt > now_utc:
        to_dt = now_utc

    interval = config.get('interval', '1minute')
    stock_code = config.get('stock_code', 'stock_code')
    exchange_code = config.get('exchange_code', 'NSE')
    product_type = config.get('product_type', 'cash').lower()

    print(f"[INFO] Preloading historical candles for {stock_code} ({exchange_code}) from {from_dt} to {to_dt} @ {interval}...")

    try:
        hist_resp = breeze.get_historical_data(
            interval=interval,
            from_date=from_dt.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            to_date=to_dt.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            stock_code=stock_code,
            exchange_code=exchange_code,
            product_type=product_type,
            # Historical API needs expiry_date for derivatives. For futures it must be ISO format
            expiry_date=(
                # Convert dd-MMM-yyyy -> YYYY-MM-DDT00:00:00.000Z for futures
                dt_parser.parse(config.get('expiry_date')).strftime('%Y-%m-%dT%H:%M:%S.000Z')
                if (product_type == 'futures' and config.get('expiry_date'))
                else (config.get('expiry_date') if product_type == 'options' else None)
            ),
            right=config.get('right') if product_type == 'options' else None,
            strike_price=config.get('strike_price') if product_type == 'options' else None,
        )

        if not hist_resp or 'Success' not in hist_resp:
            print(f"[WARN] Historical API returned empty response – no preload data.")
            return

        candles = hist_resp['Success']
        if not isinstance(candles, list):
            print("[WARN] Unexpected historical response format – skipping preload.")
            return

        rows = []
        for c in candles:
            try:
                rows.append({
                    'datetime': dt_parser.isoparse(c['datetime']) if 'datetime' in c else dt_parser.isoparse(c['dateTime']),
                    'open': float(c['open']) if 'open' in c else float(c['Open']),
                    'high': float(c['high']) if 'high' in c else float(c['High']),
                    'low': float(c['low']) if 'low' in c else float(c['Low']),
                    'close': float(c['close']) if 'close' in c else float(c['Close']),
                    'volume': float(c.get('volume', c.get('Volume', 0)))
                })
            except Exception:
                # Skip malformed candle
                continue

        if rows:
            df_hist = pd.DataFrame(rows)
            df_hist.sort_values('datetime', inplace=True)
            global live_data
            if live_data.empty:
                live_data = df_hist.copy()
            else:
                live_data = pd.concat([live_data, df_hist], ignore_index=True)
            print(f"[INFO] Preloaded {len(df_hist)} historical candles.")
        else:
            print("[INFO] No historical rows parsed – skipping.")

    except Exception as ex:
        print(f"[ERROR] Failed to preload historical data: {ex}")

# Call the preload BEFORE connecting to websocket so indicators are warm
preload_historical_data()

# Connect to WebSocket
print("Connecting to WebSocket...")
breeze.ws_connect()
print("WebSocket connection established")

# Global strategy instance
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
            # Use pandas_ta module-level functions to avoid DataFrame.ta dependency
            if ta is None:
                raise ImportError("pandas_ta not available; please install with 'pip install pandas-ta'.")
            
            # MACD
            macd_df = ta.macd(df['close'], fast=12, slow=26, signal=9)
            df = pd.concat([df, macd_df], axis=1)
            df.rename(columns={"MACD_12_26_9": "macd", "MACDs_12_26_9": "macd_signal", "MACDh_12_26_9": "macd_hist"}, inplace=True)
            
            # RSI
            df['rsi'] = ta.rsi(df['close'], length=14)
            
            # Stochastic
            stoch_df = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
            df = pd.concat([df, stoch_df], axis=1)
            df.rename(columns={"STOCHk_14_3_3": "slowk", "STOCHd_14_3_3": "slowd"}, inplace=True)
            
            # ATR
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

            # EMA 20 & EMA 50
            df['ema20'] = ta.ema(df['close'], length=20)
            df['ema50'] = ta.ema(df['close'], length=50)

        # Add Support/Resistance (20-bar swing low/high)
        window = 20
        df['support'] = df['low'].rolling(window=window, min_periods=1).min()
        df['resistance'] = df['high'].rolling(window=window, min_periods=1).max()
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
        stoch_above_80 = current['slowk'] > 80
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
                # --- Support filter ---
                if current['close'] > current.get('support', float('-inf')):
                    signal = "BUY"
                    confidence = 0.8
                    reasons.append("Strict Triple Screen buy conditions met")
                    if macd_crossover:
                        confidence += 0.1
                        reasons.append("MACD bullish crossover")
                    if ema20_above_ema50:
                        confidence += 0.1
                        reasons.append("EMA20 above EMA50 (golden cross)")
                else:
                    reasons.append(f"Entry BLOCKED: Price {current['close']:.2f} not above Support {current.get('support',float('nan')):.2f}")

            
            # SELL signals for existing positions (simplified)
            elif (not price_above_ema50 or
                  (not macd_above_signal and not rsi_above_50) or
                  stoch_above_80):
                # --- Resistance filter ---
                if current['close'] < current.get('resistance', float('inf')):
                    signal = "SELL"
                    confidence = 0.7
                    reasons.append("Strict Triple Screen sell conditions met")
                    if current['close'] < current['ema50']:
                        confidence += 0.2
                        reasons.append("Price below EMA50 (trend reversal)")
                else:
                    reasons.append(f"Entry BLOCKED: Price {current['close']:.2f} not below Resistance {current.get('resistance',float('nan')):.2f}")

            # --- S/R-based profit target/exit logic ---
            # If in BUY position and price nears resistance, recommend exit
            if self.last_signal == "BUY" and current['close'] >= current.get('resistance', float('inf')) * 0.995:
                signal = "SELL"
                confidence = 0.9
                reasons.append(f"Profit target: Price {current['close']:.2f} near Resistance {current.get('resistance',float('nan')):.2f}")
            # If in SELL position and price nears support, recommend exit
            if self.last_signal == "SELL" and current['close'] <= current.get('support', float('-inf')) * 1.005:
                signal = "BUY"
                confidence = 0.9
                reasons.append(f"Profit target: Price {current['close']:.2f} near Support {current.get('support',float('nan')):.2f}")

        
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

# ----------------------
# Trading helper methods
# ----------------------

def execute_trade(signal):
    """Execute trade via Breeze if sufficient funds are available"""
    action = signal['action'].lower()
    price = signal['price']

    # Order quantity from config (must be a multiple of contract lot size)
    quantity = int(config.get('quantity', config.get('default_quantity', 1)))
    trade_value = price * quantity

    # Fetch available funds
    try:
        funds_resp = breeze.get_funds()
        print(f"[DEBUG] funds_resp: {funds_resp}")
        available_funds = None
        if isinstance(funds_resp, dict) and 'Success' in funds_resp:
            success_data = funds_resp['Success']
            # Handle dict or list response
            if isinstance(success_data, list) and success_data:
                success_data = success_data[0]
            if isinstance(success_data, dict):
                # Priority: net_margin_available > available_cash > allocated_fno (for F&O) > unallocated_balance
                if 'net_margin_available' in success_data:
                    available_funds = float(success_data['net_margin_available'])
                elif 'available_cash' in success_data:
                    available_funds = float(success_data['available_cash'])
                elif config.get('product_type','').lower() in ('options','futures') and 'allocated_fno' in success_data:
                    available_funds = float(success_data['allocated_fno'])
                elif 'unallocated_balance' in success_data:
                    available_funds = float(success_data['unallocated_balance'])
                else:
                    available_funds = 0.0
        if available_funds is None:
            print("[WARN] Could not determine available funds from response, proceeding with caution.")
            available_funds = 0.0
    except Exception as ex:
        print(f"[ERROR] Unable to fetch funds: {ex}. Proceeding without funds check.")
        available_funds = 0.0

    # Debug: show required trade value and available funds
    print(f"[DEBUG] Required trade value: ₹{trade_value:.2f}, Available funds: ₹{available_funds:.2f}")
    # Check funds and margin limits
    if available_funds and trade_value > available_funds:
        print(f"[WARN] Insufficient funds or margin (Required: ₹{trade_value:.2f}, Available: ₹{available_funds:.2f}). Trade skipped.")
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
    if config.get('product_type', 'cash').lower() == "options":
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

    # Fetch required margin for this sell order
    try:
        margin_resp = breeze.get_margin(
            exchange_code=config.get('exchange_code')
        )
        print(f"[DEBUG] margin_resp: {margin_resp}")
    except Exception as me:
        print(f"[ERROR] Could not fetch margin requirement: {me}")

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

            # --- TEMPLATE-BASED ORDER TRACKING AND SQUARE OFF ---
            # Example: After order is placed, track and square off if strategy signals exit
            # (This is a skeleton; adapt as needed for your full order lifecycle)
            try:
                # Place preview order (dry run)
                preview_resp = preview_order(stock_code=config.get('stock_code'), price=signal['price'], action=signal['action'], quantity=config.get('quantity', 1))
                print(f"[PREVIEW] {preview_resp}")
                # Place actual order (uncomment if you want real trading)
                # order_resp = place_order(...)
                # order_id = order_resp.get('order_id')
                # For demonstration, use a dummy order_id:
                order_id = 'DUMMY_ORDER_ID'  # Replace with real order_id from order_resp
                # Track order status
                order_status = get_order_detail(order_id=order_id)
                print(f"[ORDER STATUS] {order_status}")
                # Example: If strategy signals exit/square off
                if signal['action'].lower() == 'sell':
                    # Square off futures/options as per config
                    sq_resp = square_off_futures(stock_code=config.get('stock_code'), quantity=config.get('quantity', 1), expiry_date=config.get('expiry_date'))
                    print(f"[SQUARE OFF] {sq_resp}")
            except Exception as ex:
                print(f"[TEMPLATE ACTION ERROR] {ex}")

    except Exception as e:
        print(f"Error processing strategy: {e}")
        import traceback
        traceback.print_exc()

def on_event_data(ticks):
    """Process incoming tick data"""
    global live_data
    global last_minute
    
    try:
        # --- Custom 1-minute candle builder (most option ticks lack minute-OHLC) ---
        ltp = None
        for key in ('ltp', 'last', 'close'):
            if key in ticks and ticks[key] not in (None, ''):
                try:
                    ltp = float(ticks[key])
                    break
                except ValueError:
                    pass

        if ltp is None:
            return  # skip this tick – no price data

        volume = int(ticks.get('volume', 0))
        minute_key = datetime.strptime(ticks.get('datetime', datetime.now().strftime('%Y-%m-%d %H:%M:%S')), 
                                         '%Y-%m-%d %H:%M:%S').replace(second=0, microsecond=0)

        global candle_minute, candle_data
        if candle_minute is None:
            # First tick ever
            candle_minute = minute_key
            candle_data = {'open': ltp, 'high': ltp, 'low': ltp,
                           'close': ltp, 'volume': volume}
            return

        if minute_key == candle_minute:
            # Update current candle
            candle_data['high'] = max(candle_data['high'], ltp)
            candle_data['low'] = min(candle_data['low'], ltp)
            candle_data['close'] = ltp
            candle_data['volume'] += volume
            return

        # Minute rolled – finalize previous candle
        row_dict = {
            'datetime': candle_minute,
            'open': candle_data['open'],
            'high': candle_data['high'],
            'low': candle_data['low'],
            'close': candle_data['close'],
            'volume': candle_data['volume']
        }

        new_df = pd.DataFrame([row_dict])
        if live_data.empty:
            live_data = new_df
        else:
            live_data = pd.concat([live_data, new_df], ignore_index=True)

        # Maintain only recent rows
        if len(live_data) > 1000:
            live_data = live_data.tail(1000)

        # Print and run strategy
        minute_str = candle_minute.strftime('%Y-%m-%d %H:%M')
        print(f"[CANDLE] {minute_str} | O:{candle_data['open']:.2f} H:{candle_data['high']:.2f} "
              f"L:{candle_data['low']:.2f} C:{candle_data['close']:.2f}")
        if len(live_data) >= 20:
            process_strategy(live_data)

        # Start new candle with current tick
        candle_minute = minute_key
        candle_data = {'open': ltp, 'high': ltp, 'low': ltp,
                       'close': ltp, 'volume': volume}
    except Exception as e:
        print(f"Error in on_event_data: {e}")
        import traceback
        traceback.print_exc()

breeze.on_ticks = on_event_data

# Globals for custom candle building
candle_minute = None
candle_data = {}
last_minute = None  # kept for backward compatibility but no longer used

import sys

# Read all config values strictly from the config file
exchange_code = config.get('exchange_code', '')
stock_code = config.get('stock_code', '')
product_type = config.get('product_type', 'cash').lower()
expiry_date = config.get('expiry_date', '')
strike_price = config.get('strike_price', '')
right = config.get('right', '')
# `interval` is only used for historical data requests, not for websocket
interval = config.get('interval', 'interval')

# Print subscription parameters for debugging
print(f"\nVerifying stock: {stock_code} on {exchange_code}")
print("Subscribing with params:")
print("exchange_code:", exchange_code)
print("stock_code:", stock_code)
print("product_type:", product_type)

if product_type == "futures" or product_type == "options":
    print("expiry_date:", expiry_date)
    if not expiry_date:
        print("[ERROR] expiry_date is required for futures and options but not found in config")
        sys.exit(1)

if product_type == "options":
    print("strike_price:", strike_price)
    print("right:", right)
    if not strike_price or not right:
        print("[ERROR] strike_price and right are required for options but not found in config")
        sys.exit(1)

# Validate the instrument exists before subscribing
try:
    # Attempt to get stock token to validate instrument exists
    token_params = {
        "exchange_code": exchange_code,
        "stock_code": stock_code,
        "product_type": product_type,
        "get_exchange_quotes": True,
        "get_market_depth": False
    }
    
    # Add required parameters based on product type
    if product_type == "futures" or product_type == "options":
        token_params["expiry_date"] = expiry_date
    
    if product_type == "options":
        token_params["strike_price"] = strike_price
        token_params["right"] = right
    
    # Get token to validate instrument exists
    token_result = breeze.get_stock_token_value(**token_params)
    
    # Check if token is valid
    if token_result is False or token_result == False:
        print(f"\n[ERROR] Invalid instrument: {stock_code} on {exchange_code} ({product_type})")
        print("This instrument may not be available for the selected parameters.")
        print("Possible reasons:")
        print("1. The symbol doesn't exist or is incorrect")
        print("2. The instrument is not available for the specified expiry date")
        print("3. For futures/options, verify the contract specifications")
        
        if product_type == "futures":
            print("\nFor NFO futures, try using major index symbols like NIFTY, BANKNIFTY, FINNIFTY")
            print("or liquid stock futures like RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK")
        elif product_type == "options":
            print("\nVerify strike price and option type (call/put) are valid for this expiry")
        
        print("\nConsider using cash market (NSE) for testing if you're having issues with derivatives")
        sys.exit(1)
        
    print("Instrument validation successful!")
    
    # Now subscribe based on product type
    if product_type == "options":
        breeze.subscribe_feeds(
            exchange_code=exchange_code,
            stock_code=stock_code,
            product_type=product_type,
            expiry_date=expiry_date,
            strike_price=strike_price,
            right=right,
            get_market_depth=False,
            get_exchange_quotes=True
        )
    elif product_type == "futures":
        breeze.subscribe_feeds(
            exchange_code=exchange_code,
            stock_code=stock_code,
            product_type=product_type,
            expiry_date=expiry_date,
            get_market_depth=False,
            get_exchange_quotes=True
        )
    else:  # cash
        breeze.subscribe_feeds(
            exchange_code=exchange_code,
            stock_code=stock_code,
            product_type=product_type,
            get_market_depth=False,
            get_exchange_quotes=True
        )

except TypeError as te:
    print(f"\n[ERROR] Type error during subscription: {te}")
    print(f"This usually happens when the instrument {stock_code} is not found")
    print("or when a required parameter is missing or has an incorrect format.")
    sys.exit(1)
except Exception as e:
    print(f"\n[ERROR] Subscription failed: {e}")
    sys.exit(1)

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

# ----------------------
# Heartbeat thread
# ----------------------

def heartbeat():
    """Periodically print a heartbeat to confirm the script is still running."""
    while True:
        try:
            print(f"[HEARTBEAT] Alive @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        except Exception:
            pass
        time.sleep(30)

# Start the heartbeat thread
heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
heartbeat_thread.start()

input("\nPress Enter to exit...\n")
