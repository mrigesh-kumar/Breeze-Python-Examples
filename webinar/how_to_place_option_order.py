import configparser
import os
from datetime import datetime
from breeze_connect import BreezeConnect

# Read config from properties file
config = configparser.ConfigParser(interpolation=None)
config_path = os.path.join(os.path.dirname(__file__), 'config.properties')
config.read(config_path)
get_config = lambda key: config['DEFAULT'].get(key) if 'DEFAULT' in config else config.get(key)

# Read all option order parameters from config
api_key = get_config('app_key')
api_secret = get_config('secret_key')
api_session = get_config('session_token')

stock = get_config('option_stock_code')
strike = get_config('option_strike')
expiry = get_config('option_expiry')
right = get_config('option_right')
quantity = get_config('option_quantity')
exchange_code = get_config('option_exchange_code')
product = get_config('option_product')
action = get_config('option_action')
order_type = get_config('option_order_type')
validity = get_config('option_validity')
disclosed_quantity = get_config('option_disclosed_quantity')

# Setup my API keys 
api = BreezeConnect(api_key=api_key)
api.generate_session(api_secret=api_secret, session_token=api_session)

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
