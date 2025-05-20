"""
Simple script to test Breeze API connection and option contract info
"""
from breeze_connect import BreezeConnect
from app_config import load_config
import json
import sys

# --- Load config and credentials ---
config = load_config('config.properties', section='OPTIONS')
api_key = config['app_key']
api_secret = config['secret_key']
api_session = config['session_token']

# --- Initialize Breeze ---
breeze = BreezeConnect(api_key=api_key)
breeze.generate_session(api_secret=api_secret, session_token=api_session)

# Test basic API functionality
print("\n--- Testing basic API functionality ---")
try:
    user_profile = breeze.get_customer_details()
    print(f"✅ API Connection Successful: {user_profile.get('Name', 'Mrigesh')}")
    
    # Get current market price for ATM calculation
    index_info = breeze.get_indices("NSE", "NIFTY 50")
    current_price = float(index_info['Close'])
    
except Exception as e:
    print(f"❌ API Connection Failed: {e}")
    current_price = 25000  # Fallback price

# Get option chain
try:
    print("\n--- NIFTY Option Chain Information ---")
    option_chain = breeze.get_option_chain_quotes(
        stock_code="NIFTY",
        exchange_code="NFO",
        product_type="options",
        expiry_date="2025-05-29T06:00:00.000Z"
    )
    
    if option_chain and isinstance(option_chain, list):
        print(f"Found {len(option_chain)} options")
        
        # Process first 5 contracts as sample
        for opt in option_chain[:5]:
            print(f"{opt.get('strike_price')} | {opt.get('right')} | LTP: {opt.get('ltp')}")
    else:
        print("No options found or invalid response format")
        
except Exception as e:
    print(f"❌ Failed to get option chain: {e}")

# Example: Process option chain for specific expiry and right
try:
    option_chain = breeze.get_option_chain_quotes(
        stock_code="NIFTY",
        exchange_code="NFO",
        product_type="options",
        expiry_date="2025-05-29T06:00:00.000Z",
        right="Call"
    )
    
    if option_chain:
        print(f"\nFound {len(option_chain)} Call options for expiry: 2025-05-29")
        
        # Filter and display ATM options (±2% from current price)
        atm_range = (current_price * 0.98, current_price * 1.02)
        
        atm_options = [
            opt for opt in option_chain
            if atm_range[0] <= float(opt['strike_price']) <= atm_range[1]
        ]
        
        print(f"\nATM Options (within 2% of {current_price}):")
        for opt in sorted(atm_options, key=lambda x: float(x['strike_price'])):
            print(f"{opt['strike_price']} | LTP: {opt['ltp']} | OI: {opt['open_interest']}")
    else:
        print("No options found for given criteria")
        
except Exception as e:
    print(f"❌ Failed to fetch option chain: {e}")

print("\n--- Validating NIFTY Option Contract ---")
try:
    # Test with known good parameters
    symbol = "NIFTY"
    expiry_date = "29-May-2025"  # Use current expiry
    strike_price = "25000"  # ATM strike
    right = "Call"
    
    print(f"Testing contract: {symbol} {expiry_date} {strike_price} {right}")
    
    # Get contract token
    token = breeze.get_stock_token_value(
        exchange_code="NFO",
        stock_code=symbol,
        product_type="options",
        expiry_date=expiry_date,
        strike_price=strike_price,
        right=right
    )
    
    if token[0]:
        print("✅ Valid contract found!")
        print(f"Token: {token[0]}")
        print("\nRecommended Parameters:")
        print(f"stock_code='{symbol}'")
        print(f"expiry_date='{expiry_date}'")
        print(f"strike_price='{strike_price}'")
        print(f"right='{right}'")
    else:
        print("❌ Contract not found")
        print("Try different parameters or check if market is open")
        
except Exception as e:
    print(f"❌ Validation failed: {e}")
