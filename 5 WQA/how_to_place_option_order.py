import configparser
import os
from datetime import datetime
from breeze_connect import BreezeConnect

# Read config from properties file
config = configparser.ConfigParser(interpolation=None)
# Use absolute path to ensure config is found
config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.properties')
print(f"Reading config from: {config_path}")
config.read(config_path)

# Define a safer config getter that checks if section exists
def get_config(key, section='OPTIONS', fallback_section='DEFAULT', default=None):
    # Try the primary section first
    if section in config and key in config[section]:
        return config[section][key]
    # Try the fallback section next
    elif fallback_section in config and key in config[fallback_section]:
        return config[fallback_section][key]
    # Return default if key not found in any section
    return default

# Read all option order parameters from config
api_key = get_config('app_key')
api_secret = get_config('secret_key')
api_session = get_config('session_token')

# Print all available keys in OPTIONS section for debugging
print("Available keys in OPTIONS section:")
if 'OPTIONS' in config:
    for key in config['OPTIONS']:
        print(f"  - {key} = {config['OPTIONS'][key]}")
else:
    print("  No OPTIONS section found!")

# Use the keys as they appear in your config file
stock = get_config('stock_code')
strike = get_config('strike_price')
expiry = get_config('expiry_date')
right = get_config('right')
quantity = get_config('quantity')
exchange_code = get_config('exchange_code')
product = get_config('product_type')
action = get_config('option_action')
order_type = get_config('option_order_type')
validity = get_config('option_validity')
disclosed_quantity = get_config('option_disclosed_quantity')

# Debug print to verify values
print(f"Using stock_code: {stock}")
print(f"Using strike_price: {strike}")
print(f"Using exchange_code: {exchange_code}")

# Setup my API keys 
api = BreezeConnect(api_key=api_key)
api.generate_session(api_secret=api_secret, session_token=api_session)
api.get_funds

today = datetime.today().strftime('%Y-%m-%d')

# Place order
buy_order = api.place_order(
    stock_code=stock,
    exchange_code=exchange_code,
    product=product,
    action=action,
    order_type=order_type,
    stoploss="",
    quantity=quantity,
    price="",
    validity=validity,
    validity_date=today,
    disclosed_quantity=disclosed_quantity,
    expiry_date=expiry,
    right=right,
    strike_price=strike
)

print(buy_order)
