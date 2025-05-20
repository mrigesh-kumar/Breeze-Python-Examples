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
from app_config import load_config

# Load config from the [OPTIONS] section (or change to [FUTURES], [CASH] as needed)
config = load_config(config_file='config.properties', section='OPTIONS')

# Fallback to DEFAULT if not present
if not config:
    print("[ERROR] Could not load configuration. Exiting.")
    sys.exit(1)

# Credentials
api_key = config.get('app_key')
api_secret = config.get('secret_key')
api_session = config.get('session_token')

# Instrument details
exchange_code = config.get('exchange_code', 'NSE')
stock_code = config.get('stock_code', 'stock_code')
product_type = config.get('product_type', 'cash').lower()
expiry_date = config.get('expiry_date', 'expiry_date')
strike_price = config.get('strike_price', 'strike_price')
right = config.get('right', 'right')
interval = config.get('interval', '1minute')

# Connect to Breeze API
breeze = BreezeConnect(api_key=api_key)
breeze.generate_session(api_secret=api_secret, session_token=api_session)

# Set interval before any token operations
breeze.interval = interval

# Enable debug mode
breeze.debug = True

# Connect to WebSocket
print("Connecting to WebSocket...")
breeze.ws_connect()
print("WebSocket connection established")

def on_event_data(ticks):
    print("\n[FEED DATA] Time:", datetime.now().isoformat())
    print("Ticks:", ticks)
    print("---------------------------------------")

# Heartbeat function to confirm script is still running
def heartbeat():
    while True:
        print(f"[HEARTBEAT] Still connected and waiting for data... {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(30)

breeze.on_ticks = on_event_data

# Verify stock exists
print(f"Verifying stock: {stock_code} on {exchange_code}")
print("Subscribing with params:")
print("exchange_code:", exchange_code)
print("stock_code:", stock_code)
print("product_type:", product_type)
print("expiry_date:", expiry_date)
print("strike_price:", strike_price)
print("right:", right)
print("interval:", interval)
# Subscribe to live market data
if product_type == "options":
    breeze.subscribe_feeds(
        exchange_code=exchange_code,
        stock_code=stock_code,
        product_type=product_type,
        expiry_date=expiry_date,
        strike_price=strike_price,
        right=right,
        interval=interval,
        get_market_depth=False,
        get_exchange_quotes=True
    )
else:
    breeze.subscribe_feeds(
        exchange_code=exchange_code,
        stock_code=stock_code,
        product_type=product_type,
        expiry_date=expiry_date
    )

print("\nSubscription completed successfully. Waiting for data...")
print("If no data appears, it might be because:")
print("1. The market is closed or the instrument isn't actively trading")
print("2. There's an issue with the WebSocket connection")
print("3. The subscription parameters aren't matching any active instrument")
print("\nStarting heartbeat to monitor connection...")

# Start the heartbeat thread
heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
heartbeat_thread.start()

input("\nPress Enter to exit...\n")
