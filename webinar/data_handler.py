import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
from breeze_connect import BreezeConnect
from technical_indicators import TechnicalIndicators
import configparser

class DataHandler:
    """
    DataHandler class for fetching and processing market data from multiple timeframes.
    Used for the Triple Screen Trading System.
    """
    
    # Define supported timeframes by Breeze API
    SUPPORTED_TIMEFRAMES = ["1minute", "2minute", "3minute", "5minute", "10minute", 
                          "15minute", "30minute", "1hour", "2hour", "3hour", "4hour", "1day"]
    
    # Define resampling rules for pandas
    RESAMPLE_RULES = {
        '1minute': '1T',
        '2minute': '2T',
        '3minute': '3T',
        '5minute': '5T',
        '10minute': '10T',
        '15minute': '15T',
        '30minute': '30T',
        '1hour': '1H',
        '2hour': '2H',
        '3hour': '3H',
        '4hour': '4H',
        '1day': '1D'
    }
    
    def __init__(self, breeze_conn, stock_code, exchange_code, product_type, csv_folder,
                 expiry_date=None, right=None, strike_price=None):
        """
        Initialize DataHandler with connection and parameters
        
        Args:
            breeze_conn: BreezeConnect API instance
            stock_code: Stock symbol
            exchange_code: Exchange code (NSE/NFO)
            product_type: Product type (cash/futures/options)
            csv_folder: Path to historical data CSV files
            expiry_date: Required for derivatives (format: "YYYY, MM, DD, H, M, S")
            right: Required for options (call/put/others)
            strike_price: Required for options
        """
        self.breeze_conn = breeze_conn
        self.stock_code = stock_code
        self.exchange_code = exchange_code
        self.product_type = product_type
        self.csv_folder = csv_folder
        self.expiry_date = expiry_date
        self.right = right
        self.strike_price = strike_price
        
        # Load parameters from config
        config = configparser.RawConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), 'config.properties'))
        
        market_section = 'CASH' if product_type == 'cash' else 'FUTURES'
        self.interval = config.get(market_section, 'interval')
        
        # Parse from_date and to_date as datetime objects
        def parse_date(date_str):
            date_str = date_str.strip('"')
            if date_str.endswith('Z'):
                date_str = date_str[:-1] + '+00:00'
            return datetime.fromisoformat(date_str)

        self.from_date = parse_date(config.get(market_section, 'from_date'))
        self.to_date = parse_date(config.get(market_section, 'to_date'))
        self.csv_folder = config.get(market_section, 'csv_folder')
        # Read csv_pattern_template from config
        self.csv_pattern_template = config.get(market_section, 'csv_pattern_template', fallback=None)

        # Keep expiry_date as string in dd-MMM-yyyy format
        if self.product_type in ['futures', 'options']:
            self.expiry_date = config.get(market_section, 'expiry_date').strip('\"')

        # Validate instrument exists
        self.validate_stock_code()

    @property
    def from_date_iso(self):
        return self.datetime_to_iso(self.from_date)

    @property
    def to_date_iso(self):
        return self.datetime_to_iso(self.to_date)

    @property
    def expiry_date_iso(self):
        return self.expiry_date if self.expiry_date else None
    
    def datetime_to_iso(self, dt):
        """Convert Python datetime to ISO format for Breeze API."""
        if isinstance(dt, str):
            # If already in string format, return as is
            return dt
        return dt.strftime('%Y-%m-%dT%H:%M:%S') + '.000Z'
    
    def datetime_converter(self, dt_string):
        """Convert datetime string to pandas datetime."""
        return pd.to_datetime(dt_string)
    
    def get_api_interval(self, requested_interval):
        """
        Get appropriate API interval for requested interval, with resampling flag
        
        Args:
            requested_interval: Target interval (1minute, 5minute, etc.)
            
        Returns:
            Tuple of (appropriate API interval, whether resampling is needed)
        """
        # Direct mapping for supported intervals
        # Breeze API only supports 1minute, 5minute, 30minute, and 1day
        supported_intervals = ["1minute", "5minute", "30minute", "1day"]
                              
        if requested_interval in supported_intervals:
            return requested_interval, False
            
        # For intervals that need to be resampled, determine best source interval
        if requested_interval == '2minute':
            return '1minute', True
        elif requested_interval == '3minute':
            return '1minute', True
        elif requested_interval == '4hour':
            return '30minute', True  # Using 30minute since 1hour isn't supported
        elif requested_interval == '2hour':
            return '30minute', True  # Using 30minute since 1hour isn't supported
        elif requested_interval == '3hour':
            return '30minute', True  # Using 30minute since 1hour isn't supported
        elif requested_interval == '1hour':
            return '30minute', True  # Using 30minute since 1hour isn't supported
        elif requested_interval == '10minute':
            return '5minute', True
        elif requested_interval == '15minute':
            return '5minute', True
        else:
            # Default fallback to smallest supported interval
            return '5minute', True
    
    def resample_data(self, df, target_interval):
        """
        Resample dataframe to target interval
        
        Args:
            df: DataFrame with datetime index
            target_interval: Target interval (1minute, 5minute, etc.)
            
        Returns:
            Resampled DataFrame
        """
        # Mapping of intervals to pandas resample rules
        resample_map = {
            "1minute": "1T",
            "2minute": "2T",
            "3minute": "3T",
            "5minute": "5T",
            "10minute": "10T",
            "15minute": "15T",
            "30minute": "30T",
            "1hour": "1H",
            "2hour": "2H",
            "3hour": "3H",
            "4hour": "4H",
            "1day": "1D"
        }
        
        if target_interval not in resample_map:
            print(f"[ERROR] Unsupported target interval for resampling: {target_interval}")
            return df
            
        rule = resample_map[target_interval]
        print(f"Resampling data to {target_interval} (rule: {rule})")
        
        # Make sure DataFrame has required columns
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                print(f"[ERROR] Required column {col} not found in DataFrame for resampling")
                return df
                
        # Configure resampling
        resampled = df.resample(rule).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        })
        
        # Forward fill missing values and drop any remaining NaN rows
        resampled = resampled.dropna()
        
        print(f"Resampled data from {len(df)} to {len(resampled)} rows")
        
        return resampled
    
    def fetch_data(self, interval="30minute", stock_code=None, exchange_code=None, product_type=None, expiry_date=None, lookback_days=30, from_date=None, to_date=None):
        """
        Fetch historical data from Breeze API or from cached CSV
        
        Args:
            interval: Time interval (1minute, 5minute, 15minute, 30minute, 1hour, 1day)
            stock_code: Stock code for the security
            exchange_code: Exchange code (NSE, BSE, NFO)
            product_type: Product type (cash, futures, options)
            expiry_date: Expiry date for futures/options
            lookback_days: Number of days to look back
            from_date: Start date for data retrieval (datetime object)
            to_date: End date for data retrieval (datetime object)
            
        Returns:
            DataFrame with historical data
        """
        # Validate product type
        if product_type not in ['cash', 'futures', 'options']:
            raise ValueError(f"Invalid product_type: {product_type}. Must be 'cash', 'futures' or 'options'")
            
        # For cash market, ensure expiry_date and right are None
        if product_type == 'cash' and (expiry_date is not None or self.right is not None):
            print("[WARNING] Ignoring expiry_date and right parameters for cash market")
            expiry_date = None
            self.right = None

        # Check if the requested interval needs resampling
        api_interval, needs_resampling = self.get_api_interval(interval)
        
        # Use instance variables as fallbacks when parameters are None
        actual_stock_code = stock_code if stock_code is not None else self.stock_code
        actual_exchange_code = exchange_code if exchange_code is not None else self.exchange_code
        actual_product_type = product_type if product_type is not None else self.product_type
        
        # Unified CSV naming using template if available
        if self.csv_pattern_template:
            try:
                csv_pattern = self.csv_pattern_template.replace('*', '')
                if not actual_stock_code:
                    raise ValueError("Stock code is required but was not provided")
                    
                csv_filename = csv_pattern.format(
                    trade_mode=actual_product_type,
                    trade_type=actual_exchange_code,
                    stock=actual_stock_code.strip(),  # Ensure no whitespace
                    interval=api_interval
                )
                
                # Verify the filename contains the stock code
                if actual_stock_code not in csv_filename:
                    raise ValueError(f"Generated filename missing stock code: {csv_filename}")
            except Exception as e:
                print(f"[WARNING] CSV pattern template error: {e}. Using default pattern.")
                csv_filename = f"historical_{actual_product_type}_{actual_exchange_code}_{actual_stock_code}_{api_interval}.csv"
        else:
            csv_filename = f"historical_{actual_product_type}_{actual_exchange_code}_{actual_stock_code}_{api_interval}.csv"
        csv_path = os.path.join(self.csv_folder, csv_filename)
        
        # Try to fetch from cache first if enabled
        if self.use_cache and os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                df['datetime'] = pd.to_datetime(df['datetime'])
                df.set_index('datetime', inplace=True)
                
                # Apply date filtering if needed
                if from_date and to_date:
                    df = df[(df.index >= from_date) & (df.index <= to_date)]
                elif lookback_days:
                    start_date = datetime.now() - timedelta(days=lookback_days)
                    df = df[df.index >= start_date]
                
                # Resample if needed
                if needs_resampling and not df.empty:
                    df = self.resample_data(df, interval)
                
                if not df.empty:
                    return df
            except Exception as e:
                print(f"[WARNING] Error reading cached data: {e}")
        
        # Fetch from API if cache not available
        try:
            print(f"\n[DEBUG] Fetching {actual_product_type} data from API for {actual_stock_code}")
            print(f"  Exchange: {actual_exchange_code}, Interval: {api_interval}")
            print(f"  Date Range: {from_date} to {to_date}")
            
            if actual_product_type == 'cash':
                print("  Cash market parameters verified:")
                print(f"  expiry_date=None, right=None")
            
            # Make the API call
            hist_data = self.breeze_conn.get_historical_data_v2(
                interval=api_interval,
                from_date=self.from_date_iso,
                to_date=self.to_date_iso,
                stock_code=actual_stock_code,
                exchange_code=actual_exchange_code,
                product_type=actual_product_type,
                expiry_date=self.expiry_date_iso,
                right=self.right
            )
            print(f"  API returned {len(hist_data)} records")
            
            if hist_data and 'Success' in hist_data and hist_data["Success"]:
                # Convert API response to DataFrame
                df = pd.DataFrame(hist_data["Success"])
                
                # Fix data types
                df['datetime'] = pd.to_datetime(df['datetime'])
                numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'open_interest']
                for col in numeric_columns:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # Set datetime as index
                df.set_index('datetime', inplace=True)
                
                # Sort by datetime
                df.sort_index(inplace=True)
                
                # Save to cache for future use
                print(f"[INFO] Data saved to {csv_filename} and logged.")
                df.reset_index().to_csv(csv_path, index=False)
                
                # If we need to resample, do it here
                if needs_resampling and not df.empty:
                    df = self.resample_data(df, interval)
                
                # Print info about the data
                print("[INFO] DataFrame columns:", df.reset_index().columns)
                print(f"[INFO] Number of rows: {len(df)}")
                print(df.head())
                
                return df
            else:
                error_msg = f"Failed to fetch {actual_product_type} data for {actual_stock_code}. "
                error_msg += "Please check:"
                error_msg += "\n1. API connection and permissions"
                error_msg += "\n2. CSV files in {self.csv_folder}"
                error_msg += "\n3. Market open times and dates"
                if actual_product_type == 'cash':
                    error_msg += "\n4. Stock code exists in cash market (not index/derivative)"
                raise ValueError(error_msg)
        except Exception as e:
            error_msg = f"Failed to fetch {actual_product_type} data for {actual_stock_code}. "
            error_msg += "Please check:"
            error_msg += "\n1. API connection and permissions"
            error_msg += "\n2. CSV files in {self.csv_folder}"
            error_msg += "\n3. Market open times and dates"
            if actual_product_type == 'cash':
                error_msg += "\n4. Stock code exists in cash market (not index/derivative)"
            raise ValueError(error_msg)
    
    def get_historical_data(self):
        """Fetch historical data from API or CSV, now using ISEC stock code and handling all product types."""
        # Construct CSV filename based on ISEC stock code if available, else original
        # This assumes CSVs might be named with ISEC codes or original codes.
        # Adjust logic if CSV naming convention is strictly one or the other.
        # Get stock code, ensure it's not None/empty
        base_stock_code = getattr(self, 'isec_stock_code', self.stock_code)
        if not base_stock_code:
            raise ValueError("Stock code is required but was not provided")
            
        # Unify CSV naming: always use template if available, else fallback to default
        if self.csv_pattern_template:
            try:
                # Remove any '*' or wildcards from template (not valid for output files)
                csv_pattern = self.csv_pattern_template.replace('*', '')
                # Fill all placeholders with validated values
                csv_filename = csv_pattern.format(
                    trade_mode=self.product_type,
                    trade_type=self.exchange_code,
                    stock=base_stock_code.strip(),  # Ensure no whitespace
                    interval=self.interval
                )
                # Verify the filename contains the stock code
                if base_stock_code not in csv_filename:
                    raise ValueError(f"Generated filename missing stock code: {csv_filename}")
            except Exception as e:
                print(f"[WARNING] CSV pattern template error: {e}. Using default pattern.")
                csv_filename = f"historical_{self.product_type}_{self.exchange_code}_{base_stock_code}_{self.interval}.csv"
        else:
            csv_filename = f"historical_{self.product_type}_{self.exchange_code}_{base_stock_code}_{self.interval}.csv"
        
        csv_path = os.path.join(self.csv_folder, csv_filename)

        if os.path.exists(csv_path):
            print(f"[INFO] Loading data from CSV: {csv_path}")
            df = pd.read_csv(csv_path, parse_dates=['datetime'])
            df.set_index('datetime', inplace=True)
            # Ensure columns match Backtrader conventions
            df.rename(columns={'date': 'datetime', 'open': 'open', 'high': 'high', 
                               'low': 'low', 'close': 'close', 'volume': 'volume'},
                      inplace=True, errors='ignore')
            # Add openinterest if not present, default to 0
            if 'openinterest' not in df.columns:
                df['openinterest'] = 0
            return df
        else:
            print(f"[INFO] Fetching data from API for {self.stock_code} (ISEC: {getattr(self, 'isec_stock_code', 'N/A')})")
            try:
                # Ensure all dates are in ISO 8601 format (2025-03-24T09:15:00.000Z)
                def ensure_iso_format(dt):
                    if isinstance(dt, str):
                        # If it's already in ISO format, return as-is
                        if 'T' in dt and 'Z' in dt:
                            return dt
                        # If it's in 'dd-MMM-yyyy' format, convert to ISO
                        try:
                            dt_obj = datetime.strptime(dt, '%d-%b-%Y')
                            return dt_obj.strftime('%Y-%m-%dT%H:%M:%S.000Z')
                        except ValueError:
                            return dt  # Return as-is if parsing fails
                    elif isinstance(dt, (datetime, pd.Timestamp)):
                        return dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')
                    return dt
                
                api_params = {
                    "interval": self.interval,
                    "from_date": self.from_date_iso,
                    "to_date": self.to_date_iso,
                    "stock_code": getattr(self, 'isec_stock_code', self.stock_code), # Crucial: use validated ISEC code
                    "exchange_code": self.exchange_code,
                }

                if self.product_type in ['futures', 'options']:
                    api_params["expiry_date"] = self.expiry_date_iso
                    api_params["product_type"] = self.product_type
                    if self.product_type == 'options':
                        api_params["right"] = self.right
                        api_params["strike_price"] = self.strike_price
                    else:
                        api_params["right"] = "others"
                        api_params["strike_price"] = "0"

                if not hasattr(self, 'breeze_conn') or self.breeze_conn is None:
                    raise ConnectionError("BreezeConnect API object is not initialized.")

                response = self.breeze_conn.get_historical_data_v2(**api_params)
                
                # More robust response validation
                if not response:
                    print(f"[WARNING] API returned empty response for {self.stock_code}")
                    return pd.DataFrame() # Return empty DataFrame for no data

                if isinstance(response, dict) and response.get('Success') is False:
                    error_message = response.get('Message', response.get('Error', 'Unknown API error'))
                    raise ValueError(f"API Error for {self.stock_code}: {error_message}. Params: {api_params}")

                # Assuming direct list of candles for success, or a dict with a 'Data' key
                candle_data = []
                if isinstance(response, list):
                    candle_data = response
                elif isinstance(response, dict) and 'Data' in response and isinstance(response['Data'], list):
                    candle_data = response['Data']
                elif isinstance(response, dict) and 'Success' in response and isinstance(response['Success'], list):
                    candle_data = response['Success']
                elif isinstance(response, dict) and response.get('Status') == 200 and response.get('RateLimit') is not None:
                    # Handle rate limit response structure if it's different
                    print(f"[WARNING] Possible rate limit or unexpected success structure for {self.stock_code}: {response}")
                    return pd.DataFrame() # Or handle as error
                else:
                    print(f"[DEBUG] Unexpected API response format for {self.stock_code}: {response}. Params: {api_params}")
                    raise ValueError("Invalid API response format: Expected list of candles or dict with 'Data' list.")

                if not candle_data:
                    print(f"[INFO] No historical data returned by API for {self.stock_code}")
                    return pd.DataFrame()

                df = pd.DataFrame(candle_data)
                if df.empty:
                    return df

                # Standardize column names and format
                df.rename(columns={'datetime': 'dt', 'date': 'dt'}, inplace=True, errors='ignore') # dt or date to dt
                df.rename(columns={'dt':'datetime', 
                                   'stock_code':'symbol', 
                                   'exch':'exchange'},
                          inplace=True, errors='ignore') # Standardize further
            
                df['datetime'] = pd.to_datetime(df['datetime'])
                df.set_index('datetime', inplace=True)
            
                numeric_cols = ['open', 'high', 'low', 'close', 'volume'] # Add 'oi' if present
                if 'oi' in df.columns:
                    numeric_cols.append('oi')
                elif 'open_interest' in df.columns:
                    df.rename(columns={'open_interest':'oi'}, inplace=True)
                    numeric_cols.append('oi')
                
                for col in numeric_cols:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
                df.dropna(subset=numeric_cols, inplace=True) # Remove rows where essential data is missing
            
                # Ensure Backtrader required columns: open, high, low, close, volume
                # Add openinterest, default to 0 if not present
                if 'openinterest' not in df.columns:
                    if 'oi' in df.columns:
                        df.rename(columns={'oi':'openinterest'}, inplace=True)
                    else:
                        df['openinterest'] = 0.0
            
                required_bt_cols = ['open', 'high', 'low', 'close', 'volume', 'openinterest']
                for col in required_bt_cols:
                    if col not in df.columns:
                        if col == 'openinterest': df[col] = 0.0
                        else: raise ValueError(f"Missing required column '{col}' after API fetch for {self.stock_code}")
            
                # Save to CSV for future use
                df.to_csv(csv_path)
                print(f"[INFO] Data saved to CSV: {csv_path}")
                return df

            except Exception as e:
                print(f"[ERROR] Exception in get_historical_data for {self.stock_code}: {e}. Params if available: {api_params if 'api_params' in locals() else 'N/A'}")
                # traceback.print_exc() # Uncomment for detailed traceback during debugging
                raise ValueError(f"Failed to fetch/process data for {self.stock_code}: {str(e)}")
    
    def prepare_triple_screen_data(self, higher_tf="4hour", middle_tf="1hour", lower_tf="30minute", days_back=30):
        """
        Prepare data for all three timeframes in Triple Screen system
        
        Args:
            higher_tf: Higher timeframe (4hour, 1day, etc)
            middle_tf: Middle timeframe (1hour, etc)
            lower_tf: Lower timeframe (30minute, 15minute, etc)
            days_back: Number of days to look back
            
        Returns:
            Dictionary with 'higher', 'middle', and 'lower' keys containing dataframes
        """
        
        try:
            # Calculate date ranges
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            
            # Fetch data for each timeframe
            print(f"Fetching {higher_tf} data (API interval: {self.get_api_interval(higher_tf)})...")
            higher_df = self.fetch_data(
                interval=higher_tf,
                stock_code=self.stock_code,
                exchange_code=self.exchange_code,
                product_type=self.product_type,
                expiry_date=self.expiry_date,
                lookback_days=days_back
            )
            
            
            if higher_df is None or higher_df.empty:
                error_msg = f"Failed to fetch {self.product_type} data for {self.stock_code}. "
                error_msg += "Please check:"
                error_msg += "\n1. API connection and permissions"
                error_msg += "\n2. CSV files in {self.csv_folder}"
                error_msg += "\n3. Market open times and dates"
                if self.product_type == 'cash':
                    error_msg += "\n4. Stock code exists in cash market (not index/derivative)"
                raise ValueError(error_msg)
                
            print(f"Fetching {middle_tf} data (API interval: {self.get_api_interval(middle_tf)})...")
            middle_df = self.fetch_data(
                interval=middle_tf,
                stock_code=self.stock_code,
                exchange_code=self.exchange_code,
                product_type=self.product_type,
                expiry_date=self.expiry_date,
                lookback_days=days_back
            )
            
            
            if middle_df is None or middle_df.empty:
                error_msg = f"Failed to fetch {self.product_type} data for {self.stock_code}. "
                error_msg += "Please check:"
                error_msg += "\n1. API connection and permissions"
                error_msg += "\n2. CSV files in {self.csv_folder}"
                error_msg += "\n3. Market open times and dates"
                if self.product_type == 'cash':
                    error_msg += "\n4. Stock code exists in cash market (not index/derivative)"
                raise ValueError(error_msg)
                
            print(f"Fetching {lower_tf} data (API interval: {self.get_api_interval(lower_tf)})...")
            lower_df = self.fetch_data(
                interval=lower_tf,
                stock_code=self.stock_code,
                exchange_code=self.exchange_code,
                product_type=self.product_type,
                expiry_date=self.expiry_date,
                lookback_days=days_back
            )
            
            
            if lower_df is None or lower_df.empty:
                error_msg = f"Failed to fetch {self.product_type} data for {self.stock_code}. "
                error_msg += "Please check:"
                error_msg += "\n1. API connection and permissions"
                error_msg += "\n2. CSV files in {self.csv_folder}"
                error_msg += "\n3. Market open times and dates"
                if self.product_type == 'cash':
                    error_msg += "\n4. Stock code exists in cash market (not index/derivative)"
                raise ValueError(error_msg)
            
            # Add indicators to each timeframe
            # Higher timeframe: Trend indicators
            higher_df = self._add_trend_indicators(higher_df)
            
            # Middle timeframe: RSI, MACD
            middle_df = self._add_oscillator_indicators(middle_df)
            
            # Lower timeframe: ATR, volume indicators, patterns
            lower_df = self._add_execution_indicators(lower_df)
            
            return {
                'higher': higher_df,
                'middle': middle_df,
                'lower': lower_df
            }
            
        except Exception as e:
            print(f"[ERROR] Error preparing Triple Screen data: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _add_trend_indicators(self, df):
        """Add trend indicators to higher timeframe data"""
        # Add EMA indicators for trend identification
        df['ema_fast'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()
        df['EMA_Trend'] = np.where(df['ema_fast'] > df['ema_slow'], 1, -1)
        
        # Calculate ADX for trend strength
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Calculate True Range
        df['tr1'] = abs(high - low)
        df['tr2'] = abs(high - close.shift())
        df['tr3'] = abs(low - close.shift())
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        # Calculate +DM and -DM
        df['plus_dm'] = np.where((high - high.shift()) > (low.shift() - low), 
                                np.maximum(high - high.shift(), 0), 0)
        df['minus_dm'] = np.where((low.shift() - low) > (high - high.shift()), 
                                 np.maximum(low.shift() - low, 0), 0)
        
        # Calculate +DI and -DI
        df['plus_di'] = 100 * (df['plus_dm'].rolling(window=14).mean() / 
                              df['tr'].rolling(window=14).mean())
        df['minus_di'] = 100 * (df['minus_dm'].rolling(window=14).mean() / 
                               df['tr'].rolling(window=14).mean())
        
        # Calculate DX and ADX
        df['dx'] = 100 * (abs(df['plus_di'] - df['minus_di']) / 
                         (df['plus_di'] + df['minus_di']))
        df['adx'] = df['dx'].rolling(window=14).mean()
        
        return df

    def _add_oscillator_indicators(self, df):
        """Add oscillator indicators to middle timeframe data"""
        # Add RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # Add MACD
        df['ema_fast'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema_fast'] - df['ema_slow']
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        return df

    def _add_execution_indicators(self, df):
        """Add execution indicators to lower timeframe data"""
        # Add ATR
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Calculate True Range
        df['tr1'] = abs(high - low)
        df['tr2'] = abs(high - close.shift())
        df['tr3'] = abs(low - close.shift())
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        df['atr'] = df['tr'].rolling(window=14).mean()
        
        # Add volume indicators
        df['volume_ema'] = df['volume'].ewm(span=20, adjust=False).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ema']
        
        # Price action patterns
        df['pattern'] = 0  # Initialize pattern column
        
        # Identify potential support/resistance levels using swing lows/highs
        window = 5  # Lookback/forward periods for highs and lows
        try:
            df['pivot_high'] = df['high'].rolling(window=window*2+1, center=True).apply(
                lambda x: 1 if x.iloc[window] == max(x) else 0, raw=False)
            df['pivot_low'] = df['low'].rolling(window=window*2+1, center=True).apply(
                lambda x: 1 if x.iloc[window] == min(x) else 0, raw=False)
                
            # Add ADX for trend strength
            df['adx'] = self._calculate_adx(df, period=14)
        except Exception as e:
            print(f"Warning: Could not add all technical indicators: {e}")
        
        return df

    def _calculate_adx(self, df, period=14):
        """Calculate Average Directional Index"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Calculate True Range
        tr1 = abs(high - low)
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        # Calculate +DM and -DM
        plus_dm = high - high.shift()
        minus_dm = low.shift() - low
        plus_dm = plus_dm.where((plus_dm > 0) & (plus_dm > minus_dm), 0)
        minus_dm = minus_dm.where((minus_dm > 0) & (minus_dm > plus_dm), 0)
        
        # Calculate +DI and -DI
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        
        # Calculate DX and ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        
        return adx

    def validate_stock_code(self):
        """Validate stock code and store ISEC code from get_names response"""
        try:
            # For all market types, use simple get_names call with proper error handling
            try:
                response = self.breeze_conn.get_names(
                    stock_code=self.stock_code,
                    exchange_code=self.exchange_code
                )
            except Exception as e:
                print(f"[WARNING] API error during stock validation for {self.stock_code}: {str(e)}")
                # Set isec_stock_code to stock_code if API call fails
                self.isec_stock_code = self.stock_code
                return True
                
            # Verify response format
            if not isinstance(response, dict):
                print(f"[WARNING] Unexpected API response format for {self.stock_code}: {response}")
                self.isec_stock_code = self.stock_code
                return True
            
            # Store ISEC stock code
            self.isec_stock_code = response.get('isec_stock_code', self.stock_code)
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to validate {self.stock_code}: {str(e)}")
            # Still allow execution by setting isec_stock_code to stock_code
            self.isec_stock_code = self.stock_code
            return True
