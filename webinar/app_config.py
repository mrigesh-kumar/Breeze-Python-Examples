"""
Configuration settings for the Triple Screen Trading System
"""

import os
import configparser

# Portfolio parameters
INITIAL_CAPITAL = 10000000  # 1 crore initial capital
RISK_PER_TRADE = 0.01  # 1% of portfolio per trade
MAX_POSITIONS = 3

# Timeframe configuration
HIGHER_TIMEFRAME = "1day"    # Trend identification timeframe
MIDDLE_TIMEFRAME = "4hour"   # Entry signal timeframe
LOWER_TIMEFRAME = "1hour"    # Execution timeframe
DAYS_BACK = 30               # Number of days to look back for backtesting

# Higher timeframe parameters - trend identification
EMA_FAST_PERIOD = 20  # Fast EMA for responsive trend detection
EMA_SLOW_PERIOD = 50  # Reduced from 100 for more responsive trend detection

# Middle timeframe parameters - entry timing
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Lower timeframe parameters - execution
ATR_PERIOD = 14
TRAILING_PERCENT = 4.0  # Increased from 2.5 to 4.0 to give trades much more room to breathe
PROFIT_TARGET_ATR_MULT = 2.0  # Maintain reasonable profit targets
RISK_REWARD_RATIO = 1.5  # Realistic risk-reward ratio

# Volume filter parameters
VOLUME_EMA_PERIOD = 20  # For volume moving average calculation
MIN_VOLUME_RATIO = 0.8  # Minimum volume ratio for volume filter

# Support/Resistance parameters
PIVOT_WINDOW = 5  # Lookback/forward periods for pivot detection
SR_BUFFER_PERCENT = 0.005  # Buffer below support for stop loss (0.5%)

# Position sizing parameters
MAX_RISK_PERCENT_PER_POSITION = 0.01  # 1% max risk per position
MAX_POSITION_SIZE_PERCENT = 0.05  # Maximum 5% of capital per position
MAX_SHARES_PER_TRADE = 10000  # Cap maximum position size

# Volatility filters
MIN_ATR_PERCENT = 0.001  # Minimum ATR threshold

# Advanced confirmation filters
ADX_PERIOD = 14  # Period for ADX calculation
MIN_ADX_THRESHOLD = 20  # Minimum ADX value for strong trend
PRICE_ACTION_LOOKBACK = 3  # Lookback period for price action patterns

def load_config(config_file='config.properties', section=None):
    """
    Load configuration from a properties file
    
    Args:
        config_file: Path to the configuration file
        section: Section name to load (None for DEFAULT)
        
    Returns:
        Dictionary with configuration values
    """
    config = configparser.RawConfigParser(interpolation=None)
    
    # Find config file path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, config_file)
    
    if not os.path.exists(config_path):
        print(f"[ERROR] Configuration file not found: {config_path}")
        return {}
    
    config.read(config_path)
    
    # Get correct section
    if section and section in config.sections():
        section_to_use = section
    else:
        section_to_use = 'DEFAULT'
    
    # Convert config values to appropriate types
    config_dict = {}
    for key, value in config[section_to_use].items():
        # Handle different value types
        if key in ['initial_capital', 'risk_per_trade', 'trailing_percent', 
                   'profit_target_atr_mult', 'risk_reward_ratio', 'min_volume_ratio', 
                   'sr_buffer_percent', 'min_atr_percent', 'max_risk_percent_per_position', 
                   'max_position_size_percent']:
            # Convert to float
            try:
                config_dict[key] = float(value)
            except ValueError:
                print(f"[WARN] Could not convert {key}={value} to float, using default")
                continue
                
        elif key in ['ema_fast_period', 'ema_slow_period', 'rsi_period', 
                     'rsi_overbought', 'rsi_oversold', 'macd_fast', 'macd_slow', 
                     'macd_signal', 'atr_period', 'max_positions', 'days_back', 
                     'volume_ema_period', 'pivot_window', 'max_shares_per_trade', 
                     'adx_period', 'min_adx_threshold', 'price_action_lookback']:
            # Convert to int
            try:
                config_dict[key] = int(value)
            except ValueError:
                print(f"[WARN] Could not convert {key}={value} to integer, using default")
                continue
                
        else:
            # Keep as string, remove quotes
            config_dict[key] = value.strip('"\'')
    
    return config_dict
