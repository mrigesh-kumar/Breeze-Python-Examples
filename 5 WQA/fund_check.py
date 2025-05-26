"""
Fund and Order Validation Module for Triple Screen Trading Strategy
-------------------------------------------------------------------
This module contains functions for checking if there are sufficient funds 
before placing orders and other order validation routines.
"""

import time
from datetime import datetime
import json
import os

# Global variables for account tracking
account_balance = None
last_balance_check_time = None
BALANCE_CHECK_INTERVAL = 300  # Check balance every 5 minutes

def get_account_balance(breeze_instance):
    """
    Fetch account details from the Breeze API and extract available balance.
    This function caches the result for BALANCE_CHECK_INTERVAL seconds to avoid excessive API calls.
    
    Args:
        breeze_instance: The BreezeConnect instance to use for API calls
    
    Returns:
        float: Available balance or None if error
    """
    global account_balance, last_balance_check_time
    current_time = time.time()
    
    # Return cached balance if recent enough
    if account_balance is not None and last_balance_check_time is not None:
        if current_time - last_balance_check_time < BALANCE_CHECK_INTERVAL:
            return account_balance
    
    try:
        # Fetch account limits from API
        resp = breeze_instance.get_limits()
        if not resp or not isinstance(resp, dict) or 'Success' not in resp:
            print("[ERROR] Failed to fetch account details")
            return None
        
        # Extract available cash balance
        account_data = resp['Success']
        
        # Handle different response formats based on exchange
        if 'cash_available' in account_data:
            # Direct cash_available field
            available_balance = float(account_data['cash_available'])
        elif 'cash' in account_data and 'available_margin' in account_data['cash']:
            # For some exchange types, the balance is nested
            available_balance = float(account_data['cash']['available_margin'])
        else:
            # If structure isn't recognized, log error and return cached value or None
            print(f"[ERROR] Unknown account data format: {account_data.keys()}")
            return account_balance
            
        # Update cached values
        account_balance = available_balance
        last_balance_check_time = current_time
        
        print(f"[INFO] Available account balance: ₹{account_balance:.2f}")
        return account_balance
        
    except Exception as e:
        print(f"[ERROR] Error fetching account balance: {e}")
        return account_balance  # Return last known balance if error occurs

def validate_order(breeze_instance, action, symbol, price, quantity):
    """
    Validate an order before executing it:
    - For BUY orders: check if there's sufficient balance
    - For SELL orders: to be implemented if needed
    
    Args:
        breeze_instance: The BreezeConnect instance
        action: 'BUY' or 'SELL' 
        symbol: Stock symbol
        price: Price per share
        quantity: Number of shares
        
    Returns:
        bool: True if the order is valid, False otherwise
    """
    if action.upper() == 'BUY':
        return check_sufficient_funds(breeze_instance, symbol, price, quantity)
    
    # For SELL orders, additional validation could be added here
    return True

def check_sufficient_funds(breeze_instance, symbol, price, quantity):
    """
    Check if there is sufficient balance to place a buy order.
    
    Args:
        breeze_instance: The BreezeConnect instance
        symbol: Stock symbol
        price: Price per share
        quantity: Number of shares
        
    Returns:
        bool: True if sufficient funds, False otherwise
    """
    if price <= 0 or quantity <= 0:
        return False
        
    # Get account balance
    balance = get_account_balance(breeze_instance)
    if balance is None:
        # If we can't determine balance, return True and let the broker reject if needed
        print("[WARNING] Unable to verify available funds. Proceeding with order anyway.")
        return True
        
    # Calculate required funds - exact amount with no buffer
    required_funds = price * quantity
    
    # Check if enough funds (exact match, no buffer)
    has_sufficient_funds = balance >= required_funds
    
    if not has_sufficient_funds:
        print(f"[ERROR] Insufficient funds for {symbol} order. Required: ₹{required_funds:.2f}, Available: ₹{balance:.2f}")
    
    return has_sufficient_funds

def log_order_validation(action, symbol, price, quantity, is_valid, reason=None):
    """
    Log order validation result to a file for record keeping
    
    Args:
        action: 'BUY' or 'SELL'
        symbol: Stock symbol
        price: Price per share
        quantity: Number of shares
        is_valid: Whether the order passed validation
        reason: Reason if validation failed
    """
    validation_log = {
        'timestamp': datetime.now().isoformat(),
        'action': action,
        'symbol': symbol,
        'price': price,
        'quantity': quantity,
        'is_valid': is_valid,
        'reason': reason
    }
    
    log_file = 'order_validations.json'
    
    try:
        # Read existing logs
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                logs = json.load(f)
        else:
            logs = []
        
        # Add new log
        logs.append(validation_log)
        
        # Write updated logs
        with open(log_file, 'w') as f:
            json.dump(logs, f, indent=2)
            
    except Exception as e:
        print(f"[ERROR] Failed to log order validation: {e}")
