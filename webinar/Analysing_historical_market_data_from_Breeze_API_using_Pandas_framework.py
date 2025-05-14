import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import configparser
from breeze_connect import BreezeConnect
from datetime import datetime, timedelta
import pandas as pd
import backtrader as bt
import os
import glob
from technical_indicators import TechnicalIndicators
import numpy as np

# Read config from properties file
config = configparser.RawConfigParser(interpolation=None)
config_path = os.path.join(os.path.dirname(__file__), 'config.properties')
config.read(config_path)

# --- Robust config getter with fallback and warning ---
def get_config(key, section=None, default=None):
    try:
        if section:
            if config.has_option(section, key):
                return config.get(section, key)
        if config.has_option('DEFAULT', key):
            return config.get('DEFAULT', key)
    except Exception as e:
        print(f"[WARN] Could not read config key '{key}' from section '{section}': {e}")
    if default is not None:
        print(f"[WARN] Using default value for '{key}': {default}")
    return default

def get_config_old(key, section=None):
    # Try to get from section first, then fallback to DEFAULT
    if section and section in config:
        if key in config[section]:
            return config[section][key]
    if 'DEFAULT' in config and key in config['DEFAULT']:
        return config['DEFAULT'][key]
    return None

# --- Prompt user for market type (Options, Futures, Cash) ---
market_type_map = {'1': 'OPTIONS', '2': 'FUTURES', '3': 'CASH'}
print("Select market type:")
print("  1. Options")
print("  2. Futures")
print("  3. Cash")
market_type_choice = input("Enter 1, 2, or 3: ").strip()
while market_type_choice not in ['1', '2', '3']:
    market_type_choice = input("Invalid choice. Please enter 1 for Options, 2 for Futures, or 3 for Cash: ").strip()
selected_market_type = market_type_map[market_type_choice]

# --- Load correct parameters based on market type section, fallback to DEFAULT ---
section = selected_market_type
from datetime import datetime

def parse_config_datetime(dt_str):
    dt_str = dt_str.strip().replace('"', '').replace("'", "")
    parts = [x.strip() for x in dt_str.split(',') if x.strip() != '']
    if len(parts) < 3:
        raise ValueError(f"Date string '{dt_str}' is not valid. Needs at least year, month, day.")
    try:
        return datetime(*[int(x) for x in parts])
    except Exception as e:
        print(f"[ERROR] Could not parse datetime from '{dt_str}': {e}")
        raise

params = {
    'stock_code': get_config('stock_code', section).strip('"'),
    'exchange_code': get_config('exchange_code', section).strip('"'),
    'product_type': get_config('product_type', section).strip('"'),
    'interval': get_config('interval', section).strip('"'),
    'from_date': parse_config_datetime(get_config('from_date', section)),
    'to_date': parse_config_datetime(get_config('to_date', section)),
    'expiry_date': parse_config_datetime(get_config('expiry_date', section)),
    'right': get_config('right', section).strip('"'),
    'strike_price': get_config('strike_price', section).strip('"')
}
csv_filename = f"{selected_market_type.lower()}_{params['stock_code']}_{params['interval']}.csv"
print("csv_filename : " , csv_filename)

# --- Check for data in CSV, else fetch from API ---
csv_path = get_config('csv_folder', section).strip('"') + "/" + csv_filename
print("csv_path : " , csv_path)
data_loaded_from_csv = False
if os.path.exists(csv_path):
    try:
        df_hdata = pd.read_csv(csv_path)
        if not df_hdata.empty and 'datetime' in df_hdata.columns:
            df_hdata['datetime'] = pd.to_datetime(df_hdata['datetime'])
            from_dt = pd.to_datetime(params['from_date'])
            to_dt = pd.to_datetime(params['to_date'])
            if (df_hdata['datetime'].min() <= from_dt) and (df_hdata['datetime'].max() >= to_dt):
                data_loaded_from_csv = True
    except Exception as e:
        print(f"[WARN] Could not read CSV: {e}")

if not data_loaded_from_csv:
    api_key = get_config('app_key')
    api_secret = get_config('secret_key')
    api_session = get_config('session_token')

    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=api_session)

    try:
        names_info = breeze.get_names(exchange_code=params['exchange_code'], stock_code=params['stock_code'])
        resolved_stock_code = names_info.get('isec_stock_code', params['stock_code'])
    except Exception as e:
        print(f"[WARN] get_names() failed, using original stock_code. Reason: {e}")
        resolved_stock_code = params['stock_code']

    # Compose a descriptive log message like 'NIFTY 24500 15 min candle'
    log_parts = [
        str(params.get('stock_code', '')),
        str(params.get('strike_price', '')) if params.get('strike_price') and params.get('strike_price') != '0' else '',
        str(params.get('interval', '')),
    ]
    log_msg = ' '.join([part for part in log_parts if part]).replace('  ', ' ').strip()
    print(f"[INFO] Fetching historical data for {log_msg} from Breeze API...")
    print("[DEBUG] Breeze API request parameters:")
    print(params)
    try:
        data = breeze.get_historical_data_v2(
            interval=params['interval'],
            from_date=params['from_date'].strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            to_date=params['to_date'].strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            stock_code=resolved_stock_code,
            exchange_code=params['exchange_code'],
            product_type=params['product_type'],
            expiry_date=params['expiry_date'].strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            right=params['right'],
            strike_price=params['strike_price']
        )
        df_hdata = pd.DataFrame(data['Success'])
        df_hdata.to_csv(csv_path, index=False)
        with open('webinar/data_load.log', 'a') as logf:
            logf.write(f"{datetime.now()} - {log_msg} data saved to {csv_filename}\n")
        print(f"[INFO] Data saved to {csv_filename} and logged.")
    except Exception as e:
        print(f"[ERROR] Exception while fetching data from Breeze API: {e}")
        df_hdata = pd.DataFrame()
else:
    print(f"[INFO] Loaded data from {csv_filename}.")

# --- DataFrame diagnostics ---
print("[INFO] DataFrame columns:", df_hdata.columns)
print("[INFO] Number of rows:", len(df_hdata))
print(df_hdata.head())

# NEW: Check if DataFrame is empty and print API parameters if so
if df_hdata.empty:
    print("[ERROR] DataFrame is empty! No data returned from Breeze API.")
    print("[DEBUG] Parameters used:")
    print(f"stock_code: {get_config('stock_code', section)}")
    print(f"exchange_code: {get_config('exchange_code', section)}")
    print(f"product_type: {get_config('product_type', section)}")
    print(f"from_date: {get_config('from_date', section)}")
    print(f"to_date: {get_config('to_date', section)}")
    print(f"interval: {get_config('interval', section)}")
    print(f"expiry_date: {get_config('expiry_date', section)}")
    print(f"right: {get_config('right', section)}")
    print(f"strike_price: {get_config('strike_price', section)}")
    print("[SUGGESTION] Check if these parameters are correct and if data is available for this combination.")
    print("[DEBUG] If you see an empty or error response above, the issue is with the API or parameters.")
    import sys; sys.exit(1)

# === Example: Calculate Technical Indicators ===
# Calculate MACD
macd_df = TechnicalIndicators.calculate_macd(df_hdata, close_col='close')

# Calculate Stochastic RSI
stochrsi_df = TechnicalIndicators.calculate_stochastic_rsi(df_hdata, close_col='close')

# Optionally merge with main DataFrame
df_hdata = df_hdata.join(macd_df)
df_hdata = df_hdata.join(stochrsi_df)

# --- Calculate classic and Fibonacci pivots/support/resistance levels ---
pivots_classic = TechnicalIndicators.calculate_pivots(df_hdata)
pivots_fibo = TechnicalIndicators.calculate_fibonacci_pivots(df_hdata)
# Add suffix to avoid column name clash
pivots_fibo = pivots_fibo.add_suffix('_fibo')
df_hdata = df_hdata.join(pivots_classic).join(pivots_fibo)

# --- Signal confirmation logic ---
# Signal only when all of: MACD bullish, Stochastic RSI bullish, high volume, and trend is bullish
print("[INFO] Using MACD, Stochastic RSI, high volume, and trend filter for signal generation.")

# Calculate trend using SMA or user-defined method (e.g., 50-period SMA)
df_hdata['SMA50'] = df_hdata['close'].rolling(window=50).mean()
df_hdata['trend'] = 'sideways'
df_hdata.loc[df_hdata['close'] > df_hdata['SMA50'], 'trend'] = 'bullish'
df_hdata.loc[df_hdata['close'] < df_hdata['SMA50'], 'trend'] = 'bearish'

# MACD bullish: MACD > Signal
macd_bull = df_hdata['MACD'] > df_hdata['Signal']
# Stochastic RSI bullish: %K < 20
stoch_bull = df_hdata['%K'] < 20
# MACD bearish: MACD < Signal
macd_bear = df_hdata['MACD'] < df_hdata['Signal']
# Stochastic RSI bearish: %K > 80
stoch_bear = df_hdata['%K'] > 80
# High volume: >2x median of previous 10 candles
def is_high_volume(idx, df, volume_multiplier=2):
    if idx < 10:
        return False
    recent_vol = df['volume'].iloc[idx-10:idx]
    median_vol = recent_vol.median()
    return df['volume'].iloc[idx] > (volume_multiplier * median_vol)

# Find bullish and bearish signals where all conditions are met
bullish_signal_indices = []
bearish_signal_indices = []
for idx, row in df_hdata.iterrows():
    if (
        macd_bull.iloc[idx]
        and stoch_bull.iloc[idx]
        and row['trend'] == 'bullish'
        and is_high_volume(idx, df_hdata)
    ):
        bullish_signal_indices.append(idx)
    if (
        macd_bear.iloc[idx]
        and stoch_bear.iloc[idx]
        and row['trend'] == 'bearish'
        and is_high_volume(idx, df_hdata)
    ):
        bearish_signal_indices.append(idx)

bullish_signals = df_hdata.loc[bullish_signal_indices].copy()
bullish_signals['Combined_Signal'] = 'bullish'
bearish_signals = df_hdata.loc[bearish_signal_indices].copy()
bearish_signals['Combined_Signal'] = 'bearish'

# --- Enhanced signal confirmation logic (trade only NEAR S/R) ---
confirmed_signals = []
for idx, sig_row in pd.concat([bullish_signals, bearish_signals]).iterrows():
    dt = sig_row['datetime']
    sig_type = sig_row['Combined_Signal']
    candle_idx = df_hdata.index[df_hdata['datetime'] == dt]
    if len(candle_idx) == 0:
        continue
    next_idx = candle_idx[0]
    close = sig_row['close']
    volume = sig_row['volume']
    found = False
    if sig_type == 'bullish':
        for level in [df_hdata.loc[next_idx, 'r1'], df_hdata.loc[next_idx, 'r1_fibo'], df_hdata.loc[next_idx, 'r2'], df_hdata.loc[next_idx, 'r2_fibo']]:
            if abs(close - level) <= 0.005 * level and is_high_volume(next_idx, df_hdata):
                confirmed_signals.append({'datetime': df_hdata.loc[next_idx, 'datetime'],
                                         'close': close, 'signal': 'bullish', 'volume': volume,
                                         'level': f'near {level:.2f}', 'sr_level_val': float(level)})
                found = True
                break
    if sig_type == 'bearish':
        for level in [df_hdata.loc[next_idx, 's1'], df_hdata.loc[next_idx, 's1_fibo'], df_hdata.loc[next_idx, 's2'], df_hdata.loc[next_idx, 's2_fibo']]:
            if abs(close - level) <= 0.005 * level and is_high_volume(next_idx, df_hdata):
                confirmed_signals.append({'datetime': df_hdata.loc[next_idx, 'datetime'],
                                         'close': close, 'signal': 'bearish', 'volume': volume,
                                         'level': f'near {level:.2f}', 'sr_level_val': float(level)})
                found = True
                break
    if found:
        continue

confirmed_signals_df = pd.DataFrame(confirmed_signals)
# Initialize 'outcome' column if it doesn't exist
# Initialize 'outcome' column if it doesn't exist
if 'outcome' not in confirmed_signals_df.columns:
    confirmed_signals_df['outcome'] = 'unknown'  # or your logic to determine outcome

# Win/Loss Summary
if 'outcome' in confirmed_signals_df.columns:
    win_count = (confirmed_signals_df['outcome'] == 'target').sum()
    loss_count = (confirmed_signals_df['outcome'] == 'stop').sum()
    total = win_count + loss_count
    if total > 0:
        win_rate = (win_count/total)
    else:
        win_rate = 0
    print(f"Win: {win_count}, Loss: {loss_count}, Win Rate: {win_rate:.2%}")
else:
    print("[WARN] No 'outcome' column in confirmed_signals_df; skipping win/loss summary.")

# --- Custom Plotly Candlestick Chart for Signals and Trades ---
import plotly.graph_objs as go
import webbrowser

# Assume price_data is your DataFrame with columns: datetime, open, high, low, close
price_data = df_hdata.copy()
price_data['datetime'] = pd.to_datetime(price_data['datetime'])

# --- Merge signal info for plotting (if available) ---
if 'signal' not in price_data.columns:
    if 'confirmed_signals_df' in locals() and not confirmed_signals_df.empty:
        # Use the correct datetime column for merging
        if 'datetime' in confirmed_signals_df.columns:
            confirmed_signals_df['datetime'] = pd.to_datetime(confirmed_signals_df['datetime'])
            price_data = price_data.merge(
                confirmed_signals_df[['datetime', 'signal']],
                on='datetime', how='left'
            )
        else:
            print("[WARN] confirmed_signals_df has no datetime column for merging signals.")
fig = go.Figure()

# Add candlestick trace (default hover)
fig.add_trace(go.Candlestick(
    x=price_data['datetime'],
    open=price_data['open'],
    high=price_data['high'],
    low=price_data['low'],
    close=price_data['close'],
    increasing_line_color='green',
    decreasing_line_color='red',
    name='Candles',
    showlegend=True
))

# --- Add ATR and EMA indicators ---
def compute_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr = true_range.rolling(window=period).mean()
    return atr

def compute_ema(df, period=50):
    return df['close'].ewm(span=period, adjust=False).mean()

price_data['ATR'] = compute_atr(price_data)
price_data['EMA50'] = compute_ema(price_data)

# --- Improved Signal Generation ---
# MACD stricter: require delta > 0.1, longer signal line
macd_delta = price_data['MACD'] - price_data['Signal']
macd_signal = (macd_delta > 0.1)

# StochRSI: use only extremes, require %K > %D by margin
stochrsi_buy = (price_data['StochRSI'] < 0.2) & (price_data['%K'] > price_data['%D'] + 5)
stochrsi_sell = (price_data['StochRSI'] > 0.8) & (price_data['%K'] < price_data['%D'] - 5)

# ATR filter: only trade if ATR above its 20th percentile
atr_thresh = price_data['ATR'].quantile(0.2)
atr_good = price_data['ATR'] > atr_thresh

# EMA filter: only buy if close > EMA50, sell if < EMA50
ema_buy = price_data['close'] > price_data['EMA50']
ema_sell = price_data['close'] < price_data['EMA50']

# --- Add Breakout Confirmation and Fibonacci Pivot Check Logic ---
from technical_indicators import TechnicalIndicators

# Calculate Fibonacci pivots
fibo_pivots = TechnicalIndicators.calculate_fibonacci_pivots(price_data)
price_data = pd.concat([price_data, fibo_pivots], axis=1)

N = 10  # lookback period for breakout
PIVOT_THRESH = 0.002  # 0.2% proximity to pivot
signals = []

# Ensure MACD columns are available
macd_line = price_data['MACD'] if 'MACD' in price_data.columns else price_data['macd']
macd_signal = price_data['Signal'] if 'Signal' in price_data.columns else price_data.get('macd_signal')

# Calculate rolling average volume for volume filter
price_data['vol_ma'] = price_data['volume'].rolling(window=20).mean()
VOLUME_MULTIPLIER = 1.5  # Confirmation candle volume must be > 1.5x rolling mean

# Calculate rolling highs/lows for breakout detection (before main loop!)
price_data['rolling_high'] = price_data['close'].rolling(window=N).max()
price_data['rolling_low'] = price_data['close'].rolling(window=N).min()

# Ensure DataFrame index is unique and monotonic
price_data = price_data.reset_index(drop=True)
# Remove duplicate columns, keeping only the first occurrence
price_data = price_data.loc[:, ~price_data.columns.duplicated()]

# Limit the number of iterations to avoid infinite or excessive loops
max_signals = 1000  # or another reasonable upper limit
signal_count = 0

for i in range(N, len(price_data) - 1):
    if signal_count >= max_signals:
        print(f"[WARN] Signal loop stopped after {max_signals} iterations to prevent infinite execution.")
        break
    # --- MACD must be positive for bullish, negative for bearish ---
    # Bullish MACD
    if macd_line.iloc[i] > macd_signal.iloc[i]:
        # Bullish breakout detection
        if price_data['close'].iloc[i] > price_data['rolling_high'].iloc[i-1]:
            # Confirmation: next candle close > breakout close
            if price_data['close'].iloc[i+1] > price_data['close'].iloc[i]:
                # Volume filter
                if price_data['volume'].iloc[i+1] > VOLUME_MULTIPLIER * price_data['vol_ma'].iloc[i+1]:
                    # Check if close is near any resistance
                    for r in ['r1', 'r2', 'r3']:
                        pivot_val = float(price_data.loc[i+1, r])
                        close_val = float(price_data.loc[i+1, 'close'])
                        if abs(close_val - pivot_val) <= PIVOT_THRESH * pivot_val:
                            signals.append({
                                'index': i+1,
                                'datetime': price_data.loc[i+1, 'datetime'],
                                'signal_marker': 'bullish',
                                'pivot': r,
                                'pivot_val': pivot_val
                            })
                            signal_count += 1
                            break
    # Bearish MACD
    elif macd_line.iloc[i] < macd_signal.iloc[i]:
        # Bearish breakout detection
        if price_data['close'].iloc[i] < price_data['rolling_low'].iloc[i-1]:
            # Confirmation: next candle close < breakout close
            if price_data['close'].iloc[i+1] < price_data['close'].iloc[i]:
                # Volume filter
                if price_data['volume'].iloc[i+1] > VOLUME_MULTIPLIER * price_data['vol_ma'].iloc[i+1]:
                    # Check if close is near any support
                    for s in ['s1', 's2', 's3']:
                        pivot_val = float(price_data.loc[i+1, s])
                        close_val = float(price_data.loc[i+1, 'close'])
                        if abs(close_val - pivot_val) <= PIVOT_THRESH * pivot_val:
                            signals.append({
                                'index': i+1,
                                'datetime': price_data.loc[i+1, 'datetime'],
                                'signal_marker': 'bearish',
                                'pivot': s,
                                'pivot_val': pivot_val
                            })
                            signal_count += 1
                            break

# Clear previous signal markers
price_data['signal_marker'] = None
for sig in signals:
    price_data.at[sig['index'], 'signal_marker'] = sig['signal_marker']

# After signal generation loop, create confirmed_signal column for Backtrader
price_data['confirmed_signal'] = 0
for sig in signals:
    idx = sig['index']
    if sig['signal_marker'] == 'bullish':
        price_data.at[idx, 'confirmed_signal'] = 1
    elif sig['signal_marker'] == 'bearish':
        price_data.at[idx, 'confirmed_signal'] = -1

# --- Matched signals for post-analysis ---
matched_signals = price_data[price_data['signal_marker'].notnull()]
# Check for Matched Signals
if matched_signals.empty:
    print("[INFO] No matched signals found. Exiting script.")
    exit()  # or return if within a function

# Continue with analysis and plotting if there are matched signals
else:
    # --- POST-ANALYSIS: Clean, user-friendly outcome summary ---
    if len(matched_signals) == 0:
        print("[POST-ANALYSIS] No signals generated with current strategy settings.")
    else:
        # Print concise summary of matched signals and P/L
        if 'trade_results_df' in locals() and isinstance(trade_results_df, pd.DataFrame) and not trade_results_df.empty:
            required_cols = ['entry_time', 'signal', 'entry_price', 'exit_price', 'outcome', 'pnl']
            if all(col in trade_results_df.columns for col in required_cols):
                print(f"\nMatched signals: {len(trade_results_df)}")
                total_pnl = trade_results_df['pnl'].sum()
                print(f"Total Trade Profit/Loss: {total_pnl:.2f}")
                # Optionally: print a few sample trades for quick view
                print("Sample trades:")
                print(trade_results_df[required_cols].head(5).to_string(index=False))
            else:
                print(f"[POST-ANALYSIS] trade_results_df does not have expected columns: {trade_results_df.columns.tolist()}")
        else:
            print("[POST-ANALYSIS] No trade results to display.")
        # Print win/loss summary using new signals if possible
        if 'confirmed_signals_df' in locals() and not confirmed_signals_df.empty and 'outcome' in confirmed_signals_df.columns:
            win_count = (confirmed_signals_df['outcome'] == 'target').sum()
            loss_count = (confirmed_signals_df['outcome'] == 'stop').sum()
            total = win_count + loss_count
            if total > 0:
                win_rate = (win_count/total)
            else:
                win_rate = 0
            print(f"Win: {win_count}, Loss: {loss_count}, Win Rate: {win_rate:.2%}")
        else:
            print("[WARN] No 'outcome' column in confirmed_signals_df; skipping win/loss summary.")

    # --- Plotting: Add signal markers ---
    signal_candles = matched_signals
    fig.add_trace(go.Scatter(
        x=signal_candles['datetime'],
        y=signal_candles['high'] + 5,  # plot above candle
        mode='markers',
        marker=dict(
            symbol=np.where(signal_candles['signal_marker']=='bullish', 'triangle-up', 'triangle-down'),
            color=np.where(signal_candles['signal_marker']=='bullish', 'lime', 'red'),
            size=14,
            line=dict(width=2, color='black')
        ),
        name='Signals',
        text=signal_candles['signal_marker'],
        hoverinfo='text+x+y',
        showlegend=True
    ))

    # Enable crosshair (spikelines) and mousewheel zoom
    fig.update_layout(
        title='Historical Market Data (Interactive Candlestick)',
        xaxis_title='Datetime',
        yaxis_title='Price',
        xaxis_rangeslider_visible=True,
        template='plotly_dark',
        autosize=True,
        hovermode='x unified',  # crosshair
        dragmode='pan',         # default drag mode
    )
    fig.update_xaxes(showspikes=True, spikemode='across', spikesnap='cursor', showline=True)
    fig.update_yaxes(showspikes=True, spikemode='across', spikesnap='cursor', showline=True)

    # --- Enable scroll zoom in both show and HTML export ---
    plotly_config = {'scrollZoom': True}
    fig.show(config=plotly_config)
    fig.write_html("market_chart.html", auto_open=False, full_html=True, include_plotlyjs='cdn', config=plotly_config)
    webbrowser.open_new_tab("market_chart.html")

# --- DEBUG: Print nonzero signals before Backtrader ---
if 'confirmed_signal' in price_data.columns:
    print("[DEBUG] Nonzero confirmed signals in price_data:")
    print(price_data[price_data['confirmed_signal'] != 0][['datetime', 'confirmed_signal']])
else:
    print("[DEBUG] No confirmed_signal column in price_data!")

# --- Prepare DataFrame for Backtrader ---
print("\n[INFO] Preparing data for Backtrader backtesting...")

# --- Risk-Reward Parameters ---
RISK_REWARD_RATIO = 2.0  # Balanced risk-reward approach 
SL_BUFFER_PCT = 0.002    # 0.2% buffer below/above S/R level
TRAIL_PCT = 0.01         # 1% trailing stop for less tight trailing
USE_TRAILING_STOP = True # Use trailing stops to protect profits
MAX_POSITIONS = 3        # Maximum number of concurrent positions allowed

# --- CONFIG READING FIX: Only read option config if running for Options ---
market_type = selected_market_type.lower()
if market_type == 'options':
    try:
        option_quantity = config.getint('OPTIONS', 'option_quantity')
    except Exception:
        print("[WARN] Could not read option_quantity from config, using default 75")
        option_quantity = 75
else:
    option_quantity = None  # Not relevant for non-options

# Make a fresh copy of the DataFrame to ensure it's consistent
df_hdata_bt = price_data.copy()

# The DataFrame needs 'datetime' as a regular column for this approach
if 'datetime' in df_hdata_bt.columns:
    # Ensure datetime is in the right format
    df_hdata_bt['datetime'] = pd.to_datetime(df_hdata_bt['datetime'])
else:
    # If for some reason datetime isn't a column, print this
    print("[ERROR] No 'datetime' column found in DataFrame!")

# --- Count total signals for reporting ---
signal_count = df_hdata_bt[df_hdata_bt['confirmed_signal'] != 0].shape[0]
print(f"[INFO] Total signals in data: {signal_count}")
print(f"[INFO] Signal distribution: {df_hdata_bt['confirmed_signal'].value_counts().to_dict()}")

# --- IMPORTANT: Print all signals for debugging ---
print("\n[INFO] All signals in DataFrame:")
signals_df = df_hdata_bt[df_hdata_bt['confirmed_signal'] != 0].copy()
for idx, row in signals_df.iterrows():
    print(f"  {row['datetime']}: Signal {row['confirmed_signal']}")

# --- Ensure sr_level column exists for Backtrader ---
if 'sr_level' not in df_hdata_bt.columns:
    print('[INFO] Adding sr_level column for Backtrader compatibility.')
    df_hdata_bt['sr_level'] = np.nan

# --- CRITICAL FIX: Manually add a default sr_level to every signal ---
# This ensures each signal can be executed
for idx, row in df_hdata_bt.iterrows():
    if row['confirmed_signal'] != 0 and (pd.isnull(row['sr_level']) or row['sr_level'] == 0):
        if row['confirmed_signal'] > 0:  # Long signal
            df_hdata_bt.at[idx, 'sr_level'] = row['close'] * 0.99  # Support at 1% below price
            print(f"  Added support at {df_hdata_bt.at[idx, 'sr_level']:.2f} for {idx}")
        elif row['confirmed_signal'] < 0:  # Short signal
            df_hdata_bt.at[idx, 'sr_level'] = row['close'] * 1.01  # Resistance at 1% above price
            print(f"  Added resistance at {df_hdata_bt.at[idx, 'sr_level']:.2f} for {idx}")

# --- CRITICAL: Set index to datetime for Backtrader to use it properly ---
df_hdata_bt = df_hdata_bt.set_index('datetime')

# Convert to lowercase column names for Backtrader compatibility (but keep index name as is)
df_hdata_bt.columns = [col.lower() for col in df_hdata_bt.columns]

# Remove any other unnecessary data at the end of the file
def cleanup_dataframe(df):
    """Clean out any extraneous rows or reset dates"""
    # Keep data in our specified timeframe
    min_date = pd.to_datetime("2025-01-01")
    max_date = pd.to_datetime("2025-12-31")
    return df[df.index >= min_date]

df_hdata_bt = cleanup_dataframe(df_hdata_bt)

# --- Custom DataFeed for Backtrader ---
class PandasDataWithConfirmedSignal(bt.feeds.PandasData):
    """
    Custom PandasData class that includes confirmed_signal and sr_level as data lines
    """
    # Define the lines
    lines = ('confirmed_signal', 'sr_level')
    
    # Define the parameters - these map DataFrame columns to lines
    params = (
        ('datetime', None),  # Use the index as the datetime column - VERY IMPORTANT
        ('confirmed_signal', 'confirmed_signal'),  
        ('sr_level', 'sr_level'),
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', 'open_interest'),
    )


class MACDSTOCHRSI_SR_RR_Trailing_Strategy(bt.Strategy):
    params = (
        ('risk_reward', RISK_REWARD_RATIO), 
        ('sl_buffer_pct', SL_BUFFER_PCT), 
        ('trail_pct', TRAIL_PCT),
        ('use_trailing_stop', USE_TRAILING_STOP),
        ('single_position', False),  # Set to True to only allow one position at a time
        ('max_positions', MAX_POSITIONS)  # Maximum number of concurrent positions
    )
    
    def __init__(self):
        # Access the data feed lines correctly
        self.signal_series = self.datas[0].confirmed_signal
        self.sr_level_series = self.datas[0].sr_level
        self.dataclose = self.datas[0].close
        
        # Initialize tracking variables
        self.pending_entry = False  # Flag to track if we have a pending entry order
        self.position_list = []  # Track details of each active position
        self.active_positions = 0  # Track number of active positions
        self.trade_log = []
        
        # Track performance statistics
        self.signals_processed = 0
        self.signals_ignored = 0  # New counter for ignored signals
        self.signals_executing = 0  # New counter for signals we attempt to execute
        self.trades_executed = 0
        self.trades_won = 0
        self.trades_lost = 0
        self.total_profit = 0
        self.total_loss = 0
        self.all_signals = []  # Store all the signals we find
        
        # DIRECT INSPECTION: Print out all values in the signal series
        print("\n[CRITICAL DEBUG] Inspecting signal values in each bar:")
        found_signals = 0
        for i in range(len(self.data)):
            sig_value = self.signal_series[i]
            sr_value = self.sr_level_series[i]
            if sig_value != 0:
                found_signals += 1
                dt = self.data.datetime.date(i)
                self.all_signals.append((i, dt, sig_value))
                print(f"  Bar {i}: Date {dt}, Signal: {sig_value}, SR Level: {sr_value}")
        
        print(f"\n[CRITICAL INFO] Strategy found {found_signals} signals in the data feed")
        print(f"[CRITICAL INFO] If this doesn't match expected signal count, check your data feed config")
        
        # Set our execution mode
        self.single_position_mode = self.params.single_position
        
    def log(self, txt, dt=None):
        """Logging function"""
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f'[BT] {dt.isoformat()} {txt}')
        self.trade_log.append(f'{dt.isoformat()} {txt}')
    
    def should_execute_trade(self, signal, sr_level, close_price):
        """Determine if we should execute a trade based on the current conditions"""
        # If we're in single position mode and already have a position, don't execute
        if self.position and self.single_position_mode:
            return False
            
        # Check if we've reached max positions limit
        if self.active_positions >= self.params.max_positions:
            return False
            
        # Don't execute if we're waiting on an entry order
        if self.pending_entry:
            return False
            
        # Only execute if we have a valid signal and SR level
        if signal == 0 or pd.isnull(sr_level):
            return False
            
        # Check the risk-reward ratio - don't execute if it's too low
        if signal > 0:  # Long
            stop = sr_level * (1 - self.params.sl_buffer_pct)
            risk = close_price - stop
            reward = close_price * self.params.risk_reward * risk
            # Don't take trades with very small risk (avoids calculation errors)
            if risk < close_price * 0.001:  # Risk less than 0.1%
                return False
        elif signal < 0:  # Short
            stop = sr_level * (1 + self.params.sl_buffer_pct)
            risk = stop - close_price
            reward = close_price * self.params.risk_reward * risk
            # Don't take trades with very small risk
            if risk < close_price * 0.001:  # Risk less than 0.1%
                return False
                
        # All checks passed, execute the trade
        return True
        
    def next(self):
        """Called for each bar - main execution logic"""
        # Update position tracking counters
        self.signals_processed += 1
        
        # Get current signal and SR level
        signal = self.signal_series[0]
        sr_level = self.sr_level_series[0]
        
        # Log signals for debugging
        if signal != 0:
            self.log(f"SIGNAL DETECTED: {signal} (SR Level: {sr_level}) Price: {self.dataclose[0]}")
            
        # Update trailing stop for all positions
        self.update_trailing_stop()
        
        # Check if we should execute this trade
        if self.should_execute_trade(signal, sr_level, self.dataclose[0]):
            self.signals_executing += 1
            self.execute_trade(signal, sr_level)
        elif signal != 0:
            # Explain why we're ignoring this signal
            if self.active_positions >= self.params.max_positions:
                self.log(f"SIGNAL IGNORED: Maximum positions reached ({self.active_positions}/{self.params.max_positions})")
            elif self.position and self.single_position_mode:
                self.log(f"SIGNAL IGNORED: Already in a position (single position mode)")
            elif self.pending_entry:
                self.log(f"SIGNAL IGNORED: Entry order already pending")
            elif pd.isnull(sr_level):
                self.log(f"SIGNAL IGNORED: Missing SR level for signal {signal}")
            else:
                self.log(f"SIGNAL IGNORED: Other conditions failed")
            self.signals_ignored += 1
    
    def execute_trade(self, signal, sr_level):
        """Execute a trade based on the given signal and SR level"""
        if signal == 1:  # Long signal
            entry = self.dataclose[0]
            stop = sr_level * (1 - self.params.sl_buffer_pct)
            risk = entry - stop
            target = entry + self.params.risk_reward * risk
            
            # Create a new position entry
            position = {
                'type': 'long',
                'entry_price': entry,
                'stop_level': stop,
                'target_level': target,
                'current_stop': stop,
                'entry_time': self.data.datetime.datetime(0),
                'entry_order': None,
                'stop_order': None,
                'exit_order': None
            }
            
            # Submit the entry order
            position['entry_order'] = self.buy()
            self.pending_entry = True
            
            # Add to positions list
            self.position_list.append(position)
            
            # Log the trade
            self.log(f"BUY at {entry:.2f}, SL {stop:.2f}, TP {target:.2f} (R:R = 1:{self.params.risk_reward})")
            
        elif signal == -1:  # Short signal
            entry = self.dataclose[0]
            stop = sr_level * (1 + self.params.sl_buffer_pct)
            risk = stop - entry
            target = entry - self.params.risk_reward * risk
            
            # Create a new position entry
            position = {
                'type': 'short',
                'entry_price': entry,
                'stop_level': stop,
                'target_level': target,
                'current_stop': stop,
                'entry_time': self.data.datetime.datetime(0),
                'entry_order': None,
                'stop_order': None,
                'exit_order': None
            }
            
            # Submit the entry order
            position['entry_order'] = self.sell()
            self.pending_entry = True
            
            # Add to positions list
            self.position_list.append(position)
            
            # Log the trade
            self.log(f"SELL at {entry:.2f}, SL {stop:.2f}, TP {target:.2f} (R:R = 1:{self.params.risk_reward})")
            
        # Increment trades counter
        self.trades_executed += 1
        
    def update_trailing_stop(self):
        """Update trailing stop for all active positions"""
        # If we're not using trailing stops, exit
        if not self.params.use_trailing_stop:
            return
            
        # Loop through all active positions
        for position in self.position_list:
            # Skip positions that don't have a stop order
            if 'stop_order' not in position or position['stop_order'] is None:
                continue
                
            # Update trailing stop for long positions
            if position['type'] == 'long':
                new_trail = self.dataclose[0] * (1 - self.params.trail_pct)
                if new_trail > position['current_stop']:
                    # Cancel existing stop order
                    self.cancel(position['stop_order'])
                    # Create new stop order
                    position['stop_order'] = self.sell(exectype=bt.Order.Stop, price=new_trail)
                    self.log(f"Trailing SL moved up to {new_trail:.2f} (prev: {position['current_stop']:.2f})")
                    position['current_stop'] = new_trail
                    
            # Update trailing stop for short positions
            elif position['type'] == 'short':
                new_trail = self.dataclose[0] * (1 + self.params.trail_pct)
                if new_trail < position['current_stop']:
                    # Cancel existing stop order
                    self.cancel(position['stop_order'])
                    # Create new stop order
                    position['stop_order'] = self.buy(exectype=bt.Order.Stop, price=new_trail)
                    self.log(f"Trailing SL moved down to {new_trail:.2f} (prev: {position['current_stop']:.2f})")
                    position['current_stop'] = new_trail
                    
    def notify_order(self, order):
        """Called when order status changes"""
        # Find which position this order belongs to
        position_index = -1
        for i, position in enumerate(self.position_list):
            if (position['entry_order'] == order or
                position['stop_order'] == order or
                position['exit_order'] == order):
                position_index = i
                break
                
        if order.status in [order.Submitted, order.Accepted]:
            # Order has been submitted/accepted - no action required
            return
            
        # Check if an order has been completed
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"BUY EXECUTED at {order.executed.price:.2f}")
                
                # If this was an entry order for a long position
                if position_index >= 0 and self.position_list[position_index]['type'] == 'long' and self.position_list[position_index]['entry_order'] == order:
                    position = self.position_list[position_index]
                    
                    # Place stop loss and take profit orders
                    position['stop_order'] = self.sell(exectype=bt.Order.Stop, 
                                                  price=position['stop_level'])
                    if not self.params.use_trailing_stop:
                        position['exit_order'] = self.sell(exectype=bt.Order.Limit, 
                                                      price=position['target_level'])
                    
                    # Mark entry as complete
                    self.pending_entry = False
                    self.active_positions += 1
                
                # If this was a stop or take profit for a short position
                elif position_index >= 0 and self.position_list[position_index]['type'] == 'short':
                    position = self.position_list[position_index]
                    
                    # Calculate P&L
                    pnl = position['entry_price'] - order.executed.price
                    self.log(f"TRADE CLOSED - P&L: {pnl:.2f}")
                    
                    # Update performance metrics
                    if pnl > 0:
                        self.trades_won += 1
                        self.total_profit += pnl
                    else:
                        self.trades_lost += 1
                        self.total_loss += abs(pnl)
                        
                    # Remove this position
                    self.active_positions -= 1
                    self.position_list.pop(position_index)
                
            else:  # Sell
                self.log(f"SELL EXECUTED at {order.executed.price:.2f}")
                
                # If this was an entry order for a short position
                if position_index >= 0 and self.position_list[position_index]['type'] == 'short' and self.position_list[position_index]['entry_order'] == order:
                    position = self.position_list[position_index]
                    
                    # Place stop loss and take profit orders
                    position['stop_order'] = self.buy(exectype=bt.Order.Stop, 
                                                 price=position['stop_level'])
                    if not self.params.use_trailing_stop:
                        position['exit_order'] = self.buy(exectype=bt.Order.Limit, 
                                                     price=position['target_level'])
                    
                    # Mark entry as complete
                    self.pending_entry = False
                    self.active_positions += 1
                
                # If this was a stop or take profit for a long position
                elif position_index >= 0 and self.position_list[position_index]['type'] == 'long':
                    position = self.position_list[position_index]
                    
                    # Calculate P&L
                    pnl = order.executed.price - position['entry_price']
                    self.log(f"TRADE CLOSED - P&L: {pnl:.2f}")
                    
                    # Update performance metrics
                    if pnl > 0:
                        self.trades_won += 1
                        self.total_profit += pnl
                    else:
                        self.trades_lost += 1
                        self.total_loss += abs(pnl)
                        
                    # Remove this position
                    self.active_positions -= 1
                    self.position_list.pop(position_index)
        
        # Check if there was an error or if the order was canceled or margin
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order was {order.getstatusname()}")
            
            # If this was an entry order, allow new entries again
            if position_index >= 0 and self.position_list[position_index]['entry_order'] == order:
                self.pending_entry = False
                self.position_list.pop(position_index)  # Remove the failed position
                
            # If this was a stop or take profit order, recreate it
            elif position_index >= 0:
                position = self.position_list[position_index]
                if position['stop_order'] == order:
                    # Recreate stop order if needed
                    if position['type'] == 'long':
                        position['stop_order'] = self.sell(exectype=bt.Order.Stop, 
                                                      price=position['current_stop'])
                    else:
                        position['stop_order'] = self.buy(exectype=bt.Order.Stop, 
                                                     price=position['current_stop'])
                elif position['exit_order'] == order and not self.params.use_trailing_stop:
                    # Recreate take profit order if needed
                    if position['type'] == 'long':
                        position['exit_order'] = self.sell(exectype=bt.Order.Limit, 
                                                      price=position['target_level'])
                    else:
                        position['exit_order'] = self.buy(exectype=bt.Order.Limit, 
                                                     price=position['target_level'])
                    
    def stop(self):
        """Called at the end of the backtest to print statistics"""
        print("\n--- TRADING PERFORMANCE SUMMARY ---")
        print(f"Total signals in data: {len(self.all_signals)}")
        print(f"Signals Processed: {self.signals_processed}")
        print(f"Signals Attempted Execution: {self.signals_executing}")
        print(f"Signals Ignored: {self.signals_ignored}")
        print(f"Trades Executed: {self.trades_executed}")
        
        win_rate = 0
        if self.trades_won + self.trades_lost > 0:
            win_rate = self.trades_won / (self.trades_won + self.trades_lost) * 100
            
        print(f"Wins: {self.trades_won}, Losses: {self.trades_lost}, Win Rate: {win_rate:.2f}%")
        
        if self.trades_executed > 0:
            avg_profit = self.total_profit / max(1, self.trades_won) if self.trades_won > 0 else 0
            avg_loss = self.total_loss / max(1, self.trades_lost) if self.trades_lost > 0 else 0
            print(f"Average Win: {avg_profit:.2f}, Average Loss: {avg_loss:.2f}")
            
            if avg_loss > 0:
                profit_factor = self.total_profit / self.total_loss if self.total_loss > 0 else 0
                print(f"Profit Factor: {profit_factor:.2f}")
                
        print(f"Final Portfolio Value: {self.broker.getvalue():.2f}")
        print(f"Total P&L: {self.broker.getvalue() - 300000:.2f}")
        
        # Add risk-adjusted metrics
        print(f"\n--- STRATEGY CONFIGURATION ---")
        print(f"Risk-Reward Ratio: 1:{self.params.risk_reward}")
        print(f"Stop-Loss Buffer: {self.params.sl_buffer_pct*100:.2f}%")
        print(f"Trailing Stop: {self.params.trail_pct*100:.2f}%")
        print(f"Use Trailing Stop: {self.params.use_trailing_stop}")
        print(f"Single Position Mode: {self.single_position_mode}")
        print(f"Maximum Positions: {self.params.max_positions}")
        
        # Post-analysis recommendation
        signal_execution_rate = self.trades_executed / max(1, len(self.all_signals)) * 100
        print(f"\n--- POST-ANALYSIS INSIGHTS ---")
        print(f"Signal-to-Execution Rate: {signal_execution_rate:.2f}%")
        
        # Check if the strategy is profitable and provide recommendations
        if self.broker.getvalue() > 300000:
            print("[RECOMMENDATION] The strategy is profitable. Consider:") 
            if win_rate < 50:
                print(" - Improving signal quality to increase win rate")
            if signal_execution_rate < 80:
                print(" - Fixing SR level calculation to execute more signals")
            if win_rate > 60:
                print(" - Increasing position size as the strategy performs well")
        else:
            print("[RECOMMENDATION] The strategy needs improvement. Consider:")
            print(" - Reviewing signal generation to avoid clustered signals")
            print(" - Adjusting risk-reward ratio (current: 1:{self.params.risk_reward})")
            print(" - Testing different trailing stop values (current: {self.params.trail_pct*100:.2f}%)")
            if self.params.use_trailing_stop:
                print(" - Trying fixed take-profit targets instead of trailing stops")
            

# --- Skip DEBUG printing for BREEZE API ---
print("\n[INFO] Running Backtest with Backtrader...")

# Create a Cerebro engine
cerebro = bt.Cerebro()

# Add our strategy
cerebro.addstrategy(MACDSTOCHRSI_SR_RR_Trailing_Strategy)

# Set the position size
if market_type == 'options':
    cerebro.addsizer(bt.sizers.FixedSize, stake=option_quantity)  # Use config quantity
else:
    cerebro.addsizer(bt.sizers.FixedSize, stake=1)  # Default to 1 for non-options

# Add data feed with standard options (no preload parameter)
datafeed = PandasDataWithConfirmedSignal(dataname=df_hdata_bt)
cerebro.adddata(datafeed)

# Add standard observers
cerebro.addobserver(bt.observers.Trades)
cerebro.addobserver(bt.observers.BuySell)

# Set cash
cerebro.broker.setcash(300000)
print(f"[INFO] Starting Portfolio Value: {cerebro.broker.getvalue():.2f}")

# Run backtest with maxcpus=1 to ensure sequential processing
cerebro.run(maxcpus=1)

# Print summary of trades from the strategy
print("\n[INFO] Backtesting signals and trades summary:")
print(f"Total signals in data: {signal_count}")
print(f"Signals processed by strategy: {cerebro.runstrats[0][0].signals_processed}")
print(f"Trades executed: {cerebro.runstrats[0][0].trades_executed}")
print(f"Signals ignored: {cerebro.runstrats[0][0].signals_ignored}")
# CRITICAL: Force exit here to prevent any further code execution
print("\n[INFO] Backtest completed successfully.")
import os
os._exit(0)  # Using os._exit(0) to force immediate termination
