"""
LIVEFEED FROM CONFIGURATION
--------------------------
This script reads all configuration values (API credentials, instrument details, etc.) from config.properties and connects to the Breeze WebSocket for live market data feed. No user prompts are required—everything is loaded from the config file.
"""

import os
import sys
import time
import json
import logging
import threading
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from breeze_connect import BreezeConnect
from breeze_templates import *

# Configure logging
def setup_logger(name, log_file, level=logging.INFO):
    """Function to set up a logger with file and console handlers"""
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Create file handler
    file_handler = logging.FileHandler(f'logs/{log_file}.log')
    file_handler.setFormatter(formatter)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Global logger for main process
logger = setup_logger('main', 'main')

# Load configuration
import configparser
config = configparser.ConfigParser()
config.read('config.properties')

# Initialize global variables
breeze = None
strategy_instance = None
live_data = pd.DataFrame()
positions = {}
order_history = []
active_orders = {}
own_trades = set()

# Thread-safe dictionary to store stock-specific data
from threading import Lock
stock_data = {}
stock_data_lock = Lock()

class StockProcessor:
    """Handles processing for a single stock in a separate thread"""
    
    def __init__(self, symbol, config_section='CASH'):
        """Initialize stock processor with symbol and configuration"""
        self.symbol = symbol.strip('"\' ')  # Clean up symbol
        self.config_section = config_section
        self.logger = setup_logger(f'stock_{self.symbol}', f'stock_{self.symbol}')
        self.running = False
        self.thread = None
        self.position = {}
        self.live_data = pd.DataFrame()
        self.logger.info(f"Initialized processor for {self.symbol}")
        
        # Load new configuration parameters
        self.atr_multiplier = float(config.get('atr_multiplier', '1.5'))
        self.min_profit_threshold = float(config.get('min_profit_threshold', '0.5')) / 100  # Convert % to decimal
        self.strategy_approach = config.get('strategy_approach', 'strict').lower()
    
    def start(self):
        """Start processing this stock in a separate thread"""
        if self.running:
            self.logger.warning(f"Processor for {self.symbol} is already running")
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.logger.info(f"Started processor for {self.symbol}")
    
    def stop(self):
        """Stop processing this stock"""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        self.logger.info(f"Stopped processor for {self.symbol}")
    
    def _run(self):
        """Main processing loop for this stock"""
        self.logger.info(f"Starting processing for {self.symbol}")
        
        try:
            # Initialize stock-specific data
            with stock_data_lock:
                if self.symbol not in stock_data:
                    stock_data[self.symbol] = {
                        'positions': {},
                        'orders': [],
                        'last_update': datetime.now()
                    }
            
            # Main processing loop
            while self.running:
                try:
                    # Check for new data and process
                    self._process_tick()
                    
                    # Sleep briefly to prevent high CPU usage
                    time.sleep(1)
                    
                except Exception as e:
                    self.logger.error(f"Error processing {self.symbol}: {str(e)}", exc_info=True)
                    time.sleep(5)  # Wait before retrying
                    
        except Exception as e:
            self.logger.critical(f"Fatal error in processor for {self.symbol}: {str(e)}", exc_info=True)
        finally:
            self.running = False
            self.logger.info(f"Stopped processing for {self.symbol}")
    
    def _process_tick(self):
        """Process a single tick of data for this stock"""
        try:
            # Get the latest market data for this stock
            tick_data = self._get_latest_tick()
            if not tick_data:
                self.logger.debug(f"No tick data available for {self.symbol}")
                return
                
            # Update live data with the new tick
            self._update_live_data(tick_data)
            
            # Check if we have enough data to process
            if len(self.live_data) < 50:  # Minimum data points needed for indicators
                self.logger.debug(f"Insufficient data points for {self.symbol} (have {len(self.live_data)}, need 50)")
                return
                
            # Generate trading signals
            signals = self._generate_signals()
            
            # Process any generated signals
            if signals:
                self._process_signals(signals)
                
            # Check position triggers (SL/TP)
            self._check_position_triggers()
            
        except Exception as e:
            self.logger.error(f"Error in _process_tick for {self.symbol}: {str(e)}", exc_info=True)
    
    def _get_latest_tick(self):
        """Get the latest tick data for this stock"""
        try:
            # This is a placeholder - you'll need to implement actual data fetching
            # based on your data source (WebSocket, REST API, etc.)
            tick = {
                'symbol': self.symbol,
                'timestamp': datetime.now(),
                'open': 0,
                'high': 0,
                'low': 0,
                'close': 0,
                'volume': 0
            }
            return tick
        except Exception as e:
            self.logger.error(f"Error getting tick data for {self.symbol}: {str(e)}")
            return None
    
    def _update_live_data(self, tick):
        """Update the live data DataFrame with new tick data"""
        try:
            # Convert tick to DataFrame row
            new_row = pd.DataFrame([{
                'date': tick['timestamp'],
                'open': tick['open'],
                'high': tick['high'],
                'low': tick['low'],
                'close': tick['close'],
                'volume': tick['volume']
            }])
            
            # Set the index to the timestamp
            new_row.set_index('date', inplace=True)
            
            # Append to live data
            if self.live_data.empty:
                self.live_data = new_row
            else:
                self.live_data = pd.concat([self.live_data, new_row])
                
            # Keep only the most recent data (e.g., last 1000 candles)
            if len(self.live_data) > 1000:
                self.live_data = self.live_data.iloc[-1000:]
                
        except Exception as e:
            self.logger.error(f"Error updating live data for {self.symbol}: {str(e)}")
    

    
    def _process_signals(self, signals):
        """Process the generated trading signals"""
        try:
            for signal in signals:
                # Add symbol to signal if not present
                if 'symbol' not in signal:
                    signal['symbol'] = self.symbol
                    
                # Execute the trade
                self.logger.info(f"Executing trade for {self.symbol}: {signal}")
                execute_trade(signal)
                
        except Exception as e:
            self.logger.error(f"Error processing signals for {self.symbol}: {str(e)}", exc_info=True)
    
    def _check_position_triggers(self):
        """Check for position triggers (SL/TP)"""
        try:
            # Get the latest price
            if self.live_data.empty:
                return
                
            latest_price = self.live_data.iloc[-1]['close']
            
            # Check position triggers
            check_position_triggers(self.symbol, latest_price)
            
        except Exception as e:
            self.logger.error(f"Error checking position triggers for {self.symbol}: {str(e)}", exc_info=True)

# Dictionary to store active stock processors
stock_processors = {}

def start_all_stock_processors():
    """Start a processor for each stock in the config"""
    global stock_processors
    
    try:
        if not config or 'stock_codes' not in config or not config['stock_codes']:
            logger.error("No stock codes found in configuration")
            return False
            
        stock_list = config['stock_codes']
        logger.info(f"Starting processors for {len(stock_list)} stocks")
        
        # Start a processor for each stock
        for symbol in stock_list:
            try:
                if symbol in stock_processors:
                    logger.warning(f"Processor for {symbol} already exists")
                    continue
                    
                logger.info(f"Starting processor for {symbol}")
                
                # Get stock-specific parameters if available
                stock_params = {
                    'symbol': symbol,
                    'exchange_code': config.get('exchange_code', 'NSE'),
                    'product_type': config.get('product_type', 'cash'),
                    'strategy_approach': config.get('strategy_approach', 'strict'),
                    'atr_multiplier': config.get('atr_multiplier', 1.5),
                    'min_profit_threshold': config.get('min_profit_threshold', 0.5),
                    'risk_per_trade': config.get('risk_per_trade', 1.0),
                    'max_position_size': config.get('max_position_size', 10.0)
                }
                
                processor = StockProcessor(**stock_params)
                if processor.start():
                    stock_processors[symbol] = processor
                    logger.info(f"Started processor for {symbol}")
                else:
                    logger.error(f"Failed to start processor for {symbol}")
                    
            except Exception as e:
                logger.error(f"Error starting processor for {symbol}: {str(e)}", exc_info=True)
        
        if not stock_processors:
            logger.error("No stock processors were started successfully")
            return False
            
        return True
        
    except Exception as e:
        logger.critical(f"Error in start_all_stock_processors: {str(e)}", exc_info=True)
        return False

def stop_all_stock_processors():
    """Stop all running stock processors"""
    global stock_processors
    
    logger.info("Stopping all stock processors...")
    
    for symbol, processor in list(stock_processors.items()):
        try:
            logger.info(f"Stopping processor for {symbol}...")
            processor.stop()
            del stock_processors[symbol]
            logger.info(f"Stopped processor for {symbol}")
        except Exception as e:
            logger.error(f"Error stopping processor for {symbol}: {str(e)}", exc_info=True)
    
    logger.info("All stock processors stopped")

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
from fund_check import validate_order, check_sufficient_funds

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

# --- Position Tracking ---
# Dictionary to track all open positions
positions = {}

def update_position(order_id, symbol, action, quantity, price, order_type='market', stop_loss=None, take_profit=None, sl_order_id=None, tp_order_id=None):
    """
    Update positions dictionary with new or modified position
    
    Args:
        order_id (str): The order ID that triggered this update
        symbol (str): Stock symbol
        action (str): BUY or SELL
        quantity (int): Number of shares
        price (float): Execution price
        order_type (str): Type of order (market, limit, etc.)
        stop_loss (float, optional): Stop loss price
        take_profit (float, optional): Take profit price
        sl_order_id (str, optional): Broker-side stop loss order ID
        tp_order_id (str, optional): Broker-side take profit order ID
    """
    if symbol not in positions:
        positions[symbol] = {
            'symbol': symbol,
            'quantity': 0,
            'avg_price': 0.0,
            'market_value': 0.0,
            'unrealized_pnl': 0.0,
            'realized_pnl': 0.0,
            'orders': [],
            'stop_loss': None,
            'sl_order_id': None,
            'trailing_stop': None,
            'take_profit': None,
            'tp_order_id': None,
            'last_price': 0.0,
            'entry_price': 0.0,
            'side': 'LONG' if action.upper() == 'BUY' else 'SHORT',
            'status': 'OPEN',
            'timestamp': datetime.now(),
            'pnl': 0.0,
            'pnl_pct': 0.0,
            'original_quantity': 0,
            'broker_sltp_enabled': config.get('enable_broker_sltp', 'true').lower() == 'true'
        }
    
    position = positions[symbol]
    
    # Calculate new average price and quantity
    broker_sltp_enabled = position.get('broker_sltp_enabled', False)
    
    if action.upper() == 'BUY':
        total_cost = (position['quantity'] * position['avg_price']) + (quantity * price)
        position['quantity'] += quantity
        position['original_quantity'] = position['quantity']
        position['avg_price'] = total_cost / position['quantity'] if position['quantity'] > 0 else 0
        position['status'] = 'OPEN'
    else:  # SELL
        # If position is being closed, cancel any pending SL/TP orders
        if position['quantity'] - quantity <= 0 and broker_sltp_enabled:
            # Cancel any pending SL/TP orders
            for order_type in ['sl_order_id', 'tp_order_id']:
                order_id = position.get(order_type)
                if order_id:
                    try:
                        breeze.cancel_order(
                            order_id=order_id,
                            stock_code=symbol,
                            exchange_code=config.get('exchange_code', 'NSE')
                        )
                        print(f"[ORDER] Cancelled {order_type.split('_')[0].upper()} order: {order_id}")
                    except Exception as e:
                        print(f"[WARNING] Could not cancel {order_type.split('_')[0]} order {order_id}: {e}")
                    position[order_type] = None
        
        position['quantity'] -= quantity
        if position['quantity'] == 0:
            position['status'] = 'CLOSED'
            position['realized_pnl'] = (price - position['avg_price']) * quantity
            # Clear SL/TP levels when position is closed
            position['stop_loss'] = None
            position['take_profit'] = None
            position['sl_order_id'] = None
            position['tp_order_id'] = None
    
    # Update market value and P&L
    position['market_value'] = position['quantity'] * price
    position['unrealized_pnl'] = (price - position['avg_price']) * position['quantity']
    position['last_price'] = price
    position['entry_price'] = position['avg_price']
    position['pnl'] = position['unrealized_pnl'] + position['realized_pnl']
    position['pnl_pct'] = ((price / position['avg_price']) - 1) * 100 if position['avg_price'] > 0 else 0
    
    # Update order history
    order_info = {
        'order_id': order_id,
        'action': action,
        'quantity': quantity,
        'price': price,
        'time': datetime.now(),
        'order_type': order_type,
        'status': 'executed'
    }
    position['orders'].append(order_info)
    
    # Update stop loss, take profit and their order IDs if provided
    if stop_loss is not None:
        position['stop_loss'] = stop_loss
    if take_profit is not None:
        position['take_profit'] = take_profit
    if sl_order_id is not None:
        position['sl_order_id'] = sl_order_id
    if tp_order_id is not None:
        position['tp_order_id'] = tp_order_id
    
    print(f"[POSITION] Updated {symbol}: {position['quantity']} @ {position['avg_price']:.2f}")
    if position['stop_loss'] is not None:
        print(f"[POSITION] Stop Loss: {position['stop_loss']:.2f} (Order ID: {position.get('sl_order_id', 'N/A')})")
    if position['take_profit'] is not None:
        print(f"[POSITION] Take Profit: {position['take_profit']:.2f} (Order ID: {position.get('tp_order_id', 'N/A')})")
    
    return True

def check_position_triggers(symbol, current_price):
    """Check if any position triggers (stop loss, take profit) have been hit"""
    if symbol not in positions or positions[symbol]['quantity'] == 0:
        return
    
    position = positions[symbol]
    position['last_price'] = current_price
    position['unrealized_pnl'] = (current_price - position['avg_price']) * position['quantity']
    
    # Check stop loss
    if position['stop_loss'] and current_price <= position['stop_loss']:
        print(f"[STOP LOSS] Triggered for {symbol} at {current_price}")
        # Place sell order to close position
        execute_trade({
            'action': 'SELL',
            'price': current_price,
            'reason': 'Stop loss triggered',
            'symbol': symbol,
            'quantity': position['quantity']
        })
        position['stop_loss'] = None  # Reset stop loss
    
    # Check take profit
    elif position['take_profit'] and current_price >= position['take_profit']:
        print(f"[TAKE PROFIT] Triggered for {symbol} at {current_price}")
        # Place sell order to close position
        execute_trade({
            'action': 'SELL',
            'price': current_price,
            'reason': 'Take profit triggered',
            'symbol': symbol,
            'quantity': position['quantity']
        })
        position['take_profit'] = None  # Reset take profit
    
    # Update trailing stop if active
    elif position.get('trailing_stop'):
        # Implementation of trailing stop logic would go here
        pass

# --- Fix for CASH and FUTURES market: prompt user to select one stock code ---
exchange_code_lower = config.get('exchange_code', '').lower()
product_type_lower = config.get('product_type', '').lower()

if (exchange_code_lower in ['nse', 'bse'] and
        product_type_lower in ['cash', 'eatm', 'margin']):
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

# Track own trades (persisted in JSON)
import json
OWN_TRADES_FILE = os.path.join(os.path.dirname(__file__), 'own_trades.json')
def load_own_trades():
    try:
        with open(OWN_TRADES_FILE, 'r') as f:
            return set(json.load(f))
    except Exception:
        return set()
def save_own_trades(own_trades):
    try:
        with open(OWN_TRADES_FILE, 'w') as f:
            json.dump(list(own_trades), f, indent=2)
    except Exception as e:
        print(f"[ERROR] Could not save own_trades: {e}")

# Initialize global variables
breeze = None
strategy_instance = None
live_data = pd.DataFrame()
positions = {}  # Tracks all open positions
order_history = []  # Tracks all orders
active_orders = {}  # Dictionary to track active orders with order_id as key
own_trades = set()

# Load saved trades
if os.path.exists('own_trades.json'):
    try:
        with open('own_trades.json', 'r') as f:
            own_trades = set(json.load(f))
        print(f"Loaded {len(own_trades)} saved trades")
    except Exception as e:
        print(f"Error loading saved trades: {e}")
        own_trades = set()
else:
    own_trades = set()

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

# Initialize global variables
strategy_instance = None
live_data = pd.DataFrame()
positions = {}  # Tracks all open positions
order_history = []  # Tracks all orders
active_orders = {}  # Dictionary to track active orders with order_id as key

# --------------------------------------------------------
# Helper utilities for order & position sync
# --------------------------------------------------------

def has_active_orders(symbol: str | None = None) -> bool:
    """Return True if there are active orders, optionally filtered by symbol."""
    if not active_orders:
        return False
    if symbol is None:
        return True
    for oid, order_data in active_orders.items():
        if order_data.get('symbol') == symbol:
            return True
    return False


def sync_open_orders():
    """Run at start-up: fetch open orders from broker and populate active_orders & positions (only own trades)."""
    global own_trades
    try:
        from breeze_templates import get_order_list, get_order_detail, get_portfolio_positions, set_breeze_instance
        set_breeze_instance(breeze)
        order_resp = get_order_list(exchange_code=config.get('exchange_code'))
        if isinstance(order_resp, dict) and 'Success' in order_resp:
            for od in order_resp['Success']:
                status = od.get('status', '').lower()
                oid = od.get('order_id')
                # Only track own trades
                if oid in own_trades and status in ("open", "trigger pending", "partial"):
                    active_orders[oid] = od
                    order_history.append(od)
                    sym = od.get('stock_code')
                    qty = int(od.get('quantity', 0))
                    side = od.get('action', '').lower()
                    if sym not in positions:
                        positions[sym] = {'quantity': 0, 'entry_price': 0,
                                          'current_value': 0, 'unrealized_pnl': 0,
                                          'realized_pnl': 0, 'stop_loss': None,
                                          'take_profit': None, 'trailing_stop': None,
                                          'side': 'BUY' if side == 'buy' else 'SELL'}
                    positions[sym]['quantity'] += qty if side == 'buy' else -qty
        # Only reconcile portfolio positions for own trades
        try:
            port = get_portfolio_positions()
            if port and 'Success' in port:
                for p in port['Success']:
                    sym = p.get('stock_code')
                    qty = int(float(p.get('quantity', 0)))
                    # Only keep position if we have own trades for this symbol
                    if any(od.get('stock_code') == sym for oid, od in active_orders.items()):
                        if sym not in positions:
                            positions[sym] = {'quantity': 0, 'entry_price': float(p.get('average_price',0)),
                                              'current_value': 0, 'unrealized_pnl': 0,
                                              'realized_pnl': 0, 'stop_loss': None,
                                              'take_profit': None, 'trailing_stop': None,
                                              'side': 'BUY'}
                        positions[sym]['quantity'] = qty
        except Exception:
            pass
    except Exception as ex:
        print(f"[WARN] Could not sync open orders: {ex}")


def update_order_state(order_id: str):
    """Refresh single order and update state containers."""
    from breeze_templates import get_order_detail
    try:
        odtl = get_order_detail(order_id=order_id, exchange_code=config.get('exchange_code'))
        
        # Handle different response formats
        if isinstance(odtl, dict) and 'Success' in odtl:
            # Standard success response format
            od = odtl['Success']
            
            # Check if Success is a list (some API responses return a list)
            if isinstance(od, list):
                # If it's a list, try to find the order with matching ID
                matching_orders = [order for order in od if order.get('order_id') == order_id]
                if matching_orders:
                    od = matching_orders[0]  # Use the first matching order
                else:
                    print(f"[WARN] No matching order found in list response for ID: {order_id}")
                    return
            
            # Now process the order details
            status = od.get('status', '').lower()
            
            # Find and update order in history
            for rec in order_history:
                if rec.get('order_id') == order_id:
                    # Update status and quantities
                    rec['status'] = status.upper()
                    rec['filled_quantity'] = int(od.get('filled_quantity', 0))
                    rec['pending_quantity'] = int(od.get('pending_quantity', 0))
                    
                    # If order is completed, update position
                    if status == 'completed':
                        if order_id in active_orders:
                            del active_orders[order_id]
                        symbol = rec.get('symbol')
                        if symbol in positions:
                            pos = positions[symbol]
                            if rec['action'] == 'SELL':
                                # Update realized P&L for sells
                                pnl = (rec['price'] - pos['entry_price']) * rec['filled_quantity']
                                pos['realized_pnl'] += pnl
                                pos['current_value'] = pos['quantity'] * rec['price']
                                pos['unrealized_pnl'] = pos['current_value'] - (pos['quantity'] * pos['entry_price'])
                    break
    except Exception as exc:
        print(f"[WARN] update_order_state failed for {order_id}: {exc}")


def supervisor_loop(interval: int = 5):
    """
    Background loop to refresh order status, check position triggers,
    and monitor open positions for early exit conditions (only own trades).
    """
    global own_trades
    last_status_update = 0
    while True:
        try:
            current_time = time.time()
            # Refresh all open orders every interval (only own trades)
            for order_id in list(active_orders.keys()):
                update_order_state(order_id)
            # Only monitor positions that have own trades
            for symbol in list(positions.keys()):
                # Only process if any active order for this symbol is in own_trades
                found_own = False
                for oid, od in active_orders.items():
                    if oid in own_trades and isinstance(od, dict) and od.get('stock_code') == symbol:
                        found_own = True
                        break
                if not found_own:
                    continue
                position = positions[symbol]
                current_price = get_current_price(symbol)
                entry_price = position.get('entry_price', current_price)
                if entry_price == 0:  # Avoid division by zero
                    entry_price = current_price
                # Calculate current P&L
                pnl = (current_price - entry_price) * position['quantity']
                pnl_pct = (current_price / entry_price - 1) * 100 * (1 if position['quantity'] > 0 else -1)
                # Update position with current metrics
                position['last_price'] = current_price
                position['unrealized_pnl'] = pnl
                position['unrealized_pnl_pct'] = pnl_pct
                # Check for exit conditions
                check_position_triggers(symbol, current_price)
                # Periodic status update (every 30 seconds)
                if current_time - last_status_update > 30:
                    print(f"[POSITION] {symbol}: {position['quantity']} shares | "
                          f"Entry: {entry_price:.2f} | Current: {current_price:.2f} | "
                          f"P&L: {pnl:.2f} ({pnl_pct:.2f}%)")
                    if 'stop_loss' in position and position['stop_loss'] is not None:
                        stop_pct = abs((position['stop_loss'] - entry_price) / entry_price * 100)
                        print(f"        Stop Loss: {position['stop_loss']:.2f} ({stop_pct:.2f}% from entry)")
                    if 'take_profit' in position and position['take_profit'] is not None:
                        tp_pct = abs((position['take_profit'] - entry_price) / entry_price * 100)
                        print(f"        Take Profit: {position['take_profit']:.2f} ({tp_pct:.2f}% from entry)")
            # Update status update timer
            if current_time - last_status_update > 30:
                last_status_update = current_time
        except Exception as e:
            print(f"Error in supervisor loop: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(interval)


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


def execute_trade(signal):
    """
    Execute trade via Breeze with position tracking
    
    Args:
        signal (dict): Dictionary containing trade details with keys:
            - action: 'BUY' or 'SELL'
            - price: Current market price
            - symbol: Stock symbol (optional, defaults to config)
            - quantity: Number of shares (optional, defaults to config)
            - reason: Reason for the trade (optional)
            - stop_loss: Stop loss price (optional)
            - take_profit: Take profit price (optional)
            - trailing_stop: Dict with 'trail_amt' and 'trail_dist' (optional)
    """
    global positions, active_orders, order_history
    
    try:
        # Get trade parameters
        action = signal.get('action', '').upper()
        if action not in ('BUY', 'SELL'):
            print(f"[ERROR] Invalid action: {action}")
            return None
        
        symbol = signal.get('symbol', config.get('stock_code'))
        price = float(signal.get('price', 0))
        quantity = int(signal.get('quantity', config.get('quantity', 1)))
        reason = signal.get('reason', 'Strategy signal')
        
        print(f"\n[TRADE] {action} {quantity} {symbol} @ {price} - {reason}")
        
        # Check if we have enough quantity for a SELL order
        if action == 'SELL':
            available_qty = 0
            for pos in positions.values():
                if pos['symbol'] == symbol and pos['side'] == 'BUY':
                    available_qty += pos['quantity']
            
            if available_qty <= 0:
                print(f"[WARNING] No position to sell for {symbol}")
                return None
                
            if quantity > available_qty:
                print(f"[WARNING] Not enough {symbol} to sell. Available: {available_qty}, Requested: {quantity}")
                return None
        
        print(f"\n[TRADE] {action} {quantity} {symbol} @ {price} - {reason}")
        
        # Initialize position if it doesn't exist
        if symbol not in positions:
            positions[symbol] = {
                'symbol': symbol,
                'quantity': 0,
                'entry_price': 0.0,
                'current_value': 0.0,
                'unrealized_pnl': 0.0,
                'unrealized_pnl_pct': 0.0,
                'realized_pnl': 0.0,
                'orders': [],
                'stop_loss': None,
                'take_profit': None,
                # trailing stop, etc.
                'side': None,
                'winning_trades': 0,
                'losing_trades': 0,
                'avg_profit': 0.0,
                'avg_loss': 0.0,
                'max_position_size': 0,
                'risk_percentage': float(config.get('risk_percentage', 0.75)),
                'max_risk_percentage': float(config.get('max_risk_percentage', 1.5)),
                'position_size_percentage': float(config.get('position_size_percentage', 4.0)),
                'profit_target_multiplier': float(config.get('profit_target_multiplier', 3.5))
            }
        
        position = positions[symbol]
        
        # Check if we have enough quantity to sell
        if action == 'SELL':
            available_qty = position['quantity'] - sum(
                o.get('quantity', 0) for o in active_orders.values() 
                if o.get('symbol') == symbol 
                and o.get('action') == 'SELL' 
                and o.get('status') in ('PENDING', 'OPEN')
            )
            
            if available_qty <= 0:
                print(f"[WARNING] No position to sell for {symbol}")
                return None
                
            if quantity > available_qty:
                print(f"[WARNING] Not enough {symbol} to sell. Available: {available_qty}, Requested: {quantity}")
                return None
        
        # Prepare order parameters - using only supported parameters
        order_params = {
            'stock_code': symbol,
            'exchange_code': config.get('exchange_code', 'NSE'),
            'product': config.get('product_type', 'cash').lower(),
            'action': action.lower(),
            'order_type': config.get('option_order_type', 'market'),
            'quantity': str(quantity),
            'price': '',  # Empty for market orders
            'validity': config.get('option_validity', 'day'),
            'disclosed_quantity': config.get('option_disclosed_quantity', '0')
        }
        
        # Add options/futures specific parameters
        if config.get('product_type', '').lower() == "options":
            order_params.update({
                'expiry_date': config.get('expiry_date', ''),
                'right': config.get('right', '').lower(),
                'strike_price': str(config.get('strike_price', ''))
            })
        elif config.get('product_type', '').lower() == "futures":
            order_params.update({
                'expiry_date': config.get('expiry_date', ''),
                'right': 'others',
                'strike_price': '0'
            })
        
        # Prepare order data for logging
        order_data = {
            'order_id': None,  # Will be updated after order placement
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'price': price,
            'timestamp': datetime.now().isoformat(),
            'status': 'PENDING',
            'reason': reason,
            'filled_quantity': 0,
            'pending_quantity': quantity
        }
        
        # Check if we have enough funds for BUY orders
        if action.upper() == 'BUY':
            if not check_sufficient_funds(breeze, symbol, price, quantity):
                print(f"[ORDER REJECTED] Insufficient funds to buy {quantity} {symbol} at ₹{price:.2f}")
                return None
                
        # Place the order
        resp = breeze.place_order(**order_params)
        print(f"[ORDER] Response: {resp}")
        
        # If order was successful, update our position tracking
        if isinstance(resp, dict) and 'Success' in resp and 'order_id' in resp['Success']:
            order_id = resp['Success']['order_id']
            print(f"[ORDER] Successfully placed {action} order {order_id} for {quantity} {symbol} @ {price}")
            
            # Update order data with actual order ID
            order_data['order_id'] = order_id
            order_history.append(order_data)
            active_orders[order_id] = order_data
            log_trade(order_data)
            
            # Update our position tracking
            position['last_price'] = price
            position['last_update'] = datetime.now().isoformat()
            
            if action == 'BUY':
                # Calculate new position size and entry price
                total_cost = (position['quantity'] * position.get('entry_price', 0)) + (quantity * price)
                position['quantity'] += quantity
                position['entry_price'] = total_cost / position['quantity'] if position['quantity'] > 0 else price
                position['current_value'] = position['quantity'] * price
                position['unrealized_pnl'] = 0  # Reset P&L for new position
                position['unrealized_pnl_pct'] = 0
                
                # Set stop loss and take profit based on config
                atr_multiplier = float(config.get('atr_multiplier', 1.5))
                min_profit_threshold = float(config.get('min_profit_threshold', 0.4))
                
                if position['quantity'] > 0:  # Long position
                    stop_loss = price * (1 - atr_multiplier * min_profit_threshold)
                    take_profit = price * (1 + atr_multiplier * min_profit_threshold)
                else:  # Short position
                    stop_loss = price * (1 + atr_multiplier * min_profit_threshold)
                    take_profit = price * (1 - atr_multiplier * min_profit_threshold)
                
                # Place broker-side SL/TP orders if enabled
                if config.get('enable_broker_sltp', 'true').lower() == 'true':
                    # Cancel any existing SL/TP orders
                    if position.get('sl_order_id'):
                        try:
                            breeze.cancel_order(
                                order_id=position['sl_order_id'],
                                stock_code=symbol,
                                exchange_code=config.get('exchange_code', 'NSE')
                            )
                            print(f"[ORDER] Cancelled previous stop loss order: {position['sl_order_id']}")
                        except Exception as e:
                            print(f"[WARNING] Could not cancel previous stop loss order: {e}")
                    
                    if position.get('tp_order_id'):
                        try:
                            breeze.cancel_order(
                                order_id=position['tp_order_id'],
                                stock_code=symbol,
                                exchange_code=config.get('exchange_code', 'NSE')
                            )
                            print(f"[ORDER] Cancelled previous take profit order: {position['tp_order_id']}")
                        except Exception as e:
                            print(f"[WARNING] Could not cancel previous take profit order: {e}")
                    
                    # Place new SL order
                    try:
                        sl_params = {
                            'stock_code': symbol,
                            'exchange_code': config.get('exchange_code', 'NSE'),
                            'product': config.get('product_type', 'cash').lower(),
                            'action': 'sell',
                            'order_type': 'stoploss',
                            'stoploss': str(round(stop_loss, 2)),
                            'quantity': str(position['quantity']),
                            'price': '0',
                            'validity': 'day',
                            'validity_date': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d'),
                            'disclosed_quantity': '0'
                        }
                        
                        # Add options/futures specific parameters
                        if config.get('product_type', '').lower() == "options":
                            sl_params.update({
                                'expiry_date': config.get('expiry_date', ''),
                                'right': config.get('right', '').lower(),
                                'strike_price': str(config.get('strike_price', ''))
                            })
                        elif config.get('product_type', '').lower() == "futures":
                            sl_params.update({
                                'expiry_date': config.get('expiry_date', ''),
                                'right': 'others',
                                'strike_price': '0'
                            })
                        
                        sl_resp = breeze.place_order(**sl_params)
                        if 'Success' in sl_resp and 'order_id' in sl_resp['Success']:
                            sl_order_id = sl_resp['Success']['order_id']
                            position['sl_order_id'] = sl_order_id
                            print(f"[ORDER] Placed stop loss order: {sl_order_id} @ {stop_loss:.2f}")
                            
                            # Add to active orders
                            sl_order_data = {
                                'order_id': sl_order_id,
                                'symbol': symbol,
                                'action': 'SELL',
                                'quantity': position['quantity'],
                                'price': stop_loss,
                                'timestamp': datetime.now().isoformat(),
                                'status': 'PENDING',
                                'reason': 'Stop Loss',
                                'order_type': 'STOPLOSS',
                                'parent_order_id': order_id
                            }
                            active_orders[sl_order_id] = sl_order_data
                            order_history.append(sl_order_data)
                            own_trades.add(sl_order_id)
                    except Exception as e:
                        print(f"[ERROR] Failed to place stop loss order: {e}")
                    
                    # Place new TP order if take_profit is set
                    if take_profit:
                        try:
                            tp_params = {
                                'stock_code': symbol,
                                'exchange_code': config.get('exchange_code', 'NSE'),
                                'product': config.get('product_type', 'cash').lower(),
                                'action': 'sell',
                                'order_type': 'limit',
                                'price': str(round(take_profit, 2)),
                                'quantity': str(position['quantity']),
                                'validity': 'day',
                                'validity_date': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d'),
                                'disclosed_quantity': '0'
                            }
                            
                            # Add options/futures specific parameters
                            if config.get('product_type', '').lower() == "options":
                                tp_params.update({
                                    'expiry_date': config.get('expiry_date', ''),
                                    'right': config.get('right', '').lower(),
                                    'strike_price': str(config.get('strike_price', ''))
                                })
                            elif config.get('product_type', '').lower() == "futures":
                                tp_params.update({
                                    'expiry_date': config.get('expiry_date', ''),
                                    'right': 'others',
                                    'strike_price': '0'
                                })
                            
                            tp_resp = breeze.place_order(**tp_params)
                            if 'Success' in tp_resp and 'order_id' in tp_resp['Success']:
                                tp_order_id = tp_resp['Success']['order_id']
                                position['tp_order_id'] = tp_order_id
                                print(f"[ORDER] Placed take profit order: {tp_order_id} @ {take_profit:.2f}")
                                
                                # Add to active orders
                                tp_order_data = {
                                    'order_id': tp_order_id,
                                    'symbol': symbol,
                                    'action': 'SELL',
                                    'quantity': position['quantity'],
                                    'price': take_profit,
                                    'timestamp': datetime.now().isoformat(),
                                    'status': 'PENDING',
                                    'reason': 'Take Profit',
                                    'order_type': 'LIMIT',
                                    'parent_order_id': order_id
                                }
                                active_orders[tp_order_id] = tp_order_data
                                order_history.append(tp_order_data)
                                own_trades.add(tp_order_id)
                        except Exception as e:
                            print(f"[ERROR] Failed to place take profit order: {e}")
                
                # Update position with SL/TP levels for local tracking
                position['stop_loss'] = stop_loss
                position['take_profit'] = take_profit
                
                # Set trailing stop configuration
                position['trailing_stop'] = {
                    'trail_amt': float(config.get('min_profit_threshold', 0.4)),
                    'trail_dist': float(config.get('atr_multiplier', 1.5)) * float(config.get('min_profit_threshold', 0.4))
                }
                
                # Update risk management metrics
                position['max_position_size'] = max(position['max_position_size'], position['quantity'])
                position['total_trades'] += 1
                
            else:  # SELL
                position['quantity'] -= quantity
                if position['quantity'] == 0:
                    position['entry_price'] = 0
                    position['stop_loss'] = None
                    position['take_profit'] = None
                    position['trailing_stop'] = None
                    
                    # Calculate trade metrics
                    pnl = position['realized_pnl']
                    if pnl > 0:
                        position['winning_trades'] += 1
                        position['avg_profit'] = (position['avg_profit'] * position['winning_trades'] + pnl) / position['winning_trades']
                    else:
                        position['losing_trades'] += 1
                        position['avg_loss'] = (position['avg_loss'] * position['losing_trades'] + abs(pnl)) / position['losing_trades']
                
                # Calculate realized P&L
                pnl = (price - position['entry_price']) * quantity * (1 if position['quantity'] >= 0 else -1)
                position['realized_pnl'] += pnl
                position['current_value'] = position['quantity'] * price
                position['unrealized_pnl'] = position['current_value'] - (position['quantity'] * position['entry_price'])
                position['unrealized_pnl_pct'] = (position['unrealized_pnl'] / (position['quantity'] * position['entry_price'])) * 100 if position['quantity'] > 0 else 0
            
            # Helper function to get current price for a symbol
            def get_current_price(sym):
                # First try to get from live_data
                if not live_data.empty:
                    # If symbol matches current stock code in live_data
                    if sym == config.get('stock_code') and 'close' in live_data.columns:
                        return live_data['close'].iloc[-1]
                # If we can't find price, use last known price from position or default to entry price
                return positions[sym].get('last_price', positions[sym]['entry_price'])
                
            # Display positions with symbol-specific information
            for pos_symbol, pos in positions.items():
                if pos['quantity'] > 0:  # Only show positions with active holdings
                    # Find current price for this symbol (use trade price for current symbol, check live_data for others)
                    current_price = price if pos_symbol == symbol else get_current_price(pos_symbol)
                    
                    # Calculate unrealized P&L with correct current price
                    unrealized_pnl = (current_price - pos['entry_price']) * pos['quantity']
                    if pos['entry_price'] > 0:
                        pnl_pct = (unrealized_pnl / (pos['quantity'] * pos['entry_price'])) * 100
                    else:
                        pnl_pct = 0
                        
                    print(f"[POSITION] {pos_symbol}: {pos['quantity']} shares | Entry: {pos['entry_price']:.2f} | Current: {current_price:.2f} | P&L: {unrealized_pnl:.2f} ({pnl_pct:.2f}%)")
            
            print(f"           Active Orders: {len([o for o in order_history if o.get('status') in ('PENDING', 'OPEN')])}")
            
            
            return order_id
        else:
            print(f"[ERROR] Failed to place order: {resp}")
            return None
    except Exception as e:
        print(f"[ERROR] Error executing {action} order: {e}")
        import traceback
        traceback.print_exc()
        return None

# Call sync at start-up and spawn supervisor thread
sync_open_orders()
threading.Thread(target=supervisor_loop, daemon=True).start()

# --------------------------------------------------------
# Global variables for account tracking
account_balance = None
last_balance_check_time = None
BALANCE_CHECK_INTERVAL = 300  # Check balance every 5 minutes

def get_account_balance():
    """
    Fetch account details from the Breeze API and extract available balance.
    This function caches the result for BALANCE_CHECK_INTERVAL seconds to avoid excessive API calls.
    """
    global account_balance, last_balance_check_time
    current_time = time.time()
    
    # Return cached balance if recent enough
    if account_balance is not None and last_balance_check_time is not None:
        if current_time - last_balance_check_time < BALANCE_CHECK_INTERVAL:
            return account_balance
    
    try:
        # Import get_funds from breeze_templates
        from breeze_templates import get_funds
        
        # Use get_funds API to fetch account balance
        resp = get_funds()
        
        if not resp or not isinstance(resp, dict):
            print("[ERROR] Failed to fetch account funds")
            return None
        
        # Extract available balance from the response
        if 'Success' in resp and isinstance(resp['Success'], dict):
            funds_data = resp['Success']
            
            # Extract balance from the specific response format of your Breeze API
            # First check for the keys we know are in the response
            if 'allocated_equity' in funds_data:
                # Use allocated_equity as the available balance
                available_balance = float(funds_data['allocated_equity'])
            elif 'total_bank_balance' in funds_data:
                # Use total_bank_balance as fallback
                available_balance = float(funds_data['total_bank_balance'])
            # Keep the original checks as fallbacks
            elif 'available_margin' in funds_data:
                available_balance = float(funds_data['available_margin'])
            elif 'cash_available' in funds_data:
                available_balance = float(funds_data['cash_available'])
            elif 'cash' in funds_data and 'available_margin' in funds_data['cash']:
                available_balance = float(funds_data['cash']['available_margin'])
            else:
                # If still not found, use a reasonable default balance
                print(f"[INFO] Using default trading balance since couldn't extract from: {list(funds_data.keys())[:5]}")
                available_balance = 100000.0  # Default to 1 lakh for trading
        else:
            print("[ERROR] Invalid response structure from get_funds API")
            return None
            
        # Update cached values
        account_balance = available_balance
        last_balance_check_time = current_time
        
        print(f"[INFO] Available account balance: ₹{account_balance:.2f}")
        return account_balance
        
    except Exception as e:
        print(f"[ERROR] Error fetching account balance: {e}")
        return account_balance  # Return last known balance if error occurs

def check_sufficient_funds(symbol, price, quantity):
    """
    Check if there is sufficient balance to place a buy order.
    Returns True if sufficient funds, False otherwise.
    """
    if price <= 0 or quantity <= 0:
        return False
        
    # Get account balance
    balance = get_account_balance()
    if balance is None:
        # If we can't determine balance, return True and let the broker reject if needed
        print("[WARNING] Unable to verify available funds. Proceeding with order anyway.")
        return True
        
    # Calculate required funds
    required_funds = price * quantity
    
    # Add buffer for taxes, fees, etc. (additional 1%)
    required_funds_with_buffer = required_funds * 1.01
    
    # Check if enough funds
    has_sufficient_funds = balance >= required_funds_with_buffer
    
    if not has_sufficient_funds:
        print(f"[ERROR] Insufficient funds for {symbol} order. Required: ₹{required_funds_with_buffer:.2f}, Available: ₹{balance:.2f}")
    
    return has_sufficient_funds

# 1. Pre-populate live_data with historical candles (optional)
# --------------------------------------------------------
#   We fetch candles from `from_date` (config) up to "now" (script start)
#   so that indicators (EMA, MACD, ATR, etc.) have warm-up data and
#   signals are immediately valid once the live stream begins.
# --------------------------------------------------------

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
        self.approach = approach
        self.last_signal = None
        self.last_signal_time = None
        self.last_signal_price = None
        # Track last processed candle by timeframe
        self.last_processed_timestamp = None
        # Get appropriate timeframe for signal generation based on approach
        if approach.lower() == 'strict':
            self.signal_timeframe = config.get('lower_timeframe', '4hour')
        else:  # relaxed approach
            self.signal_timeframe = config.get('interval', '30minute')
        
        # Determine which config section to use based on approach
        param_section = 'STRICT_PARAMS' if approach.lower() == 'strict' else 'RELAXED_PARAMS'
        
        # Advanced position management parameters from config
        # Pyramiding (scaling in) settings
        self.enable_pyramiding = config.get('enable_pyramiding', 'false').lower() == 'true'
        self.max_pyramid_entries = int(config.get('max_pyramid_entries', '3'))
        self.pyramid_threshold_pct = float(config.get('pyramid_threshold_pct', '1.0')) / 100
        
        # Scaling out settings
        self.enable_scale_out = config.get('enable_scale_out', 'false').lower() == 'true'
        
        # Scale out levels (default 33%, 50%, 100% of profit target)
        scale_out_levels_default = '33,50,100'
        scale_out_levels_str = config.get('scale_out_levels', scale_out_levels_default)
        self.scale_out_levels = [float(x)/100 for x in scale_out_levels_str.split(',')]
        
        # Scale out percentages (default 25%, 25%, 50% of position)
        scale_out_pct_default = '25,25,50'
        scale_out_pct_str = config.get('scale_out_percentages', scale_out_pct_default)
        self.scale_out_percentages = [float(x)/100 for x in scale_out_pct_str.split(',')]
        
        print(f"[INFO] {approach.capitalize()} strategy will generate signals based on {self.signal_timeframe} candles")
        if self.enable_pyramiding:
            print(f"[INFO] Pyramiding enabled: Max entries={self.max_pyramid_entries}, Min move={self.pyramid_threshold_pct*100}%")
        if self.enable_scale_out:
            print(f"[INFO] Scaling out enabled: Levels={[f'{x*100}%' for x in self.scale_out_levels]}, Percentages={[f'{x*100}%' for x in self.scale_out_percentages]}")
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
        
        # Log when we're processing a new candle at the appropriate timeframe
        current_time = datetime.now()
        print(f"[INFO] Generating signals for {self.approach} strategy at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"       Using {self.signal_timeframe} timeframe data for signal generation")
        
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


def execute_trade(signal):
    """
    Execute trade via Breeze with position tracking
    
    Args:
        signal (dict): Dictionary containing trade details with keys:
            - action: 'BUY' or 'SELL'
            - price: Current market price
            - symbol: Stock symbol (optional, defaults to config)
            - quantity: Number of shares (optional, defaults to config)
            - reason: Reason for the trade (optional)
            - stop_loss: Stop loss price (optional)
            - take_profit: Take profit price (optional)
            - trailing_stop: Dict with 'trail_amt' and 'trail_dist' (optional)
    """
    global positions, active_orders, order_history
    
    try:
        # Get trade parameters
        action = signal.get('action', '').upper()
        if action not in ('BUY', 'SELL'):
            print(f"[ERROR] Invalid action: {action}")
            return None
        
        symbol = signal.get('symbol', config.get('stock_code'))
        price = float(signal.get('price', 0))
        quantity = int(signal.get('quantity', config.get('quantity', 1)))
        reason = signal.get('reason', 'Strategy signal')
        
        print(f"\n[TRADE] {action} {quantity} {symbol} @ {price} - {reason}")
        
        # Check if we have enough quantity for a SELL order
        if action == 'SELL':
            available_qty = 0
            for pos in positions.values():
                if pos['symbol'] == symbol and pos['side'] == 'BUY':
                    available_qty += pos['quantity']
            
            if available_qty <= 0:
                print(f"[WARNING] No position to sell for {symbol}")
                return None
                
            if quantity > available_qty:
                print(f"[WARNING] Not enough {symbol} to sell. Available: {available_qty}, Requested: {quantity}")
                return None
        
        # Prepare order parameters
        order_params = {
            'stock_code': symbol,
            'exchange_code': config.get('exchange_code', 'NSE'),
            'product': config.get('product_type', 'cash').lower(),
            'action': action.lower(),
            'order_type': 'market',  # Always use market orders for now
            'stoploss': '0',  # Will be managed separately
            'quantity': str(quantity),
            'price': '',  # Empty for market orders
            'validity': 'day',
            'disclosed_quantity': '0'
            # Removed unsupported parameters: 'squareoff' and 'trailing_stoploss'
        }
        
        # Add options/futures specific parameters
        if config.get('product_type', '').lower() == "options":
            order_params.update({
                'expiry_date': config.get('expiry_date', ''),
                'right': config.get('right', '').lower(),
                'strike_price': str(config.get('strike_price', ''))
            })
        elif config.get('product_type', '').lower() == "futures":
            order_params.update({
                'expiry_date': config.get('expiry_date', ''),
                'right': 'others',
                'strike_price': '0'
            })
    
        # Place the order
        resp = breeze.place_order(**order_params)
        print(f"[ORDER] Response: {resp}")
        
        # If order was successful, update our position tracking
        if isinstance(resp, dict) and 'Success' in resp and 'order_id' in resp['Success']:
            order_id = resp['Success']['order_id']
            print(f"[ORDER] Successfully placed {action} order {order_id} for {quantity} {symbol} @ {price}")
            
            # Log the order as pending
            order_data = {
                'order_id': order_id,
                'symbol': symbol,
                'action': action,
                'quantity': quantity,
                'price': price,
                'timestamp': datetime.now().isoformat(),
                'status': 'PENDING',
                'reason': reason,
                'filled_quantity': 0,
                'pending_quantity': quantity
            }
            order_history.append(order_data)
            active_orders[order_id] = order_data
            log_trade(order_data)

            # Update our position tracking
            update_position(
                order_id=order_id,
                symbol=symbol,
                action=action,
                quantity=quantity,
                price=price,
                order_type=order_params.get('order_type', 'market'),
                stop_loss=signal.get('stop_loss'),
                take_profit=signal.get('take_profit')
            )

            # Add order ID to own trades
            own_trades.add(order_id)
            save_own_trades(own_trades)

            return order_id
        else:
            print(f"[ERROR] Failed to place order: {resp}")
            return None
    except Exception as ex:
        print(f"[ERROR] Failed to place {action} order: {ex}")
        import traceback
        traceback.print_exc()
        return None


def process_strategy(data):
    """
    Process the latest data with the simplified Triple Screen Strategy
    and manage open positions. Only generates signals when a new candle
    at the appropriate timeframe has closed.
    """
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
    
    # Get the latest price data
    if data.empty:
        return
    latest_price = data['close'].iloc[-1]
    latest_timestamp = data.index[-1]
    
    # Check for position triggers (stop loss, take profit) - this should run on every update
    symbol = config.get('stock_code')
    check_position_triggers(symbol, latest_price)
    
    # Check if this is a new candle at the appropriate timeframe
    new_candle_at_correct_timeframe = False
    
    # Get appropriate timeframe resolution in minutes
    timeframe = strategy_instance.signal_timeframe
    timeframe_minutes = {
        '1minute': 1,
        '5minute': 5,
        '15minute': 15,
        '30minute': 30,
        '1hour': 60,
        '4hour': 240,
        '1day': 1440,
        '1week': 10080
    }.get(timeframe, 30)  # Default to 30 minutes if unknown
    
    # Round current timestamp to the nearest timeframe interval
    if isinstance(latest_timestamp, pd.Timestamp):
        # For timeframes >= 1 day, we should check the date component
        if timeframe_minutes >= 1440:  # daily or higher
            current_interval = latest_timestamp.floor('D')
        else:
            # For intraday timeframes, round to the nearest interval
            minutes_since_midnight = latest_timestamp.hour * 60 + latest_timestamp.minute
            interval_number = minutes_since_midnight // timeframe_minutes
            current_interval = latest_timestamp.replace(
                hour=(interval_number * timeframe_minutes) // 60,
                minute=(interval_number * timeframe_minutes) % 60,
                second=0, microsecond=0
            )
    else:
        # If timestamp is not a pandas timestamp, use datetime
        current_time = datetime.now()
        if timeframe_minutes >= 1440:
            current_interval = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            minutes_since_midnight = current_time.hour * 60 + current_time.minute
            interval_number = minutes_since_midnight // timeframe_minutes
            current_interval = current_time.replace(
                hour=(interval_number * timeframe_minutes) // 60,
                minute=(interval_number * timeframe_minutes) % 60,
                second=0, microsecond=0
            )
    
    # Check if this is a new candle compared to last processed
    if strategy_instance.last_processed_timestamp is None or current_interval > strategy_instance.last_processed_timestamp:
        new_candle_at_correct_timeframe = True
        strategy_instance.last_processed_timestamp = current_interval
    
    # Only generate signals on new candles at the correct timeframe
    if new_candle_at_correct_timeframe:
        try:
            # Process data and generate signals
            signal = strategy_instance.generate_signals(data)
            if signal:
                print(f"\n🚨 SIGNAL ALERT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Strategy: Triple Screen {strategy_instance.approach.capitalize()}")
                print(f"Signal: {signal['action']} {config.get('stock_code', 'stock_code')} at ₹{signal['price']:.2f}")
                print(f"Confidence: {signal.get('confidence', 'N/A')}")
                if 'atr' in signal:
                    print(f"ATR: {signal['atr']:.2f}")
                if 'reason' in signal:
                    print(f"Reason: {signal['reason']}")
                print(f"Timeframe: {timeframe} (candle closed at {current_interval})")
                print("---------------------------------------")
                # Execute the signal automatically
                print("\n[AUTO-TRADE] Automatically executing signal...")
                # Add stock symbol to the signal
                signal['symbol'] = config.get('stock_code')
                
                # Determine quantity based on risk management
                account_balance = get_account_balance()
                if account_balance:
                    # Use 1% risk per trade by default
                    risk_pct = float(config.get('risk_per_trade', 0.01))
                    # Calculate position size based on ATR for risk management
                    price = signal['price']
                    atr = signal.get('atr', price * 0.01)  # Default to 1% if ATR not available
                    
                    # Use ATR multiplier for stop loss distance
                    stop_distance = atr * float(config.get('atr_multiplier', 1.5))
                    
                    # Calculate max position size based on risk
                    risk_amount = account_balance * risk_pct
                    max_shares = int(risk_amount / stop_distance)
                    
                    # Cap position size to avoid excessive positions
                    max_position_size = int(account_balance * float(config.get('max_position_size_percent', 0.05)) / price)
                    quantity = min(max_shares, max_position_size)
                    
                    # Ensure minimum of 1 share
                    quantity = max(1, quantity)
                    
                    signal['quantity'] = quantity
                    print(f"[AUTO-TRADE] Calculated quantity: {quantity} shares")
                    print(f"[AUTO-TRADE] Estimated risk: ₹{risk_amount:.2f} ({risk_pct*100:.1f}% of capital)")
                
                # Calculate stop loss based on ATR
                if 'atr' in signal:
                    if signal['action'] == 'BUY':
                        signal['stop_loss'] = signal['price'] - (signal['atr'] * float(config.get('atr_multiplier', 1.5)))
                    else:  # SELL
                        signal['stop_loss'] = signal['price'] + (signal['atr'] * float(config.get('atr_multiplier', 1.5)))
                    print(f"[AUTO-TRADE] Stop loss calculated at: ₹{signal['stop_loss']:.2f}")
                    
                    # Add trailing stop information
                    signal['trailing_stop'] = {
                        'trail_amt': float(config.get('min_profit_threshold', 0.5))/100,
                        'trail_dist': float(config.get('atr_multiplier', 1.5)) * signal['atr']
                    }
                
                # Execute the trade
                order_id = execute_trade(signal)
                if order_id:
                    print(f"[AUTO-TRADE] Order executed successfully with ID: {order_id}")
                else:
                    print("[AUTO-TRADE] Order execution failed")
                print("---------------------------------------")
        except Exception as e:
            print(f"[ERROR] Failed to generate signals: {e}")
            import traceback
            traceback.print_exc()
    else:
        # Debug logging - can be removed in production
        # print(f"Skipping signal generation - waiting for new {timeframe} candle (current: {current_interval})")
        pass

def check_position_triggers(symbol, current_price):
    """
    Check if any position triggers (stop loss/take profit) have been hit
    for the given symbol at the current price, and manage advanced features
    like scaling out and pyramiding.
    """
    if symbol not in positions or abs(positions[symbol]['quantity']) == 0:
        return
    
    position = positions[symbol]
    entry_price = position.get('entry_price', current_price)
    quantity = position.get('quantity', 0)
    original_quantity = position.get('original_quantity', quantity)
    
    if quantity == 0:
        return
    
    # Track if position was closed
    position_closed = False
    
    # Calculate current P&L
    direction = 1 if quantity > 0 else -1  # 1 for long, -1 for short
    price_diff = (current_price - entry_price) * direction
    pnl_pct = price_diff / entry_price * 100
    
    # Get strategy instance for configuration
    global strategy_instance
    if strategy_instance is None:
        return
    
    # Check if we should scale out (take partial profits) before checking other exits
    if not position_closed and strategy_instance.enable_scale_out:
        # Check if we have a scale-out plan
        scale_out_plan = position.get('scale_out_plan')
        if scale_out_plan is None:
            # Initialize scale-out plan if this is first time
            scale_out_plan = {
                'levels': strategy_instance.scale_out_levels.copy(),
                'percentages': strategy_instance.scale_out_percentages.copy(),
                'next_level_index': 0,
                'exits_taken': []
            }
            position['scale_out_plan'] = scale_out_plan
            position['original_quantity'] = quantity  # Store original position size
        
        # Check if we should take a partial exit
        if scale_out_plan['next_level_index'] < len(scale_out_plan['levels']):
            next_level = scale_out_plan['levels'][scale_out_plan['next_level_index']]
            target_price_move = next_level * entry_price
            
            # Check if we've reached the next scale-out level
            if (direction == 1 and current_price >= entry_price + target_price_move) or \
               (direction == -1 and current_price <= entry_price - target_price_move):
                
                # Calculate the quantity to exit at this level
                exit_percentage = scale_out_plan['percentages'][scale_out_plan['next_level_index']]
                exit_quantity = int(original_quantity * exit_percentage)
                
                if exit_quantity > 0 and exit_quantity <= abs(quantity):
                    # Create partial exit order
                    trade_params = {
                        'action': 'SELL' if direction == 1 else 'BUY',
                        'price': current_price,
                        'quantity': exit_quantity,
                        'symbol': symbol,
                        'reason': f"Scale-out level {next_level*100}% reached"
                    }
                    print(f"[SCALE OUT] Taking {exit_percentage*100}% profit ({exit_quantity} shares) for {symbol} at {current_price:.2f}")
                    
                    # Execute the partial exit
                    execute_trade(trade_params)
                    
                    # Record this exit
                    scale_out_plan['exits_taken'].append({
                        'level': next_level,
                        'price': current_price,
                        'quantity': exit_quantity,
                        'percentage': exit_percentage,
                        'time': datetime.now().isoformat()
                    })
                    
                    # Move to next scale-out level
                    scale_out_plan['next_level_index'] += 1
    
    # Check if we're using broker-side SL/TP
    broker_sltp_enabled = config.get('enable_broker_sltp', 'true').lower() == 'true'
    
    # Only check local triggers if broker-side SL/TP is disabled
    if not broker_sltp_enabled:
        # Check stop loss (fixed or trailing)
        stop_price = position.get('stop_loss')
        if stop_price is not None and not position_closed:
            stop_triggered = (direction == 1 and current_price <= stop_price) or \
                            (direction == -1 and current_price >= stop_price)
            
            if stop_triggered:
                # Close position at current price
                trade_params = {
                    'action': 'SELL' if direction == 1 else 'BUY',
                    'price': current_price,
                    'quantity': abs(quantity),
                    'symbol': symbol,
                    'reason': f"Stop loss triggered at {stop_price:.2f}",
                    'stop_loss': None,  # Clear stop loss
                    'take_profit': None  # Clear take profit
                }
                print(f"[STOP LOSS] Closing position for {symbol} at {current_price:.2f}. Stop price: {stop_price:.2f}")
                execute_trade(trade_params)
                position_closed = True
        
        # Check take profit
        take_profit = position.get('take_profit')
        if not position_closed and take_profit is not None:
            tp_triggered = (direction == 1 and current_price >= take_profit) or \
                            (direction == -1 and current_price <= take_profit)
            
            if tp_triggered:
                # Close position at current price
                trade_params = {
                    'action': 'SELL' if direction == 1 else 'BUY',
                    'price': current_price,
                    'quantity': abs(quantity),
                    'symbol': symbol,
                    'reason': f"Take profit triggered at {take_profit:.2f}",
                    'stop_loss': None,  # Clear stop loss
                    'take_profit': None  # Clear take profit
                }
                print(f"[TAKE PROFIT] Closing position for {symbol} at {current_price:.2f}. Target: {take_profit:.2f}")
                execute_trade(trade_params)
                position_closed = True
    
    # Update trailing stop if needed
    if not position_closed and position.get('trailing_stop') is not None:
        trail_config = position['trailing_stop']
        broker_sltp_enabled = position.get('broker_sltp_enabled', False)
        
        # Get ATR for trailing stop calculation
        atr = trail_config.get('atr', 0)
        multiplier = trail_config.get('multiplier', 1.5)
        min_profit = trail_config.get('min_profit_threshold', 0.005)
        
        # Only activate trailing stop if we have enough profit
        if pnl_pct >= min_profit * 100:
            trail_amount = atr * multiplier
            stop_updated = False
            
            if direction == 1:  # Long position
                new_stop = current_price - trail_amount
                if position.get('stop_loss') is None or new_stop > position['stop_loss']:
                    position['stop_loss'] = new_stop
                    stop_updated = True
                    print(f"[TRAILING STOP] Updated for {symbol}: {new_stop:.2f} (Price: {current_price:.2f})")
            else:  # Short position
                new_stop = current_price + trail_amount
                if position.get('stop_loss') is None or new_stop < position['stop_loss']:
                    position['stop_loss'] = new_stop
                    stop_updated = True
                    print(f"[TRAILING STOP] Updated for {symbol}: {new_stop:.2f} (Price: {current_price:.2f})")
            
            # If stop was updated and we're using broker-side SL, update the SL order
            if stop_updated and broker_sltp_enabled and position.get('sl_order_id'):
                try:
                    # Cancel existing SL order
                    breeze.cancel_order(
                        order_id=position['sl_order_id'],
                        stock_code=symbol,
                        exchange_code=config.get('exchange_code', 'NSE')
                    )
                    
                    # Place new SL order at updated price
                    sl_params = {
                        'stock_code': symbol,
                        'exchange_code': config.get('exchange_code', 'NSE'),
                        'product': config.get('product_type', 'cash').lower(),
                        'action': 'sell' if direction == 1 else 'buy',
                        'order_type': 'stoploss',
                        'stoploss': str(round(new_stop, 2)),
                        'quantity': str(abs(position['quantity'])),
                        'price': '0',
                        'validity': 'day',
                        'validity_date': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d'),
                        'disclosed_quantity': '0'
                    }
                    
                    # Add options/futures specific parameters
                    if config.get('product_type', '').lower() == "options":
                        sl_params.update({
                            'expiry_date': config.get('expiry_date', ''),
                            'right': config.get('right', '').lower(),
                            'strike_price': str(config.get('strike_price', ''))
                        })
                    elif config.get('product_type', '').lower() == "futures":
                        sl_params.update({
                            'expiry_date': config.get('expiry_date', ''),
                            'right': 'others',
                            'strike_price': '0'
                        })
                    
                    sl_resp = breeze.place_order(**sl_params)
                    if 'Success' in sl_resp and 'order_id' in sl_resp['Success']:
                        new_sl_order_id = sl_resp['Success']['order_id']
                        print(f"[ORDER] Updated stop loss order: {position['sl_order_id']} -> {new_sl_order_id} @ {new_stop:.2f}")
                        position['sl_order_id'] = new_sl_order_id
                        
                        # Update active orders
                        if position['sl_order_id'] in active_orders:
                            del active_orders[position['sl_order_id']]
                        
                        # Add new SL order to active orders
                        sl_order_data = {
                            'order_id': new_sl_order_id,
                            'symbol': symbol,
                            'action': 'SELL' if direction == 1 else 'BUY',
                            'quantity': abs(position['quantity']),
                            'price': new_stop,
                            'timestamp': datetime.now().isoformat(),
                            'status': 'PENDING',
                            'reason': 'Trailing Stop Loss',
                            'order_type': 'STOPLOSS',
                            'parent_order_id': order_id
                        }
                        active_orders[new_sl_order_id] = sl_order_data
                        order_history.append(sl_order_data)
                        own_trades.add(new_sl_order_id)
                except Exception as e:
                    print(f"[ERROR] Failed to update broker-side stop loss order: {e}")
    
    return False


def log_trade(trade_data):
    """
    Log trade details to a file
    
    Args:
        trade_data (dict): Dictionary containing trade details
    """
    import os
    import json
    from datetime import datetime
    
    log_dir = 'trade_logs'
    os.makedirs(log_dir, exist_ok=True)
    
    # Create a log file with today's date
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(log_dir, f'trades_{today}.json')
    
    # Add timestamp if not present
    if 'timestamp' not in trade_data:
        trade_data['timestamp'] = datetime.now().isoformat()
    
    # Append to log file
    try:
        # Read existing logs
        existing_logs = []
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                try:
                    existing_logs = json.load(f)
                    if not isinstance(existing_logs, list):
                        existing_logs = [existing_logs]
                except json.JSONDecodeError:
                    existing_logs = []
        
        # Append new trade
        existing_logs.append(trade_data)
        
        # Write back to file
        with open(log_file, 'w') as f:
            json.dump(existing_logs, f, indent=2)
            
        print(f"[TRADE] Trade logged to {log_file}")
        
    except Exception as e:
        print(f"[ERROR] Failed to log trade: {e}")


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
    except Exception as e:
        logger.error(f"Error in on_event_data: {e}", exc_info=True)

def update_live_data(tick, existing_data=None):
    """Update live data with new tick"""
    try:
        # Create a new row from the tick
        new_row = pd.DataFrame([{
            'date': tick['timestamp'],
            'open': tick['open'],
            'high': tick['high'],
            'low': tick['low'],
            'close': tick['close'],
            'volume': tick['volume']
        }])
        
        # Set the index to the timestamp
        new_row.set_index('date', inplace=True)
        
        # Initialize data if needed
        if existing_data is None or existing_data.empty:
            return new_row
            
        # Append to existing data
        updated_data = pd.concat([existing_data, new_row])
        
        # Drop duplicates (in case we get the same tick multiple times)
        updated_data = updated_data[~updated_data.index.duplicated(keep='last')]
        
        # Sort by index to ensure chronological order
        updated_data = updated_data.sort_index()
        
        # Keep only the most recent data (e.g., last 1000 candles)
        if len(updated_data) > 1000:
            updated_data = updated_data.iloc[-1000:]
            
        return updated_data
        
    except Exception as e:
        logger.error(f"Error updating live data: {e}", exc_info=True)
        return existing_data if existing_data is not None else pd.DataFrame()

breeze.on_ticks = on_event_data

# Globals for custom candle building
candle_minute = None
candle_data = {}
last_minute = None  # kept for backward compatibility but no longer used

import sys

def load_config():
    """Load and validate configuration"""
    config = configparser.ConfigParser()
    
    try:
        # Try to read the config file
        if not os.path.exists('config.properties'):
            logger.error("config.properties file not found")
            return None
            
        config.read('config.properties')
        
        # Validate required sections
        required_sections = ['DEFAULT', 'STRATEGY']
        for section in required_sections:
            if section not in config:
                logger.error(f"Missing required section in config: {section}")
                return None
        
        # Get API credentials
        api_key = config['DEFAULT'].get('api_key')
        api_secret = config['DEFAULT'].get('api_secret')
        
        if not api_key or not api_secret:
            logger.error("API key and secret are required in config")
            return None
            
        # Get trading parameters with defaults
        config_dict = {
            'api_key': api_key,
            'api_secret': api_secret,
            'session_token': config['DEFAULT'].get('session_token', ''),
            'exchange_code': config['DEFAULT'].get('exchange_code', 'NSE'),
            'product_type': config['DEFAULT'].get('product_type', 'cash').lower(),
            'interval': config['DEFAULT'].get('interval', '1minute'),
            'expiry_date': config['DEFAULT'].get('expiry_date', ''),
            'strike_price': config['DEFAULT'].get('strike_price', '0'),
            'right': config['DEFAULT'].get('right', 'call'),
            'strategy_approach': config['STRATEGY'].get('approach', 'strict').lower(),
            'atr_multiplier': float(config['STRATEGY'].get('atr_multiplier', '1.5')),
            'min_profit_threshold': float(config['STRATEGY'].get('min_profit_threshold', '0.5')),
            'risk_per_trade': float(config['STRATEGY'].get('risk_per_trade', '1.0')),  # 1% of portfolio
            'max_position_size': float(config['STRATEGY'].get('max_position_size', '10.0')),  # 10% of portfolio
        }
        
        # Parse stock codes
        stocks_str = config['DEFAULT'].get('stock_code', '')
        config_dict['stock_codes'] = [s.strip('"\' ') for s in stocks_str.split(',') if s.strip('"\' ')]
        
        if not config_dict['stock_codes']:
            logger.error("No stock codes found in configuration")
            return None
            
        logger.info(f"Loaded configuration for {len(config_dict['stock_codes'])} stocks")
        
        return config_dict
        
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}", exc_info=True)
        return None

# Load configuration
config = load_config()
if not config:
    logger.critical("Failed to load configuration. Exiting.")
    sys.exit(1)

# Set global variables
api_key = config['api_key']
api_secret = config['api_secret']
session_token = config['session_token']
stock_codes = config['stock_codes']
exchange_code = config['exchange_code']
product_type = config['product_type']
interval = config['interval']
expiry_date = config['expiry_date']
strike_price = config['strike_price']
right = config['right']

# Print subscription parameters for debugging
print(f"\nVerifying stocks: {', '.join(stock_codes)} on {exchange_code}")
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

def subscribe_to_stocks():
    """Subscribe to WebSocket for live data for all configured stocks"""
    try:
        # Get list of stocks from config
        stock_list = []
        config_section = config['CASH']  # Default section
        
        if 'stock_code' in config_section:
            stocks_str = config_section['stock_code']
            # Parse comma-separated list, handling quotes and whitespace
            stock_list = [s.strip('"\' ') for s in stocks_str.split(',') if s.strip('"\' ')]
        
        if not stock_list:
            logger.error("No stocks found in configuration")
            return False
            
        logger.info(f"Subscribing to {len(stock_list)} stocks: {', '.join(stock_list)}")
        
        # Get common parameters
        exchange_code = config.get('exchange_code', 'NSE')
        product_type = config.get('product_type', 'cash').lower()
        expiry_date = config.get('expiry_date', '')
        strike_price = config.get('strike_price', '0')
        right = config.get('right', 'call' if product_type == 'options' else 'others')
        
        # Subscribe to each stock
        for symbol in stock_list:
            try:
                logger.info(f"Subscribing to {symbol} on {exchange_code}...")
                
                # Subscribe based on product type
                if product_type == "options":
                    breeze.subscribe_feeds(
                        exchange_code=exchange_code,
                        stock_code=symbol,
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
                        stock_code=symbol,
                        product_type=product_type,
                        expiry_date=expiry_date,
                        get_market_depth=False,
                        get_exchange_quotes=True
                    )
                else:  # cash
                    breeze.subscribe_feeds(
                        exchange_code=exchange_code,
                        stock_code=symbol,
                        product_type=product_type,
                        get_market_depth=False,
                        get_exchange_quotes=True
                    )
                
                logger.info(f"Successfully subscribed to {symbol}")
                
            except Exception as e:
                logger.error(f"Failed to subscribe to {symbol}: {str(e)}", exc_info=True)
                
        return True
        
    except Exception as e:
        logger.critical(f"Error in subscribe_to_stocks: {str(e)}", exc_info=True)
        return False

if subscribe_to_stocks():
    print("\nSubscription completed successfully. Waiting for data...")
    print("Triple Screen Strategy integration is ready.")
    print("If no data appears, it might be because:")
    print("1. The market is closed or the instrument isn't actively trading")
    print("2. There's an issue with the WebSocket connection")
    print("3. The subscription parameters aren't matching any active instrument")
    print("\nStarting heartbeat to monitor connection...")
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

def main():
    """Main function to initialize and run the trading bot"""
    global breeze, stock_processors
    
    try:
        logger.info("=== Starting Trading Bot ===")
        
        # Initialize Breeze connection
        breeze = initialize_breeze_connection()
        if not breeze:
            logger.error("Failed to initialize Breeze connection. Exiting.")
            return 1
        
        # Start the heartbeat thread
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        
        # Start all stock processors
        if not start_all_stock_processors():
            logger.error("Failed to start stock processors. Exiting.")
            return 1
        
        logger.info("Trading bot is running. Press Ctrl+C to stop.")
        
        # Keep the main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutdown requested by user...")
        
        return 0
        
    except Exception as e:
        logger.critical(f"Fatal error in main thread: {str(e)}", exc_info=True)
        return 1
    finally:
        # Cleanup
        logger.info("Shutting down trading bot...")
        stop_all_stock_processors()
        logger.info("Trading bot stopped.")

def setup_websocket_connection():
    """Set up WebSocket connection and start it"""
    try:
        # Set up WebSocket callbacks
        breeze.on_ticks = on_event_data
        breeze.on_connect = on_connect
        breeze.on_close = on_close
        breeze.on_error = on_error
        breeze.on_reconnect = on_reconnect
        
        # Start WebSocket connection
        breeze.ws_connect()
        logger.info("WebSocket connection started")
        return True
        
    except Exception as e:
        logger.critical(f"Failed to set up WebSocket connection: {str(e)}", exc_info=True)
        return False

def main():
    """Main function to initialize and run the trading bot"""
    global breeze, stock_processors
    
    try:
        logger.info("=== Starting Trading Bot ===")
        
        # Initialize Breeze connection
        breeze = initialize_breeze_connection()
        if not breeze:
            logger.error("Failed to initialize Breeze connection. Exiting.")
            return 1
        
        # Start the heartbeat thread
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        
        # Start all stock processors
        if not start_all_stock_processors():
            logger.error("Failed to start stock processors. Exiting.")
            return 1
            
        # Set up and start WebSocket connection
        if not setup_websocket_connection():
            logger.error("Failed to set up WebSocket connection. Exiting.")
            return 1
            
        # Subscribe to stocks
        if not subscribe_to_stocks():
            logger.error("Failed to subscribe to stocks. Exiting.")
            return 1
        
        logger.info("Trading bot is running. Press Ctrl+C to stop.")
        
        # Keep the main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutdown requested by user...")
        
        return 0
        
    except Exception as e:
        logger.critical(f"Fatal error in main thread: {str(e)}", exc_info=True)
        return 1
    finally:
        # Cleanup
        logger.info("Shutting down trading bot...")
        stop_all_stock_processors()
        if breeze:
            try:
                breeze.ws_disconnect()
                logger.info("WebSocket connection closed")
            except:
                pass
        logger.info("Trading bot stopped.")

if __name__ == "__main__":
    sys.exit(main())
