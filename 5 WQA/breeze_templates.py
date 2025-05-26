"""
Reusable Breeze API action templates for order management, portfolio, and tracking.
Values are read from config.properties when not provided as arguments.
"""
import configparser
from datetime import datetime
from breeze_connect import BreezeConnect

# Read config
config = configparser.ConfigParser()
config.read('config.properties')

def get_config(section, key, fallback=None):
    return config.get(section, key, fallback=fallback) if config.has_option(section, key) else fallback

# Initialize BreezeConnect (assumes session is already established in main script)
breeze = None  # To be set by main script

def set_breeze_instance(instance):
    global breeze
    breeze = instance

# --- Template Functions ---
def cancel_order(order_id=None, exchange_code=None):
    order_id = order_id or get_config('ORDER', 'order_id')
    exchange_code = exchange_code or get_config('ORDER', 'exchange_code')
    return breeze.cancel_order(exchange_code=exchange_code, order_id=order_id)

def modify_order(order_id=None, exchange_code=None, **kwargs):
    params = {
        'order_id': order_id or get_config('ORDER', 'order_id'),
        'exchange_code': exchange_code or get_config('ORDER', 'exchange_code'),
        'order_type': kwargs.get('order_type', 'limit'),
        'stoploss': kwargs.get('stoploss', '0'),
        'quantity': kwargs.get('quantity', '1'),
        'price': kwargs.get('price', '0'),
        'validity': kwargs.get('validity', 'day'),
        'disclosed_quantity': kwargs.get('disclosed_quantity', '0'),
        'validity_date': kwargs.get('validity_date', datetime.now().isoformat()),
    }
    return breeze.modify_order(**params)

def get_portfolio_positions():
    return breeze.get_portfolio_positions()

def square_off_futures(stock_code=None, expiry_date=None, quantity=None, **kwargs):
    params = {
        'exchange_code': kwargs.get('exchange_code', 'NFO'),
        'product': 'futures',
        'stock_code': stock_code or get_config('ORDER', 'stock_code'),
        'expiry_date': expiry_date or get_config('ORDER', 'expiry_date'),
        'action': kwargs.get('action', 'sell'),
        'order_type': kwargs.get('order_type', 'market'),
        'validity': kwargs.get('validity', 'day'),
        'stoploss': kwargs.get('stoploss', '0'),
        'quantity': quantity or get_config('ORDER', 'quantity', '1'),
        'price': kwargs.get('price', '0'),
        'validity_date': kwargs.get('validity_date', datetime.now().isoformat()),
        'trade_password': kwargs.get('trade_password', ''),
        'disclosed_quantity': kwargs.get('disclosed_quantity', '0'),
    }
    return breeze.square_off(**params)

def preview_order(stock_code=None, exchange_code=None, **kwargs):
    params = {
        'stock_code': stock_code or get_config('ORDER', 'stock_code'),
        'exchange_code': exchange_code or get_config('ORDER', 'exchange_code'),
        'product': kwargs.get('product', 'margin'),
        'order_type': kwargs.get('order_type', 'limit'),
        'price': kwargs.get('price', '0'),
        'action': kwargs.get('action', 'buy'),
        'quantity': kwargs.get('quantity', '1'),
        'specialflag': kwargs.get('specialflag', 'N'),
    }
    return breeze.preview_order(**params)

def get_order_detail(order_id=None, exchange_code=None):
    order_id = order_id or get_config('ORDER', 'order_id')
    exchange_code = exchange_code or get_config('ORDER', 'exchange_code')
    return breeze.get_order_detail(exchange_code=exchange_code, order_id=order_id)
    
def get_funds():
    """Get available funds from the Breeze API"""
    return breeze.get_funds()

def get_order_list(exchange_code=None, from_date=None, to_date=None):
    exchange_code = exchange_code or get_config('ORDER', 'exchange_code')
    from_date = from_date or get_config('ORDER', 'from_date', datetime.now().isoformat())
    to_date = to_date or get_config('ORDER', 'to_date', datetime.now().isoformat())
    return breeze.get_order_list(exchange_code=exchange_code, from_date=from_date, to_date=to_date)
