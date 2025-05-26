"""
Performance comparison between original and improved trailing stop implementations
"""
import backtrader as bt
from triple_screen_strategy import TripleScreenStrategy
from triple_screen_relaxed import RelaxedTripleScreenStrategy
from data_handler import DataHandler
import matplotlib.pyplot as plt
from breeze_connect import BreezeConnect
import configparser
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class TrailingStopComparison:
    def __init__(self):
        self.cerebro = bt.Cerebro()
        
        # Initialize Breeze connection with raw config parser
        config = configparser.RawConfigParser()
        config_path = os.path.join(os.path.dirname(__file__), 'config.properties')
        
        try:
            config.read(config_path)
            app_key = config.get('DEFAULT', 'app_key')
            secret_key = config.get('DEFAULT', 'secret_key')
            session_token = config.get('DEFAULT', 'session_token')
            
            breeze_conn = BreezeConnect(api_key=app_key)
            breeze_conn.generate_session(
                api_secret=secret_key,
                session_token=session_token
            )
        except Exception as e:
            print(f"[WARNING] Could not initialize Breeze connection: {e}")
            print("[INFO] Proceeding with mock connection for backtesting")
            breeze_conn = None
        
        # Load and prepare data
        df = self.load_and_prepare_data(breeze_conn)
        
        # Create Backtrader data feed with proper column mapping
        data = bt.feeds.PandasData(
            dataname=df,
            datetime=None,  # Use index as datetime
            open='open',
            high='high',
            low='low',
            close='close',
            volume='volume',
            openinterest=None
        )
        self.cerebro.adddata(data)
        
        # Add analyzers
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    def load_and_prepare_data(self, breeze_conn):
        """Load and prepare data with proper formatting"""
        try:
            dh = DataHandler(breeze_conn)
            
            # Try to get data using available methods
            if hasattr(dh, 'get_historical_data'):
                df = dh.get_historical_data()
            elif hasattr(dh, 'fetch_data'):
                df = dh.fetch_data()
            else:
                raise AttributeError("No recognized data loading method")
            
            # Clean and prepare the data
            df = self.clean_data(df)
            return df
            
        except Exception as e:
            print(f"[WARNING] Error loading data: {e}")
            print("[INFO] Using properly formatted sample data")
            return self.create_sample_data()
    
    def clean_data(self, df):
        """Clean and format the DataFrame"""
        # Ensure datetime index
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
        
        # Fill NA values using modern methods
        df = df.ffill().bfill().fillna(0)
        
        # Ensure required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in df.columns:
                df[col] = df['close'] if col != 'volume' else 1000
                
        # Add required strategy signal column
        if 'confirmed_signal' not in df.columns:
            df['confirmed_signal'] = 0  # Neutral signal by default
            
        return df
    
    def create_sample_data(self):
        """Create properly formatted sample data"""
        dates = pd.date_range(end=datetime.today(), periods=100, freq='D')
        df = pd.DataFrame({
            'open': np.random.uniform(100, 105, 100),
            'high': np.random.uniform(105, 110, 100),
            'low': np.random.uniform(95, 100, 100),
            'close': np.random.uniform(100, 105, 100),
            'volume': np.random.randint(1000, 5000, 100)
        }, index=dates)
        
        # Add required strategy signal column
        df['confirmed_signal'] = 0  # Neutral signal by default
        return df
    
    def run_comparison(self):
        # Original strategy
        self.cerebro.addstrategy(TripleScreenStrategy, 
                               trail_atr_mult=0,  # Disable ATR trailing
                               min_trail_distance=0)  # Disable min distance
        print("\n[TEST] Running ORIGINAL trailing stop logic...")
        original_results = self.cerebro.run()[0]
        
        # Modified strategy
        self.cerebro.addstrategy(TripleScreenStrategy,
                               trail_atr_mult=1.5,
                               min_trail_distance=0.5)
        print("\n[TEST] Running MODIFIED trailing stop logic...")
        modified_results = self.cerebro.run()[0]
        
        # Print comparison
        self.print_results(original_results, modified_results)
        
    def print_results(self, original, modified):
        print("\n=== TRAILING STOP COMPARISON RESULTS ===")
        print("Metric\t\tOriginal\tModified\tDifference")
        
        # Sharpe Ratio
        o_sharpe = original.analyzers.sharpe.get_analysis()['sharperatio']
        m_sharpe = modified.analyzers.sharpe.get_analysis()['sharperatio']
        print(f"Sharpe\t\t{o_sharpe:.2f}\t\t{m_sharpe:.2f}\t\t{(m_sharpe-o_sharpe):+.2f}")
        
        # Max Drawdown
        o_dd = original.analyzers.drawdown.get_analysis()['max']['drawdown']
        m_dd = modified.analyzers.drawdown.get_analysis()['max']['drawdown']
        print(f"Drawdown\t{o_dd:.1f}%\t\t{m_dd:.1f}%\t\t{(m_dd-o_dd):+.1f}%")
        
        # Win Rate
        o_trades = original.analyzers.trades.get_analysis()
        m_trades = modified.analyzers.trades.get_analysis()
        o_win_rate = o_trades.won.total / o_trades.total.total if o_trades.total.total > 0 else 0
        m_win_rate = m_trades.won.total / m_trades.total.total if m_trades.total.total > 0 else 0
        print(f"Win Rate\t{o_win_rate:.1%}\t\t{m_win_rate:.1%}\t\t{(m_win_rate-o_win_rate):+.1%}")

if __name__ == '__main__':
    comparison = TrailingStopComparison()
    comparison.run_comparison()
