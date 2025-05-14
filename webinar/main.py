"""
Main execution script for the Triple Screen Trading System.
"""

import pandas as pd
import numpy as np
from breeze_connect import BreezeConnect
import backtrader as bt
from datetime import datetime
import backtrader.analyzers as btanalyzers
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')
import os
import configparser

from data_handler import DataHandler
from triple_screen_strategy import TripleScreenStrategy, CustomPandasData
import app_config as cfg

def load_api_credentials():
    """Load Breeze API credentials from config.properties file"""
    try:
        config = configparser.RawConfigParser(interpolation=None)
        config_path = os.path.join(os.path.dirname(__file__), 'config.properties')
        config.read(config_path)
        
        # Get the API credentials from the DEFAULT section
        api_key = config.get('DEFAULT', 'app_key')
        api_secret = config.get('DEFAULT', 'secret_key')
        session_token = config.get('DEFAULT', 'session_token')
        
        return api_key, api_secret, session_token
    except Exception as e:
        print(f"Error loading credentials from config.properties: {e}")
        return None, None, None

def run_backtest(data_dict, stock_code):
    """
    Run backtest of the Triple Screen Trading System.
    
    Args:
        data_dict: Dictionary with DataFrames for each timeframe
        stock_code: Stock code being tested
    """
    # Extract trend from higher timeframe
    higher_df = data_dict['higher']
    middle_df = data_dict['middle']
    
    # Get the overall trend from the higher timeframe
    # We'll consider the last 5 values to determine the trend
    recent_trend = higher_df['EMA_Trend'].tail(5).mean()
    trend_value = 1 if recent_trend > 0 else -1 if recent_trend < 0 else None
    
    print(f"Overall trend from higher timeframe: {'Bullish' if trend_value == 1 else 'Bearish'}")
    
    # Initialize Backtrader engine
    cerebro = bt.Cerebro()
    
    # Add strategy with higher timeframe trend information
    cerebro.addstrategy(TripleScreenStrategy, 
                       higher_tf_trend=trend_value,
                       rsi_period=cfg.RSI_PERIOD,
                       rsi_overbought=cfg.RSI_OVERBOUGHT,
                       rsi_oversold=cfg.RSI_OVERSOLD,
                       macd_fast=cfg.MACD_FAST,
                       macd_slow=cfg.MACD_SLOW,
                       macd_signal=cfg.MACD_SIGNAL,
                       atr_period=cfg.ATR_PERIOD,
                       trailing_pct=cfg.TRAILING_PERCENT,
                       profit_target_atr_mult=cfg.PROFIT_TARGET_ATR_MULT,
                       risk_reward_ratio=cfg.RISK_REWARD_RATIO,
                       risk_per_trade=cfg.RISK_PER_TRADE,
                       max_positions=cfg.MAX_POSITIONS)
    
    # Create data feed from middle timeframe (where we execute trades)
    data_feed = CustomPandasData(dataname=middle_df.reset_index())
    cerebro.adddata(data_feed)
    
    # Set initial cash
    cerebro.broker.setcash(cfg.INITIAL_CAPITAL)
    
    # Add analyzers
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(btanalyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(btanalyzers.Returns, _name='returns')
    
    # Print starting conditions
    print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')
    
    # Run backtest
    results = cerebro.run()
    strategy = results[0]
    
    # Print final results
    print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')
    print(f'Return: {cerebro.broker.getvalue() / cfg.INITIAL_CAPITAL - 1:.2%}')
    
    # Print trade analysis
    trade_analysis = strategy.analyzers.trades.get_analysis()
    
    # Calculate win rate if trades were made
    if hasattr(trade_analysis, 'total'):
        total_trades = trade_analysis.total.closed
        if total_trades > 0:
            won_trades = getattr(trade_analysis.won, 'total', 0)
            win_rate = won_trades / total_trades * 100
            print(f'Win Rate: {win_rate:.2f}%')
            print(f'Total Trades: {total_trades}')
            print(f'Won Trades: {won_trades}')
            print(f'Lost Trades: {getattr(trade_analysis.lost, "total", 0)}')
            
            if hasattr(trade_analysis.won, 'pnl'):
                avg_win = trade_analysis.won.pnl.average
                print(f'Average Win: {avg_win:.2f}')
                
            if hasattr(trade_analysis.lost, 'pnl'):
                avg_loss = trade_analysis.lost.pnl.average
                print(f'Average Loss: {avg_loss:.2f}')
                
            if 'avg_win' in locals() and 'avg_loss' in locals() and avg_loss != 0:
                profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
                print(f'Profit Factor: {profit_factor:.2f}')
        else:
            print('No trades were executed.')
    
    # Plot results
    cerebro.plot(style='candle', barup='green', bardown='red', volume=False)

def main():
    """Main function to execute the Triple Screen Trading System"""
    # Load credentials
    api_key, api_secret, session_token = load_api_credentials()
    
    if not all([api_key, api_secret, session_token]):
        print("Failed to load API credentials from config.properties")
        return
    
    # Initialize Breeze connection
    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=session_token)
    
    # Initialize data handler
    data_handler = DataHandler(
        breeze_conn=breeze,
        stock_code=cfg.STOCK_CODE,
        exchange_code=cfg.EXCHANGE_CODE,
        product_type=cfg.PRODUCT_TYPE
    )
    
    # Fetch data for all timeframes
    print(f"Fetching data for {cfg.STOCK_CODE}...")
    data_dict = data_handler.prepare_triple_screen_data(
        higher_tf=cfg.HIGHER_TIMEFRAME,
        middle_tf=cfg.MIDDLE_TIMEFRAME,
        lower_tf=cfg.LOWER_TIMEFRAME,
        days_back=cfg.DAYS_BACK
    )
    
    if data_dict is None:
        print("Failed to fetch data for all timeframes.")
        return
    
    print("Data fetched successfully!")
    
    # Print data information
    print(f"Higher timeframe ({cfg.HIGHER_TIMEFRAME}) data shape: {data_dict['higher'].shape}")
    print(f"Middle timeframe ({cfg.MIDDLE_TIMEFRAME}) data shape: {data_dict['middle'].shape}")
    print(f"Lower timeframe ({cfg.LOWER_TIMEFRAME}) data shape: {data_dict['lower'].shape}")
    
    # Run backtest
    print("\nRunning Triple Screen Trading System backtest...")
    run_backtest(data_dict, cfg.STOCK_CODE)

if __name__ == "__main__":
    main()
