import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

SESSION_TOKEN = "51316056"  # Not used for this simulation

# Load historical data
# Assumes 'datetime' is in yyyy-mm-dd format and 'close' is float
# You may want to parse dates for more advanced logic

df_hdata = pd.read_csv('/Users/mrigeshkumar/Documents/Historical Data/ICICIBANK_HistoricalData.csv')

# --- Simulation Parameters ---
START_CAPITAL = 100_000
LOT_SIZE = 550  # ICICI Bank F&O lot size
MIN_TRADE_DAYS = 10

# --- Calculate Indicators for Strategy Logic ---
df_hdata['SMA20'] = df_hdata['close'].rolling(window=20).mean()
df_hdata['SMA50'] = df_hdata['close'].rolling(window=50).mean()
df_hdata['RSI'] = 100 - (100 / (1 + df_hdata['close'].pct_change().add(1).rolling(window=14).mean()))

# --- Virtual Straddle Simulation ---
capital = START_CAPITAL
trade_log = []
trade_count = 0

# Use every 5th day for simulation (to get at least 10 trades if enough data)
sim_days = df_hdata.iloc[::max(len(df_hdata)//MIN_TRADE_DAYS,1)].head(MIN_TRADE_DAYS)

for idx, row in sim_days.iterrows():
    date = row['datetime']
    open_price = row['open'] if 'open' in row else row['close']
    close_price = row['close']
    sma20 = row['SMA20']
    sma50 = row['SMA50']
    rsi = row['RSI']
    # --- Strategy Logic ---
    # If price > SMA20 and SMA20 > SMA50 and RSI < 65: Bullish bias, else straddle
    if pd.notna(sma20) and pd.notna(sma50) and open_price > sma20 > sma50 and (pd.isna(rsi) or rsi < 65):
        strategy = 'Bullish Straddle'
    elif pd.notna(sma20) and pd.notna(sma50) and open_price < sma20 < sma50 and (pd.isna(rsi) or rsi > 35):
        strategy = 'Bearish Straddle'
    else:
        strategy = 'Neutral Straddle'

    # --- Straddle Simulation ---
    strike = round(open_price/10)*10
    call_premium_buy = max(open_price - strike, 0)
    put_premium_buy = max(strike - open_price, 0)
    total_premium_paid = (call_premium_buy + put_premium_buy) * LOT_SIZE

    # At close, calculate intrinsic value (simplified, ignores time decay)
    call_intrinsic = max(close_price - strike, 0)
    put_intrinsic = max(strike - close_price, 0)
    total_intrinsic = (call_intrinsic + put_intrinsic) * LOT_SIZE

    profit = total_intrinsic - total_premium_paid
    capital += profit
    trade_count += 1
    trade_log.append({
        'Date': date,
        'Strategy': strategy,
        'Strike': strike,
        'OpenPrice': open_price,
        'ClosePrice': close_price,
        'CallBuy': call_premium_buy,
        'PutBuy': put_premium_buy,
        'PremiumPaid': total_premium_paid,
        'CallIntrinsic': call_intrinsic,
        'PutIntrinsic': put_intrinsic,
        'Profit': profit,
        'Capital': capital
    })
    print(f"{date}: {strategy} | Strike: {strike} | P&L: {profit:.2f} | Capital: {capital:.2f}")

# --- Summary Log ---
results = pd.DataFrame(trade_log)
print("\n--- Trade Log ---")
print(results[['Date','Strategy','Strike','OpenPrice','ClosePrice','PremiumPaid','Profit','Capital']])
print(f"\nTotal Trades: {trade_count}")
print(f"Final Capital: {capital:.2f}")
print(f"Total P&L: {capital - START_CAPITAL:.2f}")

# Optionally, save log to CSV
results.to_csv('ICICIBANK_StraddleSimulation_Log.csv', index=False)
