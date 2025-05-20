"""
LIVE OPTIONS STRATEGY WITH REAL-TIME DATA
-----------------------------------------
This script enables live strategy execution for Options Market (NFO) using BreezeConnect WebSocket,
while keeping the backtesting workflow in triple_screen_main.py unchanged.
- Prompts user for option contract details
- Subscribes to live option feed
- Aggregates ticks into 1-minute bars
- Calls the existing strategy logic on each new bar
"""

import time
from datetime import datetime, timedelta
import pandas as pd
import sys
from breeze_connect import BreezeConnect
from app_config import load_config
from triple_screen_strategy import TripleScreenStrategy  # or import your strategy class

# --- Helper: Bar Aggregator ---
class LiveBarBuilder:
    def __init__(self, interval_seconds=60):
        self.interval = timedelta(seconds=interval_seconds)
        self.current_bar = None
        self.last_bar_close = None
        self.bars = []

    def update(self, tick):
        tick_time = datetime.strptime(tick['datetime'], '%Y-%m-%dT%H:%M:%S.%fZ')
        price = float(tick['last_traded_price'])
        volume = int(tick.get('volume', 0))
        
        # Start a new bar if needed
        if self.current_bar is None or tick_time >= self.last_bar_close:
            if self.current_bar:
                self.bars.append(self.current_bar)
            bar_start = tick_time.replace(second=0, microsecond=0)
            bar_end = bar_start + self.interval
            self.current_bar = {
                'datetime': bar_start,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': volume
            }
            self.last_bar_close = bar_end
        else:
            self.current_bar['high'] = max(self.current_bar['high'], price)
            self.current_bar['low'] = min(self.current_bar['low'], price)
            self.current_bar['close'] = price
            self.current_bar['volume'] += volume

    def get_new_bars(self):
        new_bars = self.bars[:]
        self.bars = []
        return new_bars

def validate_option_contract(breeze, symbol, expiry_date, strike_price, right):
    """Validate option contract exists and return token"""
    try:
        # Convert right to proper case (Call/Put)
        right = right.title()
        
        # First verify the contract exists
        token_value = breeze.get_stock_token_value(
            exchange_code="NFO",
            stock_code=symbol,
            product_type="options",
            expiry_date=expiry_date,
            strike_price=strike_price,
            right=right
        )
        
        if token_value[0] is False:
            raise ValueError(f"Invalid option contract for {symbol} {expiry_date} {strike_price} {right}")
            
        return token_value
        
    except Exception as e:
        print(f"❌ Contract validation failed: {str(e)}")
        print(f"Run test_breeze_api.py to check available contracts")
        return None

# --- Load config and credentials ---
config = load_config('config.properties', section='OPTIONS')
api_key = config.get('DEFAULT', 'app_key') or config.get('app_key')
api_secret = config.get('DEFAULT', 'secret_key') or config.get('secret_key')
api_session = config.get('DEFAULT', 'session_token') or config.get('session_token')

print(f"API Key: {'*'*8}{api_key[-4:]}" if api_key else "ERROR: API Key missing")
print(f"API Secret: {'*'*8}{api_secret[-4:]}" if api_secret else "ERROR: API Secret missing")
print(f"Session Token: {'*'*8}{api_session[-4:]}" if api_session else "WARNING: Session Token missing")

if not all([api_key, api_secret]):
    raise ValueError("Missing required API credentials in config.properties")

# --- Initialize Breeze ---
breeze = BreezeConnect(api_key=api_key)
breeze.generate_session(api_secret=api_secret, session_token=api_session)

# --- Get option details from config ---
symbol = str(config.get('stock_code', 'NIFTY'))
expiry_date = str(config.get('expiry_date', '29-May-2025'))
strike_price = str(config.get('strike_price', '23000'))
right = str(config.get('right', 'Call'))  # Note: Using 'Call' instead of 'CE'

print(f"\n[CONTRACT DETAILS] Symbol: {symbol} | Expiry: {expiry_date} | Strike: {strike_price} | Right: {right}")

# Validate contract before subscribing
contract_token = validate_option_contract(breeze, symbol, expiry_date, strike_price, right)
if not contract_token:
    sys.exit(1)

# --- Subscribe to live feed ---
breeze.ws_connect()
bar_builder = LiveBarBuilder(interval_seconds=60)

# For demo, maintain a DataFrame of bars
bars_df = pd.DataFrame(columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])

try:
    print("\nSubscribing to live option feed...")
    breeze.subscribe_feeds(
        exchange_code="NFO",
        stock_code=symbol,
        product_type="options",
        expiry_date=expiry_date,
        strike_price=strike_price,
        right=right,
        get_exchange_quotes=True,
        get_market_depth=False,
        interval="1minute"
    )
    print("✅ Successfully subscribed to live feed")
    
    # --- Live tick handler ---
    def on_event_data(ticks):
        # ticks: list of dicts (one per instrument)
        for tick in ticks:
            bar_builder.update(tick)
        new_bars = bar_builder.get_new_bars()
        for bar in new_bars:
            global bars_df
            bars_df = pd.concat([bars_df, pd.DataFrame([bar])], ignore_index=True)
            print(f"New bar: {bar}")
            # TODO: Call your strategy logic here, e.g.:
            # result = run_strategy_on_live_bar(bar, bars_df)
            # print(result)

    breeze.on_ticks = on_event_data

    print("Receiving live ticks. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting live option strategy.")

except Exception as e:
    print(f"❌ Subscription failed: {str(e)}")
    print("Possible solutions:")
    print("1. Verify contract details with test_breeze_api.py")
    print("2. Check if market is open")
    print("3. Confirm your API credentials are valid")
